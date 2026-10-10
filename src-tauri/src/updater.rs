//! Checking for and installing app updates (`ARCHITECTURE.md#updates`).
//!
//! The frontend asks; the shell does the work, because only the shell can stop
//! the sidecar first. An update is a signed NSIS installer named in a feed the
//! release workflow publishes; `download` refuses one whose signature does not
//! match the public key in `tauri.conf.json`.
//!
//! Whether it is *safe* to install is the frontend's call, from the states the
//! sidecar reports (no session, every box idle) — the shell knows neither.

use std::sync::Mutex;
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

use crate::sidecar::SidecarState;

/// Download progress, so the frontend can show the update is moving.
pub const PROGRESS_EVENT: &str = "update://progress";
/// The download is verified and the sidecar is about to stop.
pub const INSTALLING_EVENT: &str = "update://installing";

/// Long enough for the sidecar's own shutdown, which waits up to ~8 s for the
/// `arduino-cli` daemon before killing it.
const SIDECAR_STOP_GRACE: Duration = Duration::from_secs(12);

/// The update found by the last check, held until it is installed.
#[derive(Default)]
pub struct PendingUpdate(Mutex<Option<Update>>);

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    pub version: String,
    pub current_version: String,
    /// RFC 3339, when the release was published.
    pub date: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Progress {
    downloaded: u64,
    total: Option<u64>,
}

/// Ask the update feed whether a newer version exists. `None` when this is the
/// newest, and always in a dev build, which is not an installed app.
#[tauri::command]
pub async fn update_check(
    app: AppHandle,
    pending: State<'_, PendingUpdate>,
) -> Result<Option<UpdateInfo>, String> {
    if cfg!(debug_assertions) {
        return Ok(None);
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| e.to_string())?;
    let info = update.as_ref().map(|u| UpdateInfo {
        version: u.version.clone(),
        current_version: u.current_version.clone(),
        date: u
            .raw_json
            .get("pub_date")
            .and_then(|d| d.as_str())
            .map(String::from),
    });
    *pending.0.lock().unwrap() = update;
    Ok(info)
}

/// Download the pending update, stop the sidecar, and hand over to the
/// installer. On Windows the app exits here and the installer relaunches it,
/// so success never returns.
///
/// The download (and its signature check) happens before the sidecar is
/// touched: a failure there leaves the app exactly as it was.
#[tauri::command]
pub async fn update_install(
    app: AppHandle,
    pending: State<'_, PendingUpdate>,
) -> Result<(), String> {
    let Some(update) = pending.0.lock().unwrap().take() else {
        return Err("no update is waiting; check again".into());
    };

    let mut downloaded: u64 = 0;
    let bytes = update
        .download(
            |chunk, total| {
                downloaded += chunk as u64;
                let _ = app.emit(PROGRESS_EVENT, Progress { downloaded, total });
            },
            || {},
        )
        .await
        .map_err(|e| e.to_string())?;

    log::info!("update {} downloaded; stopping the sidecar to install", update.version);
    let _ = app.emit(INSTALLING_EVENT, ());
    app.state::<SidecarState>().stop(SIDECAR_STOP_GRACE);

    update.install(bytes).map_err(|e| e.to_string())?;
    // Reached only where install doesn't exit on its own (not Windows).
    app.restart();
}
