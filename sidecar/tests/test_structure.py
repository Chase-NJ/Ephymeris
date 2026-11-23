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
    return sorted(
        p for p in PACKAGE.rglob("*.py")
        if "rpc" not in p.parts and "tests" not in p.relative_to(PACKAGE).parts and p not in GENERATED
    )


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


REPO = PACKAGE.parents[1]

#: What stays in `sidecar/tests/`: the tests of the suite, the docs, the wire and
#: the process's own modules, which no one feature owns.
SUITE_TESTS = {
    "test_bundled_library_covers_archives.py", "test_check_frozen.py", "test_decode_only.py", "test_discovery.py",
    "test_dispatch.py", "test_doc_links.py", "test_golden.py", "test_legacy_corpus.py",
    "test_legacy_pin.py", "test_protocol_contract.py", "test_settings.py", "test_structure.py",
    "test_utility.py", "test_wire_shapes.py",
}
#: These four belong to `analytics` and `sessions`, and stay only because the
#: agents' stop gate (`.claude/hooks/stop_gate.py`) runs them by path. Move each
#: with its line there, and take it off this list.
GATE_PINNED = {
    "test_analytics_stream_is_pure.py", "test_recovery.py", "test_run_document.py", "test_writer.py",
}
#: Webview features with no sidecar package to take a name from.
WEBVIEW_ONLY = {"dashboard", "debug", "settings", "sky", "updates"}
#: What several webview features share.
SHARED_LIB = {"exports", "nav", "shell", "ws"}
SHARED_COMPONENTS = {"charts", "chrome", "common"}


def sidecar_features() -> set[str]:
    return {p.name for p in PACKAGE.iterdir() if (p / "__init__.py").is_file()}


def folders(path: Path) -> set[str]:
    return {p.name for p in path.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))}


def test_a_sidecar_feature_s_tests_live_in_its_folder() -> None:
    """One folder per feature (`ARCHITECTURE.md#one-folder-per-feature`)."""
    suite = {p.name for p in (PACKAGE.parent / "tests").glob("test_*.py")}
    assert suite == SUITE_TESTS | GATE_PINNED, "a feature's test goes in ephymeris_sidecar/<feature>/tests/"
    for path in PACKAGE.rglob("test_*.py"):
        where = path.relative_to(PACKAGE).parts
        assert len(where) == 3 and where[1] == "tests" and where[0] in sidecar_features(), path


def test_the_webview_has_no_folders_by_kind() -> None:
    src = REPO / "src"
    assert not (src / "routes").exists(), "a page lives in its feature's folder"
    assert folders(src / "lib") == SHARED_LIB, "src/lib holds only what several features share"
    assert folders(src / "components") == SHARED_COMPONENTS, "a component lives in its feature's folder"


def test_a_webview_feature_is_named_for_its_sidecar_package() -> None:
    named_for_nothing = folders(REPO / "src" / "features") - sidecar_features() - WEBVIEW_ONLY
    assert named_for_nothing == set(), "name it for the sidecar package it talks to, or list it in WEBVIEW_ONLY"
    assert WEBVIEW_ONLY.isdisjoint(sidecar_features())
