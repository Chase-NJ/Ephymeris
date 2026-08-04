"""Maps the compiler's output onto the wire shapes.

Pure functions over a CompileResult — no I/O, no state, safe to call from the
worker thread `specs.compile` runs in. The one non-obvious job here is edge
`src`: the canonical table groups edges by owning node and implies each node's
count from the NEXT node's offset (that monotonicity is rule TG503), so the
graph payload reconstructs the source index rather than asking the compiler to
carry a redundant field it deliberately doesn't.
"""

from __future__ import annotations

from typing import Any

from . import compiler


def compile_payload(text: str, spec_id: str | None = None) -> dict[str, Any]:
    """The full `SpecCompileResult` for one document."""
    import time

    start = time.perf_counter()
    result = compiler.compile(text, spec_id=spec_id)
    elapsed_ms = (time.perf_counter() - start) * 1000

    payload: dict[str, Any] = {
        "ok": result.ok,
        "diagnostics": [_diagnostic(d) for d in result.bag],
        "table": None,
        "graph": None,
        "listing": None,
        "elapsedMs": elapsed_ms,
    }
    if result.table is not None:
        table = compiler.table_json(result)
        payload["table"] = _summary(table, result)
        payload["graph"] = _graph(table)
        payload["listing"] = compiler.render_listing(result)
    return payload


def diff_payload(
    spec_id: str,
    after_text: str,
    before_text: str,
    baseline: str,
) -> dict[str, Any]:
    """`SpecListingDiff`: the LISTING diffed, never the YAML.

    The listing is the checked-in review artifact upstream, so it is what a
    topology change is reviewed against here. Three renderings turn a diff into
    a review rather than noise:

    - Hunks are grouped by the listing's own ruled sections, so a change reads
      as "in STATES" rather than "at line 71".
    - The header block is EXCLUDED from the hunks: spec_hash and template_hash
      move on every edit and would top every diff with churn. The before/after
      summaries carry them once, as a provenance strip.
    - A side that does not compile contributes a null summary and no listing;
      `changed` stays honest either way.
    """
    import difflib

    before = compiler.compile(before_text, spec_id=spec_id)
    after = compiler.compile(after_text, spec_id=spec_id)

    before_listing = compiler.render_listing(before) if before.ok else None
    after_listing = compiler.render_listing(after) if after.ok else None

    hunks: list[dict[str, Any]] = []
    added = removed = 0
    if before_listing is not None and after_listing is not None:
        before_sections = _listing_sections(before_listing)
        after_sections = _listing_sections(after_listing)
        # Section order: as they appear in the after side, then any that only
        # the before side had (a section a change deleted still shows).
        names = list(after_sections)
        names += [n for n in before_sections if n not in after_sections]
        for name in names:
            if name == _HEADER:
                continue
            lines = list(
                difflib.unified_diff(
                    before_sections.get(name, []),
                    after_sections.get(name, []),
                    lineterm="",
                    n=3,
                )
            )[3:]  # drop ---/+++/@@ header noise; sectioning replaces it
            out = [
                {"op": line[0], "text": line[1:]}
                for line in lines
                if line[:1] in (" ", "+", "-")
            ]
            if any(entry["op"] != " " for entry in out):
                hunks.append({"section": name, "lines": out})
                added += sum(1 for entry in out if entry["op"] == "+")
                removed += sum(1 for entry in out if entry["op"] == "-")

    return {
        "specId": spec_id,
        "baseline": baseline,
        "changed": bool(hunks)
        or (before_listing is None) != (after_listing is None)
        or (
            before.ok
            and after.ok
            and before.table.spec_hash != after.table.spec_hash  # type: ignore[union-attr]
        ),
        "before": _summary(compiler.table_json(before), before) if before.ok else None,
        "after": _summary(compiler.table_json(after), after) if after.ok else None,
        "hunks": hunks,
        "added": added,
        "removed": removed,
    }


