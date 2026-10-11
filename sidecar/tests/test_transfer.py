"""The verified copy both transfers use — `DATA.md#verified-transfer`.

What it must never do: delete the only copy of a file's content, or leave a
partial file under a real name.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts import transfer
from ephymeris_sidecar.cohorts.transfer import FileCopy


def pair(tmp_path: Path, name: str = "run.json", body: bytes = b"ts_data") -> FileCopy:
    src = tmp_path / "from" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(body)
    return FileCopy(src, tmp_path / "to" / "deep" / name)


def test_a_copy_is_verified_and_carries_its_hash(tmp_path: Path) -> None:
    f = pair(tmp_path)
    [done] = transfer.copy([f])
    assert f.dst.read_bytes() == b"ts_data"
    assert done.sha256 == transfer.digest(f.src)[1]
    assert not transfer.part_of(f.dst).exists()


def test_a_crash_mid_copy_leaves_only_a_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = pair(tmp_path)

    def half(src: str, dst: str, **_kwargs: object) -> str:
        Path(dst).write_bytes(Path(src).read_bytes()[:2])
        raise SystemExit("power cut")

    monkeypatch.setattr(shutil, "copy2", half)
    with pytest.raises(SystemExit):
        transfer.copy([f])
    assert not f.dst.exists()
    assert transfer.part_of(f.dst).exists()

    transfer.undo([f])
    assert not transfer.part_of(f.dst).exists()
    assert f.src.read_bytes() == b"ts_data"


def test_a_differing_destination_is_never_overwritten(tmp_path: Path) -> None:
    f = pair(tmp_path)
    f.dst.parent.mkdir(parents=True)
    f.dst.write_bytes(b"someone else's")
    with pytest.raises(OSError, match="differs"):
        transfer.copy([f])
    assert f.dst.read_bytes() == b"someone else's"


def test_an_identical_destination_is_left_as_it_is(tmp_path: Path) -> None:
    f = pair(tmp_path)
    f.dst.parent.mkdir(parents=True)
    f.dst.write_bytes(b"ts_data")
    os.utime(f.dst, ns=(1, 1))
    transfer.copy([f])
    assert f.dst.stat().st_mtime_ns == 1


def test_a_copy_that_changed_on_the_way_is_refused(tmp_path: Path) -> None:
    f = FileCopy(pair(tmp_path).src, tmp_path / "to" / "run.json", sha256="0" * 64)
    with pytest.raises(OSError, match="verify"):
        transfer.copy([f])


def test_undo_keeps_a_copy_whose_original_is_gone_or_changed(tmp_path: Path) -> None:
    gone = transfer.copy([pair(tmp_path, "gone.json")])[0]
    changed = transfer.copy([pair(tmp_path, "changed.json")])[0]
    gone.src.unlink()
    changed.src.write_bytes(b"edited since")

    transfer.undo([gone, changed])
    transfer.undo([FileCopy(gone.src, gone.dst), FileCopy(changed.src, changed.dst)])

    assert gone.dst.is_file() and changed.dst.is_file()


def test_an_original_goes_only_while_its_copy_is_there_and_the_same(tmp_path: Path) -> None:
    kept_missing = transfer.copy([pair(tmp_path, "missing.json")])[0]
    kept_changed = transfer.copy([pair(tmp_path, "changed.json")])[0]
    deleted = transfer.copy([pair(tmp_path, "fine.json")])[0]
    kept_missing.dst.unlink()  # the hash is known, but the copy is not there
    kept_changed.src.write_bytes(b"written after the copy")

    touched = transfer.delete_originals([kept_missing, kept_changed, deleted])

    assert kept_missing.src.is_file()
    assert kept_changed.src.is_file()
    assert not deleted.src.exists()
    assert touched == {deleted.src.parent}


def test_a_restart_with_no_hashes_compares_the_two_files(tmp_path: Path) -> None:
    f = transfer.copy([pair(tmp_path)])[0]
    transfer.delete_originals([FileCopy(f.src, f.dst)])
    assert not f.src.exists()
    assert f.dst.read_bytes() == b"ts_data"
