# Schema decisions

Running log. One entry per decision that constrains the schema, each naming the
**alternative rejected** and, where applicable, the **past failure mode it closes**.
Phase 1's graph linter is written against this file.

Format: `## D<n> — <decision>` / Context / Decision / Alternative rejected / Consequence.

---

<a id="d1"></a>

## D1 — Nodes are emitted by versioned epoch templates, never authored per task

**Context.** A task spec could carry an explicit node/edge list, or carry only layer-1
knobs and let a template emit the graph.

**Decision.** `topology:` is knobs only. Nodes and edges come from versioned templates in
`templates/`. Task authors never write a node.

**Alternative rejected.** Author-written node lists. They make invalid state machines
representable, force graph validation to be interactive, and pull Phase 6 toward the
free-form node canvas the roadmap names as the most costly ordering error available.

**Consequence.** The quirks in D2/D3 live in one reviewable place instead of being
copy-pasted into five specs. Linter rule: a spec containing a `nodes:` or `edges:` key is
rejected outright.

---

<a id="d2"></a>

## D2 — Paired strobes become zero-duration nodes, not per-node strobe lists

**Context.** Current firmware emits two strobes at one instant in four places, and the
order is not consistent — `BF_LIGHTS_OFF` precedes its partner on the three abort paths
(`BehaviorBox.h:1158-1159`, `:1180-1181`, `:1196-1197`) but **follows** it on the success
path (`:1210` then `:1213`). The model's invariant is one state, one entry code, one
timestamp.

**Decision.** Every strobe is emitted by exactly one node entry. A paired emission is two
nodes, the second a `DELAY` with `duration: t_zero`. Ordering is therefore authored in the
template, which reproduces the flip naturally.

**Alternative rejected.** Allowing an ordered strobe *list* per node. Cheaper by ~6 nodes
for GRGL, but it silently redefines the invariant that "which edge fired is recoverable
from which strobe appeared" — the property the entire downstream analysis story rests on.
The RAM spike (`docs/spikes/avr-ram.md`) confirms the nodes are affordable.

**Consequence.** Linter rule: a node carries at most one strobe. `t_zero` must exist in
every timing vector.

**Amended by [[D21]].** The *ordering* half of this — the `cue_off_placement` knob that
existed to encode firmware's inconsistency — is gone in template v2, which always puts
the behavioural strobe first. The zero-duration-node mechanism itself is unchanged and
is now used in more places, not fewer.

---

<a id="d3"></a>

## D3 — A strobe emitted before its guard resolves becomes a branch node

**Context.** `BehaviorBox.h:1082` emits `WATER_POKE_L/R` the moment a well beam breaks;
correctness is not tested until `:1093`. One strobe, two possible successor states — a
genuine edge-strobe under the naive reading.

**Decision.** A zero-duration branch node carries the per-channel strobe on entry
(`@ports[$ch].enter_code`) and the correctness guard on its outgoing edges.

**Alternative rejected.** Duplicating the strobe onto both successor states. That would
require the wrong-port state to emit two codes, reintroducing D2's problem one layer down.

**Consequence.** `$ch` (the channel that fired) must be part of the binding language, not
just `@`-prefixed trial bindings.

---

<a id="d4"></a>

## D4 — `strobe: null` is legal and explicit

**Context.** The omission path emits nothing at all (`BehaviorBox.h:1090-1091`). The
topology document's `RESP_OMIT` code does not exist in firmware. GRGL must reproduce the
silence bit-identically.

**Decision.** `strobe: null` is a valid, explicit value. `grgl_2odor` uses it for the
omission outcome. New tasks may declare a newly appended code instead.

**Alternative rejected.** Emitting a new `RESP_OMIT` code everywhere for uniformity. That
breaks bit-identity with `runTrial()`, failing the Phase 3 equivalence gate on the one task
that must pass it.

**Consequence.** Linter rule: a null strobe is a **warning**, not an error, and the warning
text must say that silence is deliberate where it is.

**Amended by [[D21]].** No target spec is silent any more — firmware emits `RESP_OMIT`
(262) on an omission, so all three outcomes reaching `END_INCORRECT_ITI` are
distinguishable where they occur. The rule stays: `tests/fixtures/grgl_2odor_asbuilt.yaml`
still exercises it, and a future spec reproducing an older build will need it again.

---

<a id="d5"></a>

## D5 — Strobe codes are `uint16` in the compiled table

