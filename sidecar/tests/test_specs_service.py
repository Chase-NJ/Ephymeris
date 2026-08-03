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

pytestmark = pytest.mark.skipif(
    not compiler.available()[0],
    reason=f"vendored compiler unavailable: {compiler.available()[1]}",
)


@pytest.fixture()
def specs(tmp_path: Path) -> SpecStore:
    """A store over a fresh app-data dir — bundled specs only, no user copies."""
    return SpecStore(tmp_path)


# --- store: reads -----------------------------------------------------------


def test_the_bundled_specs_enumerate(specs: SpecStore):
    entries = specs.list_entries()
    assert len(entries) >= 5
    assert all(e["origin"] == "shipped" for e in entries)
    assert all(e["upstreamChanged"] is False for e in entries)
    ids = [e["specId"] for e in entries]
    assert ids == sorted(ids), "stable order — the list must not reshuffle between calls"
    assert "grgl_2odor" in ids


def test_entries_validate_as_wire_shapes(specs: SpecStore):
    for entry in specs.list_entries():
        assert validate(("ref", "SpecEntry"), entry) == [], entry["specId"]


def test_entries_carry_the_parse_level_metadata(specs: SpecStore):
    entry = next(e for e in specs.list_entries() if e["specId"] == "gonogo")
    assert entry["label"] == "Go/no-go withhold"
    assert entry["template"] == "four_epoch"
    assert entry["templateVersion"] == 2


def test_get_finds_by_id_and_misses_cleanly(specs: SpecStore):
    assert specs.get("gonogo") is not None
    assert specs.get("no_such_spec") is None


def test_parse_document_never_raises():
    assert store.parse_document("spec_id: x") == {"spec_id": "x"}
    assert store.parse_document("{{{") is None
    assert store.parse_document("") is None
    assert store.parse_document("- a list") is None


# --- store: writes ----------------------------------------------------------


def test_saving_over_a_shipped_spec_shadows_it(specs: SpecStore):
    shipped_text = specs.get("gonogo").read_text()
    record = specs.save("gonogo", shipped_text + "\n# my edit\n")

    assert record.origin == "shipped_edited"
    entry = specs.entry_for(record)
    assert entry["origin"] == "shipped_edited"
    assert entry["editedAt"] is not None
    assert entry["upstreamChanged"] is False, "the bundled bytes have not moved"
    # The shipped file itself was never touched.
    assert "# my edit" not in (compiler.bundled_specs_dir() / "gonogo.yaml").read_text()


def test_the_baseline_is_taken_before_the_first_edit_lands(specs: SpecStore):
    shipped_bytes = (compiler.bundled_specs_dir() / "gonogo.yaml").read_bytes()
    specs.save("gonogo", "spec_id: gonogo\n")
    baseline = specs.baseline_dir / "gonogo.yaml"
    assert baseline.read_bytes() == shipped_bytes, (
        "the baseline must be the shipped bytes verbatim — it is what Reset "
        "restores, comments and all"
    )
    # A second save must NOT re-baseline; the first shipped copy is the anchor.
    specs.save("gonogo", "spec_id: gonogo\nmeta: {label: x}\n")
    assert baseline.read_bytes() == shipped_bytes


def test_reset_to_shipped_restores_the_original_bytes(specs: SpecStore):
    shipped_text = specs.get("gonogo").read_text()
    assert "# Go/no-go" in shipped_text, "the shipped comments are the thing being protected"
    specs.save("gonogo", "spec_id: gonogo\n")
    assert specs.get("gonogo").read_text() == "spec_id: gonogo\n"

    restored = specs.delete("gonogo")
    assert restored is not None and restored.origin == "shipped"
    assert restored.read_text() == shipped_text
    assert not (specs.baseline_dir / "gonogo.yaml").exists()


def test_a_user_spec_lives_and_dies_on_its_own(specs: SpecStore):
    record = specs.save("my_task", "spec_id: my_task\n")
    assert record.origin == "user"
    entry = specs.entry_for(record)
    assert entry["upstreamChanged"] is False, "a pure user spec has no upstream"

    assert specs.delete("my_task") is None
    assert specs.get("my_task") is None


def test_deleting_a_shipped_spec_is_refused(specs: SpecStore):
    with pytest.raises(store.SpecReadOnly):
        specs.delete("gonogo")


def test_a_spec_id_is_a_filename_and_traversal_dies_at_the_door(specs: SpecStore):
    for bad in ("../evil", "no/slash", "UPPER", "9starts_with_digit", "", "a" * 41):
        with pytest.raises(store.SpecIdInvalid):
            specs.save(bad, "anything")


