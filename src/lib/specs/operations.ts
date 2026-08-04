/**
 * Structural edit blocks — compound, safe-by-construction operations over the
 * spec document.
 *
 * Every op here is a PURE function composed from `setAt`/`deleteAt`, and each
 * one moves a topology knob (or a shape-bearing contingency field) TOGETHER
 * WITH everything that must move with it, so the machine is never invalid at
 * any point in between. This is the middle ground the design demands: the
 * canvas stays non-editable (docs/specs.md §5 — a node canvas would make
 * invalid machines representable), and the ops are the controlled blocks that
 * change shape without opening that door.
 *
 * OPS RECEIVE `capabilities()`, THEY NEVER COMPUTE IT. `ctx.caps` answers for
 * the document's current topology and `ctx.next` for the topology
 * `proposeTopology()` returns — both fetched by the caller over the wire
 * (`specs.capabilities`), so the reconciliation is the compiler's answer and
 * never this module's guess. An op that computed its own class set would be a
 * second implementation of `four_epoch/v2.py::capabilities`, which is the trap
 * the function-not-a-table argument exists to prevent.
 *
 * The invariants each op maintains are the lint rules that bite an operator:
 * TG201 (a timing rename rewrites every reference), TG220/TG221 (referential
 * integrity and stage counts), TG223/TG224 (channels resolve; a reward line's
 * well matches its port), TG302 (outcome classes equal `next.outcomeClasses`
 * EXACTLY — the rule errors in both directions, so stale classes are DELETED,
 * with the loss named in the preflight), TG303 (required timing appended),
 * TG304 (every added outcome carries a trigger), TG240 (escalation targets a
 * declared class). Unused TIMING rows, by contrast, are merely unused — they
 * stay, and the form greys them.
 *
 * Canonical write order (array indices shift, so order is load-bearing):
 * knobs → timing renames → timing appends (always at the END of the array,
 * never inserted — a reorder moves every line of the listing's TIMING VECTOR
 * section, and the listing is the review artifact) → contingency adds →
 * reference repairs → outcome reconciliation → policy repairs → note
 * invalidation. Array deletes descend by index.
 *
 * NEW `ms` VALUES ARE SEEDED FROM A SIBLING ROW IN THE SAME DOCUMENT, ELSE
 * ASKED FOR — NEVER A DEFAULTS TABLE. A table here would be a second
 * definition of what a reasonable task looks like, competing with the bundled
 * specs (the same objection §3 makes to a blank-skeleton generator). A seeded
 * row's preflight line names the row it copied.
 *
 * `note:` fields: an op that changes a value a note describes DELETES the
 * note and says so in the preflight. Rewriting one would mean inventing a
 * firmware citation; leaving it makes a pinned line number a lie.
 *
 * TYPECHECK COVERS THE OP IDS (the dispatch switch has no default), NOT THE
 * PATHS — `SpecDocument` is `Record<string, unknown>` on purpose, so a wrong
 * path is invisible to tsc. The ops' semantics are mirrored by
 * `sidecar/tests/test_spec_operations.py`, and the live compile confirms
 * every application against the real compiler.
 */

import { deleteAt, getAt, setAt, timingIndexOf, topologyOf } from "./document";
import type {
  ChannelRegistry,
  SpecCapabilities,
  SpecDocument,
  StrobeRegistry,
} from "./types";

/* ------------------------------------------------------------------------ */
/* Public shapes                                                            */
/* ------------------------------------------------------------------------ */

export type OpInvocation =
  | { op: "addSamplingStage" }
  | { op: "removeSamplingStage" }
  | { op: "addResponseOption" }
  | { op: "removeResponseOption"; port: string }
  | { op: "removePortBinding"; port: string }
  | { op: "addStimulus" }
  | { op: "addTrialType" }
  | { op: "setResponseMode"; mode: "n_alternative" | "go_nogo" }
  | { op: "setCommitHold"; on: boolean }
  | { op: "setRetentionDelay"; on: boolean }
  | { op: "setCorrectRewarded"; on: boolean }
  | { op: "addStageRow" }
  | { op: "removeStageRow"; index: number }
  | { op: "setStageTrial"; index: number }
  | { op: "setRampedIds"; ids: string[] };

export type OpId = OpInvocation["op"];

export interface OpContext {
  doc: SpecDocument;
  /** `capabilities()` for the document's CURRENT topology. */
  caps: SpecCapabilities;
  /** `capabilities()` for `proposeTopology()`'s answer; `caps` when null. */
  next: SpecCapabilities;
  channels: ChannelRegistry;
  strobes: StrobeRegistry;
}

export interface OpChange {
  kind: "set" | "delete" | "rename" | "keep-greyed";
  path: string;
  /** Human line for the preflight card — "timing t_sample_hold → t_sample_hold_0". */
  label: string;
  value?: unknown;
}

export interface OpQuestion {
  id: string;
  label: string;
  /** Overlay key so the UI renders the answer through `SpecField` — labels,
   * units and help stay the presentation overlay's, never this module's. */
  overlayKey: string;
  /** Where the answer lands in the document. */
  path: string;
  /** Null ⇒ free value (rendered by the overlay widget). */
  options: Array<{ value: string; label: string }> | null;
  /** Null ⇒ no legal default exists; a mandatory question with a null
   * suggestion gates Apply until answered. */
  suggested: unknown | null;
  why: string;
  mandatory: boolean;
}

export interface OpPreflight {
  op: OpId;
  title: string;
  changes: OpChange[];
  questions: OpQuestion[];
  warnings: string[];
  /** Non-null ⇒ the op cannot run here at all. Computed from the registries,
   * never hardcoded — the day the registry grows, the op wakes up. */
  blocked: string | null;
}

export interface OpResult {
  doc: SpecDocument;
  preflight: OpPreflight;
}

export type OpAnswers = Record<string, unknown>;

/* ------------------------------------------------------------------------ */
/* Document accessors (loose by necessity — the compiler owns the schema)   */
/* ------------------------------------------------------------------------ */

type Rec = Record<string, unknown>;

function asRec(v: unknown): Rec | null {
  return v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : null;
}

function timingRows(doc: SpecDocument): Rec[] {
  const t = doc["timing"];
  return Array.isArray(t) ? t.filter((r): r is Rec => asRec(r) !== null) : [];
}

function portsOf(doc: SpecDocument): Record<string, Rec> {
  const ports = asRec(asRec(doc["contingency"])?.["ports"]);
  const out: Record<string, Rec> = {};
  for (const [name, binding] of Object.entries(ports ?? {})) {
    const rec = asRec(binding);
    if (rec) out[name] = rec;
  }
  return out;
}

function stimuliOf(doc: SpecDocument): Rec[] {
  const s = asRec(doc["contingency"])?.["stimuli"];
  return Array.isArray(s) ? s.filter((r): r is Rec => asRec(r) !== null) : [];
}

function trialTypesOf(doc: SpecDocument): Rec[] {
  const t = asRec(doc["contingency"])?.["trial_types"];
  return Array.isArray(t) ? t.filter((r): r is Rec => asRec(r) !== null) : [];
}

function outcomeMapOf(doc: SpecDocument): Record<string, Rec> {
  const om = asRec(asRec(doc["contingency"])?.["outcome_map"]);
  const out: Record<string, Rec> = {};
  for (const [cls, entry] of Object.entries(om ?? {})) {
    const rec = asRec(entry);
    if (rec) out[cls] = rec;
  }
  return out;
}

