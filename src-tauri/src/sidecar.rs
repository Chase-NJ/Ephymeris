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

/// How the sidecar process gets launched — either an interpreter running the
/// package from the repo, or the PyInstaller-frozen executable from the
/// installed app's resources.
struct SidecarLaunch {
    program: PathBuf,
    /// `["-m", "ephymeris_sidecar"]` for an interpreter, empty for the frozen exe.
    module_args: Vec<&'static str>,
    cwd: PathBuf,
}

/// The repo's `sidecar/.venv` interpreter — the development path.
fn venv_launch() -> SidecarLaunch {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(PathBuf::from)
        .unwrap_or_default();
    let venv = repo_root.join("sidecar").join(".venv");
    let python = if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    };
    SidecarLaunch {
        program: python,
        module_args: vec!["-m", "ephymeris_sidecar"],
        cwd: repo_root.join("sidecar"),
    }
}

/// The frozen sidecar staged by `scripts/package-resources.mjs` and bundled
/// under the app's resource directory.
fn frozen_launch<R: Runtime>(app: &AppHandle<R>) -> Option<SidecarLaunch> {
    let resources = app.path().resource_dir().ok()?;
    let exe = resources
        .join("sidecar")
        .join(if cfg!(windows) { "ephymeris-sidecar.exe" } else { "ephymeris-sidecar" });
    exe.exists().then(|| SidecarLaunch {
        cwd: exe.parent().map(PathBuf::from).unwrap_or_default(),
        program: exe,
        module_args: vec![],
    })
}

/// Resolve how to launch the sidecar.
///
/// `EPHYMERIS_SIDECAR_PYTHON` always wins, for running against a bespoke
/// interpreter. After that the two builds prefer opposite orders on purpose:
/// dev wants the live venv (edit Python, relaunch, see it), a release build
/// wants the frozen exe it shipped with — but each falls back to the other,
/// so a release exe run from a checkout still works without staged resources.
fn resolve_launch<R: Runtime>(app: &AppHandle<R>) -> Result<SidecarLaunch, String> {
    if let Ok(explicit) = std::env::var("EPHYMERIS_SIDECAR_PYTHON") {
        let venv = venv_launch();
        return Ok(SidecarLaunch {
            program: PathBuf::from(explicit),
            ..venv
        });
    }

    let venv = venv_launch();
    let ordered: Vec<Option<SidecarLaunch>> = if cfg!(debug_assertions) {
        vec![venv.program.exists().then_some(venv), frozen_launch(app)]
    } else {
        vec![frozen_launch(app), venv.program.exists().then_some(venv)]
    };
    ordered.into_iter().flatten().next().ok_or_else(|| {
        "No sidecar found: neither a bundled ephymeris-sidecar executable nor a \
         sidecar/.venv interpreter. For development, create the venv (see README); \
         for packaging, run `npm run package`."
            .to_string()
    })
}

/// Bundled arduino-cli locations, exported to the sidecar as env vars.
///
/// Present only when the resources exist (i.e. an installed build), so the
/// dev sidecar keeps resolving `arduino-cli` from PATH exactly as before —
/// `boards/cli_tool.py` treats the env vars as a fallback below the Settings
/// override either way.
fn bundled_arduino_env<R: Runtime>(app: &AppHandle<R>) -> Vec<(&'static str, PathBuf)> {
    let Ok(resources) = app.path().resource_dir() else {
        return vec![];
    };
    let dir = resources.join("arduino");
    let cli = dir.join(if cfg!(windows) { "arduino-cli.exe" } else { "arduino-cli" });
    let data = dir.join("data");

    let mut env = vec![];
    if cli.exists() {
        env.push(("EPHYMERIS_BUNDLED_ARDUINO_CLI", cli));
    }
    if data.is_dir() {
        env.push(("EPHYMERIS_BUNDLED_ARDUINO_DATA_SEED", data));
    }
    env
}

pub fn spawn<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let launch = resolve_launch(app)?;

    // The cohort database belongs in the app's own data directory, beside
    // `settings.json` — not in the user's configured `dataDirectory`, which is
    // for browsable session output (`cohorts.md` §3). Resolved here so the
    // shell and the sidecar can't disagree about where that is.
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("could not resolve the app data directory: {e}"))?;

    log::info!(
        "spawning sidecar: {} {} --data-dir {}",
        launch.program.display(),
        launch.module_args.join(" "),
        data_dir.display()
    );

    let mut command = Command::new(&launch.program);
    command
        .args(&launch.module_args)
        .arg("--data-dir")
        .arg(&data_dir)
        .current_dir(&launch.cwd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    for (key, value) in bundled_arduino_env(app) {
        command.env(key, value);
    }

    // The frozen sidecar is a console binary (its stdout carries the
    // handshake), and a GUI parent spawning one on Windows would otherwise
    // flash a console window at every launch.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command
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
