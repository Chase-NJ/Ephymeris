"""A scoring profile inferred from the stream itself — `data.md` §8.3's last rung.

Every behaviour task this rig has ever run shares one firmware lineage and one
**append-only strobe registry**: a code has meant the same thing in every file
since the day it was issued, which is precisely what the registry's
never-renumber rule bought. So a run that resolves no profile — a legacy
archive from before `task.json` existed, a sketch folder long deleted, an
Arduino Directory re-pointed — is not undecodable. The stream itself says which
conditions ran and how each was answered, in a vocabulary this module can read
without any per-task declaration.

What a profile normally supplies, and where inference gets it instead:

* **the conditions** — the stimulus onset codes (`ODOR_n_ON` shapes) that
  actually appear in the stream. A declared code the session never presented
  contributes nothing here, exactly as it contributes no boundary live.
* **the correct answer per condition** — read from the outcomes the firmware
  already judged. `checkResponse()` reaches `FLUID_x` and
  `WATER_UNPOKE_EARLY_x` only at the *correct* well, and `WATER_POKE_ERROR_x`
  only at the wrong one, so any settled trial names the side. Majority across
  the session's trials, because a hand-edited file can hold anything.
* **the outcome vocabulary** — the registry itself, in-use and retired names
  alike, so the §3.8 tallies and the engagement ladder read the same names a
  declared profile would have carried.

THE DECLARED PATH ALWAYS WINS. A configured task's `task.json` carries its
TrialTypes' own declaration — including which conditions exist that the animal
never met — and inference is only ever the fallback beneath it (`service.py`'s
ladder). What inference cannot know: conditions the session never presented,
the operator's labels, and the authored rolling window; it uses the same
window the generator writes.

ONE HONEST LIMIT: a condition whose trials were *never answered* — no poke, no
error, no fluid, all session — has no evidence to name its side. It still
becomes a metric (its onset must stay a trial boundary, or trials of *other*
conditions abandoned before it would be mis-scored — the exact trap
`boundaries_for` documents), oriented deterministically toward the
higher-numbered slot. Provably inert in the one case it arises: no answered
trials means no enter codes inside those trials, so the metric counts nothing
whichever way it points. The exception is a stream truncated mid-poke on the
final trial, which can mis-count at most that one trial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..rig import registry
from ..rig.registry import Vocabulary
from ..tasks.profile import LiveMetric, TaskProfile

#: The shape of a stimulus onset — `ODOR_3_ON`, a hypothetical `TONE_2_ON`.
#: The same rule the task editor's picker applies, and for the same reason:
#: a bare `_ON$` would match `LIGHTS_ON`, the per-trial availability cue, and
#: every trial would look like its own condition.
_ONSET = re.compile(r"_\d+_ON$")

#: What the generator writes for every declared metric (`taskdef/generate.py`),
#: so an inferred run charts at the same resolution as a declared one.
INFERRED_WINDOW = 20

#: `task_name` when the document names no sketch — shown on profile groups.
FALLBACK_NAME = "Inferred from strobes"


@dataclass(frozen=True)
class _Slot:
    """One response port's codes, resolved to numbers."""

    number: int
    enter: int
    error: int
    early: int
    reward: int
    label: str


def infer_profile(
    codes: list[int],
    *,
    sketch_name: str | None = None,
    vocabulary: Vocabulary | None = None,
) -> TaskProfile | None:
    """Build a scoring profile from a recorded stream, or `None` if the stream
    presents no recognisable condition at all.

    Pure given its inputs; the default vocabulary is the shipped registry,
    which is package data behind a cache. `sketch_name` is only a label — it
    names the profile group in Analytics and decides nothing about scoring.
    """
    vocab = vocabulary if vocabulary is not None else registry.vocabulary()

    onsets = {e.code: e.name for e in vocab if _ONSET.search(e.name)}
    seen = set(codes)
    present = sorted(code for code in onsets if code in seen)
    if not present:
        return None

    slots = _slots(vocab)
    withhold = _code_of(vocab, "WATER_POKE_NONE")
    sides = _infer_sides(codes, frozenset(present), slots, withhold)

    metrics: list[LiveMetric] = []
    for code in present:
        stimulus = onsets[code].removesuffix("_ON").replace("_", " ").lower()
        chosen = sides.get(code)
        if chosen == "withhold" and withhold is not None and slots:
            # The wrongness of an answered no-go doesn't depend on which port
            # answered it, so any enter code closes the trial — the same
            # arrangement the generator writes for a declared no-go type.
            metrics.append(LiveMetric(
                id=f"inferred_{code}",
                label=f"P(withhold | {stimulus})",
                trigger_code=code,
                success_code=withhold,
                alternate_code=slots[0].enter,
                window_size=INFERRED_WINDOW,
            ))
            continue
        correct = chosen if isinstance(chosen, _Slot) else _fallback_slot(slots)
        if correct is None:
            return None  # a registry with no port slots cannot score anything
        other = next((s for s in slots if s.number != correct.number), correct)
        metrics.append(LiveMetric(
            id=f"inferred_{code}",
            label=f"P({correct.label} | {stimulus})",
            trigger_code=code,
            success_code=correct.enter,
            alternate_code=other.enter,
            window_size=INFERRED_WINDOW,
        ))

    # The whole registry, retired names included: a legacy stream really does
    # carry the dummy-solenoid clicks, and a name — even "DUMMY_SOLENOID_
    # CLICK_2" — reads better in a raw log than a bare number. Retired names
    # match none of the outcome patterns, so they label without scoring.
    strobes = {entry.code: entry.name for entry in vocab}
    strobes.update({code: name for code, name in vocab.retired.items()})

    return TaskProfile(
        task_name=sketch_name or FALLBACK_NAME,
        kind="behavior",
        strobes=strobes,
        live_metrics=metrics,
    )