function responsePortsOf(doc: SpecDocument): string[] {
  const rp = topologyOf(doc)?.["response_ports"];
  return Array.isArray(rp) ? rp.map(String) : [];
}

function knobNumber(doc: SpecDocument, knob: string, fallback: number): number {
  const v = topologyOf(doc)?.[knob];
  return typeof v === "number" ? v : fallback;
}

function knobBool(doc: SpecDocument, knob: string, fallback: boolean): boolean {
  const v = topologyOf(doc)?.[knob];
  return typeof v === "boolean" ? v : fallback;
}

function channelEntries(
  reg: ChannelRegistry,
): Array<[string, { kind: string; index: number; well?: string; port_slot?: number }]> {
  return Object.entries(reg.channels ?? {});
}

function strobeNames(reg: StrobeRegistry): string[] {
  return Object.keys(reg.codes ?? {});
}

/* ------------------------------------------------------------------------ */
/* The builder — accumulates the preflight while producing the document     */
/* ------------------------------------------------------------------------ */

class Op {
  doc: SpecDocument;
  changes: OpChange[] = [];
  questions: OpQuestion[] = [];
  warnings: string[] = [];
  blocked: string | null = null;

  constructor(
    doc: SpecDocument,
    private readonly answers: OpAnswers,
  ) {
    this.doc = doc;
  }

  set(path: string, value: unknown, label: string): void {
    this.doc = setAt(this.doc, path, value);
    this.changes.push({ kind: "set", path, label, value });
  }

  del(path: string, label: string): void {
    this.doc = deleteAt(this.doc, path);
    this.changes.push({ kind: "delete", path, label });
  }

  note(path: string, label: string): void {
    this.changes.push({ kind: "keep-greyed", path, label });
  }

  /** Register a question and return its effective answer (user's, else the
   * suggestion). `runOp` always produces a complete document from these, so
   * the UI can preview the result beside the questions. */
  ask(q: OpQuestion): unknown {
    this.questions.push(q);
    const given = this.answers[q.id];
    return given !== undefined ? given : q.suggested;
  }
}

/* ------------------------------------------------------------------------ */
/* Shared primitives                                                        */
/* ------------------------------------------------------------------------ */

/**
 * Rename a timing id AND every reference to it — the primitive that makes
 * TG201 unbreakable by a rename. `keep` follows one rule: the same firmware
 * field at a different index keeps the note and wire_key (`t_sample_hold` →
 * `t_sample_hold_0` is still odorPokeHold); a DIFFERENT firmware field drops
 * both (`t_resp_win` → `t_withhold_win` is fluidWellPoll → nogoWellPoll, and
 * a note naming the old field would be a lie).
 */
export function renameTimingId(
  doc: SpecDocument,
  from: string,
  to: string,
  keep: { note: boolean; wireKey: boolean },
): SpecDocument {
  const index = timingIndexOf(doc, from);
  if (index < 0) return doc;

  let next = setAt(doc, `timing[${index}].id`, to);
  if (!keep.note && getAt(next, `timing[${index}].note`) !== undefined) {
    next = deleteAt(next, `timing[${index}].note`);
  }
  if (!keep.wireKey && getAt(next, `timing[${index}].wire_key`) !== undefined) {
    next = deleteAt(next, `timing[${index}].wire_key`);
  }

  for (const [cls, entry] of Object.entries(outcomeMapOf(next))) {
    if (entry["delay"] === from) {
      next = setAt(next, `contingency.outcome_map.${cls}.delay`, to);
    }
  }
  for (const [name, binding] of Object.entries(portsOf(next))) {
    if (binding["reward_duration"] === from) {
      next = setAt(next, `contingency.ports.${name}.reward_duration`, to);
    }
  }
  const schedule = asRec(next["policy"])?.["stage_schedule"];
  if (Array.isArray(schedule)) {
    for (const [i, row] of schedule.entries()) {
      const set = asRec(asRec(row)?.["set"]);
      if (set && from in set) {
        const value = set[from];
        next = deleteAt(next, `policy.stage_schedule[${i}].set.${from}`);
        next = setAt(next, `policy.stage_schedule[${i}].set.${to}`, value);
      }
    }
  }
  return next;
}

function rename(
  b: Op,
  from: string,
  to: string,
  keep: { note: boolean; wireKey: boolean },
): void {
  if (timingIndexOf(b.doc, from) < 0) return;
  b.doc = renameTimingId(b.doc, from, to, keep);
  b.changes.push({
    kind: "rename",
    path: `timing.${from}`,
    label: keep.note
      ? `timing ${from} → ${to} (same firmware field — note and wire key kept)`
      : `timing ${from} → ${to} (different firmware field — note and wire key dropped)`,
  });
}

/**
 * Append every id in `required` the document lacks, at the END of the timing
 * array. The seed comes from a sibling row in this document when one is the
 * template's own peer; otherwise the value is asked for inline.
 */
function appendMissingTiming(b: Op, required: readonly string[]): void {
  for (const id of required) {
    if (timingIndexOf(b.doc, id) >= 0) continue;
    const index = timingRows(b.doc).length;

    const seed = seedFor(b.doc, id);
    if (seed !== null) {
      b.set(`timing[${index}]`, { id, ms: seed.ms }, `add timing ${id} = ${seed.ms} ms (copied from ${seed.from})`);
      continue;
    }
    const gap = /^t_interstim_gap_\d+$/.test(id);
    const ms = b.ask({
      id: `ms_${id}`,
      label: `${id} (ms)`,
      overlayKey: "timing[].ms",
      path: `timing[${index}].ms`,
      options: null,
      // A gap of 0 is a real task — seq2_retention's own note says "set to 0
      // for a compound simultaneous cue". The others have no sibling and no
      // defensible default, so Apply waits for a number.
      suggested: gap ? 0 : null,
      why: gap
        ? "Unfilled gap between stimuli; engagement still required. 0 makes a compound simultaneous cue."
        : `No existing row is this id's peer, so there is nothing honest to copy.`,
      mandatory: true,
    });
    b.set(
      `timing[${index}]`,
      { id, ms: typeof ms === "number" ? ms : 0 },
      `add timing ${id}`,
    );
  }
}

/** A sibling row that is the template's own peer of `id`, or null. */
function seedFor(doc: SpecDocument, id: string): { ms: number; from: string } | null {
  const msOf = (sib: string): number | null => {
    const i = timingIndexOf(doc, sib);
    if (i < 0) return null;
    const ms = getAt(doc, `timing[${i}].ms`);
    return typeof ms === "number" ? ms : null;
  };
  // Stage-indexed holds start equal to stage 0 and the operator ramps them —
  // the template's own comment says indexed ids exist "so each stage is
  // independently rampable".
  if (/^t_sample_hold_\d+$/.test(id)) {
    for (const sib of ["t_sample_hold_0", "t_sample_hold"]) {
      const ms = msOf(sib);
      if (ms !== null && sib !== id) return { ms, from: sib };
    }
    return null;
  }
  // grgl_2odor's note makes the identity explicit: same wire key, same value,
  // deliberately distinct indices.
  if (id === "t_commit_hold" || id === "t_sample_hold" || id === "t_sample_hold_0") {
    for (const sib of ["t_sample_hold", "t_sample_hold_0", "t_commit_hold"]) {
      const ms = msOf(sib);
      if (ms !== null && sib !== id) return { ms, from: sib };
    }
    return null;
  }
  if (/^t_reward_/.test(id)) {
    for (const row of timingRows(doc)) {
      const rid = String(row["id"] ?? "");
      if (/^t_reward_/.test(rid) && rid !== id && typeof row["ms"] === "number") {
        return { ms: row["ms"], from: rid };
      }
    }
    return null;
  }
  return null;
}

