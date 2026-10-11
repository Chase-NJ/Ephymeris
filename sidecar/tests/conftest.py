"""Suite-wide test configuration.

Turns on wire-shape validation (`protocol.wire_validation_enabled`) for every
test: any event built via `protocol.event()` — the runner, backup manager, and
analytics service all go through it — and any command reply dispatched through
`SidecarServer` is checked against `protocol/schema.py` and fails loudly on
drift. Production leaves this off, so a benign schema lag can never take down
a live session.

Also two volume fixtures that fake the filesystem boundary: `coarse_volume`,
for a transfer onto a volume that rounds mtimes, and `hung_volume`, for a
share that stops answering mid-copy.
"""

from __future__ import annotations

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


def fine_mtime(*paths: Path) -> None:
    """Give files an mtime a 10 ms volume cannot keep, as NTFS's 100 ns can."""
    for path in paths:
        os.utime(path, ns=(1_760_000_000_123_456_789, 1_760_000_000_123_456_789))
