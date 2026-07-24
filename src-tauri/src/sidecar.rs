//! Spawns and supervises the Python sidecar.
//!
//! The sidecar binds an ephemeral loopback port and prints a single handshake
//! line on stdout:
//!
//! ```text
//! EPHYMERIS_WS_PORT=<port> EPHYMERIS_WS_TOKEN=<token>
//! ```
//!
//! We capture both, hand them to the frontend via the `sidecar_endpoint`
//! command (and a `sidecar://ready` event), and hold the child's stdin open for
//! the life of the app so the sidecar's own orphan-watch can notice if we die.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, Runtime, State};

/// Emitted once the handshake line has been parsed.
pub const READY_EVENT: &str = "sidecar://ready";
/// Emitted if the sidecar exits or fails to start.
pub const DOWN_EVENT: &str = "sidecar://down";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SidecarEndpoint {
    pub port: u16,
    pub token: String,
}

#[derive(Default)]
pub struct SidecarState {
    endpoint: Mutex<Option<SidecarEndpoint>>,
    /// Held open deliberately: closing it is how the sidecar learns we exited.
    stdin: Mutex<Option<ChildStdin>>,
    child: Mutex<Option<Child>>,
}

impl SidecarState {
    pub fn endpoint(&self) -> Option<SidecarEndpoint> {
        self.endpoint.lock().ok().and_then(|g| g.clone())
    }

    /// Kill the child on app exit so it can never outlive us holding serial ports.
    pub fn shutdown(&self) {
        if let Ok(mut guard) = self.stdin.lock() {
            guard.take(); // dropping closes the pipe -> sidecar's stdin watch fires
        }
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

/// Resolve the interpreter that runs the sidecar.
///
/// Development uses the repo's `sidecar/.venv`. `EPHYMERIS_SIDECAR_PYTHON`
/// overrides it. Packaging the sidecar as a frozen binary is deferred along
/// with Windows packaging generally.
fn resolve_python() -> PathBuf {
    if let Ok(explicit) = std::env::var("EPHYMERIS_SIDECAR_PYTHON") {
        return PathBuf::from(explicit);
    }
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(PathBuf::from)
        .unwrap_or_default();
    let venv = repo_root.join("sidecar").join(".venv");
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn sidecar_cwd() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(|p| p.join("sidecar"))
        .unwrap_or_default()
}

pub fn spawn<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let python = resolve_python();
    let cwd = sidecar_cwd();

    if !python.exists() {
        return Err(format!(
            "Sidecar interpreter not found at {}. Create it with: python3 -m venv sidecar/.venv",
            python.display()
        ));
    }

    // The cohort database belongs in the app's own data directory, beside
    // `settings.json` — not in the user's configured `dataDirectory`, which is
    // for browsable session output (`cohorts.md` §3). Resolved here so the
    // shell and the sidecar can't disagree about where that is.
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("could not resolve the app data directory: {e}"))?;

    log::info!(
        "spawning sidecar: {} -m ephymeris_sidecar --data-dir {}",
        python.display(),
        data_dir.display()
    );

    let mut child = Command::new(&python)
        .arg("-m")
        .arg("ephymeris_sidecar")
        .arg("--data-dir")
        .arg(&data_dir)
        .current_dir(&cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

    let stdout = child.stdout.take().ok_or("sidecar stdout unavailable")?;
    let stderr = child.stderr.take().ok_or("sidecar stderr unavailable")?;
    let stdin = child.stdin.take().ok_or("sidecar stdin unavailable")?;

    let state: State<SidecarState> = app.state();
    *state.stdin.lock().unwrap() = Some(stdin);
    *state.child.lock().unwrap() = Some(child);

    // stdout: the handshake line, then nothing we care about.
    {
        let app = app.clone();
        std::thread::spawn(move || {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
                match parse_handshake(&line) {
                    Some(endpoint) => {
                        log::info!("sidecar ready on port {}", endpoint.port);
                        let state: State<SidecarState> = app.state();
                        *state.endpoint.lock().unwrap() = Some(endpoint.clone());
                        let _ = app.emit(READY_EVENT, endpoint);
                    }
                    None => log::debug!("sidecar stdout: {line}"),
                }
            }
            log::warn!("sidecar stdout closed; process has exited");
            let state: State<SidecarState> = app.state();
            *state.endpoint.lock().unwrap() = None;
            let _ = app.emit(DOWN_EVENT, ());
        });
    }

    // stderr: the sidecar's log stream, forwarded so failures are visible.
    std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            log::info!("[sidecar] {line}");
        }
    });

    Ok(())
}

fn parse_handshake(line: &str) -> Option<SidecarEndpoint> {
    let mut port = None;
    let mut token = None;
    for field in line.split_whitespace() {
        match field.split_once('=') {
            Some(("EPHYMERIS_WS_PORT", v)) => port = v.parse::<u16>().ok(),
            Some(("EPHYMERIS_WS_TOKEN", v)) => token = Some(v.to_string()),
            _ => {}
        }
    }
    Some(SidecarEndpoint {
        port: port?,
        token: token?,
    })
}

#[tauri::command]
pub fn sidecar_endpoint(state: State<SidecarState>) -> Option<SidecarEndpoint> {
    state.endpoint()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_well_formed_handshake() {
        let parsed = parse_handshake("EPHYMERIS_WS_PORT=53834 EPHYMERIS_WS_TOKEN=abc123").unwrap();
        assert_eq!(parsed.port, 53834);
        assert_eq!(parsed.token, "abc123");
    }

    #[test]
    fn ignores_ordinary_log_lines() {
        assert!(parse_handshake("sidecar listening on 127.0.0.1:53834").is_none());
        assert!(parse_handshake("EPHYMERIS_WS_PORT=53834").is_none());
        assert!(parse_handshake("EPHYMERIS_WS_PORT=notaport EPHYMERIS_WS_TOKEN=x").is_none());
    }
}
