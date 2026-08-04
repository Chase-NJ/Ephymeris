"""Paradigms, and the skeleton generator they drive.

A PARADIGM IS A SHAPE, NOT A FILE. It names a template and fixes the knobs that
make a kind of experiment what it is -- one stimulus and two ports for a 2AFC,
a withhold window for go/no-go -- and it says what the wizard should ask about
everything else. It declares no `nodes:`, no timing value and no strobe code;
`schema/paradigm.v1.json` rejects all three, so a paradigm file cannot grow into
a second spec format.

WHY A GENERATOR IS ALLOWED HERE, WHEN IT WAS NOT BEFORE
-------------------------------------------------------
`docs/specs.md` used to argue that a blank-skeleton generator "would be a second
definition of what a minimal legal spec is, competing with the schema", and that
a bundled paradigm was better because it was a task the compiler and the linter
already agreed on. That argument is comparative, and both of its terms have
moved:

1.  There are no bundled specs any more, so the alternative to a generator is
    not a curated example -- it is nothing.

2.  More importantly, THIS GENERATOR DEFINES NOTHING. Every value it emits is
    read from an authority that already existed:

        which knobs are fixed, which are asked   -> the paradigm file
        which outcome classes, which timing ids,
        each class's trigger/terminal/strobe,
        each id's default ms/wire_key/note       -> the TEMPLATE, via
                                                    capabilities()
        channel names, reward-line/well pairing  -> the channel registry
        the five per-port strobes                -> the strobe vocabulary
        anything else                            -> the user's answer, or the
                                                    field is not emitted

    That is the rule the structural edit operations already follow -- seeded
    from a sibling or asked for inline, never from a defaults table -- applied
    to creation instead of to editing. The generator is a join, not a source.

What is genuinely lost, and worth saying rather than papering over: the deleted
bundled specs carried hand-written comments citing firmware line numbers. Some
of that survives, because `timing_defaults` carries `wire_key` and `note` into
the generated document. The prose framing does not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import yaml

from .paths import PARADIGM_DIR, SCHEMA_DIR
from .registries import channels, vocabulary


class ParadigmError(RuntimeError):
    """A paradigm file is malformed. An install-integrity failure, not a user error."""


@dataclass(frozen=True)
class Question:
    """One thing the wizard asks, bound to a document path the schema knows.

    `path` being a real document path is what keeps this declarative: an answer
    is a `setAt` on a validated location, never new structure the paradigm
    invented.
    """

    id: str
    label: str
    path: str
    help: str = ""
    source: str = "value"      # value | channel | stimulus | trial_type | strobe
    kind: str | None = None    # for source=channel: which channel kind
    required: bool = False


@dataclass(frozen=True)
class Paradigm:
    id: str
    name: str
    affords: str
    order: int
    hidden: bool
    template: str
    template_version: int
    topology: dict[str, Any]
    contingency: dict[str, Any]
    policy: dict[str, Any] = field(default_factory=dict)
    questions: tuple[Question, ...] = ()

    @property
    def n_response_ports(self) -> int:
        return int(self.topology.get("response_ports", 2))

    @property
    def n_stimuli(self) -> int:
        return int(self.contingency.get("stimuli", 1))

    @property
    def rewarded(self) -> bool:
        return bool(self.contingency.get("rewarded", True))


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads((SCHEMA_DIR / "paradigm.v1.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_all() -> tuple[Paradigm, ...]:
    """Every paradigm on disk, validated, in gallery order.

    Validation failures raise rather than warn: a malformed paradigm means the
    New Task screen offers something that cannot be built, and `self_check()`
    is where that surfaces -- at startup, in the log, once.
    """
    import jsonschema

    found: list[Paradigm] = []
    seen: set[str] = set()
    for path in sorted(PARADIGM_DIR.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(raw, _schema())
        except jsonschema.ValidationError as exc:
            raise ParadigmError(f"{path.name}: {exc.message}") from exc
        if raw["id"] in seen:
            raise ParadigmError(f"{path.name}: duplicate paradigm id {raw['id']!r}")
        seen.add(raw["id"])
        found.append(
            Paradigm(
                id=raw["id"],
                name=raw["name"],
                affords=raw["affords"].strip(),
                order=raw.get("order", 100),
                hidden=bool(raw.get("hidden", False)),
                template=raw["template"],
                template_version=raw["template_version"],
                topology=raw.get("topology", {}),
                contingency=raw.get("contingency", {}),
                policy=raw.get("policy", {}),
                questions=tuple(Question(**q) for q in raw.get("questions", [])),
            )
        )
    if not found:
        raise ParadigmError(f"no paradigms in {PARADIGM_DIR}")
    return tuple(sorted(found, key=lambda p: (p.order, p.id)))


def get(paradigm_id: str) -> Paradigm:
    for p in load_all():
        if p.id == paradigm_id:
            return p
    raise ParadigmError(f"no paradigm {paradigm_id!r}")


def canonical() -> Paradigm:
    """The one `self_check()` compiles. Lowest order, ties by id."""
    return load_all()[0]


# --------------------------------------------------------------------------- #
# Fingerprinting
# --------------------------------------------------------------------------- #


def fingerprint(doc: dict) -> str | None:
    """Which paradigm's shape this document has, or None for a custom one.

    Computed from the document rather than recorded in it, so a task the operator
    reshaped in the Designer stops claiming to be what it started as. Cheap
    enough to run on every library row: six scalars off an already-parsed dict.
    """
    topo = doc.get("topology") or {}
    if not isinstance(topo, dict):
        return None
    contingency = doc.get("contingency") or {}
    outcome = (contingency.get("outcome_map") or {}).get("correct") or {}
    mine = (
        int(topo.get("n_sampling_stages", 1)),
        bool(topo.get("retention_delay", False)),
        str(topo.get("response_mode", "n_alternative")),
        len(topo.get("response_ports") or []),
        bool(topo.get("commit_hold", True)),
        outcome.get("reward") is not None,
    )
    for p in load_all():
        if p.hidden:
            # `blank` is the floor a task starts from, not a shape it HAS. Left
            # in, every one-stimulus one-port rewarded task would come back
            # labelled "From scratch" -- which is where it began and says
            # nothing about what it is.
            continue
        theirs = (
            int(p.topology.get("n_sampling_stages", 1)),
            bool(p.topology.get("retention_delay", False)),
            str(p.topology.get("response_mode", "n_alternative")),
            p.n_response_ports,
            bool(p.topology.get("commit_hold", True)),
            p.rewarded,
        )
        if mine == theirs:
            return p.id
    return None


# --------------------------------------------------------------------------- #
# The skeleton
# --------------------------------------------------------------------------- #

#: The port binding fields that take a strobe, split by whether an unrewarded
#: task reaches them. WHICH code each one takes is not decided here -- the
#: channel's `port_slot` selects a row of the vocabulary's `port_slots` table,
#: which is the only place a per-port code name is written down.
_PORT_FIELDS = ("enter_code", "error_code", "break_code", "exit_code")
_REWARD_FIELDS = ("reward_code", "reward_stop_code")


def skeleton(
    paradigm: Paradigm,
    *,
    spec_id: str,
    answers: dict[str, Any] | None = None,
    label: str | None = None,
    description: str | None = None,
) -> dict:
    """A complete, compiling document for this paradigm.

    Ordered the way the four layers are: identity, meta, topology, timing,
    contingency, policy. Key order is the authored order in the YAML, so a
    generated file reads like one somebody wrote.
    """
    from . import templates

    answers = dict(answers or {})
    caps = templates.load(paradigm.template, paradigm.template_version).capabilities(
        _knobs(paradigm)
    )
    chans = channels()
    vocab = vocabulary()

    ports = _ports(paradigm, chans, vocab, caps)
    stimuli = _stimuli(paradigm, chans, vocab, answers)
    trial_types = _trial_types(paradigm, stimuli, ports, answers)

    doc: dict[str, Any] = {
        "spec_version": 1,
        "spec_id": spec_id,
        "vocab_version": vocab.version,
        "meta": {
            "label": label or paradigm.name,
            "description": description or paradigm.affords,
        },
        "topology": {
            "template": paradigm.template,
            "template_version": paradigm.template_version,
            "n_sampling_stages": paradigm.topology.get("n_sampling_stages", 1),
            "retention_delay": paradigm.topology.get("retention_delay", False),
            "response_mode": paradigm.topology.get("response_mode", "n_alternative"),
            "response_ports": list(ports),
            "commit_hold": paradigm.topology.get("commit_hold", True),
        },
        "timing": _timing(caps, ports, paradigm),
        "contingency": {
            **({"stimuli": stimuli} if stimuli else {}),
            "ports": ports,
            "trial_types": trial_types,
            "context_schedule": [],
            "outcome_map": _outcome_map(caps, paradigm),
        },
        "policy": _policy(paradigm, ports, answers),
    }

    # Answers land last, on paths the schema already knows, so an answer can only
    # ever overwrite a value the generator itself produced.
    for q in paradigm.questions:
        if q.id in answers and answers[q.id] is not None:
            _set_path(doc, q.path, answers[q.id])
    _reconcile(doc, vocab)
    return doc


def _reconcile(doc: dict, vocab) -> None:
    """Re-derive the fields an answer invalidates.

    An answer sets one path, but some fields are two halves of one fact. A
    stimulus's `on_code` is determined by its `emitter` -- odor line 3 announces
    itself as ODOR_3_ON -- so answering "which line" and leaving the code alone
    produces a document claiming line 3 emits ODOR_2_ON. It compiles, because
    both halves are individually legal; it is simply wrong, and the way it
    surfaces is a byte-equivalence gate against real firmware disagreeing about
    which odor was presented.

    This is the same rule the editor's structural operations follow: an
    operation fills every field its change makes reachable, not just the one its
    name mentions.
    """
    contingency = doc.get("contingency", {})

    for stim in contingency.get("stimuli", []) or []:
        emitter = stim.get("emitter")
        if not isinstance(emitter, str):
            continue
        tail = emitter.rsplit("_", 1)[-1]
        if not tail.isdigit():
            continue
        code = f"ODOR_{tail}_ON"
        if code in vocab.names():
            stim["on_code"] = code

    # A trial type's id is generated as tt_<stimulus>_<target>, so answering
    # "which arm is offered" leaves the NAME describing the old side while the
    # target describes the new one. Shaping-L came out carrying a trial type
    # called `tt_odor1_right_well` that targeted the left well -- which compiles,
    # because an id is only a label, and is exactly the kind of thing that makes
    # somebody misread a listing at the bench.
    #
    # Only the generated shape is rewritten, and only when the stimulus half
    # still matches: an id the operator chose is theirs. The one field that
    # references a trial type by id, `context_schedule[].targets`, cannot be
    # populated at all (TG230 rejects a non-empty schedule), so nothing can be
    # pointing at the old name.
    ports = list((contingency.get("ports") or {}).keys())
    for tt in contingency.get("trial_types", []) or []:
        tid, target = tt.get("id"), tt.get("target")
        stages = tt.get("stages") or []
        if not (isinstance(tid, str) and isinstance(target, str) and stages):
            continue
        if target not in ports:
            continue
        stem = f"tt_{stages[0]}_"
        if tid.startswith(stem) and tid[len(stem) :] in ports:
            tt["id"] = f"{stem}{target}"


def _knobs(paradigm: Paradigm):
    from types import SimpleNamespace

    t = paradigm.topology
    return SimpleNamespace(
        n_sampling_stages=t.get("n_sampling_stages", 1),
        retention_delay=t.get("retention_delay", False),
        response_mode=t.get("response_mode", "n_alternative"),
        commit_hold=t.get("commit_hold", True),
        response_ports=[],
    )


def _ports(paradigm: Paradigm, chans, vocab, caps) -> dict:
    """The response ports, bound to real channels with real codes.

    Ports come from the channel registry in its own order, so "two response
    ports" means the two this box has rather than two names invented here. Every
    port carries all five codes whether or not this shape reaches them: a shape
    change (go/no-go to n-alternative) makes three of them reachable at once, and
    TG506 wants them present when it does.

    WHICH CODES A PORT REPORTS WITH COMES FROM ITS SLOT, not from its name. The
    channel declares `port_slot` and the vocabulary's `port_slots` table says
    what that slot's six codes are called. This used to be `_SIDE = {"left_well":
    "_L", "right_well": "_R"}` -- a box whose wells were named anything else got
    a port with no codes at all, silently, because every one of those fields is
    individually optional and TG506 only fires once a shape makes them reachable.
    """
    available = [c.name for c in chans.of_kind("response")]
    wanted = available[: paradigm.n_response_ports]
    if len(wanted) < paradigm.n_response_ports:
        raise ParadigmError(
            f"paradigm {paradigm.id!r} wants {paradigm.n_response_ports} response "
            f"ports; the pinout {chans.pinout_id!r} has {len(available)}"
        )

    out: dict[str, Any] = {}
    for name in wanted:
        channel = chans.get(name)
        slot = vocab.port_slot(channel.port_slot) if channel and channel.port_slot else None
        binding: dict[str, Any] = {"channel": name}
        for field_ in _PORT_FIELDS:
            code = (slot or {}).get(field_)
            if code and code in vocab.names():
                binding[field_] = code
        if paradigm.rewarded:
            line = next(
                (c for c in chans.of_kind("reward") if c.well == name), None
            )
            if line is None:
                raise ParadigmError(
                    f"no reward line is plumbed to {name!r} in pinout "
                    f"{chans.pinout_id!r}, but paradigm {paradigm.id!r} rewards"
                )
            binding["reward_line"] = line.name
            binding["reward_duration"] = _reward_id(name)
            for field_ in _REWARD_FIELDS:
                code = (slot or {}).get(field_)
                if code and code in vocab.names():
                    binding[field_] = code
        out[name] = binding
    return out


def _reward_id(port: str) -> str:
    """A per-port reward duration id.

    `right_well` -> `t_reward_right`, and any other channel name -> itself, so a
    rig whose ports are called something else still gets one id per port rather
    than a collision. The `_well` strip keeps the two shipped names reading the
    way every existing spec spells them.
    """
    stem = port[: -len("_well")] if port.endswith("_well") else port
    return f"t_reward_{stem}"


def _stimuli(paradigm: Paradigm, chans, vocab, answers) -> list:
    """One stimulus per declared count, on consecutive emitter lines.

    The onset code follows the line -- `odor_line_3` emits `ODOR_3_ON` -- which
    is the pairing every hand-authored spec used and the only one the vocabulary
    supports. Past the sixth there is no code, and that is a hard stop rather
    than a made-up name.
    """
    # BY NAME, NOT BY PIN. `of_kind` sorts by pin index, and the odor pins are not
    # monotonic past line 6 -- 22,24,26,28,30,32 then 23,25,27,29,31,33 -- so pin
    # order interleaves lines 1-6 with 7-12 and "the first emitter" comes out as
    # odor_line_7. The channel registry's note on that channel says exactly this:
    # resolve by name, never by arithmetic. This is the arithmetic it warns about.
    def line_number(name: str) -> tuple[int, str]:
        tail = name.rsplit("_", 1)[-1]
        return (int(tail), name) if tail.isdigit() else (10**6, name)

    emitters = sorted((c.name for c in chans.of_kind("emitter")), key=line_number)
    out = []
    for i in range(paradigm.n_stimuli):
        if i >= len(emitters):
            raise ParadigmError(f"only {len(emitters)} emitter channels available")
        line = emitters[i]
        code = f"ODOR_{line.rsplit('_', 1)[-1]}_ON"
        if code not in vocab.names():
            raise ParadigmError(
                f"the vocabulary declares no onset code for {line!r} "
                f"(expected {code}); it declares six, and this paradigm wants "
                f"{paradigm.n_stimuli} stimuli"
            )
        out.append({"id": f"odor{i + 1}", "emitter": line, "on_code": code})
    return out


def _trial_types(paradigm: Paradigm, stimuli, ports, answers) -> list:
    """The stimulus-to-answer mapping, in one of three declared shapes.

    A small enum rather than an index-into-index structure, because
    index-into-index is exactly the fragile thing a declarative registry should
    not invent. A fourth shape needs a fourth value and a branch here, which is
    the right amount of friction.
    """
    shape = paradigm.contingency.get("trial_types", "one_per_stimulus")
    names = list(ports)

    if shape == "single_withhold":
        # target: null IS the withhold declaration.
        return [{"id": f"nogo_{s['id']}", "stages": [s["id"]], "target": None}
                for s in stimuli]

    if shape == "sequence_pairs":
        a, b = stimuli[0]["id"], stimuli[1]["id"]
        return [
            {"id": "seq_ab", "stages": [a, b], "target": names[0]},
            {"id": "seq_ba", "stages": [b, a], "target": names[-1]},
        ]

    if shape == "one_per_stimulus":
        n = paradigm.topology.get("n_sampling_stages", 1)
        if not stimuli:
            # Nothing to discriminate, but a task still needs a trial to run: one
            # type, no stages, answered at the first port. The pool is degenerate
            # by design rather than empty by accident.
            return [{"id": "trial", "stages": [], "target": names[0] if names else None}]
        out = []
        for i, s in enumerate(stimuli):
            stages = [s["id"]] * n
            target = names[i % len(names)] if names else None
            entry = {"id": f"tt_{s['id']}_{target}", "stages": stages, "target": target}
            if paradigm.contingency.get("weight_one_only"):
                # Shaping: the whole machine exists, one arm is offered. Turning a
                # weight up later is a policy edit, not a reshape.
                entry["weight"] = 1 if i == 0 else 0
            out.append(entry)
        return out

    raise ParadigmError(f"unknown trial_types shape {shape!r}")


def _timing(caps, ports, paradigm) -> list:
    """Every duration the shape requires, plus one per rewarded port.

    Order is the template's own, because the index is what the firmware holds
    and the listing prints them in this order too.
    """
    rows = []
    for tid in caps.required_timing:
        d = caps.timing_defaults[tid]
        row: dict[str, Any] = {"id": tid, "ms": d.ms}
        if d.wire_key:
            row["wire_key"] = d.wire_key
        if d.note:
            row["note"] = d.note
        rows.append(row)

    seen = {r["id"] for r in rows}
    for outcome in caps.outcome_defaults.values():
        if outcome.delay not in seen:
            d = caps.timing_defaults[outcome.delay]
            row = {"id": outcome.delay, "ms": d.ms}
            if d.wire_key:
                row["wire_key"] = d.wire_key
            if d.note:
                row["note"] = d.note
            rows.append(row)
            seen.add(outcome.delay)

    for name, binding in ports.items():
        tid = binding.get("reward_duration")
        if tid and tid not in seen:
            rows.append({"id": tid, "ms": 100,
                         "note": f"Pulse width IS the delivered volume at {name}."})
            seen.add(tid)
    return rows


def _outcome_map(caps, paradigm) -> dict:
    out = {}
    for cls in sorted(caps.outcome_classes):
        d = caps.outcome_defaults[cls]
        entry: dict[str, Any] = {"trigger": d.trigger}
        entry["reward"] = "@target" if (cls == "correct" and paradigm.rewarded) else None
        entry["terminal"] = d.terminal
        entry["delay"] = d.delay
        entry["strobe"] = d.strobe
        if cls == "correct" and not paradigm.rewarded:
            # Without a reward there is no consummatory bout to report the end of.
            entry["strobe"] = "END_CORRECT_ITI" if d.strobe == "@target.exit_code" else d.strobe
        if d.note:
            entry["note"] = d.note
        out[cls] = entry
    return out


def _policy(paradigm: Paradigm, ports, answers) -> dict:
    pol: dict[str, Any] = {}
    selection = dict(paradigm.policy.get("selection") or {"mode": "weighted_pool"})
    pol["selection"] = selection
    if paradigm.policy.get("correction_budgets", False):
        pol["correction"] = {"budgets": {name: 0 for name in ports}}
    if paradigm.policy.get("penalty_escalation"):
        pol["penalty_escalation"] = dict(paradigm.policy["penalty_escalation"])
    pol["stage_schedule"] = []
    pol["n_trials"] = paradigm.policy.get("n_trials", 300)
    pol["seed"] = "host"
    return pol


def _set_path(doc: dict, path: str, value: Any) -> None:
    """Minimal path setter for answers. Mirrors the frontend's `setAt` grammar."""
    node: Any = doc
    parts: list[Any] = []
    for chunk in path.split("."):
        while "[" in chunk:
            head, rest = chunk.split("[", 1)
            if head:
                parts.append(head)
            idx, chunk = rest.split("]", 1)
            parts.append(int(idx))
        if chunk:
            parts.append(chunk)
    for step in parts[:-1]:
        node = node[step]
    node[parts[-1]] = value


def to_yaml(doc: dict) -> str:
    """The document as the bytes a save would write."""
    return yaml.safe_dump(doc, sort_keys=False, width=100, allow_unicode=True)
