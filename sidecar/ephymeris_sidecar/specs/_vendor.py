"""Put the vendored Task-Graph compiler on `sys.path`. Import for the side effect.

    from . import _vendor          # noqa: F401  -- side effect: sys.path
    from taskgraph.pipeline import compile_text

THE TREE MIRRORS THE TASK-GRAPH REPO ROOT, NOT A PACKAGE. `taskgraph/` and
`schema/` are siblings under `sidecar/vendor/` because `taskgraph.registries`
resolves `SCHEMA_DIR` as `Path(__file__).parent.parent / "schema"`, and three other
modules resolve `templates/`, the JSON Schema and the codegen root the same way.
Preserving that layout is what lets the copy stay byte-identical to upstream --
and a copy nobody can diff is a fork with extra steps.

ONE IMPORT PATH ONLY. Never `from ephymeris_sidecar.vendor...`; the vendor
directory is deliberately not a package and is deliberately outside
`ephymeris_sidecar` (`[tool.setuptools.packages.find] include = ["ephymeris_sidecar*"]`
excludes it, and PyInstaller's `--collect-submodules ephymeris_sidecar` will not
walk into it). Reaching it by a dotted path would create a SECOND module object
alongside `taskgraph.pipeline` -- and `pipeline.py` calls `load_all_rules()` at
module scope while `registries` is `lru_cache`d, so two copies means two rule
registries and two strobe vocabularies, disagreeing silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Overrides the search. Set by nothing in production; useful for pointing a dev
#: sidecar at a live Task-Graph checkout instead of the synced copy.
VENDOR_ENV = "EPHYMERIS_TASKGRAPH_VENDOR"

_MARKERS = ("taskgraph", "schema", "templates")


def _candidates() -> list[Path]:
    import os

    out: list[Path] = []
    override = os.environ.get(VENDOR_ENV)
    if override:
        out.append(Path(override))
    # PyInstaller onedir: `--add-data <vendor>;vendor` lands it beside _internal.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(Path(meipass) / "vendor")
    # Source checkout: sidecar/ephymeris_sidecar/specs/ -> sidecar/vendor/
    out.append(Path(__file__).resolve().parent.parent.parent / "vendor")
    return out


def vendor_root() -> Path:
    for candidate in _candidates():
        if all((candidate / marker).is_dir() for marker in _MARKERS):
            return candidate
    tried = "\n  ".join(str(c) for c in _candidates())
    raise ImportError(
        "the vendored Task-Graph compiler is missing. Looked for a directory "
        f"holding {', '.join(_MARKERS)} in:\n  {tried}\n"
        "In a checkout, run Task-Graph's scripts/sync_to_ephymeris.py --dest "
        "sidecar/vendor. In a packaged build this means the PyInstaller --add-data "
        "entry was dropped."
    )


def ensure_importable() -> Path:
    """Idempotent. Returns the root that was put on the path."""
    root = vendor_root()
    entry = str(root)
    if entry not in sys.path:
        sys.path.insert(0, entry)
    return root


ROOT = ensure_importable()
