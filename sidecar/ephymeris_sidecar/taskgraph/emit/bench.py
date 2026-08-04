"""The bench card: what to put a probe on, and what it should read.

Phase 5's first half is a scope on a jig, and the failure mode of that kind of
work is a judgement call — someone looks at a trace, decides it "looks about
right", and a 10% reward-volume error ships. So every number an operator will
compare against is generated here, from the compiled table, with its provenance
next to it.

WHAT IS AND IS NOT A FIXED NUMBER. Half the durations in a task are thresholds
rather than durations: a HOLD does not last 500 ms, it *requires* 500 ms and then
ends whenever the subject lets go. A WAIT_EXIT has no duration at all — it lasts
exactly as long as the animal takes. Printing those as expected trace widths would
send someone chasing a discrepancy that is the animal, so they are listed
separately with the measurement that IS meaningful for each.

The one number that is both fixed and consequential is the reward pulse. Pulse
width *is* delivered volume, it is the only duration resolved per trial rather
than from the timing vector, and it is where Phase 1's one compiler bug lived. It
gets its own section and its own procedure.
"""

from __future__ import annotations

from ephymeris_sidecar.taskgraph.graph import NodeType
from ephymeris_sidecar.taskgraph.registries import channels
from ephymeris_sidecar.taskgraph.table import DUR_FROM_TRIAL, StateTable


def _rule(title: str) -> list[str]:
    return ["", title, "-" * max(len(title), 60)]