**Context.** `BF_WATER_POKE_NONE`=256, `..._ERROR_L`=257, `..._ERROR_R`=258,
`BF_STOP_FLUID_G_R`=357, `BF_STOP_FLUID_G_L`=369 (`BehaviorBox.h:117-121`). Five codes
exceed 255.

**Decision.** `uint16`. Saving a byte per node by using `uint8` is a correctness bug, not an
optimisation.

**Alternative rejected.** `uint8` with an escape table. Two bytes per node is affordable
(see `docs/spikes/avr-ram.md`) and the escape table would be a permanent trap.

**Consequence.** `emitStrobe` formats `"%03d"` and the host regex is `^\d{1,3}\t\d+$`, so
codes are additionally capped at **999**. Both bounds are enforced by the vocabulary schema.

---

<a id="d6"></a>

## D6 — Durations are `uint16` with an out-of-band sentinel

**Context.** Firmware stores timings as signed `int` (max 32767) while `lazyDelayMax`
defaults to 30000 — and `32767` is *simultaneously* the `StageStep` "never" sentinel
(`BehaviorBox.h:531-536`). A legal duration collides with a sentinel value.

**Decision.** The timing vector is `uint16` (0–65535). The stage-schedule "never" sentinel
is out-of-band (absence of a row), not a magic in-range number.

**Alternative rejected.** Matching firmware's signed `int` exactly. It preserves an
existing collision for no benefit.

**Consequence.** A **deliberate, documented divergence from current firmware.** The
compiler must reject a duration > 65535 rather than wrapping. Phase 3's equivalence gate
must not exercise durations above 32767 for GRGL, since `runTrial()` cannot represent them.

---

<a id="d7"></a>

## D7 — `task.json` is not extended; the spec is a sibling artifact

**Context.** Ephymeris `CLAUDE.md:114` forbids adding a `states`/`graph` key because it
changes `profile_hash` and "permanently splits a sketch's historical runs from its future
ones in Analytics."

**Decision.** `task.json` stays byte-identical. The task spec is a separate artifact with
its own `spec_hash`, recorded on the run alongside `profile_hash` and `params_hash`.

**Alternative rejected.** Embedding the compiled table in `task.json`. Breaks historical
comparability, which is a hard requirement.

**Consequence.** Provenance for a session is the 4-tuple
`(profile_hash, params_hash, spec_hash, seed)` plus firmware and protocol versions.

---

<a id="d8"></a>

## D8 — One firmware value may map to several timing ids

**Context.** `odorPokeHold` is read at both `BehaviorBox.h:1176` (pre-odor commitment hold)
and `:1191` (sampling hold). One value, two semantically distinct states.

**Decision.** The spec declares `t_commit_hold` and `t_sample_hold` as separate ids holding
the same value. The compiler emits both from the single `S0P` wire key for legacy
compatibility.

**Alternative rejected.** A single shared id mirroring firmware exactly. It would make
separating the two holds a firmware change, which is precisely the generality layer 3 is
being bought for.

**Consequence.** The spec→START-line mapping is many-to-one and must be declared, not
inferred.

---

<a id="d9"></a>

## D9 — Scoring is an edge effect, never a node or trigger property

**Context.** Go/no-go requires "correct = the window expired", inverting the usual meaning
of `TIMEOUT` on a `WAIT_ENTRY`.

**Decision.** Outcome classification lives in an edge's `effect`. A `TIMEOUT` edge can
carry `score: correct` exactly as an `ENTER` edge can.

**Alternative rejected.** A `response_mode` branch inside the interpreter. It would put a
task-specific special case into the fixed interpreter — the exact thing this project
exists to eliminate.

**Consequence.** The interpreter never inspects `response_mode`; it walks edges and applies
effects. Reward/consumption states are omitted by the *absence* of a reward binding, not by
a suppressing flag.

---

<a id="d10"></a>

## D10 — Capabilities are announced before `READY`, never on it

**Context.** The host matches readiness as an exact whole line —
`if text.upper() == READY_TOKEN` (`Ephymeris/sidecar/ephymeris_sidecar/ports/handler.py:337`,
`READY_TOKEN = "READY"` at `:31`). Any line arriving *before* it returns the unchanged
`"ready"` phase and is mirrored to scrollback at `:334`.

**Decision.** Migrated firmware emits `CAP\t<key>=<value>` lines *before* a bare `READY`.