/**
 * Canonical shape for an outcome class the reconciliation must add. These
 * mirror the bundled corpus (gonogo.yaml / grgl_2odor.yaml) rather than
 * invent: the trigger is structurally forced by the template edge each class
 * is wired from, the strobes are the vocabulary's own names for the events,
 * and the delay ids are the penalty rows every bundled spec carries.
 */
const OUTCOME_SHAPES: Record<
  string,
  { trigger: string; terminal: string; delay: string; strobe: string | null }
> = {
  wrong: {
    trigger: "ENTER",
    terminal: "TRIAL_INCORRECT",
    delay: "t_pen_error",
    strobe: "@ports[$ch].error_code",
  },
  omission: {
    trigger: "TIMEOUT",
    terminal: "TRIAL_INCORRECT",
    delay: "t_pen_error",
    strobe: "RESP_OMIT",
  },
  hold_fail: {
    trigger: "BROKEN",
    terminal: "TRIAL_INCORRECT",
    delay: "t_pen_break",
    strobe: "@ports[$ch].break_code",
  },
  false_alarm: {
    trigger: "ENTER",
    terminal: "TRIAL_INCORRECT",
    delay: "t_pen_error",
    strobe: "@ports[$ch].enter_code",
  },
  no_engage: {
    trigger: "TIMEOUT",
    terminal: "TRIAL_INVALID",
    delay: "t_pen_noengage",
    strobe: "LAZY_RAT",
  },
  hold_break: {
    trigger: "BROKEN",
    terminal: "TRIAL_INVALID",
    delay: "t_pen_break",
    strobe: "ODOR_UNPOKE_EARLY",
  },
};

/**
 * Make `outcome_map` equal `next.outcomeClasses` EXACTLY. TG302 errors in
 * both directions — a produced class the spec omits is a hang, a declared
 * class the topology can't produce is a dead branch — so stale classes are
 * deleted (named in the preflight; the baseline recovers them) and missing
 * ones are added with their canonical shapes. `correct` is never touched
 * here; the mode ops own it.
 */
function reconcileOutcomes(b: Op, next: SpecCapabilities): void {
  const produced = new Set(next.outcomeClasses);
  const declared = outcomeMapOf(b.doc);

  for (const cls of Object.keys(declared)) {
    if (cls === "correct" || produced.has(cls)) continue;
    b.del(
      `contingency.outcome_map.${cls}`,
      `remove outcome ${cls} — this topology cannot produce it (TG302), its values are recoverable from the baseline`,
    );
  }

  for (const cls of produced) {
    if (cls === "correct" || cls in declared) continue;
    const shape = OUTCOME_SHAPES[cls];
    if (!shape) {
      b.warnings.push(
        `The topology produces the outcome class "${cls}", which this build has no canonical shape for — fill it in on the Parameters view.`,
      );
      continue;
    }
    appendMissingTiming(b, [shape.delay]);
    b.set(
      `contingency.outcome_map.${cls}`,
      {
        trigger: shape.trigger,
        reward: null,
        terminal: shape.terminal,
        delay: shape.delay,
        strobe: shape.strobe,
      },
      `add outcome ${cls} (${shape.trigger} → ${shape.terminal}, delay ${shape.delay})`,
    );
  }

  // TG240: penalty escalation must target a class that still exists.
  const applies = getAt(b.doc, "policy.penalty_escalation.applies_to");
  if (typeof applies === "string" && applies !== "correct" && !produced.has(applies)) {
    const fallback = produced.has("no_engage") ? "no_engage" : (next.outcomeClasses[0] ?? null);
    const target = b.ask({
      id: "escalation_applies_to",
      label: "Penalty escalation applies to",
      overlayKey: "policy.penalty_escalation.applies_to",
      path: "policy.penalty_escalation.applies_to",
      options: next.outcomeClasses.map((c) => ({ value: c, label: c })),
      suggested: fallback,
      why: `The escalation targeted "${applies}", which this topology no longer produces (TG240).`,
      mandatory: true,
    });
    b.set(
      "policy.penalty_escalation.applies_to",
      target,
      `repoint penalty escalation from ${applies}`,
    );
  }
}

/**
 * The four per-port strobes and the vocabulary family each is drawn from.
 *
 * A port only needs the codes for events its topology can produce, so a
 * go/no-go spec legitimately declares `enter_code` and nothing else — the
 * withhold task never reports a wrong port, a broken response hold or a
 * departure from a reward port. Switching that spec to n-alternative makes
 * all three reachable at once, and TG506 rejects a bound strobe that cannot
 * resolve for every port it could select. So the mode op has to fill them,
 * and this is the table it fills them from.
 */
/** The per-port strobe fields, and what each one records. WHICH code fills a
 * field is the slot's business (`portSlotCodes`), not this table's — it used to
 * carry a `family` here and glue a `_L`/`_R` onto it. */
const PORT_CODES = [
  { field: "enter_code", why: "a poke at this port" },
  { field: "error_code", why: "a poke here when it was the wrong port" },
  { field: "break_code", why: "the response hold broken here" },
  { field: "exit_code", why: "leaving this port" },
] as const;

/**
 * The six per-port code names this channel's slot reports with, or null.
 *
 * THIS REPLACES `sideSuffix()`, which read `left_well → _L`, `right_well → _R`
 * and null for anything else. Two problems with that: it was a second copy of
 * `paradigms.py`'s `_SIDE` table with nothing keeping them in step, and a rig
 * whose wells were named anything else got null — so every per-port strobe
 * arrived unsuggested and the operator picked six codes by hand, or left them
 * unset until a shape change made TG506 fire.
 *
 * Now the channel declares `port_slot` and the vocabulary's `port_slots` table
 * says what that slot's codes are called. Both come from `specs.schema`, so
 * this reads the compiler's own answer rather than restating it.
 */
function portSlotCodes(
  channel: string | null,
  ctx: OpContext,
): Record<string, string> | null {
  if (channel === null) return null;
  const slot = ctx.channels.channels?.[channel]?.port_slot;
  if (slot === undefined) return null;
  return ctx.strobes.port_slots?.[String(slot)] ?? null;
}

/** Ask for any per-port strobe the topology now needs and the port lacks. */
function ensurePortCodes(b: Op, ctx: OpContext): void {
  const known = strobeNames(ctx.strobes);
  for (const name of responsePortsOf(b.doc)) {
    const binding = portsOf(b.doc)[name];
    if (!binding) continue;
    const channel = typeof binding["channel"] === "string" ? binding["channel"] : null;
    const slot = portSlotCodes(channel, ctx);

    for (const { field, why } of PORT_CODES) {
      if (binding[field] !== undefined && binding[field] !== null) continue;
      const suggestion = slot?.[field] ?? null;
      const code = b.ask({
        id: `${field}_${name}`,
        label: `${name} ${field.replace(/_/g, " ")}`,
        overlayKey: `contingency.ports.*.${field}`,
        path: `contingency.ports.${name}.${field}`,
        options: known.map((s) => ({ value: s, label: s })),
        suggested: suggestion !== null && known.includes(suggestion) ? suggestion : null,
        why: `The strobe the data file records for ${why}. Required now that this mode can produce it (TG506).`,
        mandatory: true,
      });
      if (code !== null) {
        b.set(`contingency.ports.${name}.${field}`, code, `set ${name} ${field}`);
      }
    }
  }
}

