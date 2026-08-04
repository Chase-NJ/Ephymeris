"""The human-readable state-table listing.

CHECKED INTO VERSION CONTROL ALONGSIDE THE SPEC. This is the review surface: a
topology change shows up as a diff in the emitted graph, which is a far stronger
artifact than a diff of the rule that produced it. Someone editing a task six
months from now sees exactly which states moved.

Design constraints that follow from being a diff target:

  * Stable ordering everywhere. Nothing may depend on dict iteration or set
    ordering, or an unrelated edit produces spurious diff noise and reviewers stop
    reading it.
  * No timestamps, no absolute paths, no host details. A listing that changes when
    nothing changed is a listing nobody trusts.
  * Symbolic names next to numeric ones. The numbers are what the board runs; the
    names are what a person can check against the spec.
"""

from __future__ import annotations

from ephymeris_sidecar.taskgraph.errors import DiagnosticBag, Severity
from ephymeris_sidecar.taskgraph.graph import NodeType
from ephymeris_sidecar.taskgraph.table import DUR_FROM_TRIAL, NO_STROBE, NO_TARGET, StateTable

RULE = "=" * 78
THIN = "-" * 78


def _strobe_cell(node) -> str:
    """What this state entry actually puts on the wire."""
    if node.strobe_name:
        if node.strobe == NO_STROBE:
            return node.strobe_name          # a @binding, resolved per trial
        return f"{node.strobe_name}({node.strobe})"
    return "— silent" if node.silent_by_design else "—"


def _duration_cell(table: StateTable, node) -> str:
    if node.type in (NodeType.WAIT_EXIT, NodeType.TERMINAL):
        return "—"
    if node.dur_idx == DUR_FROM_TRIAL:
        return "@trial.reward"
    if node.dur_idx < len(table.timing_ids):
        return f"{table.timing_ids[node.dur_idx]}[{node.dur_idx}]"
    return f"?[{node.dur_idx}]"


