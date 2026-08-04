"""Every path this package resolves, in one place.

Before the fold into Ephymeris, five modules independently walked `__file__` to
the same two directories at three different depths -- `registries.py`,
`loader.py`, `presentation.py`, `lint/rules_load.py` and `codegen/strobes.py`
-- plus two more that walked to a repo root that, inside the vendored tree, did
not exist. That arrangement worked only because the tree mirrored a repo root
and every walk agreed about how deep it was; it was the reason the vendored
copy could never be nested one level further down.

There are two kinds of path here and the distinction is the whole point:

RUNTIME DATA -- `schema/`, `hardware/`, `templates/`, `paradigms/` -- lives
inside the package, resolves relative to this file, and is present in every
install: editable, wheel, or PyInstaller freeze. Nothing may compile without
it, so `self_check()` proves it on startup rather than trusting it.

REPO-ONLY PATHS -- `firmware/`, the test fixtures -- exist only in a source
checkout. They are reached by walking UP for a marker file, and they raise a
named error rather than returning a plausible wrong answer when the marker is
absent. `codegen` and the CLI are their only consumers and both are developer
tools; a frozen sidecar has no business writing C headers.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

SCHEMA_DIR = PACKAGE_DIR / "schema"
HARDWARE_DIR = PACKAGE_DIR / "hardware"
TEMPLATE_DIR = PACKAGE_DIR / "templates"
PARADIGM_DIR = PACKAGE_DIR / "paradigms"

TASK_SPEC_SCHEMA = SCHEMA_DIR / "task_spec.v1.json"
PRESENTATION_SCHEMA = SCHEMA_DIR / "task_spec.presentation.v1.json"


class NotASourceCheckout(RuntimeError):
    """Raised when a repo-only path is asked for and there is no repo.

    Its own type because the callers -- codegen and the CLI -- want to say
    something specific ("this command needs a source checkout"), and because a
    bare RuntimeError from a path helper reads like a bug rather than a
    misuse.
    """


def repo_root() -> Path:
    """The Ephymeris checkout containing this package. DEVELOPER TOOLS ONLY.

    Walks up for `sidecar/pyproject.toml` rather than counting `..` segments,
    so moving this package deeper does not silently retarget it -- which is
    exactly what the old `parent.parent.parent` did when the tree was vendored:
    it pointed `codegen` at an `Arduino/` directory that was never copied, and
    the command stayed dead for months without erroring.
    """
    for candidate in (PACKAGE_DIR, *PACKAGE_DIR.parents):
        if (candidate / "sidecar" / "pyproject.toml").is_file():
            return candidate
    raise NotASourceCheckout(
        "no Ephymeris source checkout above "
        f"{PACKAGE_DIR} -- this is a packaged or installed build, and the "
        "path being asked for (firmware sources or test fixtures) ships only "
        "in the repository."
    )


def firmware_root() -> Path:
    """`firmware/` -- the interpreter library and the TaskRunner sketches."""
    return repo_root() / "firmware"


def firmware_lib() -> Path:
    """Where generated C headers land, and where the interpreter reads them."""
    return firmware_root() / "libraries" / "TaskInterpreter"