/** The reward bindings a rewarded task needs on every response port —
 * options filtered to lines whose `well` IS the port's channel, which is what
 * makes TG224 unviolatable from here. */
function ensureRewardBindings(b: Op, ctx: OpContext): void {
  const ports = portsOf(b.doc);
  for (const name of responsePortsOf(b.doc)) {
    const binding = ports[name];
    if (!binding) continue;
    const channel = typeof binding["channel"] === "string" ? binding["channel"] : null;

    if (binding["reward_line"] === undefined || binding["reward_line"] === null) {
      const lines = channelEntries(ctx.channels).filter(
        ([, c]) => c.kind === "reward" && (channel === null || c.well === channel),
      );
      const line = b.ask({
        id: `reward_line_${name}`,
        label: `${name} reward line`,
        overlayKey: "contingency.ports.*.reward_line",
        path: `contingency.ports.${name}.reward_line`,
        options: lines.map(([n, c]) => ({ value: n, label: `${n} (pin ${c.index})` })),
        suggested: lines[0]?.[0] ?? null,
        why: `Only lines plumbed to ${channel ?? name} are offered — a line to the other well would deliver water to the wrong side of the box (TG224).`,
        mandatory: true,
      });
      if (line !== null) {
        b.set(`contingency.ports.${name}.reward_line`, line, `set ${name} reward line`);
      }
    }

    if (binding["reward_duration"] === undefined || binding["reward_duration"] === null) {
      const id = `t_reward_${name.replace(/_well$/, "")}`;
      appendMissingTiming(b, [id]);
      b.set(
        `contingency.ports.${name}.reward_duration`,
        id,
        `set ${name} reward duration → ${id}`,
      );
    }

    const slot = portSlotCodes(channel, ctx);
    for (const field of ["reward_code", "reward_stop_code"] as const) {
      if (binding[field] !== undefined && binding[field] !== null) continue;
      const suggestion = slot?.[field] ?? null;
      const known = strobeNames(ctx.strobes);
      const code = b.ask({
        id: `${field}_${name}`,
        label: `${name} ${field.replace(/_/g, " ")}`,
        overlayKey: `contingency.ports.*.${field}`,
        path: `contingency.ports.${name}.${field}`,
        options: known.map((s) => ({ value: s, label: s })),
        suggested: suggestion !== null && known.includes(suggestion) ? suggestion : null,
        why: "The strobe the data file records when this line opens/closes.",
        mandatory: true,
      });
      if (code !== null) {
        b.set(`contingency.ports.${name}.${field}`, code, `set ${name} ${field}`);
      }
    }
  }
}

function uniqueId(stem: string, taken: ReadonlySet<string>): string {
  if (!taken.has(stem)) return stem;
  for (let n = 2; n < 100; n++) {
    if (!taken.has(`${stem}${n}`)) return `${stem}${n}`;
  }
  return `${stem}_x`;
}

/* ------------------------------------------------------------------------ */
/* proposeTopology                                                          */
/* ------------------------------------------------------------------------ */

/**
 * The topology this op would produce, for the caller to feed to
 * `specs.capabilities` — or null when no knob moves and `ctx.next` should
 * simply be `ctx.caps`.
 */
export function proposeTopology(
  doc: SpecDocument,
  invocation: OpInvocation,
): Record<string, unknown> | null {
  const topology = topologyOf(doc) ?? {};
  switch (invocation.op) {
    case "addSamplingStage":
      return { ...topology, n_sampling_stages: knobNumber(doc, "n_sampling_stages", 1) + 1 };
    case "removeSamplingStage":
      return {
        ...topology,
        n_sampling_stages: Math.max(0, knobNumber(doc, "n_sampling_stages", 1) - 1),
      };
    case "setResponseMode":
      return { ...topology, response_mode: invocation.mode };
    case "setCommitHold":
      return { ...topology, commit_hold: invocation.on };
    case "setRetentionDelay":
      return { ...topology, retention_delay: invocation.on };
    case "removeResponseOption":
      return {
        ...topology,
        response_ports: responsePortsOf(doc).filter((p) => p !== invocation.port),
      };
    case "addResponseOption":
    case "removePortBinding":
    case "addStimulus":
    case "addTrialType":
    case "setCorrectRewarded":
    case "addStageRow":
    case "removeStageRow":
    case "setStageTrial":
    case "setRampedIds":
      return null;
  }
}

/* ------------------------------------------------------------------------ */
/* runOp                                                                    */
/* ------------------------------------------------------------------------ */

const TITLES: Record<OpId, string> = {
  addSamplingStage: "Add a sampling stage",
  removeSamplingStage: "Remove the last sampling stage",
  addResponseOption: "Add a response option",
  removeResponseOption: "Remove a response option",
  removePortBinding: "Remove a port binding",
  addStimulus: "Add a stimulus",
  addTrialType: "Add a trial type",
  setResponseMode: "Switch response mode",
  setCommitHold: "Commitment hold",
  setRetentionDelay: "Retention delay",
  setCorrectRewarded: "Reward on correct",
  addStageRow: "Add a stage to the ramp",
  removeStageRow: "Remove a stage from the ramp",
  setStageTrial: "Move a stage boundary",
  setRampedIds: "Choose what ramps",
};

export function runOp(
  ctx: OpContext,
  invocation: OpInvocation,
  answers: OpAnswers,
): OpResult {
  const b = new Op(ctx.doc, answers);

  switch (invocation.op) {
    case "addSamplingStage":
      addSamplingStage(b, ctx);
      break;
    case "removeSamplingStage":
      removeSamplingStage(b, ctx);
      break;
    case "addResponseOption":
      addResponseOption(b, ctx);
      break;
    case "removeResponseOption":
      removeResponseOption(b, ctx, invocation.port);
      break;
    case "removePortBinding":
      removePortBinding(b, invocation.port);
      break;
    case "addStimulus":
      addStimulus(b, ctx);
      break;
    case "addTrialType":
      addTrialType(b, ctx);
      break;
    case "setResponseMode":
      setResponseMode(b, ctx, invocation.mode);
      break;
    case "setCommitHold":
      setCommitHold(b, ctx, invocation.on);
      break;
    case "setRetentionDelay":
      setRetentionDelay(b, ctx, invocation.on);
      break;
    case "addStageRow":
      addStageRow(b);
      break;
    case "removeStageRow":
      removeStageRow(b, invocation.index);
      break;
    case "setStageTrial":
      setStageTrial(b, invocation.index, answers);
      break;
    case "setRampedIds":
      setRampedIds(b, invocation.ids);
      break;
    case "setCorrectRewarded":
      setCorrectRewarded(b, ctx, invocation.on);
      break;
  }

  return {
    doc: b.doc,
    preflight: {
      op: invocation.op,
      title: TITLES[invocation.op],
      changes: b.changes,
      questions: b.questions,
      warnings: b.warnings,
      blocked: b.blocked,
    },
  };
}

/* ------------------------------------------------------------------------ */
/* The ops                                                                  */
/* ------------------------------------------------------------------------ */

