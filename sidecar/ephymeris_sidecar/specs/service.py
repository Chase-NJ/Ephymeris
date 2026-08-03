"""Maps the vendored compiler's output onto the wire shapes.

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