def render(table: StateTable) -> str:
    chans = channels()
    out: list[str] = []
    add = out.append

    add("=" * 78)
    add(f"  BENCH CARD — {table.spec_id}")
    add(f"  spec {table.spec_hash[:8]} · template {table.template} v{table.template_version}")
    add("=" * 78)
    add("")
    add("  Generated from the compiled table. Every figure below is what the board")
    add("  will actually do, not what the spec was intended to say — so a trace that")
    add("  disagrees is a real disagreement.")
    add("")
    add("  NOT FOR ANIMAL USE until the pulse widths in section 2 have been measured.")

    # ---------------------------------------------------------------- #
    out.extend(_rule("1 · WHERE TO PROBE"))
    add("")
    add(f"  {'channel':<16} {'pin':>4}  {'kind':<12} driven by")
    add(f"  {'-' * 16} {'-' * 4}  {'-' * 12} {'-' * 30}")

    driven: dict[int, list[str]] = {}
    for i, n in enumerate(table.nodes):
        for a in table.actions[n.action_idx : n.action_idx + n.action_count]:
            driven.setdefault(a.channel, []).append(
                f"S{i:02d} {n.label} ({'set' if a.op else 'clear'})"
            )
    for p in table.ports:
        if p.reward_line != 0xFF:
            driven.setdefault(p.reward_line, []).append(f"reward pulse, {p.name}")
    for s in table.stimuli:
        driven.setdefault(s.emitter, []).append(f"stimulus {s.name}")

    seen: set[int] = set()
    for entry in sorted(chans, key=lambda c: c.index):
        if entry.direction != "out" or entry.index in seen:
            continue
        uses = driven.get(entry.index)
        if not uses:
            continue
        seen.add(entry.index)
        add(f"  {entry.name:<16} {entry.index:>4}  {entry.kind:<12} {uses[0]}")
        for extra in uses[1:]:
            add(f"  {'':<16} {'':>4}  {'':<12} {extra}")

    add("")
    add("  Inputs, for the trigger:")
    for entry in sorted(chans, key=lambda c: c.index):
        if entry.direction == "in" and entry.index in set(table.watch_pins):
            add(f"    {entry.name:<16} pin {entry.index:>2}   {entry.kind}")
    add("")
    add("  INPUT_PULLUP: HIGH is beam intact, LOW is broken. A probe on an input")
    add("  reads inverted relative to 'the animal is there'.")

    # ---------------------------------------------------------------- #
    out.extend(_rule("2 · REWARD PULSE — THE MEASUREMENT THAT MATTERS"))
    add("")
    add("  Pulse width IS delivered volume. Measure this one properly.")
    add("")
    add(f"  {'port':<14} {'line pin':>8} {'expected':>10}   from")
    add(f"  {'-' * 14} {'-' * 8} {'-' * 10}   {'-' * 24}")
    for p in table.ports:
        if p.reward_line == 0xFF:
            add(f"  {p.name:<14} {'—':>8} {'—':>10}   no reward on this port")
            continue
        ms = table.timing[p.reward_dur_idx]
        tid = table.timing_ids[p.reward_dur_idx]
        add(f"  {p.name:<14} {p.reward_line:>8} {ms:>8} ms   {tid}")
    add("")
    add("  Procedure. With the manifold dry and a scope on the line's gate:")
    add("    1. Upload the table, then `BENCH PULSE <port>` on the serial console.")
    add("    2. Measure the HIGH width at the MOSFET gate, and again at the coil.")
    add("    3. Repeat ten times; the spread matters as much as the mean.")
    add("")
    add("  Then wet, by mass: ten pulses into a tared vessel, divided by ten. That")
    add("  is the only measurement that closes the loop from `ms` to `microlitres`,")
    add("  and it is the number an experiment is actually about.")
    add("")
    add("  A gate-width that matches and a volume that does not is a rig problem —")
    add("  line pressure, a tired solenoid, an air bubble. A gate width that does")
    add("  not match is a firmware problem, and Gate D says it should not happen.")

    # ---------------------------------------------------------------- #
    out.extend(_rule("3 · FIXED DURATIONS — traces with a width to compare"))
    add("")
    add("  Every DELAY. These run to completion regardless of the subject, so each")
    add("  one is a width you can measure directly.")
    add("")
    add(f"  {'state':<6} {'label':<26} {'expected':>10}   from")
    add(f"  {'-' * 6} {'-' * 26} {'-' * 10}   {'-' * 20}")
    for i, n in enumerate(table.nodes):
        if n.type is not NodeType.DELAY or n.dur_idx == DUR_FROM_TRIAL:
            continue
        ms = table.timing[n.dur_idx]
        if ms == 0:
            continue  # epsilon nodes carry paired strobes; there is no width
        add(f"  S{i:02d}    {n.label[:26]:<26} {ms:>8} ms   {table.timing_ids[n.dur_idx]}")

    zero = [i for i, n in enumerate(table.nodes)
            if n.type is NodeType.DELAY and n.dur_idx != DUR_FROM_TRIAL
            and table.timing[n.dur_idx] == 0]
    if zero:
        add("")
        add(f"  {len(zero)} zero-duration states carry paired strobes and have no width:")
        add("    " + ", ".join(f"S{i:02d}" for i in zero))
        add("  Measured on hardware at 0 ms skew — see docs/spikes/avr-ram.md, Q7.")

    # ---------------------------------------------------------------- #
    out.extend(_rule("4 · THRESHOLDS — not widths; test the boundary"))
    add("")
    add("  A HOLD does not last this long, it REQUIRES this long. A WAIT_ENTRY")
    add("  closes after this long if nothing happens. Measuring the trace width")
    add("  tells you about the animal, not the box; test the boundary instead.")
    add("")
    add(f"  {'state':<6} {'label':<26} {'threshold':>10}   type")
    add(f"  {'-' * 6} {'-' * 26} {'-' * 10}   {'-' * 12}")
    for i, n in enumerate(table.nodes):
        if n.type not in (NodeType.HOLD, NodeType.WAIT_ENTRY):
            continue
        if n.dur_idx == DUR_FROM_TRIAL or n.dur_idx >= len(table.timing):
            continue
        add(f"  S{i:02d}    {n.label[:26]:<26} {table.timing[n.dur_idx]:>8} ms   {n.type}")
    add("")
    add("  With a jig that can break a beam on a timer: release 5 ms UNDER the")
    add("  threshold and confirm the abort path; release 5 ms OVER and confirm the")
    add("  hold completes. Both, for each row. A threshold that is right on average")
    add("  and wrong at the boundary is the failure a mean cannot see.")

    # ---------------------------------------------------------------- #
    unbounded = table.unbounded_nodes()
    out.extend(_rule("5 · SUBJECT-PACED — no expected width exists"))
    add("")
    if unbounded:
        for i in unbounded:
            add(f"  S{i:02d}    {table.nodes[i].label}")
        add("")
        add("  These end when the animal ends them. There is nothing to compare a")
        add("  width against, and a trace here is data about the subject.")
        add("")
        add("  What IS checkable: the watchdog ceiling. Hold the beam broken past")
        add(f"  {_ceiling()} ms and the box must emit WATCHDOG_FAULT, shut every actuator")
        add("  off, and end the session — rather than waiting with an animal in it.")
        add("  That is worth doing once on the bench, because it is the one failure")
        add("  mode no recording can show you after the fact.")
    else:
        add("  None — every state in this task is bounded.")

    # ---------------------------------------------------------------- #
    out.extend(_rule("6 · WHAT A DISAGREEMENT MEANS"))
    add("")
    add("  Gates B, D and E prove the interpreter and runTrial() issue the same")
    add("  writes on the same pins at the same milliseconds. So a bench trace that")
    add("  disagrees with this card is, in order of likelihood:")
    add("")
    add("    1. the rig — wiring, a MOSFET, a solenoid, line pressure;")
    add("    2. the START line — the app is sending a value this card did not use;")
    add("    3. the table on the box is not this table — check the CRC the board")
    add("       reported against `taskgraph upload`'s;")
    add("    4. the interpreter, which would be a gate failing to catch something")
    add("       and is worth stopping for.")
    add("")
    add("  Rule out 3 first. It is one command and it is free:")
    add(f"    taskgraph upload specs/{table.spec_id}.yaml --port <device>")
    add("")
    return "\n".join(out) + "\n"


def _ceiling() -> int:
    from ephymeris_sidecar.taskgraph.registries import limits

    return limits().TG_WATCHDOG_CEILING_MS