function addSamplingStage(b: Op, ctx: OpContext): void {
  const n = knobNumber(b.doc, "n_sampling_stages", 1);
  if (n >= 4) {
    b.blocked = "The schema caps sampling at 4 stages.";
    return;
  }
  const stimuli = stimuliOf(b.doc);
  if (stimuli.length === 0) {
    b.blocked = "Declare a stimulus first (Add a stimulus) — a sampling stage presents one.";
    return;
  }

  b.set("topology.n_sampling_stages", n + 1, `sampling stages ${n} → ${n + 1}`);
  if (n === 1) {
    // Crossing 1→2: the unsuffixed hold becomes stage 0's. Same firmware
    // field, so its note and wire key stay true.
    rename(b, "t_sample_hold", "t_sample_hold_0", { note: true, wireKey: true });
  }
  appendMissingTiming(b, ctx.next.requiredTiming);

  const stimulusOptions = stimuli.map((s) => ({
    value: String(s["id"] ?? ""),
    label: String(s["id"] ?? ""),
  }));
  for (const [i, tt] of trialTypesOf(b.doc).entries()) {
    const stages = Array.isArray(tt["stages"]) ? tt["stages"].map(String) : [];
    const ttId = String(tt["id"] ?? i);
    // Repeating the last stimulus is legal — seq2_retention documents an AA
    // trial — and it is the only suggestion that came from this document.
    const stim = b.ask({
      id: `stage_stim_${ttId}`,
      label: `${ttId} — stage ${n} stimulus`,
      overlayKey: "contingency.trial_types[].stages",
      path: `contingency.trial_types[${i}].stages[${n}]`,
      options: stimulusOptions,
      suggested: stages[stages.length - 1] ?? stimulusOptions[0]?.value ?? null,
      why: "Every trial type needs exactly one stimulus per stage (TG221).",
      mandatory: true,
    });
    b.set(
      `contingency.trial_types[${i}].stages`,
      [...stages, stim ?? stages[stages.length - 1] ?? ""],
      `trial type ${ttId}: stage ${n} presents ${String(stim)}`,
    );
  }

  reconcileOutcomes(b, ctx.next);
}

function removeSamplingStage(b: Op, ctx: OpContext): void {
  const n = knobNumber(b.doc, "n_sampling_stages", 1);
  if (n <= 0) {
    b.blocked = "There is no sampling stage to remove.";
    return;
  }
  b.set("topology.n_sampling_stages", n - 1, `sampling stages ${n} → ${n - 1}`);
  if (n === 2) {
    rename(b, "t_sample_hold_0", "t_sample_hold", { note: true, wireKey: true });
  }
  for (const [i, tt] of trialTypesOf(b.doc).entries()) {
    const stages = Array.isArray(tt["stages"]) ? tt["stages"].map(String) : [];
    if (stages.length >= n) {
      b.set(
        `contingency.trial_types[${i}].stages`,
        stages.slice(0, n - 1),
        `trial type ${String(tt["id"] ?? i)}: drop stage ${n - 1}`,
      );
    }
  }
  for (const id of ctx.caps.requiredTiming) {
    if (!ctx.next.requiredTiming.includes(id) && timingIndexOf(b.doc, id) >= 0) {
      b.note(`timing.${id}`, `timing ${id} is no longer required — kept, greyed in the form`);
    }
  }
  reconcileOutcomes(b, ctx.next);
}

function addResponseOption(b: Op, ctx: OpContext): void {
  // Computed from the registry, never hardcoded: the day the channel registry
  // grows a third response channel (and the vocabulary its codes), a re-sync
  // of the vendored compiler turns this op on with no frontend edit.
  const bound = new Set(
    Object.values(portsOf(b.doc)).map((p) => String(p["channel"] ?? "")),
  );
  const free = channelEntries(ctx.channels).filter(
    ([name, c]) => c.kind === "response" && !bound.has(name),
  );
  if (free.length === 0) {
    const total = channelEntries(ctx.channels).filter(([, c]) => c.kind === "response").length;
    b.blocked =
      `The channel registry declares ${total} response channel${total === 1 ? "" : "s"} and ` +
      `every one is already bound to a port. Add one in Task → Rig wiring, and this ` +
      `block turns on by itself — it counts the registry rather than a number written here.`;
    return;
  }

  const [channelName, channel] = free[0]!;
  const ports = portsOf(b.doc);
  const name = uniqueId(channelName, new Set(Object.keys(ports)));
  b.set(
    `contingency.ports.${name}`,
    { channel: channelName },
    `add port ${name} on ${channelName} (pin ${channel.index})`,
  );
  const rp = responsePortsOf(b.doc);
  b.set("topology.response_ports", [...rp, name], `add ${name} to the response window`);
  /*
   * A budget for the new port ONLY IF the task already runs correction trials.
   *
   * Setting this unconditionally created a `policy.correction.budgets` block
   * holding one entry — the port just added — on a document that had none, so
   * a task built from `blank` came out with a correction policy for its second
   * well and nothing for its first. Two wrongs in one line: it invents a policy
   * the task never declared, and where the policy IS declared, a block covering
   * some of the ports is worse than one covering none, because the missing
   * entry reads as a deliberate zero.
   *
   * `budgets` is a map keyed by port, so an existing block is the signal that
   * this task uses correction trials at all. Zero is the identity here — no
   * correction trials for this port — and not a tuning value pulled from a
   * defaults table, which is why it can be written without asking.
   */
  if (getAt(b.doc, "policy.correction.budgets") !== undefined) {
    b.set(`policy.correction.budgets.${name}`, 0, `correction budget ${name} = 0`);
  }

  ensurePortCodes(b, ctx);
  const om = outcomeMapOf(b.doc);
  if (om["correct"]?.["reward"] != null) ensureRewardBindings(b, ctx);
  reconcileOutcomes(b, ctx.next);
}

function removeResponseOption(b: Op, ctx: OpContext, port: string): void {
  const rp = responsePortsOf(b.doc);
  if (!rp.includes(port)) {
    b.blocked = `"${port}" is not in the response window.`;
    return;
  }
  const remaining = rp.filter((p) => p !== port);
  if (remaining.length === 0) {
    b.blocked = "At least one response port must remain — the schema requires it.";
    return;
  }

  b.set("topology.response_ports", remaining, `remove ${port} from the response window`);

  for (const [i, tt] of trialTypesOf(b.doc).entries()) {
    if (tt["target"] !== port) continue;
    const ttId = String(tt["id"] ?? i);
    // Only one remaining port is a safe default; with several, no default is —
    // and a dangling target makes a trial that can never be answered, which no
    // lint rule catches.
    const target = b.ask({
      id: `retarget_${ttId}`,
      label: `${ttId} — new target`,
      overlayKey: "contingency.trial_types[].target",
      path: `contingency.trial_types[${i}].target`,
      options: remaining.map((p) => ({ value: p, label: p })),
      suggested: remaining.length === 1 ? remaining[0]! : null,
      why: `This trial type targeted ${port}, which is leaving the response window.`,
      mandatory: true,
    });
    b.set(
      `contingency.trial_types[${i}].target`,
      target,
      `trial type ${ttId}: target ${port} → ${String(target)}`,
    );
  }
  b.note(
    `contingency.ports.${port}`,
    `the ${port} binding stays declared — remove it separately if the box no longer has it`,
  );
  reconcileOutcomes(b, ctx.next);
}