_HEADER = "HEADER"
_RULE = "-" * 10


def _listing_sections(listing: str) -> dict[str, list[str]]:
    """Split a rendered listing at its ruled section headers.

    The renderer writes each section as a rule line, the indented name, and a
    closing rule; everything before the first rule is the header block. Parsed
    positionally rather than against a name list, so a future section joins the
    diff without a change here.
    """
    sections: dict[str, list[str]] = {_HEADER: []}
    current = _HEADER
    lines = listing.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            line.strip().startswith(_RULE)
            and i + 2 < len(lines)
            and lines[i + 2].strip().startswith(_RULE)
            and lines[i + 1].strip()
        ):
            current = lines[i + 1].strip()
            sections[current] = []
            i += 3
            continue
        sections[current].append(line)
        i += 1
    return sections


#: What `specs.export` can produce. Everything is a pure function of a compile,
#: and the bin is base64 because the wire is JSON — the frontend decodes and
#: writes it through the user's own save dialog.
def export_payload(spec_id: str, text: str, kinds: list[str]) -> dict[str, Any]:
    import base64

    result = compiler.compile(text, spec_id=spec_id)
    artifacts: list[dict[str, Any]] = []

    def add(kind: str, filename: str, *, content: str | None = None, blob: bytes | None = None):
        artifacts.append(
            {
                "kind": kind,
                "filename": filename,
                "text": content,
                "base64": base64.b64encode(blob).decode("ascii") if blob is not None else None,
            }
        )

    for kind in kinds:
        if kind == "spec":
            add("spec", f"{spec_id}.yaml", content=text)
        elif not result.ok:
            # Everything else is a function of a compiled table; a spec that
            # doesn't compile has none, and the caller's live diagnostics
            # already say why.
            continue
        elif kind == "listing":
            add("listing", f"{spec_id}.table.txt", content=compiler.render_listing(result))
        elif kind == "lint":
            add("lint", f"{spec_id}.lint.txt", content=compiler.render_lint(result))
        elif kind == "table_json":
            import json as _json

            add(
                "table_json",
                f"{spec_id}.table.json",
                content=_json.dumps(compiler.table_json(result), indent=2, sort_keys=True) + "\n",
            )
        elif kind == "table_bin":
            blob, _crc = compiler.table_bytes(result)
            add("table_bin", f"{spec_id}.table.bin", blob=blob)
        elif kind == "bench":
            add("bench", f"{spec_id}.bench.txt", content=compiler.render_bench(result))
    return {"artifacts": artifacts}


def paradigms_payload() -> dict[str, Any]:
    """The gallery, and the wizard's script.

    `fixes` is the paradigm's topology fragment verbatim rather than a resolved
    topology: what it does NOT contain is exactly what the operator may still
    move in the Designer, and resolving it would erase that distinction.
    """
    from ephymeris_sidecar.taskgraph import paradigms as reg

    return {
        "paradigms": [
            {
                "id": p.id,
                "name": p.name,
                "affords": p.affords,
                "order": p.order,
                "template": p.template,
                "templateVersion": p.template_version,
                "fixes": dict(p.topology),
                "questions": [
                    {
                        "id": q.id,
                        "label": q.label,
                        "path": q.path,
                        "help": q.help or None,
                        "source": q.source,
                        "kind": q.kind,
                        "required": q.required,
                    }
                    for q in p.questions
                ],
            }
            for p in reg.load_all()
        ]
    }


