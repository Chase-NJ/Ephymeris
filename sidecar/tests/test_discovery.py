"""Bundled sketch library discovery — `TASKS.md#sketch-library`.

The scan itself is unchanged from the configured-directory era; what changed is
where the root comes from (`library_root()`, not a setting) and what a non-ok
state MEANS — a broken install rather than a wrong setting. The tests point the
library at `tmp_path` through the developer override, which is also the only
way a test can exercise the scan without depending on this machine's staged
`<repo>/sketches`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.discovery import (
    BUNDLED_ENV,
    LIBRARY_ENV,
    MAX_SCAN_DEPTH,
    discover,
    library_root,
    library_status,
)


@pytest.fixture(autouse=True)
def _library_at_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test scans its own tmp_path, never this machine's real library."""
    monkeypatch.setenv(LIBRARY_ENV, str(tmp_path))


def make_sketch(root: Path, category: str, name: str, ino_name: str | None = None) -> Path:
    folder = root / category / name
    folder.mkdir(parents=True)
    (folder / f"{ino_name or name}.ino").write_text("void setup(){}\n", encoding="utf-8")
    return folder


# --- library states (`TASKS.md#library-states`) ----------------------------


def test_the_resolution_order_is_override_then_bundled_then_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundled = tmp_path / "from-shell"
    bundled.mkdir()
    monkeypatch.setenv(BUNDLED_ENV, str(bundled))

    # The developer override outranks the shell's bundled path…
    root, source = library_root()
    assert root == tmp_path
    assert source == "override"

    # …and the bundled path answers when the override is absent.
    monkeypatch.delenv(LIBRARY_ENV)
    root, source = library_root()
    assert root == bundled
    assert source == "bundled"


def test_a_verbatim_windows_path_is_simplified_before_it_reaches_arduino_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r"""A `\\?\C:\...` path from the shell must not reach `--libraries`.

    Tauri's `resource_dir()` is verbatim on Windows, so the exported bundled
    path carried the prefix. Python reads such a path perfectly well, which is
    why this went unnoticed: discovery reported a librariesPath, the compile
    ran, and arduino-cli — being Go — resolved no libraries under it and failed
    much later on `#include <BehaviorBox.h>`. Shipped in v1.1.0-rc.2.
    """
    monkeypatch.delenv(LIBRARY_ENV)
    monkeypatch.setenv(BUNDLED_ENV, "\\\\?\\" + str(tmp_path))

    root, source = library_root()
    assert source == "bundled"
    assert not str(root).startswith("\\\\?\\")
    assert root == tmp_path


def test_a_missing_library_is_damaged_and_points_at_reinstalling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(LIBRARY_ENV, str(tmp_path / "gone"))
    status = library_status()
    assert status.state == "damaged"
    assert "reinstall" in (status.message or "").lower()


def test_a_file_where_the_library_should_be_is_damaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "notadir"
    target.write_text("", encoding="utf-8")
    monkeypatch.setenv(LIBRARY_ENV, str(target))
    assert library_status().state == "damaged"


def test_a_library_with_no_valid_sketch_is_empty_not_damaged(tmp_path: Path) -> None:
    (tmp_path / "utility").mkdir()
    result = discover()
    assert result.library.state == "empty"
    # Empty can only mean a partial install now, and the message says so
    # rather than explaining a naming convention nobody here misapplied.
    assert "reinstall" in (result.library.message or "").lower()