function removePortBinding(b: Op, port: string): void {
  if (responsePortsOf(b.doc).includes(port)) {
    b.blocked = `${port} is still in the response window — remove it from there first.`;
    return;
  }
  const om = outcomeMapOf(b.doc);
  for (const [cls, entry] of Object.entries(om)) {
    if (entry["reward"] === port) {
      b.blocked = `The ${cls} outcome rewards through ${port} — repoint it first.`;
      return;
    }
  }
  if (!(port in portsOf(b.doc))) {
    b.blocked = `No port named "${port}" is declared.`;
    return;
  }
  b.del(`contingency.ports.${port}`, `remove the ${port} binding`);
  if (getAt(b.doc, `policy.correction.budgets.${port}`) !== undefined) {
    b.del(`policy.correction.budgets.${port}`, `remove the ${port} correction budget`);
  }
}

function addStimulus(b: Op, ctx: OpContext): void {
  const stimuli = stimuliOf(b.doc);
  if (stimuli.length >= 8) {
    b.blocked = "The table caps stimuli at 8 (TG_MAX_STIMULI).";
    return;
  }
  const usedEmitters = new Set(stimuli.map((s) => String(s["emitter"] ?? "")));
  const usedCodes = new Set(stimuli.map((s) => String(s["on_code"] ?? "")));
  const emitters = channelEntries(ctx.channels).filter(([, c]) => c.kind === "emitter");
  const freeEmitters = emitters.filter(([name]) => !usedEmitters.has(name));

  const taken = new Set(stimuli.map((s) => String(s["id"] ?? "")));
  const id = b.ask({
    id: "stimulus_id",
    label: "Stimulus id",
    overlayKey: "contingency.stimuli[].id",
    path: "",
    options: null,
    suggested: uniqueId("stim", taken),
    why: "Names this stimulus in trial types.",
    mandatory: true,
  });

  const emitter = b.ask({
    id: "stimulus_emitter",
    label: "Emitter line",
    overlayKey: "contingency.stimuli[].emitter",
    path: "",
    options: emitters.map(([n, c]) => ({ value: n, label: `${n} (pin ${c.index})` })),
    suggested: freeEmitters[0]?.[0] ?? null,
    why: "Which solenoid line delivers it. Unused lines are suggested first.",
    mandatory: true,
  });

  // ODOR_<k>_ON pairs with odor_line_<k>, and the family is READ rather than
  // assumed to stop at six. It did stop at six: twelve odor lines were plumbed
  // and only half of them could announce an onset, so lines 7-12 existed on the
  // board and could not be discriminanda. The vocabulary now declares twelve,
  // and this line finds however many it declares.
  const known = strobeNames(ctx.strobes);
  const onsetFamily = known.filter((s) => /^ODOR_\d+_ON$/.test(s));
  const match = typeof emitter === "string" ? /^odor_line_(\d+)$/.exec(emitter) : null;
  const paired = match ? `ODOR_${match[1]}_ON` : null;
  const suggestion =
    paired !== null && known.includes(paired) && !usedCodes.has(paired)
      ? paired
      : (onsetFamily.find((s) => !usedCodes.has(s)) ?? null);
  if (suggestion === null) {
    b.warnings.push(
      "All declared stimulus-onset codes are in use — a new one must be appended to the vocabulary upstream.",
    );
  }
  const onCode = b.ask({
    id: "stimulus_on_code",
    label: "Onset strobe",
    overlayKey: "contingency.stimuli[].on_code",
    path: "",
    options: onsetFamily.map((s) => ({ value: s, label: s })),
    suggested: suggestion,
    why: "The strobe the data file records at stimulus onset — how analysis knows what was presented.",
    mandatory: true,
  });

  const index = stimuli.length;
  b.set(
    `contingency.stimuli[${index}]`,
    { id: id ?? uniqueId("stim", taken), emitter, on_code: onCode },
    `add stimulus ${String(id)} on ${String(emitter)}`,
  );
}

function addTrialType(b: Op, ctx: OpContext): void {
  const types = trialTypesOf(b.doc);
  if (types.length >= 16) {
    b.blocked = "The table caps trial types at 16 (TG_MAX_TRIAL_TYPES).";
    return;
  }
  const n = knobNumber(b.doc, "n_sampling_stages", 1);
  const stimuli = stimuliOf(b.doc);
  if (n > 0 && stimuli.length === 0) {
    b.blocked = "Declare a stimulus first — every stage of a trial type presents one.";
    return;
  }
  const gonogo = topologyOf(b.doc)?.["response_mode"] === "go_nogo";
  const previous = types[types.length - 1];
  const previousStages = Array.isArray(previous?.["stages"])
    ? previous["stages"].map(String)
    : [];

  const taken = new Set(types.map((t) => String(t["id"] ?? "")));
  const id = b.ask({
    id: "trial_type_id",
    label: "Trial type id",
    overlayKey: "contingency.trial_types[].id",
    path: "",
    options: null,
    suggested: uniqueId("tt", taken),
    why: "Names this trial type in the context schedule and the data.",
    mandatory: true,
  });

  const stimulusOptions = stimuli.map((s) => ({
    value: String(s["id"] ?? ""),
    label: String(s["id"] ?? ""),
  }));
  const stages: unknown[] = [];
  for (let i = 0; i < n; i++) {
    stages.push(
      b.ask({
        id: `trial_type_stage_${i}`,
        label: `Stage ${i} stimulus`,
        overlayKey: "contingency.trial_types[].stages",
        path: "",
        options: stimulusOptions,
        suggested: previousStages[i] ?? stimulusOptions[0]?.value ?? null,
        why: "Exactly one stimulus per stage (TG221). Repeats are legal.",
        mandatory: true,
      }),
    );
  }

  let target: unknown = null;
  if (!gonogo) {
    const rp = responsePortsOf(b.doc);
    const counts = new Map<string, number>(rp.map((p) => [p, 0]));
    for (const tt of types) {
      const t = tt["target"];
      if (typeof t === "string" && counts.has(t)) counts.set(t, counts.get(t)! + 1);
    }
    const leastUsed = [...counts.entries()].sort((a, b2) => a[1] - b2[1])[0]?.[0] ?? null;
    target = b.ask({
      id: "trial_type_target",
      label: "Target port",
      overlayKey: "contingency.trial_types[].target",
      path: "",
      options: rp.map((p) => ({ value: p, label: p })),
      suggested: leastUsed,
      why: "The port that scores correct. The least-targeted port is suggested to keep the sides balanced.",
      mandatory: true,
    });
  } else {
    b.note("contingency.trial_types", "go/no-go: the target is null — withholding is correct");
  }

  const index = types.length;
  b.set(
    `contingency.trial_types[${index}]`,
    { id: id ?? uniqueId("tt", taken), stages, target, weight: 1 },
    `add trial type ${String(id)}`,
  );
  void ctx;
}

