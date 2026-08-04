"""The overlay and the schema must name the same set of fields.

This test is the whole reason schema/task_spec.presentation.v1.json lives in this
repo rather than in the app that renders it. A label table in another repository is
a mirror, and this repo has already been bitten twice by mirrors that drift --
START_LINE_MAX across two repos, baudRate across nine files. Here the drift is
mechanical to detect, so it is detected.

Both directions matter. A schema leaf with no overlay entry renders as a raw dotted
path with no units and no help, which is exactly the "flat list of forty unlabelled
numbers" the presentation metadata exists to prevent. An overlay entry naming
nothing is a field that was removed, and it will sit there looking authoritative.
"""

from __future__ import annotations

import json
from functools import lru_cache

import pytest

from ephymeris_sidecar.taskgraph.loader import SCHEMA_PATH
from ephymeris_sidecar.taskgraph.presentation import ID_ADDRESSED, is_keyed_collection, presentation


def _scalar_array(node: dict) -> bool:
    """An array of scalars, edited as one control rather than as rows."""
    items = node.get("items")
    return isinstance(items, dict) and "properties" not in items and items.get("type") != "object"


def _walk(node: dict, path: str, defs: dict, out: dict[str, dict]) -> None:
    if "$ref" in node:
        _walk(defs[node["$ref"].split("/")[-1]], path, defs, out)
        return

    props = node.get("properties")
    additional = node.get("additionalProperties")

    if props:
        # A keyed collection's child properties are instance names, not schema
        # keys -- the seven outcome classes are seven rows of one form, not seven
        # forms. They collapse to the wildcard the overlay is keyed by.
        if is_keyed_collection(path):
            _walk(_merged(props, defs), f"{path}.*", defs, out)
            return
        for key, child in props.items():
            _walk(child, f"{path}.{key}" if path else key, defs, out)
        return

    if isinstance(additional, dict):
        _walk(additional, f"{path}.*" if path else "*", defs, out)
        return

    if node.get("type") == "array" and isinstance(node.get("items"), dict) and not _scalar_array(node):
        # An id-addressed array is spelled `.*` and not `[]`, because that is how
        # its diagnostics address it (see presentation.ID_ADDRESSED).
        tail = ".*" if path in ID_ADDRESSED else "[]"
        _walk(node["items"], f"{path}{tail}", defs, out)
        return

    out[path] = node


def _merged(props: dict, defs: dict) -> dict:
    """One representative shape for a keyed collection's instances.

    The seven outcome classes are declared separately but must offer the same
    fields; merging rather than picking one is what makes a class that quietly
    grew an extra key show up as an uncovered leaf.
    """
    merged: dict = {"properties": {}}
    for child in props.values():
        while "$ref" in child:
            child = defs[child["$ref"].split("/")[-1]]
        merged["properties"].update(child.get("properties", {}))
    return merged


@lru_cache(maxsize=1)
def schema_leaves() -> dict[str, dict]:
    schema = json.loads(SCHEMA_PATH.read_text())
    out: dict[str, dict] = {}
    _walk(schema, "", schema.get("$defs", {}), out)
    return out


def test_every_schema_leaf_has_an_overlay_entry():
    missing = sorted(set(schema_leaves()) - set(presentation()["fields"]))
    assert not missing, (
        "these schema fields have no entry in task_spec.presentation.v1.json, so a "
        "form would render them as bare dotted paths:\n  " + "\n  ".join(missing)
    )


def test_every_overlay_entry_names_a_schema_leaf():
    extra = sorted(set(presentation()["fields"]) - set(schema_leaves()))
    assert not extra, (
        "these overlay entries name nothing in task_spec.v1.json -- the field was "
        "probably removed from the schema:\n  " + "\n  ".join(extra)
    )


def test_every_field_declares_a_label_and_a_known_group():
    groups = {g["id"] for g in presentation()["groups"]}
    for key, spec in presentation()["fields"].items():
        assert spec.get("label"), f"{key} has no label"
        assert spec.get("widget"), f"{key} has no widget"
        if "group" in spec:
            assert spec["group"] in groups, f"{key} names unknown group {spec['group']!r}"


def test_every_section_names_a_known_group():
    groups = {g["id"] for g in presentation()["groups"]}
    for key, spec in presentation()["sections"].items():
        assert spec["group"] in groups, f"section {key} names unknown group {spec['group']!r}"
        assert spec["rows"] in ("indexed", "by_id", "by_key", "object"), key


ENUM_FIELDS = sorted(k for k, v in presentation()["fields"].items() if v.get("widget") == "enum")


def test_there_are_enum_fields_to_check():
    """Guards the parametrisation itself: an empty list would pass silently."""
    assert len(ENUM_FIELDS) >= 5, ENUM_FIELDS


@pytest.mark.parametrize("key", ENUM_FIELDS)
def test_enum_options_match_the_schema(key: str):
    """An enum whose options drift from the schema offers a value the compiler rejects.

    No skip branch on purpose. Every overlay enum must resolve to a schema enum --
    if one does not, either the widget is wrong or the walk is, and both are worth
    a failure rather than a quiet pass.
    """
    declared = schema_leaves()[key].get("enum")
    assert declared is not None, f"{key} is an enum in the overlay but not in the schema"
    offered = [o["value"] for o in presentation()["fields"][key]["options"]]
    assert offered == list(declared), (
        f"{key}: overlay offers {offered}, schema allows {list(declared)}"
    )