def test_a_populated_library_is_ok(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    result = discover()
    assert result.library.state == "ok"
    assert result.library.source == "override"
    assert result.to_json()["skippedCount"] == 0


# --- sketch validity (`TASKS.md#folder-rules`) ----------------------------


def test_folder_name_must_match_the_ino_name(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    make_sketch(tmp_path, "utility", "broken", ino_name="main")

    result = discover()

    assert [s.name for s in result.sketches] == ["clean_flush"]
    assert len(result.skipped) == 1
    assert result.skipped[0].path.endswith("broken")


def test_skipped_folders_are_reported_not_silently_dropped(tmp_path: Path) -> None:
    """`TASKS.md#folder-rules` — a misnamed sketch must be discoverable, not just missing."""
    make_sketch(tmp_path, "shaping", "fr1_shaping")
    make_sketch(tmp_path, "shaping", "typo_sketch", ino_name="typo_sketchh")

    payload = discover().to_json()

    assert payload["skippedCount"] == 1
    assert "typo_sketch.ino" in payload["skipped"][0]["reason"]


def test_a_sketchless_folder_with_skips_is_still_empty(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "broken", ino_name="main")
    result = discover()
    assert result.library.state == "empty"
    assert len(result.skipped) == 1


# --- categories and libraries (`TASKS.md#folder-rules`) ------------------


def test_categories_are_not_a_fixed_enum(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    make_sketch(tmp_path, "some_new_paradigm", "novel_task")

    categories = {s.category for s in discover().sketches}

    assert categories == {"utility", "some_new_paradigm"}


@pytest.mark.parametrize("dirname", ["libraries", "Libraries", "LIBRARIES"])
def test_libraries_is_reserved_case_insensitively(tmp_path: Path, dirname: str) -> None:
    """Both target filesystems are case-insensitive by default (`TASKS.md#folder-rules`)."""
    make_sketch(tmp_path, "utility", "clean_flush")
    (tmp_path / dirname / "EphymerisStrobe").mkdir(parents=True)

    result = discover()

    assert result.libraries == ["EphymerisStrobe"]
    assert result.libraries_path is not None
    # Reserved: never treated as a category.
    assert all(s.category.lower() != "libraries" for s in result.sketches)


def test_libraries_path_is_absent_when_there_is_no_libraries_folder(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    result = discover()
    assert result.libraries_path is None
    assert result.libraries == []


def test_loose_files_at_the_root_are_ignored(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    (tmp_path / "README.md").write_text("notes", encoding="utf-8")

    result = discover()

    assert len(result.sketches) == 1
    assert result.skipped == []


# --- nested categories (`TASKS.md#folder-rules`) --------------------------


def test_sketches_nested_below_a_subcategory_are_found(tmp_path: Path) -> None:
    """Real lab trees group by paradigm *and* stage, not a flat two levels.

    The names here are synthetic: this exercises the SHAPE of the tree, and
    using the bundle's own names would make the test read as a claim about what
    ships.
    """
    make_sketch(tmp_path, "Olfactory Behavior/01_Early", "one_deep")
    make_sketch(tmp_path, "Olfactory Behavior/02_Later", "also_deep")
    make_sketch(tmp_path, "Utility", "shallow")

    result = discover()

    assert {s.name for s in result.sketches} == {"one_deep", "also_deep", "shallow"}
    assert result.skipped == []


def test_category_is_the_folder_directly_containing_the_sketch(tmp_path: Path) -> None:
    make_sketch(tmp_path, "Olfactory Behavior/01_Shaping", "shaping_GL")
    make_sketch(tmp_path, "Utility", "PRIME_Lines")

    by_name = {s.name: s.category for s in discover().sketches}

    assert by_name["shaping_GL"] == "01_Shaping"  # not "Olfactory Behavior"
    assert by_name["PRIME_Lines"] == "Utility"


def test_a_sketch_folder_is_not_descended_into(tmp_path: Path) -> None:
    """`src/`, `extras/` and friends belong to the sketch, not the tree."""
    sketch = make_sketch(tmp_path, "utility", "clean_flush")
    nested = sketch / "extras" / "host_test"
    nested.mkdir(parents=True)
    (nested / "host_test.ino").write_text("void setup(){}", encoding="utf-8")

    result = discover()

    assert [s.name for s in result.sketches] == ["clean_flush"]


def test_organisational_folders_without_sketches_are_not_reported(tmp_path: Path) -> None:
    """An empty grouping folder is not the same as a broken sketch."""
    make_sketch(tmp_path, "utility", "clean_flush")
    (tmp_path / "notes" / "scratch").mkdir(parents=True)

    assert discover().skipped == []


def test_a_misnamed_sketch_is_still_reported_when_nested(tmp_path: Path) -> None:
    make_sketch(tmp_path, "behavior/stage_one", "good_one")
    make_sketch(tmp_path, "behavior/stage_one", "bad_one", ino_name="main")

    result = discover()

    assert [s.name for s in result.sketches] == ["good_one"]
    assert len(result.skipped) == 1
    assert "bad_one.ino" in result.skipped[0].reason


def test_scanning_stops_at_a_sane_depth(tmp_path: Path) -> None:
    deep = tmp_path.joinpath(*[f"level{i}" for i in range(MAX_SCAN_DEPTH + 3)])
    deep.mkdir(parents=True)
    (deep / f"{deep.name}.ino").write_text("void setup(){}", encoding="utf-8")

    result = discover()

    assert result.sketches == []


# --- hidden folders and reserved names at depth ---------------------------


@pytest.mark.parametrize("hidden", [".git", ".claude", ".vscode"])
def test_hidden_folders_are_ignored_silently(tmp_path: Path, hidden: str) -> None:
    """`.git/objects` in a "couldn't be read" count buries real problems."""
    make_sketch(tmp_path, "utility", "clean_flush")
    junk = tmp_path / hidden / "objects"
    junk.mkdir(parents=True)
    (junk / "stray.ino").write_text("noise", encoding="utf-8")

    result = discover()

    assert [s.name for s in result.sketches] == ["clean_flush"]
    assert result.skipped == []


def test_nested_libraries_folders_are_reserved_but_not_passed_to_compile(
    tmp_path: Path,
) -> None:
    """Reserved at every depth; only the root one goes to `--libraries`."""
    make_sketch(tmp_path, "behavior/stage_one", "task")
    nested_lib = tmp_path / "behavior" / "libraries" / "SharedThing"
    nested_lib.mkdir(parents=True)
    (nested_lib / "SharedThing.h").write_text("#pragma once", encoding="utf-8")
    (tmp_path / "libraries" / "RootThing").mkdir(parents=True)

    result = discover()

    assert [s.name for s in result.sketches] == ["task"]
    # The nested libraries folder was never treated as a category…
    assert result.skipped == []
    # …and only the root one is offered to arduino-cli.
    assert result.libraries == ["RootThing"]
    assert result.libraries_path == str(tmp_path / "libraries")


def test_a_sketch_at_the_root_is_reported_rather_than_ignored(tmp_path: Path) -> None:
    stray = tmp_path / "loose_sketch"
    stray.mkdir()
    (stray / "loose_sketch.ino").write_text("void setup(){}", encoding="utf-8")
    make_sketch(tmp_path, "utility", "clean_flush")

    result = discover()

    assert [s.name for s in result.sketches] == ["clean_flush"]
    assert len(result.skipped) == 1
    assert "category folder" in result.skipped[0].reason


def test_symlink_cycles_do_not_hang_the_scan(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    loop = tmp_path / "utility" / "loop"
    loop.symlink_to(tmp_path / "utility", target_is_directory=True)

    result = discover()

    assert "clean_flush" in {s.name for s in result.sketches}
