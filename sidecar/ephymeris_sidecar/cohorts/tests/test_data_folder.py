"""Data folder resolution — `DATA.md#data-folder`."""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.folders import (
    DataFolderError,
    ensure_folder,
    relocate,
    resolve_default_folder,
    sanitize_name,
)


# --- naming ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Batch A", "Batch A"),
        ("Cohort/2024", "Cohort-2024"),      # path separators can't survive
        ("a:b*c?d", "a-b-c-d"),              # Windows-illegal characters
        ("  padded  ", "padded"),
        ("...", "cohort"),                    # nothing usable left
        ("", "cohort"),
    ],
)
def test_sanitize_produces_a_safe_single_segment(raw: str, expected: str) -> None:
    assert sanitize_name(raw) == expected


def test_sanitize_caps_absurd_lengths() -> None:
    assert len(sanitize_name("x" * 500)) <= 64


# --- default resolution ---------------------------------------------------


def test_default_is_data_directory_plus_sanitized_name(tmp_path: Path) -> None:
    assert resolve_default_folder(str(tmp_path), "Batch A") == tmp_path / "Batch A"


def test_collisions_get_a_numeric_suffix(tmp_path: Path) -> None:
    (tmp_path / "Batch A").mkdir()
    assert resolve_default_folder(str(tmp_path), "Batch A") == tmp_path / "Batch A-2"

    (tmp_path / "Batch A-2").mkdir()
    assert resolve_default_folder(str(tmp_path), "Batch A") == tmp_path / "Batch A-3"


def test_an_unset_data_directory_is_an_error_not_a_guess() -> None:
    """There's no basis for a default, and inventing one hides the data."""
    with pytest.raises(DataFolderError) as exc:
        resolve_default_folder(None, "Batch A")
    assert "Settings" in str(exc.value)

    with pytest.raises(DataFolderError):
        resolve_default_folder("   ", "Batch A")


def test_ensure_folder_creates_nested_paths(tmp_path: Path) -> None:
    target = ensure_folder(tmp_path / "a" / "b" / "c")
    assert target.is_dir()


def test_ensure_folder_rejects_a_file(tmp_path: Path) -> None:
    victim = tmp_path / "not-a-dir"
    victim.write_text("", encoding="utf-8")
    with pytest.raises(DataFolderError):
        ensure_folder(victim)


# --- relocate (`DATA.md#data-folder`) -------------------------------------


def test_relocate_moves_contents_when_asked(tmp_path: Path) -> None:
    source = tmp_path / "old"
    source.mkdir()
    (source / "session.json").write_text("{}", encoding="utf-8")
    destination = tmp_path / "new"

    result = relocate(source, destination, move_existing=True)

    assert result == destination
    assert (destination / "session.json").read_text(encoding="utf-8") == "{}"
    assert not source.exists()


def test_relocate_without_moving_just_creates_the_destination(tmp_path: Path) -> None:
    source = tmp_path / "old"
    source.mkdir()
    (source / "keep.txt").write_text("still here", encoding="utf-8")
    destination = tmp_path / "new"

    relocate(source, destination, move_existing=False)

    assert destination.is_dir()
    # The old contents are deliberately left where they are.
    assert (source / "keep.txt").exists()


def test_relocate_refuses_a_non_empty_destination(tmp_path: Path) -> None:
    """`DATA.md#data-folder` — fails safely rather than merging into or overwriting."""
    source = tmp_path / "old"
    source.mkdir()
    (source / "a.txt").write_text("source", encoding="utf-8")
    destination = tmp_path / "new"
    destination.mkdir()
    (destination / "existing.txt").write_text("do not clobber", encoding="utf-8")

    with pytest.raises(DataFolderError) as exc:
        relocate(source, destination, move_existing=True)

    assert "isn't empty" in str(exc.value)
    assert (destination / "existing.txt").read_text(encoding="utf-8") == "do not clobber"
    assert (source / "a.txt").exists()


def test_relocate_attaches_to_an_archive_that_is_already_full(tmp_path: Path) -> None:
    """`DATA.md#data-folder` — the *other* intent: point a cohort at data that is already there.

    This is how a cohort adopts an archive written before this app existed
    (`DATA.md#orphan-adoption`), so the destination is *expected* to be full.
    Refusing a non-empty destination here made that impossible to express: the
    only control for it rejected exactly the folders it was meant to accept.
    """
    source = tmp_path / "D_drive" / "The Remy's"  # the old path, long gone
    destination = tmp_path / "K_drive" / "Remy"
    (destination / "01_2O-Bdisc").mkdir(parents=True)
    (destination / "01_2O-Bdisc" / "run.json").write_text("{}", encoding="utf-8")

    assert relocate(source, destination, move_existing=False) == destination
    # Nothing was written, moved, or cleared — only a path was chosen.
    assert (destination / "01_2O-Bdisc" / "run.json").read_text(encoding="utf-8") == "{}"
    assert not source.exists()


def test_relocate_into_an_existing_empty_folder_does_not_nest(tmp_path: Path) -> None:
    """shutil.move would otherwise put `old/` *inside* `new/`."""
    source = tmp_path / "old"
    source.mkdir()
    (source / "a.txt").write_text("x", encoding="utf-8")
    destination = tmp_path / "new"
    destination.mkdir()

    relocate(source, destination, move_existing=True)

    assert (destination / "a.txt").exists()
    assert not (destination / "old").exists()


def test_relocating_onto_itself_is_a_no_op(tmp_path: Path) -> None:
    source = tmp_path / "same"
    source.mkdir()
    (source / "a.txt").write_text("x", encoding="utf-8")

    assert relocate(source, source, move_existing=True) == source
    assert (source / "a.txt").exists()


def test_relocate_rejects_a_file_destination(tmp_path: Path) -> None:
    source = tmp_path / "old"
    source.mkdir()
    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")

    with pytest.raises(DataFolderError):
        relocate(source, blocker, move_existing=True)
