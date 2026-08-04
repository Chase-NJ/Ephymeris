"""P0 — load YAML, run the parse/schema rules, hash, bind.

The TG1xx checks themselves live in lint/rules_load.py, registered like every
other rule so they carry help text and are covered by the same fixture battery.
This module is the driver.

THE HASH IS TAKEN BEFORE BINDING. spec_hash covers the file as authored, because
it is session provenance: two runs with the same hash must have been the same
document. Hashing the bound dataclasses instead would make a defaulted field
invisible to the hash, so a spec that changed a default would record as unchanged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from ephymeris_sidecar.taskgraph.errors import DiagnosticBag
from ephymeris_sidecar.taskgraph.lint import Pass, run_pass
from ephymeris_sidecar.taskgraph.lint.rules_load import LoadContext
from ephymeris_sidecar.taskgraph.spec import (
    ContextRow,
    Contingency,
    Meta,
    Outcome,
    PenaltyEscalation,
    Policy,
    PortBinding,
    Selection,
    StageRow,
    Stimulus,
    TaskSpec,
    TimingEntry,
    Topology,
    TrialType,
)

from .paths import TASK_SPEC_SCHEMA as SCHEMA_PATH  # noqa: F401


def compute_spec_hash(raw: dict) -> str:
    """SHA-256 over canonical JSON, truncated to 16 hex chars.

    Matches the shape Ephymeris already uses for profile_hash and params_hash, so
    the three read alike in a session record and can be compared at a glance.
    """
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Binding
# --------------------------------------------------------------------------- #


def _timing(raw: list[dict]) -> tuple[TimingEntry, ...]:
    return tuple(
        TimingEntry(
            id=t["id"],
            ms=t["ms"],
            wire_key=t.get("wire_key"),
            note=t.get("note"),
            index=i,  # ORDER IS LOAD-BEARING -- this is the firmware's index
        )
        for i, t in enumerate(raw)
    )


def _contingency(raw: dict) -> Contingency:
    return Contingency(
        ports={
            name: PortBinding(name=name, **{k: v for k, v in p.items()})
            for name, p in raw["ports"].items()
        },
        trial_types=tuple(
            TrialType(
                id=t["id"],
                stages=tuple(t.get("stages", ())),
                target=t.get("target"),
                weight=t.get("weight", 1),
                note=t.get("note"),
            )
            for t in raw["trial_types"]
        ),
        outcome_map={
            name: Outcome(
                name=name,
                terminal=o["terminal"],
                delay=o["delay"],
                reward=o.get("reward"),
                strobe=o.get("strobe"),
                trigger=o.get("trigger"),
                note=o.get("note"),
                strobe_declared="strobe" in o,
            )
            for name, o in raw["outcome_map"].items()
        },
        stimuli=tuple(
            Stimulus(id=s["id"], emitter=s["emitter"], on_code=s.get("on_code"), note=s.get("note"))
            for s in raw.get("stimuli", ())
        ),
        context_schedule=tuple(
            ContextRow(at_trial=c["at_trial"], targets=c["targets"], context=c.get("context"))
            for c in raw.get("context_schedule", ())
        ),
    )


def _policy(raw: dict) -> Policy:
    sel = raw.get("selection")
    esc = raw.get("penalty_escalation")
    return Policy(
        selection=Selection(**sel) if sel else None,
        correction=dict((raw.get("correction") or {}).get("budgets", {})),
        penalty_escalation=PenaltyEscalation(**esc) if esc else None,
        stage_schedule=tuple(
            StageRow(at_trial=s["at_trial"], set=dict(s["set"]))
            for s in raw.get("stage_schedule", ())
        ),
        n_trials=raw.get("n_trials"),
        seed=raw.get("seed", "host"),
    )


def bind(raw: dict, *, source_path: str | None = None, spec_hash: str = "") -> TaskSpec:
    """dict -> frozen TaskSpec. Assumes the schema already validated."""
    t = raw["topology"]
    return TaskSpec(
        spec_version=raw["spec_version"],
        spec_id=raw["spec_id"],
        vocab_version=raw["vocab_version"],
        meta=Meta(**raw.get("meta", {})),
        topology=Topology(
            template=t["template"],
            template_version=t.get("template_version", 1),
            n_sampling_stages=t["n_sampling_stages"],
            retention_delay=t.get("retention_delay", False),
            response_mode=t["response_mode"],
            response_ports=tuple(t["response_ports"]),
            commit_hold=t.get("commit_hold", True),
            cue_off_placement=t.get("cue_off_placement", "before_partner"),
        ),
        timing=_timing(raw["timing"]),
        contingency=_contingency(raw["contingency"]),
        policy=_policy(raw.get("policy", {})),
        source_path=source_path,
        spec_hash=spec_hash,
    )


def load_text(
    text: str,
    bag: DiagnosticBag,
    *,
    source_path: str | None = None,
    spec_id: str | None = None,
) -> TaskSpec | None:
    """Full P0 on an in-memory document. Returns None when it cannot be bound.

    Binding is attempted only once the LOAD rules are clean: _contingency() and
    friends index required keys directly, so a KeyError from a malformed document
    would be a crash where a diagnostic belongs.

    A GUI editor compiles the string it is about to save, so the whole LOAD pass
    -- schema validation, the TG1xx rules, the YAML `on:` trap -- runs on exactly
    the bytes that will land on disk, not on a dict that skipped parsing.
    """
    ctx = LoadContext(text=text, source_path=source_path, spec_id=spec_id)
    try:
        ctx.raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        ctx.parse_error = str(exc)

    if isinstance(ctx.raw, dict) and isinstance(ctx.raw.get("spec_id"), str):
        ctx.spec_id = ctx.raw["spec_id"]

    bag.extend(run_pass(Pass.LOAD, ctx))
    if bag.has_errors():
        return None

    # Belt as well as braces. TG100 rejects every non-mapping, so reaching here
    # with one means a LOAD rule regressed -- and the cost of that is a TypeError
    # out of bind() instead of a diagnostic, on a call the editor makes per
    # keystroke. "Never raises for a spec problem" is worth more than the branch.
    if not isinstance(ctx.raw, dict):
        return None

    return bind(ctx.raw, source_path=source_path, spec_hash=compute_spec_hash(ctx.raw))


def load(path: str | Path, bag: DiagnosticBag) -> TaskSpec | None:
    """Full P0 from a file. See load_text for the pass itself."""
    path = Path(path)
    return load_text(path.read_text(encoding="utf-8"), bag, source_path=str(path), spec_id=path.stem)