def test_upstream_changed_and_acknowledge(specs: SpecStore, monkeypatch: pytest.MonkeyPatch):
    """The whole no-merge policy, end to end, against a simulated app update."""
    import shutil

    # Point the store's view of the bundle at a copy this test can mutate.
    bundled_copy = specs.root / "fake-bundle"
    bundled_copy.mkdir(parents=True)
    shutil.copy(compiler.bundled_specs_dir() / "gonogo.yaml", bundled_copy / "gonogo.yaml")
    monkeypatch.setattr(compiler, "bundled_specs_dir", lambda: bundled_copy)

    specs.save("gonogo", "spec_id: gonogo\n")
    assert specs.upstream_changed("gonogo") is False

    # "An app update ships a changed gonogo."
    (bundled_copy / "gonogo.yaml").write_text("spec_id: gonogo\n# v2 of the shipped spec\n")
    assert specs.upstream_changed("gonogo") is True
    entry = specs.entry_for(specs.get("gonogo"))
    assert entry["upstreamChanged"] is True

    # Keep mine: re-baseline; the badge clears; the user's text is untouched.
    specs.acknowledge_upstream("gonogo")
    assert specs.upstream_changed("gonogo") is False
    assert specs.get("gonogo").read_text() == "spec_id: gonogo\n"


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


# --- diff -------------------------------------------------------------------


def _shipped(spec_id: str) -> str:
    return (compiler.bundled_specs_dir() / f"{spec_id}.yaml").read_text()


def test_an_unedited_spec_diffs_clean_against_itself():
    text = _shipped("gonogo")
    payload = service.diff_payload("gonogo", text, text, "shipped")
    assert validate(("ref", "SpecListingDiff"), payload) == []
    assert payload["changed"] is False
    assert payload["hunks"] == []
    assert payload["before"]["specHash"] == payload["after"]["specHash"]


def test_a_timing_edit_lands_in_the_timing_vector_section_only():
    before = _shipped("gonogo")
    after = before.replace("ms: 2000, wire_key: NWP", "ms: 2500, wire_key: NWP")
    payload = service.diff_payload("gonogo", after, before, "shipped")
    assert payload["changed"] is True
    sections = [h["section"] for h in payload["hunks"]]
    assert "TIMING VECTOR" in sections
    # The header block's hash churn is deliberately NOT a hunk — the summaries
    # carry it once, as provenance, instead of topping every diff.
    assert all("spec_hash" not in line["text"] for h in payload["hunks"] for line in h["lines"])
    assert payload["before"]["specHash"] != payload["after"]["specHash"]


def test_the_ez_variant_is_a_pure_timing_delta():
    """The acceptance criterion the roadmap names, matched to what upstream
    actually pins: the eased variant's STRUCTURE is identical (no STATES or
    TRIAL TYPES hunks — same nodes, same edges), and every hunk lives in a
    value-carrying section. STAGE SCHEDULE and DWELL BUDGET move WITH the
    timing vector because they are derived from it — their hunks are the
    layer-3 delta being visible, not noise."""
    payload = service.diff_payload(
        "shaping_gr_ez", _shipped("shaping_gr_ez"), _shipped("shaping_gr"), "spec"
    )
    assert payload["changed"] is True
    sections = {h["section"] for h in payload["hunks"]}
    assert "TIMING VECTOR" in sections
    structural = {s for s in sections if s.startswith(("STATES", "TRIAL TYPES"))}
    assert not structural, f"an eased variant must not change the graph: {structural}"
    # And the headline agrees: same shape, different bytes.
    assert payload["before"]["nNodes"] == payload["after"]["nNodes"]
    assert payload["before"]["nEdges"] == payload["after"]["nEdges"]
    assert payload["before"]["specHash"] != payload["after"]["specHash"]


def test_a_side_that_does_not_compile_reports_honestly():
    payload = service.diff_payload("gonogo", "not: a spec", _shipped("gonogo"), "shipped")
    assert payload["changed"] is True
    assert payload["after"] is None
    assert payload["before"] is not None
    assert payload["hunks"] == []
    assert validate(("ref", "SpecListingDiff"), payload) == []


def test_a_topology_change_reads_as_states_moving():
    before = _shipped("gonogo")
    after = before.replace("commit_hold: true", "commit_hold: false")
    payload = service.diff_payload("gonogo", after, before, "shipped")
    # Dropping the commitment hold restructures the graph — the STATES section
    # must carry hunks, and the headline counts must move.
    assert any(h["section"] == "STATES" for h in payload["hunks"])
    assert payload["before"]["nNodes"] != payload["after"]["nNodes"]


# --- export -----------------------------------------------------------------


def test_export_produces_every_artifact_kind():
    import base64

    text = _shipped("gonogo")
    payload = service.export_payload(
        "gonogo", text, ["spec", "listing", "lint", "table_json", "table_bin", "bench"]
    )
    by_kind = {a["kind"]: a for a in payload["artifacts"]}
    assert set(by_kind) == {"spec", "listing", "lint", "table_json", "table_bin", "bench"}
    for artifact in payload["artifacts"]:
        assert validate(("ref", "SpecArtifact"), artifact) == []
    assert by_kind["spec"]["text"] == text
    # The listing export IS the checked-in review artifact, byte for byte.
    assert by_kind["listing"]["text"] == (
        compiler.bundled_specs_dir() / "gonogo.table.txt"
    ).read_text()
    blob = base64.b64decode(by_kind["table_bin"]["base64"])
    assert blob[:4] == b"TGTB", "the packed table's magic"
    assert by_kind["bench"]["filename"] == "gonogo.bench.txt"


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
