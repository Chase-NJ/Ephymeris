mod sidecar;

use tauri::{LogicalSize, Manager, RunEvent, WebviewWindow};

/// Fractions of the display the window opens at.
const WIDTH_FRACTION: f64 = 4.0 / 5.0;
const HEIGHT_FRACTION: f64 = 4.0 / 5.0;

/// Mirrors `minWidth`/`minHeight` in `tauri.conf.json`. Duplicated rather than
/// read back from the config because clamping here keeps the result the same on
/// every platform instead of depending on the window backend enforcing it.
const MIN_WIDTH: f64 = 1024.0;
const MIN_HEIGHT: f64 = 700.0;

/// The opening size for a display of the given **logical** dimensions.
///
/// Split out from the window plumbing so the arithmetic — including the min
/// clamp, which is what actually bites on a small screen — is testable without
/// a live monitor.
fn opening_size(screen_width: f64, screen_height: f64) -> (f64, f64) {
    (
        (screen_width * WIDTH_FRACTION).max(MIN_WIDTH),
        (screen_height * HEIGHT_FRACTION).max(MIN_HEIGHT),
    )
}

/// Size the window against whichever display it opened on.
///
/// A fixed pixel size can't serve both the dev Mac and the lab PCs — the same
/// 1280x820 is most of one screen and a small square on another. The size in
/// `tauri.conf.json` stays as the fallback for when no monitor resolves.
fn size_to_display(window: &WebviewWindow) -> tauri::Result<()> {
    let Some(monitor) = window.current_monitor()?.or(window.primary_monitor()?) else {
        log::warn!("no monitor resolved; keeping the window size from the config");
        return Ok(());
    };

    // Monitor size is physical and the minimums are logical, so convert before
    // comparing them — on any HiDPI display the two aren't the same number.
    let screen = monitor.size().to_logical::<f64>(monitor.scale_factor());
    let (width, height) = opening_size(screen.width, screen.height);
    log::info!(
        "display is {}x{} logical; opening the window at {}x{}",
        screen.width.round(),
        screen.height.round(),
        width.round(),
        height.round()
    );

    window.set_size(LogicalSize::new(width, height))?;
    window.center()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_dialog::init())
        .manage(sidecar::SidecarState::default())
        .invoke_handler(tauri::generate_handler![sidecar::sidecar_endpoint])
        .setup(|app| {
            // The window is created hidden so this sizing never shows up as a
            // resize jump on launch. Show it either way — a window that stays
            // invisible because sizing failed is far worse than a wrong size.
            if let Some(window) = app.get_webview_window("main") {
                if let Err(err) = size_to_display(&window) {
                    log::warn!("could not size the window to the display: {err}");
                }
                let _ = window.show();
            }

            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // A failed spawn is reported to the frontend rather than aborting
            // startup: Settings must stay reachable when the sidecar won't run,
            // since a bad config is the likeliest reason it didn't.
            if let Err(err) = sidecar::spawn(app.handle()) {
                log::error!("sidecar failed to start: {err}");
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
            app_handle.state::<sidecar::SidecarState>().shutdown();
        }
    });
}
