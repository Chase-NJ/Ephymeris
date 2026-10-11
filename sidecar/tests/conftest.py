"""Suite-wide test configuration.

Turns on wire-shape validation (`protocol.wire_validation_enabled`) for every
test: any event built via `protocol.event()` — the runner, backup manager, and
analytics service all go through it — and any command reply dispatched through
`SidecarServer` is checked against `protocol/schema.py` and fails loudly on
drift. Production leaves this off, so a benign schema lag can never take down
a live session.

Also fixtures that fake the filesystem boundary, so a test reaches a failure
through the code's real path rather than by replacing one of its steps:
`coarse_volume` rounds mtimes, `hung_volume` stops answering mid-copy,
`other_volume` is a second device a folder can't be renamed onto,
`unreachable_volume` can't be read at all, and `power_cut` kills the process
at the nth copy or delete below a folder.
"""

from __future__ import annotations

import errno
import os
import shutil
import threading
from pathlib import Path

import pytest

os.environ.setdefault("EPHYMERIS_WIRE_VALIDATE", "1")


@pytest.fixture
def coarse_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every `shutil.copy2` lands on a volume that keeps mtimes to 10 ms, as
    exFAT does: the copy's stat is not the original's. A temp dir is one
    volume, so this is the only way a test sees it."""
    real = shutil.copy2

    def copy2(src, dst, *, follow_symlinks=True):  # noqa: ANN001, ANN202
        out = real(src, dst, follow_symlinks=follow_symlinks)
        st = os.stat(out)
        os.utime(out, ns=(st.st_atime_ns, st.st_mtime_ns - st.st_mtime_ns % 10_000_000))
        return out

    monkeypatch.setattr(shutil, "copy2", copy2)


class HungVolume:
    """A volume that stopped answering: a copy onto it blocks until `release()`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        #: Set once a copy is stuck on this volume.
        self.entered = threading.Event()
        self._released = threading.Event()
        self._stuck = 0

    @property
    def stuck(self) -> bool:
        """A copy is waiting on the volume right now. Asserting this after the
        thing under test finished is what proves it did not wait for the copy:
        code that did wait would only get there once the safety timeout let go."""
        return self._stuck > 0

    def release(self) -> None:
        self._released.set()


@pytest.fixture
def hung_volume(monkeypatch: pytest.MonkeyPatch):
    """`hung_volume(root)`: every `shutil.copy2` onto `root` hangs until released,
    as a network share does when it goes away mid-copy. Released at teardown
    whatever the test did, so a failing test can't leave a thread stuck."""
    volumes: list[HungVolume] = []
    real = shutil.copy2

    def copy2(src, dst, *, follow_symlinks=True):  # noqa: ANN001, ANN202
        for volume in volumes:
            if Path(dst).is_relative_to(volume.root):
                volume._stuck += 1
                volume.entered.set()
                try:
                    if not volume._released.wait(timeout=10):
                        volume.release()  # the safety timeout: the share comes back for good
                finally:
                    volume._stuck -= 1
        return real(src, dst, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(shutil, "copy2", copy2)

    def hang(root: Path) -> HungVolume:
        volume = HungVolume(root)
        volumes.append(volume)
        return volume

    yield hang
    for volume in volumes:
        volume.release()


class _StatOnAnotherDevice:
    """`os.stat`'s result for a path on the other volume: every field the
    same but the device."""

    def __init__(self, st: os.stat_result) -> None:
        self._st = st

    @property
    def st_dev(self) -> int:
        return self._st.st_dev + 1

    def __getattr__(self, name: str):  # noqa: ANN204
        return getattr(self._st, name)


@pytest.fixture
def other_volume(monkeypatch: pytest.MonkeyPatch):
    """`other_volume(root)`: `root` is the mount point of a second volume, so a
    folder can't be renamed onto it and has to be copied. A temp dir is one
    volume; this fakes the device number `os.stat` reports below `root`."""
    roots: list[Path] = []
    real = os.stat

    def stat(path, *args, **kwargs):  # noqa: ANN001, ANN202
        st = real(path, *args, **kwargs)
        if isinstance(path, (str, os.PathLike)) and any(
            Path(path).is_relative_to(root) for root in roots
        ):
            return _StatOnAnotherDevice(st)
        return st

    monkeypatch.setattr(os, "stat", stat)

    def mount(root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)  # a mounted volume's root exists
        roots.append(Path(root))
        return root

    return mount


@pytest.fixture
def unreachable_volume(monkeypatch: pytest.MonkeyPatch):
    """`unreachable_volume(root)`: a share that stopped answering. Every `os.stat`
    below `root` fails with `EIO`, which says nothing about whether the files
    are there."""
    roots: list[Path] = []
    real = os.stat

    def stat(path, *args, **kwargs):  # noqa: ANN001, ANN202
        if isinstance(path, (str, os.PathLike)) and any(
            Path(path).is_relative_to(root) for root in roots
        ):
            raise OSError(errno.EIO, os.strerror(errno.EIO), str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    return roots.append


@pytest.fixture
def power_cut(monkeypatch: pytest.MonkeyPatch):
    """`power_cut(op, under, nth=1)`: the `nth` `"copy2"` or `"unlink"` of a path
    below `under` is where the power goes, raising `SystemExit` the way a
    killed process stops. A cut copy leaves half the file at its destination.
    It fires once, so whatever runs after the "restart" works normally."""
    real_copy2, real_unlink = shutil.copy2, os.unlink
    cuts: list[dict] = []

    def due(op: str, path) -> bool:  # noqa: ANN001
        for cut in cuts:
            if cut["op"] == op and not cut["fired"] and Path(path).is_relative_to(cut["under"]):
                cut["seen"] += 1
                if cut["seen"] == cut["nth"]:
                    cut["fired"] = True
                    return True
        return False

    def copy2(src, dst, *, follow_symlinks=True):  # noqa: ANN001, ANN202
        if due("copy2", dst):
            data = Path(src).read_bytes()
            Path(dst).write_bytes(data[: len(data) // 2])
            raise SystemExit("power cut")
        return real_copy2(src, dst, follow_symlinks=follow_symlinks)

    def unlink(path, *args, **kwargs):  # noqa: ANN001, ANN202
        if due("unlink", path):
            raise SystemExit("power cut")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", copy2)
    monkeypatch.setattr(os, "unlink", unlink)

    def arm(op: str, under: Path, nth: int = 1) -> None:
        assert op in ("copy2", "unlink"), op
        cuts.append({"op": op, "under": Path(under), "nth": nth, "seen": 0, "fired": False})

    return arm


def rewrite_keeping_stat(path: Path, data: bytes) -> None:
    """Change a file's bytes behind a stat-keyed cache's back: same size, same
    mtime. A pass that serves the old answer never read the file; one that
    read it sees `data`."""
    st = path.stat()
    assert len(data) == st.st_size, "a cache keyed on size would notice"
    path.write_bytes(data)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


def fine_mtime(*paths: Path) -> None:
    """Give files an mtime a 10 ms volume cannot keep, as NTFS's 100 ns can."""
    for path in paths:
        os.utime(path, ns=(1_760_000_000_123_456_789, 1_760_000_000_123_456_789))