**Alternative rejected.** Extending the READY line itself (`READY TASKGRAPH=1`). Every
existing host would fail with "board never reported READY".

**Consequence.** A migrated box needs **zero** Ephymeris changes to keep working — the
fallback is current behaviour, not a new code path. See `docs/protocol-negotiation.md`.

---

<a id="d21"></a>

## D21 — The model is authoritative; firmware conforms

**Context.** Phase 0 treated `runTrial()` as immovable, so the model accommodated its
quirks: a `cue_off_placement` knob existed only to encode an inconsistency, and the
omission path was deliberately silent because firmware was. Firmware is now developed
alongside this compiler.

**Decision.** The spec defines correct behaviour and firmware changes to match. The
Phase 3 equivalence gate becomes "the interpreter and the updated `runTrial()` agree"
rather than "the interpreter reproduces today's build byte for byte".

**Alternative rejected.** Freezing firmware through Phase 3 to preserve bit-identity
for longer. It would have carried both accommodations through the hardest phase of the
project for a comparability guarantee that a later change breaks anyway. Also rejected:
dropping the equivalence gate — the roadmap names that as how this project quietly
dies at 90%.

**Consequence.** Template **v1 is frozen** as as-built and pinned by
`tests/fixtures/grgl_2odor_asbuilt.yaml`; **v2** is the model. That is what the
file-per-version rule ([[D14]]) was for, and it is what keeps the corpus evidence —
1.5 million recorded events — reproducible after the model moves ahead. The required
firmware changes are enumerated in `docs/firmware-changes.md`, and a test measures
when they have shipped.

---

<a id="d20"></a>

## D20 — INVALID_TRIAL is the repeat marker, not a terminal's strobe

**Context.** The first version of the template made `END_CORRECT_ITI`,
`END_INCORRECT_ITI` and `INVALID_TRIAL` alternative terminal strobes. Replaying real
recorded sessions rejected 52 of them — **every session that had ever run with a
non-zero correction budget, and no others.**

`INVALID_TRIAL` is emitted by the sketch loop whenever `runTrial()` returns false,
which includes a correction repeat. So a wrong answer under an unspent budget emits
`END_INCORRECT_ITI` **and then** `INVALID_TRIAL`. Two strobes in that order means two
nodes in that order, and a graph whose terminal carries the first cannot produce the
second.

**Decision.** The scoring strobe moves off the terminal onto its own zero-duration
node, and a trial ends at one of two terminals: `TRIAL_ADVANCE` (silent) or
`TRIAL_REPEAT` (`INVALID_TRIAL`).

**Alternative rejected.** Placing a repeat-marker node *after* the terminal. Nothing
may follow a terminal: termination analysis severs terminal out-edges before it runs,
so such a node is unreachable by construction — and the linter said so immediately.

**Consequence.** Found from data already on disk, before any firmware existed. This is
the backward check earning its keep exactly as the roadmap predicted, and it is the
reason the corpus replay is a permanent test rather than a one-off exercise.

---

<a id="d19"></a>

## D19 — Warnings are pinned by a checked-in lint baseline

**Context.** Some warnings are correct and permanent — `grgl_2odor`'s deliberately
silent omission path fires TG231 on every compile, forever.

**Decision.** Each spec carries `specs/<id>.lint.txt`, a checked-in record of its accepted
diagnostics, golden-tested like the listing. A new warning anywhere becomes a failing diff.

**Alternative rejected.** An `expect_warnings:` key in the spec. It changes `spec_hash`,
and `spec_hash` is session provenance ([[D7]]) — suppressing a warning would silently
re-identify every session that spec produced.

**Consequence.** The accepted set is explicit, versioned and reviewed. This is the only
warning discipline that survives a working lab; the alternative is a slowly growing pile
nobody reads.

---

<a id="d18"></a>

## D18 — Graph rules see a GraphView, never a TaskSpec

**Context.** The TG4xx rules are the ones the roadmap says deserve most of the effort.

**Decision.** They take a structure-only view: node types, watch masks, edges. No spec, no
vocabulary, no channel map.

**Alternative rejected.** Passing the bound spec, which would have been less plumbing.

**Consequence.** Graph rules fire on TEMPLATE bugs, not spec bugs — a `WAIT_ENTRY` missing
its `TIMEOUT` edge cannot be produced by any valid spec. Had the rules needed a spec, the
checks that matter most would have been the ones that could never be tested. Every TG4xx
rule now has a hand-built negative case.

