"""The specs.* surface: the store (reads and writes), compile payloads, capabilities.

Wire-shape conformance rides on EPHYMERIS_WIRE_VALIDATE (conftest sets it), so
these tests validate every payload against the generated schema — a field the
service forgets or misspells fails here, not in the frontend.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.protocol import validate
from ephymeris_sidecar.specs import compiler, service, store
from ephymeris_sidecar.specs.store import SpecStore


def _generated(paradigm_id: str) -> str:
    from ephymeris_sidecar.taskgraph import paradigms

    p = paradigms.get(paradigm_id)
    return paradigms.to_yaml(paradigms.skeleton(p, spec_id=paradigm_id))


pytestmark = pytest.mark.skipif(
    not compiler.available()[0],
    reason=f"vendored compiler unavailable: {compiler.available()[1]}",
)


@pytest.fixture()
def specs(tmp_path: Path) -> SpecStore:
    """A store over a fresh app-data dir.

    EMPTY, and that is the point: nothing ships as a spec, so a rig that has
    never made one has none. Tests that need a spec put one there, which is also
    the only way one ever arrives in production.
    """
    return SpecStore(tmp_path)


@pytest.fixture()
def one_spec(specs: SpecStore) -> SpecStore:
    """A store holding a single generated task."""
    specs.save("go_nogo", _generated("go_nogo"))
    return specs


def test_a_fresh_rig_has_no_specs(specs: SpecStore):
    """The first-run state, asserted rather than assumed.

    This used to be impossible -- five specs shipped -- and it is the state the
    whole New Task flow now has to handle. `specs.list` returning [] must be a
    clean answer, not an error.
    """
    assert specs.list_entries() == []
    assert specs.records() == []


# --- store: reads -----------------------------------------------------------
def test_entries_validate_as_wire_shapes(specs: SpecStore):
    for entry in specs.list_entries():
        assert validate(("ref", "SpecEntry"), entry) == [], entry["specId"]


def test_entries_carry_the_parse_level_metadata(one_spec: SpecStore):
    entry = next(e for e in one_spec.list_entries() if e["specId"] == "go_nogo")
    assert entry["label"] == "Go / no-go"
    assert entry["template"] == "four_epoch"
    assert entry["templateVersion"] == 2
    assert entry["paradigmId"] == "go_nogo", (
        "the shape is recognised from the document, not recorded in it"
    )


def test_a_reshaped_spec_stops_claiming_its_paradigm(one_spec: SpecStore):
    """`paradigmId` is computed, which is the whole reason to prefer it to the
    old origins: edit a task into a different shape and the library says so."""
    doc = _generated("go_nogo").replace("response_mode: go_nogo",
                                        "response_mode: n_alternative")
    one_spec.save("go_nogo", doc)
    entry = next(e for e in one_spec.list_entries() if e["specId"] == "go_nogo")
    assert entry["paradigmId"] != "go_nogo"


def test_get_finds_by_id_and_misses_cleanly(one_spec: SpecStore):
    assert one_spec.get("go_nogo") is not None
    assert one_spec.get("no_such_spec") is None
def test_a_spec_lives_and_dies_on_its_own(specs: SpecStore):
    record = specs.save("my_task", "spec_id: my_task\n")
    assert record.origin == "user"
    assert specs.entry_for(record)["paradigmId"] is None, "an unparseable shape is Custom"

    specs.delete("my_task")
    assert specs.get("my_task") is None
    assert specs.get("my_task") is None
def test_a_spec_id_is_a_filename_and_traversal_dies_at_the_door(specs: SpecStore):
    for bad in ("../evil", "no/slash", "UPPER", "9starts_with_digit", "", "a" * 41):
        with pytest.raises(store.SpecIdInvalid):
            specs.save(bad, "anything")
@pytest.fixture(scope="module")
def gonogo_payload() -> dict:
    text = _generated("go_nogo")
    return service.compile_payload(text, "go_nogo")


def test_a_clean_compile_validates_as_a_wire_shape(gonogo_payload: dict):
    assert gonogo_payload["ok"] is True
    assert validate(("ref", "SpecCompileResult"), gonogo_payload) == []


def test_the_summary_matches_the_cli_numbers(gonogo_payload: dict):
    table = gonogo_payload["table"]
    # Pinned against the go_nogo paradigm's golden listing — if these move,
    # either the paradigm changed (fine, update them) or the mapping broke (not).
    assert table["nNodes"] == 21
    assert table["nEdges"] == 29
    assert table["nTiming"] == 11
    assert len(table["specHash"]) == 16
    assert table["crc32"].startswith("0x")


def test_the_graph_reconstructs_edge_sources(gonogo_payload: dict):
    graph = gonogo_payload["graph"]
    assert len(graph["nodes"]) == 21
    assert len(graph["edges"]) == 29
    # Every edge's src/dst is a real node index.
    n = len(graph["nodes"])
    for edge in graph["edges"]:
        assert 0 <= edge["src"] < n
        assert 0 <= edge["dst"] < n
    # Edge ownership is grouped and monotonic (TG503), so sources ascend.
    sources = [e["src"] for e in graph["edges"]]
    assert sources == sorted(sources)
    # Every non-terminal node owns at least one edge; terminals own the returns.
    assert {e["src"] for e in graph["edges"]} | {
        i for i, node in enumerate(graph["nodes"]) if node["type"] == "TERMINAL"
    } == set(range(n))
def test_a_failing_compile_is_a_payload_not_an_exception():
    payload = service.compile_payload("not: a spec", "scratch")
    assert payload["ok"] is False
    assert payload["table"] is None and payload["graph"] is None and payload["listing"] is None
    assert any(d["severity"] == "ERROR" for d in payload["diagnostics"])
    assert validate(("ref", "SpecCompileResult"), payload) == []


def test_diagnostics_carry_a_placement_and_field_anchors_are_overlay_keys():
    text = _generated("go_nogo")
    broken = text.replace("  ms: 2000\n  wire_key: NWP", "  ms: 2000000\n  wire_key: NWP")
    payload = service.compile_payload(broken, "go_nogo")
    assert payload["ok"] is False
    placed = {d["placement"] for d in payload["diagnostics"]}
    assert placed <= {"field", "row", "section", "node", "document"}
    field_diags = [d for d in payload["diagnostics"] if d["placement"] == "field"]
    assert field_diags, payload["diagnostics"]
    overlay = compiler.registries()["overlay"]["fields"]
    for d in field_diags:
        assert d["anchor"] in overlay, f"{d['code']} anchored to unknown key {d['anchor']}"


# --- diff -------------------------------------------------------------------


def _shipped(spec_id: str) -> str:
    """Kept under its old name so the diff tests below read unchanged; what it
    returns is a generated task, because that is what there is."""
    return _generated(spec_id)


def test_an_unedited_spec_diffs_clean_against_itself():
    text = _shipped("go_nogo")
    payload = service.diff_payload("go_nogo", text, text, "saved")
    assert validate(("ref", "SpecListingDiff"), payload) == []
    assert payload["changed"] is False
    assert payload["hunks"] == []
    assert payload["before"]["specHash"] == payload["after"]["specHash"]


def test_a_timing_edit_lands_in_the_timing_vector_section_only():
    before = _shipped("go_nogo")
    after = before.replace("  ms: 2000\n  wire_key: NWP", "  ms: 2500\n  wire_key: NWP")
    payload = service.diff_payload("go_nogo", after, before, "saved")
    assert payload["changed"] is True
    sections = [h["section"] for h in payload["hunks"]]
    assert "TIMING VECTOR" in sections
    # The header block's hash churn is deliberately NOT a hunk — the summaries
    # carry it once, as provenance, instead of topping every diff.
    assert all("spec_hash" not in line["text"] for h in payload["hunks"] for line in h["lines"])
    assert payload["before"]["specHash"] != payload["after"]["specHash"]
def test_a_side_that_does_not_compile_reports_honestly():
    payload = service.diff_payload("go_nogo", "not: a spec", _shipped("go_nogo"), "saved")
    assert payload["changed"] is True
    assert payload["after"] is None
    assert payload["before"] is not None
    assert payload["hunks"] == []
    assert validate(("ref", "SpecListingDiff"), payload) == []


def test_a_topology_change_reads_as_states_moving():
    before = _shipped("go_nogo")
    after = before.replace("commit_hold: true", "commit_hold: false")
    payload = service.diff_payload("go_nogo", after, before, "saved")
    # Dropping the commitment hold restructures the graph — the STATES section
    # must carry hunks, and the headline counts must move.
    assert any(h["section"] == "STATES" for h in payload["hunks"])
    assert payload["before"]["nNodes"] != payload["after"]["nNodes"]


# --- export -----------------------------------------------------------------


def test_export_produces_every_artifact_kind():
    import base64

    text = _shipped("go_nogo")
    payload = service.export_payload(
        "go_nogo", text, ["spec", "listing", "lint", "table_json", "table_bin", "bench"]
    )
    by_kind = {a["kind"]: a for a in payload["artifacts"]}
    assert set(by_kind) == {"spec", "listing", "lint", "table_json", "table_bin", "bench"}
    for artifact in payload["artifacts"]:
        assert validate(("ref", "SpecArtifact"), artifact) == []
    assert by_kind["spec"]["text"] == text
    # The listing export IS the review artifact, byte for byte.
    goldens = Path(__file__).resolve().parent / "compiler" / "goldens"
    assert by_kind["listing"]["text"] == (goldens / "go_nogo.table.txt").read_text()
    blob = base64.b64decode(by_kind["table_bin"]["base64"])
    assert blob[:4] == b"TGTB", "the packed table's magic"
    assert by_kind["bench"]["filename"] == "go_nogo.bench.txt"


def test_export_of_a_broken_spec_yields_only_the_spec_itself():
    payload = service.export_payload("scratch", "not: a spec", ["spec", "listing", "table_bin"])
    kinds = [a["kind"] for a in payload["artifacts"]]
    assert kinds == ["spec"], (
        "everything but the YAML is a function of a compiled table, and a spec "
        "that doesn't compile has none"
    )


# --- capabilities -----------------------------------------------------------


def test_capabilities_payload_validates_and_gates():
    payload = service.capabilities_payload(
        {"n_sampling_stages": 1, "response_mode": "go_nogo", "commit_hold": True}
    )
    assert validate(("ref", "SpecCapabilities"), payload) == []
    assert "false_alarm" in payload["outcomeClasses"]
    assert "wrong" not in payload["outcomeClasses"]
    assert payload["requiredTiming"][0] == "t_zero"
    assert payload["template"] == "four_epoch"


def test_capabilities_accepts_a_half_built_topology():
    payload = service.capabilities_payload({})
    assert validate(("ref", "SpecCapabilities"), payload) == []
    assert payload["outcomeClasses"], "defaults must produce a real answer"


# --------------------------------------------------------------------------- #
# Paradigms and the skeleton generator
# --------------------------------------------------------------------------- #


def test_every_paradigm_generates_a_document_that_compiles():
    """The claim the whole zero-shipped-specs design rests on.

    If a paradigm cannot produce a compiling draft, the New Task screen offers a
    card that leads nowhere -- and since nothing ships as a spec, there is no
    fallback path to a working task.
    """
    from ephymeris_sidecar.specs import service
    from ephymeris_sidecar.taskgraph import paradigms

    listed = service.paradigms_payload()["paradigms"]
    assert listed, "no paradigms shipped"
    assert [p["id"] for p in listed] == [p.id for p in paradigms.load_all()]

    for p in listed:
        reply = service.skeleton_payload(p["id"], "probe_spec", {})
        assert reply["result"]["ok"], (
            f"the {p['id']} skeleton does not compile: "
            + "; ".join(
                d["message"] for d in reply["result"]["diagnostics"]
                if d["severity"] == "ERROR"
            )
        )
        assert reply["text"].startswith("spec_version:")


def test_an_answer_lands_on_the_path_the_paradigm_named():
    """An answer is a set on a document path the schema already knows.

    That is what keeps `questions` declarative: the paradigm names a location,
    never a structure, so an answer cannot introduce a shape the generator did
    not already produce.
    """
    import yaml

    from ephymeris_sidecar.specs import service

    reply = service.skeleton_payload(
        "shaping", "shaping_left", {"rewarded_arm": "left_well"}
    )
    doc = yaml.safe_load(reply["text"])
    assert doc["contingency"]["trial_types"][0]["target"] == "left_well"
    assert reply["result"]["ok"]


def test_shaping_builds_every_arm_and_offers_one():
    """Shaping is the full machine with the pool collapsed, not a smaller task.

    Widening it later must be a policy edit -- one weight -- rather than a
    reshape, because a reshape moves the spec hash and splits the animal's
    history in Analytics.
    """
    import yaml

    from ephymeris_sidecar.specs import service

    doc = yaml.safe_load(service.skeleton_payload("shaping", "s", {})["text"])
    weights = [t.get("weight") for t in doc["contingency"]["trial_types"]]
    assert weights.count(1) == 1 and set(weights) == {0, 1}, weights
    assert len(doc["topology"]["response_ports"]) == 2, "both ports stay live"


def test_the_skeleton_writes_nothing(tmp_path):
    """Pure. Creating a task stays specs.save, so rename-and-save keeps one
    definition and a wizard that is abandoned halfway leaves no orphan."""
    from ephymeris_sidecar.specs import service, store as spec_store

    s = spec_store.SpecStore(tmp_path)
    before = [e.spec_id for e in s.records()]
    service.skeleton_payload("two_afc", "not_saved", {})
    assert [e.spec_id for e in s.records()] == before
