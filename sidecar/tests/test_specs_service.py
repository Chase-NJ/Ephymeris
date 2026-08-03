"""The specs.* surface: store enumeration, compile payloads, capabilities.

Wire-shape conformance rides on EPHYMERIS_WIRE_VALIDATE (conftest sets it), so
these tests validate every payload against the generated schema — a field the
service forgets or misspells fails here, not in the frontend.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.protocol import validate
from ephymeris_sidecar.specs import compiler, service, store

pytestmark = pytest.mark.skipif(
    not compiler.available()[0],
    reason=f"vendored compiler unavailable: {compiler.available()[1]}",
)


# --- store ------------------------------------------------------------------


def test_the_bundled_specs_enumerate():
    entries = store.list_entries()
    assert len(entries) >= 5
    assert all(e["origin"] == "shipped" for e in entries)
    ids = [e["specId"] for e in entries]
    assert ids == sorted(ids), "stable order — the list must not reshuffle between calls"
    assert "grgl_2odor" in ids


def test_entries_validate_as_wire_shapes():
    for entry in store.list_entries():
        assert validate(("ref", "SpecEntry"), entry) == [], entry["specId"]


def test_entries_carry_the_parse_level_metadata():
    entry = next(e for e in store.list_entries() if e["specId"] == "gonogo")
    assert entry["label"] == "Go/no-go withhold"
    assert entry["template"] == "four_epoch"
    assert entry["templateVersion"] == 2


def test_get_finds_by_id_and_misses_cleanly():
    assert store.get("gonogo") is not None
    assert store.get("no_such_spec") is None


def test_parse_document_never_raises():
    assert store.parse_document("spec_id: x") == {"spec_id": "x"}
    assert store.parse_document("{{{") is None
    assert store.parse_document("") is None
    assert store.parse_document("- a list") is None


# --- compile payloads -------------------------------------------------------


@pytest.fixture(scope="module")
def gonogo_payload() -> dict:
    text = (compiler.bundled_specs_dir() / "gonogo.yaml").read_text()
    return service.compile_payload(text, "gonogo")


def test_a_clean_compile_validates_as_a_wire_shape(gonogo_payload: dict):
    assert gonogo_payload["ok"] is True
    assert validate(("ref", "SpecCompileResult"), gonogo_payload) == []


def test_the_summary_matches_the_cli_numbers(gonogo_payload: dict):
    table = gonogo_payload["table"]
    # Pinned against the checked-in listing header for gonogo — if these move,
    # either the spec changed (fine, update them) or the mapping broke (not).
    assert table["nNodes"] == 21
    assert table["nEdges"] == 29
    assert table["nTiming"] == 11
    assert table["specHash"] == "a598fb6cc57b8aab"
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


def test_the_listing_is_the_checked_in_review_artifact(gonogo_payload: dict):
    golden = (compiler.bundled_specs_dir() / "gonogo.table.txt").read_text()
    assert gonogo_payload["listing"] == golden


def test_a_failing_compile_is_a_payload_not_an_exception():
    payload = service.compile_payload("not: a spec", "scratch")
    assert payload["ok"] is False
    assert payload["table"] is None and payload["graph"] is None and payload["listing"] is None
    assert any(d["severity"] == "ERROR" for d in payload["diagnostics"])
    assert validate(("ref", "SpecCompileResult"), payload) == []


def test_diagnostics_carry_a_placement_and_field_anchors_are_overlay_keys():
    text = (compiler.bundled_specs_dir() / "gonogo.yaml").read_text()
    broken = text.replace("ms: 2000, wire_key: NWP", "ms: 2000000, wire_key: NWP")
    payload = service.compile_payload(broken, "gonogo")
    assert payload["ok"] is False
    placed = {d["placement"] for d in payload["diagnostics"]}
    assert placed <= {"field", "row", "section", "node", "document"}
    field_diags = [d for d in payload["diagnostics"] if d["placement"] == "field"]
    assert field_diags, payload["diagnostics"]
    overlay = compiler.registries()["overlay"]["fields"]
    for d in field_diags:
        assert d["anchor"] in overlay, f"{d['code']} anchored to unknown key {d['anchor']}"


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
