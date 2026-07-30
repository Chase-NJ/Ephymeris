"""Arduino Directory discovery — `tasks.md` §2.2, §4, §6."""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.discovery import MAX_SCAN_DEPTH, discover, validate_directory


def make_sketch(root: Path, category: str, name: str, ino_name: str | None = None) -> Path:
    folder = root / category / name
    folder.mkdir(parents=True)
    (folder / f"{ino_name or name}.ino").write_text("void setup(){}\n")
    return folder


# --- §6 directory states --------------------------------------------------


def test_unset_path_is_not_configured_rather_than_an_error() -> None:
    assert validate_directory(None).state == "not_configured"
    assert validate_directory("").state == "not_configured"
    assert validate_directory("   ").state == "not_configured"


def test_missing_path_is_invalid(tmp_path: Path) -> None:
    status = validate_directory(str(tmp_path / "gone"))
    assert status.state == "invalid"
    assert "Can't find" in (status.message or "")


def test_file_instead_of_directory_is_invalid(tmp_path: Path) -> None:
    target = tmp_path / "notadir"
    target.write_text("")
    assert validate_directory(str(target)).state == "invalid"


def test_readable_but_sketchless_directory_is_empty_not_invalid(tmp_path: Path) -> None:
    (tmp_path / "utility").mkdir()
    result = discover(str(tmp_path))
    assert result.directory.state == "empty"
    # The empty state points at the naming convention rather than just saying
    # "nothing here" (§6).
    assert ".ino" in (result.directory.message or "")


