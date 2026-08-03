"""Guards `sidecar/vendor/` against being edited in place.

The Task-Graph compiler is vendored rather than depended on, because the sidecar is
frozen with PyInstaller onto lab machines that never run pip. The copy is
byte-identical to its source repo and that is the entire design: the moment it is
allowed to differ, the two drift and the drift is invisible.

This test catches ONE of the two ways that happens -- someone edits the copy,
whether by hand or by an editor's auto-format on the way past. It cannot catch the
other, a copy that is stale because Task-Graph moved, because this repo has no idea
what upstream looks like. That direction is Task-Graph's own
`tests/test_ephymeris_mirror.py`, which reads this tree and is skipped unless
`$EPHYMERIS_REPO` points at it. Both are needed; neither is sufficient.

Deliberately self-contained: it recomputes hashes against the committed `VENDORED`
manifest, so it needs no second checkout and no network, and it runs on every CI
machine rather than only where both repos happen to be side by side.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

VENDOR = Path(__file__).resolve().parent.parent / "vendor"
MANIFEST = VENDOR / "VENDORED"

FIX = (
    "\n\nIf you meant to change the compiler, change it in Task-Graph and re-run\n"
    "  python scripts/sync_to_ephymeris.py --dest <ephymeris>/sidecar/vendor\n"
    "An edit made here would be silently reverted by the next sync."
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST.is_file(), f"{MANIFEST} is missing — the vendor tree was not synced"
    return json.loads(MANIFEST.read_text())


def _tracked_files() -> dict[str, Path]:
    out = {}
    for tree in ("taskgraph", "templates", "schema", "specs"):
        for path in (VENDOR / tree).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                out[str(path.relative_to(VENDOR))] = path
    return out


def test_manifest_records_the_source_commit(manifest: dict):
    assert manifest["source"] == "Task-Graph"
    assert manifest["commit"] != "unknown", "sync ran outside a git checkout"
    assert manifest["files"], "the manifest lists no files"


def test_no_vendored_file_has_been_edited(manifest: dict):
    tracked = _tracked_files()
    changed = [
        name
        for name, digest in manifest["files"].items()
        if name in tracked
        and hashlib.sha256(tracked[name].read_bytes()).hexdigest() != digest
    ]
    assert not changed, "these vendored files differ from what was synced:\n  " + "\n  ".join(
        sorted(changed)
    ) + FIX


def test_no_vendored_file_is_missing_or_extra(manifest: dict):
    tracked = set(_tracked_files())
    recorded = set(manifest["files"])
    missing = sorted(recorded - tracked)
    extra = sorted(tracked - recorded)
    assert not missing, "these files are in the manifest but not on disk:\n  " + "\n  ".join(
        missing
    ) + FIX
    assert not extra, (
        "these files are on disk but not in the manifest — something was added to "
        "the vendor tree by hand:\n  " + "\n  ".join(extra) + FIX
    )


def test_the_vendor_tree_mirrors_the_repo_root_not_a_package():
    """`taskgraph/` and `schema/` must stay siblings.

    `taskgraph.registries` resolves SCHEMA_DIR as `__file__/../../schema`, and three
    other modules resolve the templates dir, the JSON Schema and the codegen root
    the same way. Nesting the copy one level deeper would break all four — and the
    natural fix, patching the paths, is what makes the copy un-diffable.
    """
    assert (VENDOR / "taskgraph" / "registries.py").is_file()
    assert (VENDOR / "schema" / "task_spec.v1.json").is_file()
    assert (VENDOR / "templates" / "four_epoch" / "v2.py").is_file()
    assert not (VENDOR / "__init__.py").exists(), (
        "sidecar/vendor must NOT be a package. Importing it by a dotted path would "
        "create a second copy of every module alongside the sys.path one, and the "
        "linter's rule registry and the lru_cached registries are module-level state."
    )