---

<a id="d17"></a>

## D17 — TgTimingSet carries an explicit pad byte

**Context.** `{uint8 idx; uint16 ms;}` measures **3 bytes under `avr-g++ -mmcu=atmega2560`
and 4 under `clang++`** — verified by compiling both. AVR has no alignment requirement for
`uint16`; the host wants it 2-byte aligned. **Reordering the fields does not fix it** (both
orders still measure 3/4). It was also the only record with no `static_assert` and the only
one absent from `extras/host_test/`.

This is exactly the hazard `TaskTable.h`'s own header warns about: *"a layout that differs
between the host build and the AVR build would corrupt every uploaded table while compiling
cleanly on both."* It was live in the file that warns about it.

**Decision.** An explicit `_pad` byte, and **generated** size + field-offset assertions
compiled under both toolchains (`TgLayoutAssert.h`, from `taskgraph/codegen/layout.py`).

**Alternative rejected.** `__attribute__((packed))` — 3 bytes everywhere, but every field
access becomes unaligned on the host, and one byte is not worth a permanent footgun in the
trial loop. Also rejected: hand-written assertions, which are only ever added to records
someone already suspected — which is precisely why the one record that diverged lacked them.

**Consequence.** Python owns the layout table; C++ asserts conformance. A uint16 at an odd
offset now fails a Python test *and* both C++ builds. Corrected `docs/spikes/avr-ram.md`,
whose budget formula omitted the `timing_sets` term because the probe never allocated one.

---

<a id="d16"></a>

## D16 — Layer 4 rides the START line; a context_schedule is a hard error

**Context.** `TaskTable.h` has records for the graph and timing and **none** for layer-2
block boundaries or layer-4 policy. All five specs carry `context_schedule: []`, so it has
never bitten — but "a reversal is one more entry here and nothing else" is the schema's
headline claim.

**Decision.** Policy keeps riding the existing START line, where firmware's policy classes
already read it from `TaskParams`. A non-empty `context_schedule` is TG230, a named ERROR.

**Alternative rejected.** Defining `TgContextRow`/`TgPolicy` now — designing transport
structures before Phase 4 needs them, exercised by no current spec. Also rejected: dropping
it silently, which would be a reversal the spec declares, the listing shows, and the board
never performs.

---

<a id="d15"></a>

## D15 — A channel registry, resolved by kind

**Context.** Phase 0's specs name channels (`left_well`, `odor_line_1`, `fluid_0`) and
documented them as "resolved against the box pinout". No such artifact existed. Worse, the
**odor port and trial light are named nowhere at all**, though every engagement window must
watch one and every `LIGHTS_ON`/`OFF` must drive the other.

**Decision.** `schema/channels.v1.json`, transcribed from `BehaviorBox.h:55-92` with the
source line per entry. The engagement port and cue resolve **by kind**, not by name.

**Alternative rejected.** Declaring channels per spec (reopens the frozen schema, repeats
the pinout five times); parsing `BehaviorBox.h` (couples the compiler to reading C++ from a
read-only repo, for a table that changes roughly never).

**Consequence.** Resolution by kind is what lets one template serve a box whose ports are
named differently. Non-uniqueness is TG225, because silently picking one would route every
trial in every task through the wrong channel. The registry also declares which port each
fluid line serves, which is what makes TG224 possible — a reward wired to the opposite well
looks entirely correct in the listing and shows up only as an animal that will not learn.

---

<a id="d14"></a>

## D14 — Epoch templates are Python; the listing is the review artifact

**Context.** D1 says nodes come from versioned templates. It did not say what a template is.

**Decision.** A Python function emitting *symbolic* drafts, versioned **by file**
(`templates/four_epoch/v1.py`, never edited once pinned; a change copies to `v2.py`).
Reviewability comes from the checked-in listing, not from the template's source.

**Alternative rejected.** A declarative YAML template language. It would need booleans, an
indexed loop, string interpolation for stage-indexed ids, and guard expressions — i.e.
Python, badly. D1's constraint is on task AUTHORS, and it holds either way: the spec still
has no `nodes:` key, and the representable graphs are still exactly the image of `emit()`
over the topology enum.