function setResponseMode(b: Op, ctx: OpContext, mode: "n_alternative" | "go_nogo"): void {
  const current = topologyOf(b.doc)?.["response_mode"];
  if (current === mode) {
    b.blocked = `The response mode is already ${mode}.`;
    return;
  }
  b.set("topology.response_mode", mode, `response mode → ${mode}`);

  if (mode === "go_nogo") {
    // fluidWellPoll → nogoWellPoll: a different firmware field, so the note
    // and wire key are dropped rather than left to lie.
    rename(b, "t_resp_win", "t_withhold_win", { note: false, wireKey: false });
    appendMissingTiming(b, ctx.next.requiredTiming);

    // The inversion: window expiry IS the correct outcome, and any entry is a
    // false alarm. gonogo.yaml is the corpus for every value here.
    b.set("contingency.outcome_map.correct.trigger", "TIMEOUT", "correct: trigger → TIMEOUT");
    if (getAt(b.doc, "contingency.outcome_map.correct.reward") != null) {
      b.set(
        "contingency.outcome_map.correct.reward",
        null,
        "correct: reward → none (a withhold task has no port to reward)",
      );
    }
    const known = strobeNames(ctx.strobes);
    const strobe = b.ask({
      id: "correct_strobe",
      label: "Correct (withheld) strobe",
      overlayKey: "contingency.outcome_map.*.strobe",
      path: "contingency.outcome_map.correct.strobe",
      options: known.map((s) => ({ value: s, label: s })),
      suggested: known.includes("WATER_POKE_NONE") ? "WATER_POKE_NONE" : null,
      why: "WATER_POKE_NONE is the vocabulary's own name for a survived window — what the data records is not a silent decision.",
      mandatory: true,
    });
    b.set("contingency.outcome_map.correct.strobe", strobe, `correct: strobe → ${String(strobe)}`);
    if (getAt(b.doc, "contingency.outcome_map.correct.note") !== undefined) {
      b.del(
        "contingency.outcome_map.correct.note",
        "note on outcome correct — it described a consummatory bout this mode does not have",
      );
    }
    for (const [i, tt] of trialTypesOf(b.doc).entries()) {
      if (tt["target"] == null) continue;
      b.set(
        `contingency.trial_types[${i}].target`,
        null,
        `trial type ${String(tt["id"] ?? i)}: target → null — THAT is the withhold declaration`,
      );
    }
  } else {
    // nogoWellPoll → fluidWellPoll — again a different firmware field.
    rename(b, "t_withhold_win", "t_resp_win", { note: false, wireKey: false });
    appendMissingTiming(b, ctx.next.requiredTiming);

    b.set("contingency.outcome_map.correct.trigger", "HELD", "correct: trigger → HELD");
    if (getAt(b.doc, "contingency.outcome_map.correct.note") !== undefined) {
      b.del(
        "contingency.outcome_map.correct.note",
        "note on outcome correct — it described the withhold this mode does not have",
      );
    }

    // A withhold task's ports only ever declared `enter_code`. Wrong-port,
    // hold-break and reward-exit reporting all become reachable here at once,
    // and TG506 wants a code for each on EVERY port.
    ensurePortCodes(b, ctx);

    const rp = responsePortsOf(b.doc);
    for (const [i, tt] of trialTypesOf(b.doc).entries()) {
      if (tt["target"] != null) continue;
      const ttId = String(tt["id"] ?? i);
      const target = b.ask({
        id: `target_${ttId}`,
        label: `${ttId} — target port`,
        overlayKey: "contingency.trial_types[].target",
        path: `contingency.trial_types[${i}].target`,
        options: rp.map((p) => ({ value: p, label: p })),
        suggested: rp[i % Math.max(1, rp.length)] ?? null,
        why: "An n-alternative trial needs a port that scores correct.",
        mandatory: true,
      });
      b.set(
        `contingency.trial_types[${i}].target`,
        target,
        `trial type ${ttId}: target → ${String(target)}`,
      );
    }

    const rewarded = b.ask({
      id: "rewarded",
      label: "Reward a correct trial",
      overlayKey: "contingency.outcome_map.*.reward",
      path: "contingency.outcome_map.correct.reward",
      options: [
        { value: "yes", label: "Yes — open the target's line" },
        { value: "no", label: "No reward" },
      ],
      suggested: "yes",
      why: "Rewarding adds the delivery and consumption states to the outcome epoch.",
      mandatory: true,
    });
    if (rewarded === "yes") {
      b.set("contingency.outcome_map.correct.reward", "@target", "correct: reward → @target");
      const strobe = getAt(b.doc, "contingency.outcome_map.correct.strobe");
      if (strobe === null || strobe === "WATER_POKE_NONE") {
        b.set(
          "contingency.outcome_map.correct.strobe",
          "@target.exit_code",
          "correct: strobe → @target.exit_code (end of the consummatory bout)",
        );
      }
      ensureRewardBindings(b, ctx);
    } else {
      b.set("contingency.outcome_map.correct.reward", null, "correct: no reward");
      const strobe = getAt(b.doc, "contingency.outcome_map.correct.strobe");
      if (strobe === "WATER_POKE_NONE") {
        b.set(
          "contingency.outcome_map.correct.strobe",
          "@target.exit_code",
          "correct: strobe → @target.exit_code",
        );
      }
    }
  }

  reconcileOutcomes(b, ctx.next);
}

function setCommitHold(b: Op, ctx: OpContext, on: boolean): void {
  const current = knobBool(b.doc, "commit_hold", true);
  if (current === on) {
    b.blocked = `The commitment hold is already ${on ? "on" : "off"}.`;
    return;
  }
  b.set("topology.commit_hold", on, `commitment hold → ${on ? "on" : "off"}`);
  if (on) {
    appendMissingTiming(b, ctx.next.requiredTiming);
  } else if (timingIndexOf(b.doc, "t_commit_hold") >= 0) {
    b.note("timing.t_commit_hold", "timing t_commit_hold is no longer required — kept, greyed");
  }
  reconcileOutcomes(b, ctx.next);
}

function setRetentionDelay(b: Op, ctx: OpContext, on: boolean): void {
  const current = knobBool(b.doc, "retention_delay", false);
  if (current === on) {
    b.blocked = `The retention delay is already ${on ? "on" : "off"}.`;
    return;
  }
  b.set("topology.retention_delay", on, `retention delay → ${on ? "on" : "off"}`);
  if (on) {
    appendMissingTiming(b, ctx.next.requiredTiming);
  } else if (timingIndexOf(b.doc, "t_retention") >= 0) {
    b.note("timing.t_retention", "timing t_retention is no longer required — kept, greyed");
  }
  reconcileOutcomes(b, ctx.next);
}

function setCorrectRewarded(b: Op, ctx: OpContext, on: boolean): void {
  if (topologyOf(b.doc)?.["response_mode"] === "go_nogo") {
    // The outcome band is not emitted at all under go/no-go — the template's
    // own structure, not a policy choice made here.
    b.blocked =
      "A go/no-go task has no reward path: the outcome epoch's delivery and consumption states are only emitted for n-alternative responding.";
    return;
  }
  const current = getAt(b.doc, "contingency.outcome_map.correct.reward") != null;
  if (current === on) {
    b.blocked = `Reward on correct is already ${on ? "on" : "off"}.`;
    return;
  }

  if (on) {
    b.set("contingency.outcome_map.correct.reward", "@target", "correct: reward → @target");
    const strobe = getAt(b.doc, "contingency.outcome_map.correct.strobe");
    if (strobe === null || strobe === undefined) {
      b.set(
        "contingency.outcome_map.correct.strobe",
        "@target.exit_code",
        "correct: strobe → @target.exit_code (end of the consummatory bout)",
      );
    }
    // `@target.exit_code` has to resolve for every port it could select.
    ensurePortCodes(b, ctx);
    ensureRewardBindings(b, ctx);
  } else {
    b.set(
      "contingency.outcome_map.correct.reward",
      null,
      "correct: reward → none — drops the delivery and consumption states from the outcome epoch",
    );
    if (getAt(b.doc, "contingency.outcome_map.correct.note") !== undefined) {
      b.del(
        "contingency.outcome_map.correct.note",
        "note on outcome correct — it described the consummatory bout an unrewarded task does not have",
      );
    }
    b.note(
      "contingency.ports",
      "the ports' reward bindings stay declared — harmless, and turning reward back on finds them",
    );
  }
}

/* ------------------------------------------------------------------------ */
/* The shaping ramp — policy.stage_schedule                                  */
/* ------------------------------------------------------------------------ */