def skeleton_payload(
    paradigm_id: str,
    spec_id: str,
    answers: dict[str, Any] | None,
    *,
    label: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """A first draft, and the compile of it, in one reply."""
    from ephymeris_sidecar.taskgraph import paradigms as reg

    doc = reg.skeleton(
        reg.get(paradigm_id),
        spec_id=spec_id,
        answers=answers or {},
        label=label,
        description=description,
    )
    text = reg.to_yaml(doc)
    return {"text": text, "result": compile_payload(text, spec_id)}


def capabilities_payload(topology: dict[str, Any]) -> dict[str, Any]:
    caps = compiler.capabilities_for(topology)
    name = topology.get("template") or compiler.DEFAULT_TEMPLATE[0]
    version = topology.get("template_version") or compiler.DEFAULT_TEMPLATE[1]
    return {
        # Sorted for a stable wire; the ORDER that matters is requiredTiming's,
        # which is the template's own and is preserved.
        "outcomeClasses": sorted(caps.outcome_classes),
        "requiredTiming": list(caps.required_timing),
        "knobs": list(caps.knobs),
        "template": str(name),
        "templateVersion": int(version),
    }


def _diagnostic(d: Any) -> dict[str, Any]:
    placement, anchor = compiler.diagnostic_placement(d.location)
    return {
        "code": d.code,
        "severity": d.severity.name,
        "message": d.message,
        "location": d.location,
        "placement": placement,
        "anchor": anchor,
        "detail": d.detail,
        "help": d.help,
        "decision": d.decision,
    }


def _summary(table: dict[str, Any], result: Any) -> dict[str, Any]:
    _, crc = compiler.table_bytes(result)
    return {
        "specId": table["spec_id"],
        "specHash": table["spec_hash"],
        "specVersion": table["spec_version"],
        "vocabVersion": table["vocab_version"],
        "template": table["template"],
        "templateVersion": table["template_version"],
        "templateHash": table["template_hash"],
        "pinoutId": table["pinout_id"],
        "pinoutHash": table["pinout_hash"],
        "nNodes": len(table["nodes"]),
        "nEdges": len(table["edges"]),
        "nTiming": len(table["timing"]),
        "nTrialTypes": len(table["trial_types"]),
        "sizeBytes": table["size_bytes"],
        "crc32": f"{crc:#010x}",
    }


def _graph(table: dict[str, Any]) -> dict[str, Any]:
    timing = table["timing"]
    nodes = table["nodes"]
    edges = table["edges"]

    def duration(node: dict[str, Any]) -> tuple[str | None, int | None]:
        idx = node["duration_index"]
        # Sentinels (DUR_FROM_TRIAL and friends) sit far above the vector; a
        # real index resolves to an id and a value, anything else is "no static
        # duration" — which the graph renders as such rather than as a number.
        if isinstance(idx, int) and 0 <= idx < len(timing):
            return timing[idx]["id"], timing[idx]["ms"]
        return None, None

    out_nodes = []
    for node in nodes:
        duration_id, duration_ms = duration(node)
        out_nodes.append(
            {
                "index": node["index"],
                "symbol": node["symbol"],
                "label": node["label"],
                "band": node["band"],
                "type": node["type"],
                "durationId": duration_id,
                "durationMs": duration_ms,
                "strobeName": node["strobe_name"],
                "strobe": node["strobe"],
                "silentByDesign": node["silent_by_design"],
                "watch": node["watch"],
            }
        )

    # Edge ownership: node i owns edges [edge_index_i, edge_index_{i+1}).
    offsets = [node["edge_index"] for node in nodes] + [len(edges)]
    out_edges = []
    for i, node in enumerate(nodes):
        for j in range(offsets[i], offsets[i + 1]):
            edge = edges[j]
            out_edges.append(
                {
                    "index": edge["index"],
                    "src": node["index"],
                    "dst": edge["target"],
                    "trigger": edge["trigger"],
                    # The emitters render "no guard/effect" as an empty string;
                    # the wire says null, so a client can `?? "default"` without
                    # a truthiness footgun.
                    "guard": edge["guard_text"] or None,
                    "channel": edge["channel"] or None,
                    "effect": edge["effect_text"] or None,
                }
            )

    return {"nodes": out_nodes, "edges": out_edges, "entry": 0}