**Consequence.** The listing is a stronger review artifact than a declarative template
would have been, because it shows the graph a change actually produced rather than the rule
that was supposed to produce it. Capabilities are a FUNCTION, not a sidecar JSON, because
which outcome classes exist depends on `response_mode`, `commit_hold` and
`n_sampling_stages` together — data would have needed the same mini-language.

---

<a id="d13"></a>

## D13 — Serial runs at 115200, changed immediately

**Context.** 9600 blocks the trial loop from the seventh strobe in a burst and skews the
timestamps that follow (`docs/spikes/transport.md`). Rates from 115200 to 1000000 were all
tested on a Mega 2560 and all pass a 300-strobe integrity check with zero loss.

**Decision.** 115200, applied now rather than deferred to Phase 5.

**Alternatives rejected.**

- *250000 / 500000 / 1000000* — exact divisors at 16 MHz, where 115200 carries +2.12% error.
  Rejected on two grounds: the error is **symmetric** (both the 2560 and the 16U2 bridge are
  16 MHz AVRs computing the same `UBRR`, so they agree exactly and the USB side is
  packet-based), and macOS `stty` rejects all three — `screen`/`minicom`/`cu` cannot open a
  non-POSIX rate, only `IOSSIOSPEED`-aware code such as pyserial can. Losing
  `screen /dev/cu.usbmodem… <rate>` as a debugging path is a poor trade for headroom the
  measurements show is unobservable: at 115200 every inter-strobe delta is already a
  `millis()` tick boundary, so a faster wire changes nothing that reaches the record.
- *Deferring to Phase 5*, as an earlier draft of the transport note recommended. **That
  recommendation was wrong.** Its premise was that changing wire timing would confound the
  Phase 3 equivalence gate — but Phase 3 is entirely off-target, running in
  `extras/host_test/` with mock time and no serial wire, so there is no baud rate in that
  comparison at all. Phase 2 replays recorded sessions and is equally unaffected. Nothing
  was gained by waiting, and every session recorded at 9600 in the interim carried worse
  timing for no reason.

**Consequence.** Cable length does not enter into it: the ~10 ft run carries USB
full-speed signalling, and the UART the baud governs is centimetres of PCB trace between the
16U2 and the 2560. Until `CAP` negotiation lands, the value is mirrored in nine places —
eight `const int baudRate` sketch constants plus `DEFAULT_BAUD` — which must move together,
and which is the concrete argument for [[D11]].

---

<a id="d12"></a>

## D12 — The outcome trigger field is named `trigger`, never `on`

**Context.** The first draft of the outcome map used `on: TIMEOUT`. YAML 1.1 — which
PyYAML implements — resolves a bare `on` key to the **boolean `true`**, so every spec
silently parsed as `{True: "TIMEOUT"}` and the field simply vanished. The schema caught it
only because `additionalProperties: false` rejected the stray boolean key; with a laxer
schema it would have surfaced in Phase 1 as a compiler reading a key that was not there.

**Decision.** The field is `trigger`. Reserved YAML 1.1 words (`on`, `off`, `yes`, `no`,
`y`, `n`) are banned as key names anywhere in the schema.

**Alternative rejected.** Keeping `on` and quoting it (`"on":`) in every spec. It works
until one author forgets the quotes, and the failure is silent.

**Consequence.** `trigger` also matches the edge vocabulary the model already uses, so the
rename cost nothing. **This is the first concrete payoff of hand-authoring the specs** —
the roadmap's claim that hand-authoring "forces every schema decision you would otherwise
defer" turned out to include decisions nobody would have thought to make.

---

<a id="d11"></a>

## D11 — Shared limits are announced at runtime, not mirrored as constants

**Context.** `START_LINE_MAX` is mirrored across two repos with nothing keeping it in sync,
and both copies carry comments explaining why that is dangerous (`BehaviorBox.h:701-706`,
`start_command.py:21-30`). A **second, undocumented** instance exists: `baudRate`
(`GRGL_2-Odor.ino:30`) against `DEFAULT_BAUD` (`settings.py:24`).

**Decision.** Table limits, line limits and baud are announced in the `CAP` lines. Where a
constant must still exist in source, it is generated from one definition in this repo.

**Alternative rejected.** A third hand-maintained mirror. Ephymeris already recorded that
hand-maintained mirrors "had already drifted"
(`docs/websocket-protocol.md:554-567`) before it moved to codegen.

**Consequence.** A limit mismatch is *detected at connect time* rather than silently
truncating a table.