/**
 * The rows of a stage schedule, as records with a numeric `at_trial`.
 *
 * TG205 scans them descending with `>=`, so ORDER IS SEMANTIC, not cosmetic:
 * a schedule listed out of order does not fail, it applies the wrong row. Every
 * op below re-sorts rather than trusting where the operator typed.
 */
function stageRows(doc: SpecDocument): Rec[] {
  const rows = asRec(doc["policy"])?.["stage_schedule"];
  return Array.isArray(rows) ? rows.filter((r): r is Rec => asRec(r) !== null) : [];
}

function sortedRows(rows: Rec[]): Rec[] {
  return [...rows].sort(
    (a, b) => (Number(a["at_trial"]) || 0) - (Number(b["at_trial"]) || 0),
  );
}

/** Which timing ids this schedule currently ramps, in timing-vector order. */
function rampedIds(doc: SpecDocument): string[] {
  const seen = new Set<string>();
  for (const row of stageRows(doc)) {
    for (const id of Object.keys(asRec(row["set"]) ?? {})) seen.add(id);
  }
  return timingRows(doc)
    .map((r) => String(r["id"]))
    .filter((id) => seen.has(id));
}

/**
 * Add a boundary to the ramp.
 *
 * A new row carries EVERY id the schedule already ramps, because a row that
 * omits one does not leave it alone -- the firmware rewrites the whole set at a
 * boundary, so a missing id silently reverts to whatever the previous row left.
 * That is the partial-row trap TG507 exists for, and the reason this op fills
 * the row rather than letting the operator build it column by column.
 *
 * Values are seeded from the row BEFORE it in trial order, which is the only
 * honest starting point: a ramp step that begins where the previous step ended
 * is a no-op until the operator moves it, and a no-op is a better default than
 * a number this module invented.
 */
function addStageRow(b: Op): void {
  const rows = sortedRows(stageRows(b.doc));
  const ids = rampedIds(b.doc);

  if (ids.length === 0) {
    b.blocked =
      "This task ramps nothing yet. Choose which durations should change across " +
      "the session first, then add the trials at which they change.";
    return;
  }

  const last = rows[rows.length - 1];
  const lastAt = last ? Number(last["at_trial"]) || 0 : -1;
  const suggestedAt = lastAt < 0 ? 0 : lastAt + 25;

  const at = b.ask({
    id: "at_trial",
    label: "Switches at trial",
    overlayKey: "policy.stage_schedule[].at_trial",
    path: `policy.stage_schedule[${rows.length}].at_trial`,
    options: null,
    suggested: suggestedAt,
    why:
      "The completed-trial count at which this row takes over. Rows are scanned " +
      "in order, so this must be higher than the row before it.",
    mandatory: true,
  });
  const atTrial = Number(at);

  if (rows.some((r) => Number(r["at_trial"]) === atTrial)) {
    b.blocked = `There is already a row at trial ${atTrial}. Edit that one instead.`;
    return;
  }

  const carried = asRec(last?.["set"]) ?? {};
  const set: Rec = {};
  for (const id of ids) {
    const previous = carried[id];
    set[id] =
      previous !== undefined
        ? previous
        : (getAt(b.doc, `timing[${timingIndexOf(b.doc, id)}].ms`) ?? 0);
  }

  const next = sortedRows([...rows, { at_trial: atTrial, set }]);
  b.set("policy.stage_schedule", next, `stage row at trial ${atTrial}`);
  b.note(
    "policy.stage_schedule",
    `carries all ${ids.length} ramped duration${ids.length === 1 ? "" : "s"} ` +
      "from the row before it — a row that omits one does not leave it alone",
  );
}

/**
 * Move a boundary to a different trial.
 *
 * RE-SORTS, which is the whole point. TG205 wants rows ascending by `at_trial`,
 * and an out-of-order schedule is the dangerous kind of wrong: the board takes
 * the latest row whose count has been reached, so it does not fail, it applies
 * a row the operator did not intend. Sorting here means the document is never
 * in that state, whatever order the numbers were typed in.
 *
 * A collision is refused rather than merged. Two rows at one trial is TG205's
 * other half, and silently dropping one of them would discard values somebody
 * entered.
 */
function setStageTrial(b: Op, index: number, answers: OpAnswers): void {
  const rows = sortedRows(stageRows(b.doc));
  const row = rows[index];
  if (!row) {
    b.blocked = "That stage row is no longer there.";
    return;
  }
  const at = Number(answers["at_trial"]);
  if (!Number.isInteger(at) || at < 0) {
    b.blocked = "A stage boundary is a whole number of completed trials.";
    return;
  }
  if (at === (Number(row["at_trial"]) || 0)) return;
  if (rows.some((r, i) => i !== index && (Number(r["at_trial"]) || 0) === at)) {
    b.blocked = `There is already a row at trial ${at}. Move that one first, or remove it.`;
    return;
  }
  const next = sortedRows(
    rows.map((r, i) => (i === index ? { ...r, at_trial: at } : r)),
  );
  b.set("policy.stage_schedule", next, `the boundary at trial ${at}`);
}

/** Remove a boundary. The remaining rows keep their order and their ids. */
function removeStageRow(b: Op, index: number): void {
  const rows = sortedRows(stageRows(b.doc));
  const row = rows[index];
  if (!row) {
    b.blocked = "That stage row is no longer there.";
    return;
  }
  if (rows.length === 1) {
    b.set("policy.stage_schedule", [], "the ramp — every duration holds its base value");
    return;
  }
  const next = rows.filter((_, i) => i !== index);
  b.set(
    "policy.stage_schedule",
    next,
    `the row at trial ${Number(row["at_trial"]) || 0}`,
  );
}

/**
 * Choose which durations ramp.
 *
 * Adding an id fills it into EVERY existing row (seeded from the timing vector,
 * so nothing changes until the operator moves it); removing one drops it from
 * every row. Both directions matter for the same reason: the set of ids has to
 * be identical across rows, or a boundary silently reverts whatever it omits.
 */
function setRampedIds(b: Op, ids: string[]): void {
  const rows = sortedRows(stageRows(b.doc));
  const wanted = timingRows(b.doc)
    .map((r) => String(r["id"]))
    .filter((id) => ids.includes(id));

  if (wanted.length === 0) {
    b.set("policy.stage_schedule", [], "the ramp — nothing is ramped any more");
    return;
  }
  if (rows.length === 0) {
    // Nothing to fill yet; the first Add row will carry these.
    b.set(
      "policy.stage_schedule",
      [
        {
          at_trial: 0,
          set: Object.fromEntries(
            wanted.map((id) => [
              id,
              getAt(b.doc, `timing[${timingIndexOf(b.doc, id)}].ms`) ?? 0,
            ]),
          ),
        },
      ],
      `a first stage row at trial 0, ramping ${wanted.join(", ")}`,
    );
    b.note("policy.stage_schedule", "seeded from the timing vector, so the ramp starts as a no-op");
    return;
  }

  const next = rows.map((row) => {
    const had = asRec(row["set"]) ?? {};
    const set: Rec = {};
    for (const id of wanted) {
      set[id] =
        had[id] !== undefined
          ? had[id]
          : (getAt(b.doc, `timing[${timingIndexOf(b.doc, id)}].ms`) ?? 0);
    }
    return { ...row, set };
  });
  b.set("policy.stage_schedule", next, `ramped durations → ${wanted.join(", ")}`);
}