def render(table: StateTable, bag: DiagnosticBag | None = None) -> str:
    out: list[str] = []
    add = out.append

    add(RULE)
    add(f"  {table.spec_id}  —  compiled state table")
    add(RULE)
    add("")
    add(f"  spec_version    {table.spec_version}")
    add(f"  spec_hash       {table.spec_hash}")
    add(f"  vocab_version   {table.vocab_version}")
    add(f"  template        {table.template} v{table.template_version} ({table.template_hash})")
    # WHICH WIRING. Without this line the listing is blind to a re-pin: every
    # state, edge and duration is identical, because the listing prints channel
    # NAMES -- and specs.diff diffs the listing. A rewired box would produce a
    # different table and a diff that said nothing changed.
    if table.pinout_id or table.pinout_hash:
        add(f"  pinout          {table.pinout_id} ({table.pinout_hash})")
    add("")
    add(
        f"  {len(table.nodes)} states, {len(table.edges)} edges, "
        f"{len(table.timing)} timing entries, {len(table.trial_types)} trial types"
    )
    add(f"  {table.size_bytes()} bytes uploaded")
    add("")

    # -- states ----------------------------------------------------------- #
    add(THIN)
    add("  STATES")
    add(THIN)
    add("")
    add(f"  {'':4} {'TYPE':<11} {'DURATION':<22} {'WATCHES':<24} STROBE")
    add("")
    band_names = {1: "engagement", 2: "stimulus sampling", 3: "response", 4: "outcome"}
    last_band = None
    for i, n in enumerate(table.nodes):
        if n.band != last_band:
            add(f"  ── {n.band} · {band_names.get(n.band, '?')} " + "─" * 40)
            last_band = n.band
        watches = _watch_names(table, n)
        add(
            f"  S{i:02d}  {str(n.type):<11} {_duration_cell(table, n):<22} "
            f"{watches:<24} {_strobe_cell(n)}"
        )
        add(f"       {n.label}")
        for a in table.actions[n.action_idx : n.action_idx + n.action_count]:
            add(f"         on entry: {'set' if a.op else 'clear'} {a.channel_name}")
        for e in table.edges[n.edge_idx : _edge_end(table, i)]:
            guard = f" [{e.guard_text}]" if e.guard_text else ""
            chan = f"({e.channel})" if e.channel else ""
            effect = f"  → {e.effect_text}" if e.effect_text else ""
            add(f"         {str(e.trigger)}{chan}{guard} → S{e.target:02d}{effect}")
        add("")

    # -- timing ----------------------------------------------------------- #
    add(THIN)
    add("  TIMING VECTOR")
    add(THIN)
    add("")
    add("  Durations are INDICES into this vector, never literals — which is what")
    add("  makes a shaping ramp a table rewrite rather than a recompile.")
    add("")
    for i, (tid, ms) in enumerate(zip(table.timing_ids, table.timing, strict=False)):
        add(f"  [{i:2d}] {tid:<22} {ms:>6} ms")
    add("")

    # -- trial types ------------------------------------------------------ #
    add(THIN)
    add("  TRIAL TYPES")
    add(THIN)
    add("")
    for i, tt in enumerate(table.trial_types):
        target = "withhold" if tt.target == NO_TARGET else f"port[{tt.target}]"
        reward = "none" if tt.reward_line == NO_TARGET else f"ch{tt.reward_line}"
        add(
            f"  [{i}] {tt.label:<14} stimuli={list(tt.stimulus)} target={target} "
            f"weight={tt.weight} reward={reward}"
        )
    add("")

    # -- stage schedule --------------------------------------------------- #
    if table.stage_rows:
        add(THIN)
        add("  STAGE SCHEDULE")
        add(THIN)
        add("")
        add("  Scanned DESCENDING with >=, so applying twice or skipping a count lands")
        add("  on the same row. An unreachable row is expressed by omitting it.")
        add("")
        for i, row in enumerate(table.stage_rows):
            add(f"  [{i}] at trial {row.at_trial}:")
            for s in table.timing_sets[row.first_idx : row.first_idx + row.count]:
                tid = table.timing_ids[s.idx] if s.idx < len(table.timing_ids) else "?"
                add(f"        {tid:<22} := {s.ms:>6} ms")
        add("")

    # -- watchdog handoff -------------------------------------------------- #
    add(THIN)
    add("  DWELL BUDGET  (for the Phase 4 watchdog)")
    add(THIN)
    add("")
    unbounded = table.unbounded_nodes()
    if unbounded:
        add("  Bounded ONLY by the runtime watchdog — no static analysis can bound these,")
        add("  because they wait on the subject rather than on a clock:")
        add("")
        for i in unbounded:
            add(f"    S{i:02d}  {table.nodes[i].type}  {table.nodes[i].label}")
        add("")
    worst = sum(d for d in table.max_dwell if d)
    add(f"  Worst-case bounded dwell, summed over all states: {worst} ms")
    add("  (an upper bound on one trial, excluding the states above)")
    add("")

    # -- diagnostics -------------------------------------------------------- #
    if bag is not None and len(bag):
        add(THIN)
        add("  DIAGNOSTICS")
        add(THIN)
        add("")
        for d in bag:
            if d.severity is Severity.INFO:
                add(f"  {d.severity} {d.code}  {d.message}")
        add("")

    return "\n".join(out).rstrip() + "\n"


def _edge_end(table: StateTable, node_index: int) -> int:
    """Where this node's edges stop.

    The count is implied by the NEXT node's offset -- exactly as the firmware
    computes it -- so rendering the listing exercises the same convention the
    interpreter relies on. A break in that invariant shows up here as visibly
    wrong output, not just as a TG503 diagnostic.
    """
    if node_index + 1 < len(table.nodes):
        return table.nodes[node_index + 1].edge_idx
    return len(table.edges)


def _watch_names(table: StateTable, node) -> str:
    """Prefer the symbolic list: it shows runtime-bound watches, which carry no
    static mask bit but are the entire point of the state that holds them."""
    if node.watch_text:
        return ",".join(node.watch_text)
    if not node.watch_mask:
        return "—"
    from ephymeris_sidecar.taskgraph.registries import channels

    names = [c.name for c in channels().watchable if node.watch_mask & (1 << c.watch_bit)]
    return ",".join(names) or "—"


def render_lint(bag: DiagnosticBag, spec_id: str) -> str:
    """The per-spec warning baseline.

    Checked in beside the listing so the ACCEPTED set of warnings is explicit,
    versioned and reviewed. A new warning anywhere becomes a failing diff, which is
    the only warning discipline that survives contact with a working lab -- the
    alternative is a slowly growing pile nobody reads.

    Deliberately NOT a spec key: an `expect_warnings:` field would change
    spec_hash, and spec_hash is session provenance (D7).
    """
    out = [f"# {spec_id} — accepted diagnostics", ""]
    shown = [d for d in bag if d.severity is not Severity.INFO]
    if not shown:
        out.append("(none)")
    for d in shown:
        out.append(d.format())
        out.append("")
    return "\n".join(out).rstrip() + "\n"
