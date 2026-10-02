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
    // Simplified like the rest: the verbatim form spawns fine, but it also
    // becomes the sidecar's own cwd and shows up in every process listing.
    let resources = simplified(app.path().resource_dir().ok()?);
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

/// Drop Windows' verbatim (`\\?\`) prefix when what's left is still an ordinary
/// path — the same policy the `dunce` crate calls "simplified".
///
/// **Load-bearing, not cosmetic.** `resource_dir()` hands back a verbatim path
/// on Windows, and every path built from it inherits the prefix. Windows APIs
/// accept that, so the sidecar spawns and Python reads the directories happily —
/// but `arduino-cli` is Go, and a verbatim path given to `--libraries` resolves
/// to nothing. The failure has no symptom at that layer: the compile runs, the
/// library is silently absent, and the sketch fails on `#include <BehaviorBox.h>`
/// as though the library were missing from the install. Shipped as v1.1.0-rc.2.
///
/// Only `\\?\C:\…` is simplified. A verbatim UNC path (`\\?\UNC\…`) is left
/// exactly as it came: rewriting one is a different transformation, and the
/// prefix is load-bearing for paths past `MAX_PATH`, which is the one case
/// where dropping it would break something that currently works.
fn simplified(path: PathBuf) -> PathBuf {
    use std::path::{Component, Prefix};

    let verbatim_disk = matches!(
        path.components().next(),
        Some(Component::Prefix(prefix)) if matches!(prefix.kind(), Prefix::VerbatimDisk(_))
    );
    if !verbatim_disk {
        return path;
    }
    match path.as_os_str().to_string_lossy().strip_prefix(r"\\?\") {
        // Past MAX_PATH the prefix is what makes the path usable at all.
        Some(rest) if rest.len() < 260 => PathBuf::from(rest),
        _ => path,
    }
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
    let dir = simplified(resources.join("arduino"));
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

/// The bundled sketch library, exported the same way.
///
/// Absent in a dev run (no staged resources), where the sidecar falls back to
/// `<repo>/sketches`, staged by `npm run predev` — see `discovery.library_root()`
/// for the full resolution order, including the `EPHYMERIS_SKETCH_LIBRARY`
/// developer override that outranks both.
fn bundled_sketches_env<R: Runtime>(app: &AppHandle<R>) -> Vec<(&'static str, PathBuf)> {
    let Ok(resources) = app.path().resource_dir() else {
        return vec![];
    };
    // Simplified before export: this one is handed to `arduino-cli --libraries`
    // via the sidecar, and Go does not resolve a verbatim path (see `simplified`).
    let dir = simplified(resources.join("sketches"));
    if dir.is_dir() {
        vec![("EPHYMERIS_BUNDLED_SKETCHES", dir)]
    } else {
        vec![]
    }
}

pub fn spawn<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let launch = resolve_launch(app)?;

    // The cohort database belongs in the app's own data directory, beside
    // `settings.json` — not in the user's configured `dataDirectory`, which is
    // for browsable session output (`DATA.md#layout`). Resolved here so the
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

    // **The sidecar reads and writes UTF-8 on a machine whose locale isn't.**
    //
    // Python picks its default text encoding from the locale at interpreter
    // startup, which on the lab's Windows 11 boxes is cp1252 — so a task spec
    // carrying an em dash in a `note:`, or a µ in a duration, decodes to
    // mojibake or raises UnicodeDecodeError on a file the app itself wrote.
    // Set before spawn because the interpreter reads it before any of our code
    // runs; nothing in conftest or `main()` can fix it after the fact.
    command.env("PYTHONUTF8", "1");

    for (key, value) in bundled_arduino_env(app) {
        command.env(key, value);
    }
    for (key, value) in bundled_sketches_env(app) {
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

    /// `resource_dir()` returns a verbatim path on Windows, and everything
    /// built from it inherits the prefix. arduino-cli is Go and resolves
    /// nothing under one, so a bundled `--libraries` silently found no
    /// libraries and the compile failed on the include (v1.1.0-rc.2).
    #[cfg(windows)]
    #[test]
    fn strips_the_verbatim_prefix_from_a_drive_path() {
        assert_eq!(
            simplified(PathBuf::from(r"\\?\C:\Users\lab\Ephymeris\sketches")),
            PathBuf::from(r"C:\Users\lab\Ephymeris\sketches")
        );
    }

    #[cfg(windows)]
    #[test]
    fn leaves_ordinary_and_unc_paths_alone() {
        // Nothing to strip.
        assert_eq!(
            simplified(PathBuf::from(r"C:\Users\lab\sketches")),
            PathBuf::from(r"C:\Users\lab\sketches")
        );
        // A verbatim UNC path is a different transformation; don't guess at it.
        assert_eq!(
            simplified(PathBuf::from(r"\\?\UNC\server\share\sketches")),
            PathBuf::from(r"\\?\UNC\server\share\sketches")
        );
    }

    /// Past MAX_PATH the prefix is what makes the path usable at all, so the
    /// one case where stripping would break something keeps it.
    #[cfg(windows)]
    #[test]
    fn keeps_the_prefix_on_a_path_past_max_path() {
        let long = format!(r"\\?\C:\{}", "segment\\".repeat(40));
        assert_eq!(simplified(PathBuf::from(&long)), PathBuf::from(&long));
    }
}
