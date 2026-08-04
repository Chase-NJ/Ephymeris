"""The TaskGraph documents, pinned against the code they describe.

Two failure modes, both quiet, both closed here.

A DOCUMENT THAT DESCRIBES A TASK THE APP WOULD NOT PRODUCE. `creating-a-task.md`
prints the generated `two_afc` skeleton in full, and it is the one example a
reader is most likely to copy. If the paradigm file, the template's timing
defaults or the channel registry moves, that block silently becomes a
description of a previous version. Regenerating and comparing byte for byte is
the only check that survives every one of those edits.

A DECISION POINTER THAT GOES NOWHERE. Roughly half the linter's rules carry a
`decision="D<n>"`, which the frontend turns into a link into
`taskgraph-decisions.md`. GitHub's heading slugs cannot be constructed from
"D4" -- the headings carry em-dashes and prose -- so the file has explicit
`<a id="dN">` anchors, and an anchor is exactly the kind of thing that gets
dropped by a well-meaning reformat. A dead link in a diagnostic is worse than no
link: it reads as though the rationale was written and then lost.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph import paradigms
from ephymeris_sidecar.taskgraph.lint import REGISTRY, load_all_rules

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
CREATING = DOCS / "creating-a-task.md"
DECISIONS = DOCS / "taskgraph-decisions.md"
TASKGRAPH = DOCS / "TaskGraph.md"

#: The spec_id the embedded example uses. Not "two_afc" -- the block is a
#: worked example of naming your own task, and using the paradigm's id would
#: quietly teach the opposite.
EXAMPLE_SPEC_ID = "my_task"

_BEGIN = "<!-- BEGIN GENERATED two_afc SKELETON -->"
_END = "<!-- END GENERATED two_afc SKELETON -->"


def _embedded_yaml() -> str:
    text = CREATING.read_text()
    assert _BEGIN in text and _END in text, (
        "the generated-skeleton markers are gone from creating-a-task.md. They "
        "delimit the one block this test can check; without them the example is "
        "unpinned."
    )
    block = text.split(_BEGIN, 1)[1].split(_END, 1)[0]
    fence = re.search(r"```yaml\n(.*?)```", block, re.S)
    assert fence is not None, "the marked block no longer contains a ```yaml fence"
    return fence.group(1)


def test_creating_a_task_example_is_current():
    """The embedded skeleton is byte-for-byte what the app generates."""
    generated = paradigms.to_yaml(
        paradigms.skeleton(paradigms.get("two_afc"), spec_id=EXAMPLE_SPEC_ID)
    )
    assert _embedded_yaml() == generated, (
        "the two_afc skeleton in docs/creating-a-task.md is stale. Regenerate it:\n"
        "  python -c \"from ephymeris_sidecar.taskgraph import paradigms as p; \"\n"
        "    \"print(p.to_yaml(p.skeleton(p.get('two_afc'), spec_id='my_task')))\""
    )


def test_the_embedded_example_compiles():
    """And it is not merely current -- it is a task that would run.

    A skeleton is documented as arriving working rather than as a stub, so the
    document making that claim is the right place to prove it.
    """
    from ephymeris_sidecar.specs import compiler

    result = compiler.compile(_embedded_yaml())
    assert result.ok, [d.code for d in result.bag if not result.ok]


def _decision_pointers() -> set[str]:
    load_all_rules()
    return {rule.decision for rule in REGISTRY.all() if rule.decision}


def test_every_decision_pointer_resolves():
    """Every `decision=` a rule carries has an anchor to land on."""
    anchors = set(re.findall(r'<a id="(d\d+)"></a>', DECISIONS.read_text()))
    assert anchors, "taskgraph-decisions.md has no <a id=...> anchors at all"

    missing = sorted(
        d for d in _decision_pointers() if d.lower() not in anchors
    )
    assert not missing, (
        f"linter rules point at {missing}, which have no anchor in "
        f"{DECISIONS.name}. A diagnostic linking there would 404."
    )


def test_decision_links_in_the_docs_resolve():
    """And so does every hand-written link in the two prose documents."""
    anchors = set(re.findall(r'<a id="(d\d+)"></a>', DECISIONS.read_text()))
    broken = []
    for doc in (TASKGRAPH, CREATING):
        for target in re.findall(r"taskgraph-decisions\.md#(d\d+)", doc.read_text()):
            if target not in anchors:
                broken.append(f"{doc.name} → #{target}")
    assert not broken, broken


@pytest.mark.parametrize("doc", [TASKGRAPH, CREATING])
def test_relative_doc_links_point_at_files_that_exist(doc: Path):
    """No link to a document that was renamed or never written."""
    missing = [
        target
        for target in re.findall(r"\]\((?!https?:)([A-Za-z0-9._-]+\.md)", doc.read_text())
        if not (DOCS / target).is_file()
    ]
    assert not missing, f"{doc.name} links to missing documents: {sorted(set(missing))}"
