"""`analytics/stream/` stays pure — `ANALYTICS.md#the-folder-at-a-glance`.

The folder's promise is that a reader checks the science by reading it and
nothing else: a document and a profile in, numbers out, with no file, database
or clock in between. That holds only while no module in it imports one, so
this walks every import and fails on any that reaches for I/O or for the
analytics plumbing around it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

STREAM = Path(__file__).resolve().parents[1] / "ephymeris_sidecar" / "analytics" / "stream"

#: Standard-library modules that touch the disk, the network, threads or the clock.
FORBIDDEN_STDLIB = {
    "asyncio", "datetime", "io", "json", "logging", "os", "pathlib", "shutil",
    "socket", "sqlite3", "subprocess", "tempfile", "threading", "time",
}

#: The sidecar packages a pure module may lean on: the profile it decodes with,
#: the vocabulary inference reads, the session-name parser false starts order
#: runs by, and the lowering whose outcome classes and phase map a spine run's
#: replay is named by (standard library only, by its own rule). All are pure
#: functions of their arguments.
ALLOWED_SIDECAR = {"tasks.profile", "rig", "rig.registry", "sessions.paths", "taskdef.lowering"}


def _imports(path: Path) -> list[tuple[int, str]]:
    """`(level, dotted module)` for every import in `path`."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.extend((0, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append((node.level, node.module or ""))
    return out


@pytest.mark.parametrize("path", sorted(STREAM.glob("*.py")), ids=lambda p: p.name)
def test_a_stream_module_imports_nothing_impure(path: Path) -> None:
    for level, module in _imports(path):
        if level == 0:
            assert module.split(".")[0] not in FORBIDDEN_STDLIB, f"{path.name} imports {module}"
            assert not module.startswith("ephymeris_sidecar"), f"{path.name}: use a relative import"
        elif level == 1:
            # A sibling inside stream/ — pure by this same test.
            continue
        elif level == 3:
            assert module in ALLOWED_SIDECAR, f"{path.name} imports ...{module}"
        else:
            # level 2 is analytics/ itself: reader, scoring, the cache, the archive.
            pytest.fail(f"{path.name} imports {'.' * level}{module}, outside stream/")
