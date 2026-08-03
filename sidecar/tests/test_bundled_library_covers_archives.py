"""The bundled library must resolve every sketch name the lab's archives record.

Analytics resolves a historical run's `sketch` field against CURRENT discovery
(`app.py::_sketch_path_for_name`), by folder name with a `legacyNames` fallback.
That resolution is load-bearing for orphan-adopted archives (`data.md` §8.1) —
runs with no database record, where the recorded name is the only key there is.
Both of the lab's decoded archives are exactly that.

While the library was a user-configured directory, keeping it complete was the
user's problem. Now it ships with the app, so dropping a sketch from the bundle
is a CODE change — and its blast radius is a year of history that stops decoding
**with a warning, not an error**, because a missing profile is treated as data.
This test is what makes that failure loud instead.

ARCHIVE_RECORDED_NAMES is a checked-in transcript of what the archives actually
contain (gathered 2026-08-03 from `04_Data/00_Behavior`), not something computed
at test time: the archives live on lab machines and network shares this test
must not depend on. When a new archive introduces a new name, add it here — the
cost of the list going stale is one missing assertion, while the cost of reading
the real archives would be a test that only passes where they're mounted.

Note the two label-valued names: `Shape - L` / `Shape - R` are what pre-Ephymeris
software wrote as a human label. They resolve ONLY through `legacyNames` in
shaping_GL/shaping_GR's task.json — which is precisely the kind of dependency
nobody would think to preserve while renaming a folder.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
STAGED = REPO / "sketches"

#: Every value of `sketch` observed across the lab's session archives.
ARCHIVE_RECORDED_NAMES = frozenset(
    {
        "GRGL_2-Odor",
        "GRGL_Sim",
        "Shape - L",
        "Shape - R",
    }
)

pytestmark = pytest.mark.skipif(
    not STAGED.is_dir(),
    reason="the sketch library isn't staged — run `npm run stage:sketches` first",
)


def _resolvable_names() -> set[str]:
    """Folder names plus every legacyNames entry, mirroring the app's rule."""
    names: set[str] = set()
    for ino in STAGED.rglob("*.ino"):
        folder = ino.parent
        if ino.stem != folder.name:
            continue  # not a valid sketch; discovery would skip it too
        names.add(folder.name)
        profile = folder / "task.json"
        if profile.is_file():
            try:
                legacy = json.loads(profile.read_text()).get("legacyNames", [])
            except (OSError, json.JSONDecodeError):
                continue  # a broken profile is its own problem, reported elsewhere
            names.update(n for n in legacy if isinstance(n, str))
    return names


def test_every_archived_sketch_name_resolves_against_the_bundle():
    unresolvable = sorted(ARCHIVE_RECORDED_NAMES - _resolvable_names())
    assert not unresolvable, (
        "these sketch names appear in the lab's session archives but resolve "
        "against nothing in the bundled library:\n  "
        + "\n  ".join(unresolvable)
        + "\n\nShipping this build would make those runs stop decoding in "
        "Analytics — silently, because a missing profile is treated as data. "
        "Restore the sketch folder, or add the name to an existing sketch's "
        "legacyNames."
    )


def test_the_label_valued_names_still_ride_on_legacy_names():
    """The two names that would not survive a folder rename.

    Separate from the superset check so that a failure names the actual hazard:
    these resolve through shaping_GL/shaping_GR's `legacyNames` arrays alone,
    and editing those profiles is where the history quietly breaks.
    """
    names = _resolvable_names()
    assert "Shape - L" in names
    assert "Shape - R" in names


def test_the_transcript_itself_is_not_empty():
    """Guards the guard: an emptied list would pass everything forever."""
    assert len(ARCHIVE_RECORDED_NAMES) >= 4
