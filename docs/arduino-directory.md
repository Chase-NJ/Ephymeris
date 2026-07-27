# Arduino Directory

> **Status** · Living spec — **Built and verified against real compiles.** Discovery, all four states in §6, the categorized picker, and `--libraries` resolution are live.
>
> **Owns** · Where flashable sketches come from: the configured root folder, its required structure, how it is scanned, and what each failure looks like.
>
> **Read with** · [hardware-interaction.md](hardware-interaction.md) (consumes the sketches discovered here) · [websocket-protocol.md](websocket-protocol.md) (the `sketches.refresh` / `sketches.updated` payloads)
>
> **Still open** · Whether a live filesystem watcher is ever worth adding

**Contents** — [1. Purpose](#1-purpose) · [2. Location](#2-location--configuration) · [3. Required Structure](#3-required-directory-structure) · [4. Discovery](#4-sketch-discovery) · [5. Presentation](#5-gui-presentation) · [6. Error & Empty States](#6-error--empty-states) · [7. Resolved Decisions](#7-resolved-decisions) · [8. Open Items](#8-open-items--tbd)

> **The rule that causes the most confusion, stated once up front:** a folder is a valid sketch **only if it contains a `.ino` whose filename matches the folder's own name** — `clean_flush/clean_flush.ino`, never `clean_flush/main.ino`. This is arduino-cli's requirement, not ours, and it is far and away the most common reason a sketch a user just wrote fails to appear in the picker. Folders that fail it are **skipped and reported**, never silently dropped.

---

## 1. Purpose

Today, `hardware-interaction.md` §4 describes flashing as the user browsing to an arbitrary sketch file each time. This doc replaces that with something more useful for a lab running the same rotating set of sketches repeatedly: a single **configured root folder** that the app scans, categorizes, and presents as a browsable list — with shared libraries resolved automatically at compile time.

---

## 2. Location & Configuration

- No default path is shipped or assumed. The user sets the Arduino Directory explicitly via a **Settings** field (native OS directory picker, Tauri-provided).
- Persisted in the Tauri-side settings store (per `ephymeris_v1.0.md` §4.5) and pushed to the Python sidecar on connect/change, same as every other setting.
- On receipt, the sidecar validates the path (exists, is a directory, readable) and reports back one of the states defined in §6 — validation is immediate, not deferred until the user opens Debug Mode.

---

## 3. Required Directory Structure

```
<ArduinoDirectory>/
├── Utility/                     ← a category
│   └── BOX_Utility/
│       ├── BOX_Utility.ino
│       └── task.json            ← optional; makes it app-drivable (data-saving.md §6)
├── Olfactory Behavior/          ← a category holding sub-categories
│   ├── 01_Shaping/              ← a sub-category
│   │   ├── shaping_GL/
│   │   │   └── shaping_GL.ino
│   │   └── shaping_GR/
│   │       └── shaping_GR.ino
│   └── 02_Bdisc/                ← another sub-category
│       ├── GRGL_2-Odor/
│       │   └── GRGL_2-Odor.ino
│       └── libraries/           ← reserved at any depth; not passed to compile
├── <any other category>/
└── libraries/                   ← reserved name, not a category
    ├── EphymerisStrobe/
    │   ├── EphymerisStrobe.h
    │   └── EphymerisStrobe.cpp
    └── ...
```

- **Category folders** sit at the root alongside the reserved `libraries/` folder. Category names are not hardcoded by the app — "Utility" and "Olfactory Behavior" are examples, not a fixed enum. Any top-level folder other than `libraries/` (matched case-insensitively, since Windows and macOS filesystems are case-insensitive by default) is treated as a category.
- **Categories may nest.** Sketches are *not* required to sit exactly one level below the root: the scan descends through sub-category folders until it finds sketches. Lab directories organise by paradigm *and* stage (`Olfactory Behavior/01_Shaping/shaping_GL/`), and a fixed two-level rule silently hides everything deeper. A sketch's **category is the folder that directly contains it** — `shaping_GL` is filed under `01_Shaping`, not `Olfactory Behavior`. Scanning stops at a bounded depth so pointing the app at an unexpectedly large tree can't crawl.
- **A sketch folder is never descended into.** Once a folder is recognised as a valid sketch, its contents (`src/`, `extras/`, …) belong to that sketch and are not scanned for further sketches.
- **Hidden folders are ignored silently** — anything beginning with `.` (`.git/`, `.claude/`, `.vscode/`). They are not sketches, and reporting `.git/objects` as unreadable would bury genuine problems in noise.
- **Sketches must live inside a category.** A valid sketch folder sitting directly at the root is reported as skipped rather than silently ignored, since it has no category to be filed under.
- **Sketch validity** follows the standard Arduino convention: a folder is a valid sketch only if it contains a `.ino` file whose base filename matches the folder's own name (`clean_flush/clean_flush.ino`, not `clean_flush/main.ino`). This is arduino-cli's own requirement, not an app-specific rule — worth documenting here since it's the single most common cause of a sketch silently failing to appear.
- **Libraries** are plain folders under `libraries/`, each expected to contain matching `.h`/`.cpp` files by standard convention. Kept intentionally lightweight for v1 — not requiring a `library.properties` manifest, since these are internal shared headers, not published libraries. **Confirmed against arduino-cli 1.5.1** (§8): this layout resolves correctly.
- **`libraries/` is reserved at every depth**, not just the root — a nested `.../libraries/` is never scanned as a category or a sketch. Only the **root** `libraries/` is passed to `arduino-cli --libraries`, so every sketch sees exactly one shared collection with no per-sketch configuration. Shared headers therefore live **directly** in the root `libraries/` (e.g. `libraries/BehaviorBox/BehaviorBox.h`, the single header every sketch includes). A real folder is preferred over a symlink from the root into a nested collection — symlinks are fragile on the Windows lab machines and only the root path is handed to the compiler anyway.

---

## 4. Sketch Discovery

Ownership: the Python sidecar performs discovery (filesystem + `arduino-cli` interaction already lives there per the established architecture).

**Trigger points:**
- Immediately when the Arduino Directory setting is set or changed.
- On-demand via a manual "Refresh" affordance in Settings and/or Debug Mode.
- Automatically on Debug Mode mount, so newly added sketches show up without requiring an explicit refresh.

No live filesystem watcher for v1 (e.g. no `watchdog`-style continuous monitoring) — scan-on-trigger is enough for how often lab sketches actually change, and it avoids adding a background process for marginal benefit. Worth revisiting if that assumption turns out wrong (see §8).

**Algorithm:**
1. Validate the root path (§6).
2. Enumerate top-level subfolders; set aside the root `libraries/` as reserved, and ignore hidden folders.
3. For every remaining top-level folder (a category), descend looking for sketch folders, applying the folder-name-matches-`.ino` rule from §3. A folder that is itself a valid sketch is recorded (category = its parent) and not descended into; a folder that holds no `.ino` is treated as a sub-category and scanned one level deeper, up to a bounded depth.
4. Folders that **contain an `.ino` but none matching the folder's own name** are **skipped but reported**, not silently dropped — surfaced as a count in the UI (§6, Partial state) so a misnamed sketch is discoverable rather than mysteriously missing. A folder holding no `.ino` at all is plain organisation, not a broken sketch, and is not reported.
5. Result: a flat list of `{category, sketch_name, path}` sent to the frontend, naturally groupable by category for display.
6. Enumerate the root `libraries/` subfolders separately; that path is passed to `arduino-cli compile` via its `--libraries <path>` flag, so every sketch gets access to all shared libraries with no per-sketch configuration.

**Bounds and safety.** The scan descends at most **5 levels**, so pointing the app at an unexpectedly large tree cannot crawl. Symlinks are followed, but every directory is resolved and recorded, so a symlink loop terminates and a directory reachable by two paths is only reported once.

**The three reported skip reasons**, all surfaced with their path so the problem is inspectable rather than mysterious:

| Reason | Meaning |
|---|---|
| `no <name>.ino matching the folder name` | The folder holds some `.ino`, just not the one arduino-cli needs |
| `sketch folders belong inside a category folder` | A valid sketch sitting directly at the root, with no category to file it under |
| `couldn't be read: <error>` | Permissions or an I/O failure on that directory |

Hidden folders and any `libraries/` are skipped **silently** — they are not mistakes, and reporting `.git/objects` as unreadable would bury the genuine problems in noise. A folder holding no `.ino` at all is plain organisation, not a broken sketch, and is likewise not reported.

---

## 5. GUI Presentation

The Debug Mode / flashing flow (`hardware-interaction.md` §4) presents a **categorized list** of detected sketches — grouped by category, sourced from this discovery process. This is the only path to a flashable sketch for v1: no arbitrary "browse outside the Arduino Directory" fallback. Keeping a single source of truth also makes the error/empty states in §6 unambiguous — there's never a question of which sketch a user actually flashed.

---

## 6. Error & Empty States

Four distinct states, surfaced clearly rather than collapsed into a single generic "error":

| State | Condition | UI Treatment |
|---|---|---|
| **Not configured** | No Arduino Directory set yet | Prompt to configure, with a direct link into Settings — this is expected on first run, not an error |
| **Invalid path** | Configured path doesn't exist / isn't a directory / isn't readable (moved, deleted, permissions changed) | Clear error: "Can't find your configured Arduino Directory," link back to Settings to fix |
| **Valid but empty** | Path is readable, but zero valid sketches found (no category folders, or none contain a validly-named sketch) | Distinct empty state, not an error — in the interface's voice, pointing at the naming convention from §3 rather than just saying "nothing here" |
| **Partial** | Some valid sketches found, but some folders were skipped for invalid structure | Non-blocking — sketch list populates normally, with a small "N items couldn't be read" note (from §4 step 4) |

---

## 7. Resolved Decisions

| Decision | Outcome |
|---|---|
| Arbitrary sketch fallback | **No** — the configured Arduino Directory is the only source for v1 (§5) |
| Shared vs. per-machine directory | **Per-machine** — each lab PC has its own independently-configured local directory, no network dependency |
| Category nesting | **Supported** — the scan descends until it finds sketches rather than assuming a fixed two-level shape (§3). Driven by a real lab directory where half the sketches sat at `category/sub-category/sketch` and were invisible under the original rule |
| Category label when nested | **The folder directly containing the sketch** — `shaping_GL` files under `01_Shaping`, not `Olfactory Behavior` (§3) |
| Nested `libraries/` folders | **Reserved at every depth, but only the root one is passed to `--libraries`** (§3). Keeps every sketch compiling against one predictable library set; put shared headers directly in the root `libraries/` (a real folder, not a symlink from the root into a nested collection) |

The per-machine decision lines up with an existing constraint from `hardware-interaction.md` (bundled `arduino:avr` core, no runtime internet dependency for flashing): the Arduino Directory is now confirmed local-disk-only too, so sketch/library discovery has no network dependency in any form, consistent with the "minimal internet requirements" target for lab PCs with no shared lab network.

No open questions remaining as of this revision.

---

## 8. Open Items / TBD

- [x] ~~Confirm real-world `arduino-cli --libraries` behavior against the `libraries/` folder layout in §3~~ — **confirmed** (arduino-cli 1.5.1): a sketch `#include <EphymerisStrobe.h>` compiled against a plain `libraries/EphymerisStrobe/` folder holding matching `.h`/`.cpp` files with no `library.properties`; the compile result's `used_libraries` reported the library resolved from that exact path. The §3 lightweight layout stands as specified
- [ ] Decide if a live filesystem watcher is worth adding later, or if scan-on-trigger remains sufficient. Judged sufficient so far — revisit only if that assumption proves wrong in practice

---

**Next:** [cohorts.md](cohorts.md) → [starting-a-session.md](starting-a-session.md) → [data-saving.md](data-saving.md) — three interdependent documents, in dependency order.
[Documentation index](README.md) · [Open items register](TODO.md)
