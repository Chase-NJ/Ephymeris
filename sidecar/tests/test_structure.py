"""Rules about the shape of the sidecar's source, checked instead of remembered."""

from __future__ import annotations

import ast
import tokenize
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "ephymeris_sidecar"
GENERATED = {PACKAGE / "protocol.py"}

#: `#` comments in the sidecar. It only goes down: put a rule in a test, a
#: name or a doc section instead, and lower this when you remove comments.
COMMENT_CEILING = 3351


def sources() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "rpc" not in p.parts and p not in GENERATED)


def test_the_comment_count_only_goes_down() -> None:
    count = 0
    for path in sources():
        with tokenize.open(path) as fh:
            count += sum(1 for token in tokenize.generate_tokens(fh.readline) if token.type == tokenize.COMMENT)
    assert count <= COMMENT_CEILING, (
        f"{count - COMMENT_CEILING} new comment(s): say it in a name, a test or a doc section, not a comment"
    )


def test_only_the_database_module_opens_a_connection() -> None:
    openers = {p.relative_to(PACKAGE).as_posix() for p in sources() if "sqlite3.connect(" in p.read_text("utf-8")}
    assert openers == {"cohorts/db.py"}, "reach SQLite through db.read() / db.write() (DATA.md#transactions)"


def test_a_port_state_changes_only_behind_assert_transition() -> None:
    writers = {}
    for path in sources():
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            assigns = any(
                isinstance(target, ast.Attribute) and target.attr == "_state"
                for stmt in ast.walk(node) if isinstance(stmt, ast.Assign) for target in stmt.targets
            )
            if assigns and path.parent.name == "ports":
                checked = any(isinstance(n, ast.Name) and n.id == "assert_transition" for n in ast.walk(node))
                writers[f"{path.name}:{node.name}"] = checked
    unchecked = sorted(name for name, checked in writers.items() if not checked)
    assert unchecked == ["handler.py:__init__"], "move a port only through _set_state (ARCHITECTURE.md#port-state-machine)"
