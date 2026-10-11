"""Suite-wide test configuration.

Turns on wire-shape validation (`protocol.wire_validation_enabled`) for every
test: any event built via `protocol.event()` — the runner, backup manager, and
analytics service all go through it — and any command reply dispatched through
`SidecarServer` is checked against `protocol/schema.py` and fails loudly on
drift. Production leaves this off, so a benign schema lag can never take down
a live session.

Also the `coarse_volume` fixture, for a transfer onto a volume that rounds
mtimes.
"""

from __future__ import annotations

import os
import shutil
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


def fine_mtime(*paths: Path) -> None:
    """Give files an mtime a 10 ms volume cannot keep, as NTFS's 100 ns can."""
    for path in paths:
        os.utime(path, ns=(1_760_000_000_123_456_789, 1_760_000_000_123_456_789))
