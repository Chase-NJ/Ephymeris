# Arduino Directory — Full Spec

**Status:** Living document. Covers the configured Arduino Directory: location, detection, structure, and error handling.
**Companion documents:** `hardware-interaction.md` (flashing/reset/passthrough layer — consumes sketches discovered here), `ephymeris_v1.0.md` (tech stack, dashboard, Settings).

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
├── utility/                     ← a category
│   ├── clean_flush/
│   │   └── clean_flush.ino
│   └── prime_lines/
│       └── prime_lines.ino
├── shaping/                     ← another category
│   ├── fr1_shaping/
│   │   └── fr1_shaping.ino
│   └── ...
├── <any other category>/
└── libraries/                   ← reserved name, not a category
    ├── EphymerisStrobe/
    │   ├── EphymerisStrobe.h
    │   └── EphymerisStrobe.cpp
    └── ...
```

- **Category folders** sit at the root, one level deep, alongside the reserved `libraries/` folder. Category names are not hardcoded by the app — "utility" and "shaping" are examples, not a fixed enum. Any top-level folder other than `libraries/` (matched case-insensitively, since Windows and macOS filesystems are case-insensitive by default) is treated as a category.
- **Sketch validity** follows the standard Arduino convention: a folder is a valid sketch only if it contains a `.ino` file whose base filename matches the folder's own name (`clean_flush/clean_flush.ino`, not `clean_flush/main.ino`). This is arduino-cli's own requirement, not an app-specific rule — worth documenting here since it's the single most common cause of a sketch silently failing to appear.
- **Libraries** are plain folders under `libraries/`, each expected to contain matching `.h`/`.cpp` files by standard convention. Kept intentionally lightweight for v1 — not requiring a `library.properties` manifest, since these are internal shared headers, not published libraries. If a specific layout turns out to be needed for `arduino-cli` to resolve them correctly, that's an implementation-time detail to confirm against the real compile step, not something to over-specify here.

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
2. Enumerate top-level subfolders; set aside `libraries/` as reserved.
3. For every remaining top-level folder (a category), look one level deeper for sketch folders, applying the folder-name-matches-`.ino` rule from §3.
4. Folders that fail that rule are **skipped but reported**, not silently dropped — surfaced as a count in the UI (§6, Partial state) so a misnamed sketch is discoverable rather than mysteriously missing.
5. Result: a flat list of `{category, sketch_name, path}` sent to the frontend, naturally groupable by category for display.
6. Enumerate `libraries/` subfolders separately; the whole `libraries/` path is passed to `arduino-cli compile` via its `--libraries <path>` flag, so every sketch gets access to all shared libraries with no per-sketch configuration.

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

The per-machine decision lines up with an existing constraint from `hardware-interaction.md` (bundled `arduino:avr` core, no runtime internet dependency for flashing): the Arduino Directory is now confirmed local-disk-only too, so sketch/library discovery has no network dependency in any form, consistent with the "minimal internet requirements" target for lab PCs with no shared lab network.

No open questions remaining as of this revision.

---

## 8. Open Items / TBD

- [ ] Confirm real-world `arduino-cli --libraries` behavior against the `libraries/` folder layout in §3 once implementation starts
- [ ] Decide if a live filesystem watcher is worth adding later, or if scan-on-trigger remains sufficient
