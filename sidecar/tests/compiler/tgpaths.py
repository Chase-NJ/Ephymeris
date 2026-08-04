"""Where this suite's data lives, in one place.

Every module in here used to define its own `ROOT = __file__.parent.parent` and
derive `specs/`, `schema/` and `Arduino/libraries/TaskInterpreter/` from it,
which worked only while the suite sat directly under a repo root whose shape
they all agreed about. It does not any more, so the walks are collected here
for the same reason `ephymeris_sidecar/taskgraph/paths.py` collects the
package's: one definition, and moving the tree retargets one file.

Nothing ships as a spec, so the tests that need a spec FILE generate one from
a paradigm. That is a stronger claim than a checked-in example: it is the same
document the New Task wizard produces, so a paradigm that stops generating a
valid task fails the gates rather than passing beside a file nobody makes.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ephymeris_sidecar.taskgraph import paths

TESTS_DIR = Path(__file__).resolve().parent
BROKEN_DIR = TESTS_DIR / "broken"
FIXTURES_DIR = TESTS_DIR / "fixtures"
GOLDENS_DIR = TESTS_DIR / "goldens"

AS_BUILT = FIXTURES_DIR / "grgl_2odor_asbuilt.yaml"

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


#: Generated skeletons, written once per session, for the tests that need a spec
#: FILE rather than a document -- the gates compile from a path, and the CLI is
#: driven by subprocess.
#:
#: NOTHING SHIPS AS A SPEC ANY MORE, so there is no directory of examples to read
#: and no copy of one under fixtures/. What these tests exercise is the same
#: thing an operator gets from the New Task wizard, which is a stronger claim
#: than a curated file would make: if a paradigm stops producing a valid task,
#: the gates fail rather than passing against an example nobody generates.
_SKELETON_DIR = Path(tempfile.mkdtemp(prefix="tg-skeletons-"))
_written: dict[str, Path] = {}


def spec(paradigm_id: str) -> Path:
    """A generated skeleton on disk for `paradigm_id`, written once."""
    if paradigm_id not in _written:
        from ephymeris_sidecar.taskgraph import paradigms

        p = paradigms.get(paradigm_id)
        path = _SKELETON_DIR / f"{paradigm_id}.yaml"
        path.write_text(paradigms.to_yaml(paradigms.skeleton(p, spec_id=paradigm_id)), encoding="utf-8")
        _written[paradigm_id] = path
    return _written[paradigm_id]


def all_specs() -> list[Path]:
    """One skeleton per paradigm, in gallery order."""
    from ephymeris_sidecar.taskgraph import paradigms

    return [spec(p.id) for p in paradigms.load_all()]


def spec_with(paradigm_id: str, answers: dict, *, name: str) -> Path:
    """A skeleton generated with specific answers, written once under `name`."""
    if name not in _written:
        from ephymeris_sidecar.taskgraph import paradigms

        p = paradigms.get(paradigm_id)
        path = _SKELETON_DIR / f"{name}.yaml"
        path.write_text(
            paradigms.to_yaml(paradigms.skeleton(p, spec_id=name, answers=answers))
        , encoding="utf-8")
        _written[name] = path
    return _written[name]


#: The lab's shaping ramp: a 10 ms hold walking up to the full task over 100
#: trials. Declared here rather than shipped in the paradigm because the VALUES
#: and the trial boundaries are the operator's -- the paradigm only names which
#: ids ramp. This is what the wizard's ramp step produces.
SHAPING_RAMP = [
    {"at_trial": 0, "set": {"t_commit_hold": 10, "t_sample_hold": 10,
                            "t_resp_hold": 10, "t_resp_win": 10000,
                            "t_engage_win": 8000}},
    {"at_trial": 20, "set": {"t_commit_hold": 100, "t_sample_hold": 100,
                             "t_resp_hold": 50, "t_resp_win": 10000,
                             "t_engage_win": 8000}},
    {"at_trial": 25, "set": {"t_commit_hold": 125, "t_sample_hold": 125,
                             "t_resp_hold": 250, "t_resp_win": 5000,
                             "t_engage_win": 8000}},
    {"at_trial": 50, "set": {"t_commit_hold": 250, "t_sample_hold": 250,
                             "t_resp_hold": 500, "t_resp_win": 2000,
                             "t_engage_win": 4000}},
    {"at_trial": 100, "set": {"t_commit_hold": 500, "t_sample_hold": 500,
                              "t_resp_hold": 500, "t_resp_win": 2000,
                              "t_engage_win": 4000}},
]


def shaping_ramped(side: str = "right_well") -> Path:
    """A shaping task with its ramp filled in, as an operator would leave it.

    A skeleton ships `stage_schedule: []` -- the paradigm names which ids ramp,
    never how far or when, because those are the experiment. Anything that needs
    a task whose timings actually MOVE has to add them, which is what the
    wizard's ramp step does and what this reproduces.
    """
    name = f"shaping_ramped_{side}"
    if name not in _written:
        from ephymeris_sidecar.taskgraph import paradigms

        doc = paradigms.skeleton(
            paradigms.get("shaping"), spec_id=name, answers={"rewarded_arm": side}
        )
        doc["policy"]["stage_schedule"] = [dict(r) for r in SHAPING_RAMP]
        # The base vector starts where the ramp starts. A skeleton opens at the
        # full-task values, which is right for a task nobody is shaping toward;
        # a shaping task begins eased and walks up, so trial 0's row and the
        # compiled timings have to agree or the first trials run at values the
        # schedule immediately overwrites.
        first = SHAPING_RAMP[0]["set"]
        for row in doc["timing"]:
            if row["id"] in first:
                row["ms"] = first[row["id"]]
        path = _SKELETON_DIR / f"{name}.yaml"
        path.write_text(paradigms.to_yaml(doc), encoding="utf-8")
        _written[name] = path
    return _written[name]


def grgl_equivalent() -> Path:
    """The 2AFC task the lab's firmware actually runs, for the equivalence gates.

    THE GATES COMPARE AGAINST runTrial(), which is a specific task and not a
    shape: odor 1 (sandalwood) sends the animal right, odor 3 (orange) sends it
    left. A skeleton's DEFAULT stimulus lines are the first two the registry
    offers, which is the right default for someone designing a new task and the
    wrong one for a byte-equivalence test against firmware that predates it.

    So the gates construct the task they are testing rather than relying on a
    default to happen to match it -- which is also what stops a future change to
    that default silently turning an equivalence failure into a passing test
    about a different experiment.
    """
    return spec_with(
        "two_afc",
        {"stim_a_emitter": "odor_line_1", "stim_b_emitter": "odor_line_3"},
        name="grgl_equivalent",
    )