def test_populated_directory_is_ok(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    result = discover(str(tmp_path))
    assert result.directory.state == "ok"
    assert result.to_json()["skippedCount"] == 0


# --- §3 sketch validity ---------------------------------------------------


def test_folder_name_must_match_the_ino_name(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    make_sketch(tmp_path, "utility", "broken", ino_name="main")

    result = discover(str(tmp_path))

    assert [s.name for s in result.sketches] == ["clean_flush"]
    assert len(result.skipped) == 1
    assert result.skipped[0].path.endswith("broken")


def test_skipped_folders_are_reported_not_silently_dropped(tmp_path: Path) -> None:
    """§4 step 4 — a misnamed sketch must be discoverable, not just missing."""
    make_sketch(tmp_path, "shaping", "fr1_shaping")
    make_sketch(tmp_path, "shaping", "typo_sketch", ino_name="typo_sketchh")

    payload = discover(str(tmp_path)).to_json()

    assert payload["skippedCount"] == 1
    assert "typo_sketch.ino" in payload["skipped"][0]["reason"]


def test_a_sketchless_folder_with_skips_is_still_empty(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "broken", ino_name="main")
    result = discover(str(tmp_path))
    assert result.directory.state == "empty"
    assert len(result.skipped) == 1


# --- §3 categories and libraries -----------------------------------------


def test_categories_are_not_a_fixed_enum(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    make_sketch(tmp_path, "some_new_paradigm", "novel_task")

    categories = {s.category for s in discover(str(tmp_path)).sketches}

    assert categories == {"utility", "some_new_paradigm"}


@pytest.mark.parametrize("dirname", ["libraries", "Libraries", "LIBRARIES"])
def test_libraries_is_reserved_case_insensitively(tmp_path: Path, dirname: str) -> None:
    """Both target filesystems are case-insensitive by default (§3)."""
    make_sketch(tmp_path, "utility", "clean_flush")
    (tmp_path / dirname / "EphymerisStrobe").mkdir(parents=True)

    result = discover(str(tmp_path))

    assert result.libraries == ["EphymerisStrobe"]
    assert result.libraries_path is not None
    # Reserved: never treated as a category.
    assert all(s.category.lower() != "libraries" for s in result.sketches)


def test_libraries_path_is_absent_when_there_is_no_libraries_folder(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    result = discover(str(tmp_path))
    assert result.libraries_path is None
    assert result.libraries == []


def test_loose_files_at_the_root_are_ignored(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    (tmp_path / "README.md").write_text("notes")

    result = discover(str(tmp_path))

    assert len(result.sketches) == 1
    assert result.skipped == []


# --- §3 nested categories -------------------------------------------------


def test_sketches_nested_below_a_subcategory_are_found(tmp_path: Path) -> None:
    """Real lab trees group by paradigm *and* stage, not a flat two levels."""
    make_sketch(tmp_path, "Olfactory Behavior/01_Shaping", "shaping_GL")
    make_sketch(tmp_path, "Olfactory Behavior/02_Bdisc", "GRGL_2-Odor")
    make_sketch(tmp_path, "Utility", "PRIME_Lines")

    result = discover(str(tmp_path))

    assert {s.name for s in result.sketches} == {"shaping_GL", "GRGL_2-Odor", "PRIME_Lines"}
    assert result.skipped == []


def test_category_is_the_folder_directly_containing_the_sketch(tmp_path: Path) -> None:
    make_sketch(tmp_path, "Olfactory Behavior/01_Shaping", "shaping_GL")
    make_sketch(tmp_path, "Utility", "PRIME_Lines")

    by_name = {s.name: s.category for s in discover(str(tmp_path)).sketches}

    assert by_name["shaping_GL"] == "01_Shaping"  # not "Olfactory Behavior"
    assert by_name["PRIME_Lines"] == "Utility"


def test_a_sketch_folder_is_not_descended_into(tmp_path: Path) -> None:
    """`src/`, `extras/` and friends belong to the sketch, not the tree."""
    sketch = make_sketch(tmp_path, "utility", "clean_flush")
    nested = sketch / "extras" / "host_test"
    nested.mkdir(parents=True)
    (nested / "host_test.ino").write_text("void setup(){}")

    result = discover(str(tmp_path))

    assert [s.name for s in result.sketches] == ["clean_flush"]


def test_organisational_folders_without_sketches_are_not_reported(tmp_path: Path) -> None:
    """An empty grouping folder is not the same as a broken sketch."""
    make_sketch(tmp_path, "utility", "clean_flush")
    (tmp_path / "notes" / "scratch").mkdir(parents=True)

    assert discover(str(tmp_path)).skipped == []


def test_a_misnamed_sketch_is_still_reported_when_nested(tmp_path: Path) -> None:
    make_sketch(tmp_path, "behavior/stage_one", "good_one")
    make_sketch(tmp_path, "behavior/stage_one", "bad_one", ino_name="main")

    result = discover(str(tmp_path))

    assert [s.name for s in result.sketches] == ["good_one"]
    assert len(result.skipped) == 1
    assert "bad_one.ino" in result.skipped[0].reason


def test_scanning_stops_at_a_sane_depth(tmp_path: Path) -> None:
    deep = tmp_path.joinpath(*[f"level{i}" for i in range(MAX_SCAN_DEPTH + 3)])
    deep.mkdir(parents=True)
    (deep / f"{deep.name}.ino").write_text("void setup(){}")

    result = discover(str(tmp_path))

    assert result.sketches == []


# --- hidden folders and reserved names at depth ---------------------------


@pytest.mark.parametrize("hidden", [".git", ".claude", ".vscode"])
def test_hidden_folders_are_ignored_silently(tmp_path: Path, hidden: str) -> None:
    """`.git/objects` in a "couldn't be read" count buries real problems."""
    make_sketch(tmp_path, "utility", "clean_flush")
    junk = tmp_path / hidden / "objects"
    junk.mkdir(parents=True)
    (junk / "stray.ino").write_text("noise")

    result = discover(str(tmp_path))

    assert [s.name for s in result.sketches] == ["clean_flush"]
    assert result.skipped == []


def test_nested_libraries_folders_are_reserved_but_not_passed_to_compile(
    tmp_path: Path,
) -> None:
    """Reserved at every depth; only the root one goes to `--libraries`."""
    make_sketch(tmp_path, "behavior/stage_one", "task")
    nested_lib = tmp_path / "behavior" / "libraries" / "SharedThing"
    nested_lib.mkdir(parents=True)
    (nested_lib / "SharedThing.h").write_text("#pragma once")
    (tmp_path / "libraries" / "RootThing").mkdir(parents=True)

    result = discover(str(tmp_path))

    assert [s.name for s in result.sketches] == ["task"]
    # The nested libraries folder was never treated as a category…
    assert result.skipped == []
    # …and only the root one is offered to arduino-cli.
    assert result.libraries == ["RootThing"]
    assert result.libraries_path == str(tmp_path / "libraries")


def test_a_sketch_at_the_root_is_reported_rather_than_ignored(tmp_path: Path) -> None:
    stray = tmp_path / "loose_sketch"
    stray.mkdir()
    (stray / "loose_sketch.ino").write_text("void setup(){}")
    make_sketch(tmp_path, "utility", "clean_flush")

    result = discover(str(tmp_path))

    assert [s.name for s in result.sketches] == ["clean_flush"]
    assert len(result.skipped) == 1
    assert "category folder" in result.skipped[0].reason


def test_symlink_cycles_do_not_hang_the_scan(tmp_path: Path) -> None:
    make_sketch(tmp_path, "utility", "clean_flush")
    loop = tmp_path / "utility" / "loop"
    loop.symlink_to(tmp_path / "utility", target_is_directory=True)

    result = discover(str(tmp_path))

    assert "clean_flush" in {s.name for s in result.sketches}
