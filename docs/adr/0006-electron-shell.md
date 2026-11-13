---
status: accepted
---

# The shell is Electron, not Tauri

Ephymeris has to keep running the lab's sessions for years after its author graduates, maintained by whoever is in the lab, who will most likely know Python and perhaps TypeScript but not Rust. The shell is small (about 700 lines of Rust: start and stop the sidecar, size the window, check for and install updates), but it is the one part nobody after the author could change, and it renders through a browser engine that Windows replaces underneath it. We decided to **replace the Tauri shell with an Electron shell written in TypeScript**, and to leave the sidecar, the webview and the wire as they are.

## The decision

- **Electron owns what the Rust shell owned, and nothing more.** It opens the frameless main window and the recording pop-ups, starts the sidecar and reads its handshake line, holds the sidecar's stdin open, stops it before an update and on exit, and offers the webview folder and save dialogs, file writes, open-in-file-manager, the settings store and the app version.
- **The webview reaches the shell through one module.** Today about 17 files import `@tauri-apps/*` directly. They move behind a single shell interface first, so the swap is one implementation behind it rather than 17 edits, and so the next shell change is too.
- **The sidecar does not change.** It still binds a loopback port, prints `EPHYMERIS_WS_PORT=… EPHYMERIS_WS_TOKEN=…`, and watches its stdin to notice a dead shell. Nothing in `protocol/schema.py` moves.
- **The installer stays NSIS for Windows**, built by `electron-builder`, carrying the same three resources: the frozen sidecar, `arduino-cli` with its seeded core, and the sketch library.
- **Updates keep their shape.** An installed copy asks a feed, downloads the installer, stops the sidecar, and hands over; the operator still clicks to install, and only when no session is running. `electron-updater` replaces Tauri's updater plugin.
- **An installed Tauri copy becomes an Electron copy by an ordinary update**, done once, with someone watching, on each lab PC. Its settings and data carry over.

## Why

- **The renderer stops changing.** Tauri draws with the PC's WebView2, which Windows updates on its own schedule, so a copy nobody has touched still gets a new browser engine every few weeks. Electron carries its own Chromium: a copy installed in 2027 draws the same in 2032.
- **One engine everywhere.** Development on macOS has been WebKit and the lab has been Chromium. With Electron both are the Chromium the installer carries.
- **One toolchain fewer.** Rebuilding needs Node and Python. Rust, cargo's dependency tree and the MSVC build tools go, along with CI's `cargo test` job.
- **The shell is in a language the webview already uses**, so whoever can change a page can change the shell.

## Considered options

- **Stay on Tauri.** It works, and its signed updater is proven. But it keeps Rust and the moving WebView2, the two things most likely to strand an unmaintained copy.
- **A Python shell (pywebview).** One language for shell and sidecar, and the one a successor is likeliest to know. It still draws with WebView2, and it has no updater: we would write and maintain our own.
- **No shell: the sidecar serves the webview to a browser.** The least code. But there is no self-update, no native folder dialog, and no window that owns the sidecar's life: an operator can close a tab mid-session, or open two.
- **Electron, updated by hand.** Dropping self-update removes the feed and CI from what has to keep working. Rejected for now, because fixes must still reach two PCs without the author present; it is the fallback if the update check below cannot be made sound.

## Consequences

- **The installer grows by roughly 100 MB and the app uses more memory.** Neither matters on two dedicated lab PCs.
- **The bundled Chromium is never patched unless someone rebuilds.** That is acceptable only because the webview loads its own pages and talks to its own sidecar on loopback. A feature that loads a remote page would reopen this decision.
- **Update authenticity changes, and has to be settled before the switch ships.** Tauri's updater refuses an installer whose signature does not match a public key in the app; losing the private key strands every copy. `electron-updater` checks an unsigned Windows installer by hash only, so what it trusts is HTTPS and the GitHub repository. `electron-builder` can instead sign the update manifest with a key the app carries, which restores the check and the key to lose. The migration's first step tries both on a real Windows PC and records which one ships; this ADR is amended with the answer.
- **The update address is baked into every copy.** Copies ask a URL under the author's personal account. If the repository is to move to a lab-owned home, it moves before the first Electron build ships, so that build carries the permanent address.
- **The verbatim-path rule goes away with the Rust shell.** `simplified()` exists because Tauri's `resource_dir()` returns `\\?\C:\…` on Windows, which `arduino-cli` silently mishandles. Electron's resource path is expected to be an ordinary one; the packaged build must compile a sketch on Windows before the rule is deleted.
- **The stop-before-install order must be rebuilt, not assumed.** The installer finds `arduino-cli.exe` locked unless the sidecar has finished its own shutdown first, and the download must be complete and checked before the sidecar is touched.
- **For one release there are two shells in the repository.** `src-tauri/` is deleted only after both lab PCs run the Electron build.