def _infer_sides(
    codes: list[int],
    boundaries: frozenset[int],
    slots: list[_Slot],
    withhold: int | None,
) -> dict[int, _Slot | str | None]:
    """The correct answer per condition, by majority of settled trials.

    One pass, delimited exactly as scoring is — on the union of every present
    onset — so the evidence window for a trial is the same span of codes the
    scorer will attribute to it. Evidence, per `checkResponse()`'s emission
    rules:

    * `FLUID_x` / `WATER_UNPOKE_EARLY_x` — reached only at the correct well,
      so each is a vote **for** slot x.
    * `WATER_POKE_ERROR_x` — emitted only at the wrong well, so a vote for
      the *other* slot. Only countable when exactly two slots exist; the
      registry declares exactly two, and a third would make "the other" a
      guess.
    * `WATER_POKE_NONE` — the withheld answer on a no-go trial; a vote that
      the condition is a withhold condition.

    Majority wins; a reward-vote tie breaks toward the reward evidence, then
    deterministically toward the higher slot — an arbitrary orientation must at
    least be the *same* arbitrary orientation on every rescan, or one animal's
    unanswered condition would flip its run between profile groups per pass.
    """
    for_slot: dict[int, dict[int, int]] = {}
    reward_votes: dict[int, dict[int, int]] = {}
    withhold_votes: dict[int, int] = {}

    by_evidence: dict[int, tuple[_Slot, bool]] = {}
    for slot in slots:
        by_evidence[slot.reward] = (slot, True)
        by_evidence[slot.early] = (slot, False)
    error_to_other: dict[int, _Slot] = {}
    if len(slots) == 2:
        error_to_other[slots[0].error] = slots[1]
        error_to_other[slots[1].error] = slots[0]

    open_condition: int | None = None
    for code in codes:
        if code in boundaries:
            open_condition = code
            continue
        if open_condition is None:
            continue
        evidence = by_evidence.get(code)
        if evidence is not None:
            slot, is_reward = evidence
            votes = for_slot.setdefault(open_condition, {})
            votes[slot.number] = votes.get(slot.number, 0) + 1
            if is_reward:
                rewards = reward_votes.setdefault(open_condition, {})
                rewards[slot.number] = rewards.get(slot.number, 0) + 1
            continue
        other = error_to_other.get(code)
        if other is not None:
            votes = for_slot.setdefault(open_condition, {})
            votes[other.number] = votes.get(other.number, 0) + 1
            continue
        if withhold is not None and code == withhold:
            withhold_votes[open_condition] = withhold_votes.get(open_condition, 0) + 1

    out: dict[int, _Slot | str | None] = {}
    for condition in boundaries:
        votes = for_slot.get(condition, {})
        held = withhold_votes.get(condition, 0)
        if held > sum(votes.values()):
            out[condition] = "withhold"
            continue
        if not votes:
            out[condition] = None
            continue
        rewards = reward_votes.get(condition, {})
        best = max(
            votes,
            key=lambda number: (votes[number], rewards.get(number, 0), number),
        )
        out[condition] = next(s for s in slots if s.number == best)
    return out


def _slots(vocab: Vocabulary) -> list[_Slot]:
    """Every port slot whose codes all resolve, in slot order."""
    out: list[_Slot] = []
    for number in sorted(vocab.port_slots):
        fields = vocab.port_slots[number]
        resolved = {
            key: _code_of(vocab, fields.get(key, ""))
            for key in ("enter_code", "error_code", "break_code", "reward_code")
        }
        if any(code is None for code in resolved.values()):
            continue
        out.append(_Slot(
            number=number,
            enter=resolved["enter_code"],  # type: ignore[arg-type]
            error=resolved["error_code"],  # type: ignore[arg-type]
            early=resolved["break_code"],  # type: ignore[arg-type]
            reward=resolved["reward_code"],  # type: ignore[arg-type]
            label=_side_label(fields.get("enter_code", ""), number),
        ))
    return out


def _fallback_slot(slots: list[_Slot]) -> _Slot | None:
    """The deterministic orientation for a condition with no evidence — see
    the module docstring for why this is safe. Highest slot, matching the
    tie-break in `_infer_sides` so the two cannot disagree."""
    return slots[-1] if slots else None


def _side_label(enter_name: str, number: int) -> str:
    """`WATER_POKE_L` → "left well" — the historical suffix, read rather than
    assumed: a slot whose codes carry no side keeps its number instead."""
    if enter_name.endswith("_L"):
        return "left well"
    if enter_name.endswith("_R"):
        return "right well"
    return f"port {number}"


def _code_of(vocab: Vocabulary, name: str) -> int | None:
    entry = vocab.get(name) if name else None
    return entry.code if entry else None
