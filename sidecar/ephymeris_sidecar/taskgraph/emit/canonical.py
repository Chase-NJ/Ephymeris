"""Canonical JSON — the machine-readable table.

Phase 2's reference interpreter reads this. Deliberately NOT checked in: it
duplicates the listing's content without being reviewable, so committing it would
double every review diff for no gain.

Sorted keys and no floats, so two compiles of the same spec produce byte-identical
output. That matters because the whole-table CRC in Phase 4 is taken over the
packed form of this data, and a hash that moves when nothing moved is worthless as
provenance.
"""

from __future__ import annotations

import json

from ephymeris_sidecar.taskgraph.table import StateTable


def to_dict(table: StateTable) -> dict:
    return {
        "spec_id": table.spec_id,
        "spec_hash": table.spec_hash,
        "spec_version": table.spec_version,
        "vocab_version": table.vocab_version,
        "template": table.template,
        "template_version": table.template_version,
        "template_hash": table.template_hash,
        "size_bytes": table.size_bytes(),
        "timing": [
            {"index": i, "id": tid, "ms": ms}
            for i, (tid, ms) in enumerate(zip(table.timing_ids, table.timing, strict=False))
        ],
        "nodes": [
            {
                "index": i,
                "symbol": n.symbol,
                "label": n.label,
                "band": n.band,
                "type": str(n.type),
                "duration_index": n.dur_idx,
                "strobe": n.strobe,
                "strobe_name": n.strobe_name,
                "silent_by_design": n.silent_by_design,
                "watch_mask": n.watch_mask,
                "watch": list(n.watch_text),
                "action_index": n.action_idx,
                "action_count": n.action_count,
                "edge_index": n.edge_idx,
                # The watchdog handoff: null means no static bound exists, which is
                # precisely the set Phase 4 must cover.
                "max_dwell_ms": table.max_dwell[i] if i < len(table.max_dwell) else None,
            }
            for i, n in enumerate(table.nodes)
        ],
        "edges": [
            {
                "index": i,
                "trigger": str(e.trigger),
                "guard": e.guard,
                "guard_text": e.guard_text,
                "channel": e.channel,
                "target": e.target,
                "effect": e.effect,
                "effect_text": e.effect_text,
            }
            for i, e in enumerate(table.edges)
        ],
        "actions": [
            {"index": i, "channel": a.channel, "channel_name": a.channel_name, "op": a.op}
            for i, a in enumerate(table.actions)
        ],
        "trial_types": [
            {
                "index": i,
                "label": r.label,
                "stimulus": list(r.stimulus),
                "target": r.target,
                "weight": r.weight,
                "reward_line": r.reward_line,
                "reward_duration_index": r.reward_dur_idx,
            }
            for i, r in enumerate(table.trial_types)
        ],
        # What a `@binding` resolves against. Present because their absence was a
        # real gap: a table can be walked without them, but not REPORTED -- the
        # board would know a poke happened and not which code names it.
        "ports": [
            {
                "index": i,
                "name": p.name,
                "channel": p.channel,
                "reward_line": p.reward_line,
                "enter_code": p.enter_code,
                "error_code": p.error_code,
                "break_code": p.break_code,
                "exit_code": p.exit_code,
                "reward_code": p.reward_code,
                "reward_stop_code": p.reward_stop_code,
                "reward_duration_index": p.reward_dur_idx,
            }
            for i, p in enumerate(table.ports)
        ],
        "stimuli": [
            {"index": i, "name": s.name, "emitter": s.emitter, "on_code": s.on_code}
            for i, s in enumerate(table.stimuli)
        ],
        # Watch-mask bit -> pin, and bit -> port index. What turns a set bit back
        # into something the board can digitalRead() and something an analyst can
        # name.
        "watch": [
            {"bit": i, "pin": pin, "port_index": port}
            for i, (pin, port) in enumerate(
                zip(table.watch_pins, table.watch_ports, strict=True)
            )
        ],
        "stage_rows": [
            {
                "index": i,
                "at_trial": r.at_trial,
                "sets": [
                    {"timing_index": s.idx, "ms": s.ms}
                    for s in table.timing_sets[r.first_idx : r.first_idx + r.count]
                ],
            }
            for i, r in enumerate(table.stage_rows)
        ],
        "unbounded_nodes": table.unbounded_nodes(),
    }


def to_json(table: StateTable) -> str:
    return json.dumps(to_dict(table), indent=2, sort_keys=True) + "\n"
