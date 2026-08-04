"""Where this suite's data lives, in one place.

Every module in here used to define its own `ROOT = __file__.parent.parent` and
derive `specs/`, `schema/` and `Arduino/libraries/TaskInterpreter/` from it,
which worked only while the suite sat directly under a repo root whose shape
they all agreed about. It does not any more, so the walks are collected here
for the same reason `ephymeris_sidecar/taskgraph/paths.py` collects the
package's: one definition, and moving the tree retargets one file.

`SPEC_DIR` is deliberately the shipped directory rather than a copy under
`fixtures/`. There is one set of specs, and a test that reads a duplicate is a
test that can pass while the shipped bytes are wrong.
"""

from __future__ import annotations

import os
from pathlib import Path

from ephymeris_sidecar.taskgraph import paths

TESTS_DIR = Path(__file__).resolve().parent
BROKEN_DIR = TESTS_DIR / "broken"
FIXTURES_DIR = TESTS_DIR / "fixtures"
GOLDENS_DIR = TESTS_DIR / "goldens"

AS_BUILT = FIXTURES_DIR / "grgl_2odor_asbuilt.yaml"

#: The shipped specs. Deleted in the paradigm changeover -- when it goes, the
#: modules that read it move to generated skeletons rather than to a copy.
SPEC_DIR = paths.PACKAGE_DIR / "specs"

SCHEMA_DIR = paths.SCHEMA_DIR

REPO_ROOT = paths.repo_root()
FIRMWARE = paths.firmware_root()
FIRMWARE_LIB = paths.firmware_lib()
HOST_TEST = FIRMWARE_LIB / "extras" / "host_test"


def firmware_repo() -> Path:
    """The lab's BehaviorBox checkout -- a SIBLING repo, not part of this one.

    Three places used to find it three ways: `Arduino/build.sh` read
    `$BEHAVIORBOX_REPO`, the gates walked to a bare sibling, and Ephymeris'
    staging script read `$EPHYMERIS_FIRMWARE_REPO`. They now agree on the
    staging script's name, since that is the one a packaged build already
    depends on, with the sibling walk kept as the fallback that has always
    worked on a lab machine.
    """
    override = os.environ.get("EPHYMERIS_FIRMWARE_REPO")
    return Path(override) if override else REPO_ROOT.parent / "Arduino"


BEHAVIORBOX = firmware_repo() / "libraries" / "BehaviorBox"


def spec(spec_id: str) -> Path:
    return SPEC_DIR / f"{spec_id}.yaml"


def all_specs() -> list[Path]:
    return sorted(SPEC_DIR.glob("*.yaml"))
