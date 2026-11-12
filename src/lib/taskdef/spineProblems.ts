import type { TaskDiagnostic } from "@/lib/ws/protocol";

import type { SpineDefinition } from "./spine";
import { channelWord } from "./spineWords";
import type { RigDocument } from "@/lib/hardware/types";

/**
 * A spine task's problems as instructions (`TASKS.md#the-spine-editor`): what
 * to do, in the user's words, and the one-click fix where the document alone
 * answers. The sidecar's message stays as the detail, since it is the one
 * authority on what is wrong; this adds what to do about it.
 *
 * GROUPED BY WHAT THE FIX IS. Seven unbound roles on one row are one line
 * ("7 roles have no channel yet"), and the edges with no strobe code across
 * the whole task are one line pointing at the Rig page. Each diagnostic is
 * still shown at its target: the lines keep their diagnostics, and the cells
 * and nodes mark themselves from `location` as before.
 *
 * A fix edits the document and nothing else; whether it was enough is the
 * next preview's answer.
 */

export interface ProblemFix {
  label: string;
  apply: (def: SpineDefinition) => SpineDefinition;
}

export interface ProblemLine {
  code: string;
  /** What to do. */
  instruction: string;
  /** The sidecar's own words, one per diagnostic. */
  detail: string[];
  diagnostics: TaskDiagnostic[];
  fix: ProblemFix | null;
  /** A page that answers it: the Rig page's wiring, or the strobe vocabulary. */
  link: "wiring" | "strobes" | null;
}

/** The slot a `rows[r].bind.<slot>` location names. */
function boundSlot(location: string): string | null {
  return /^rows\[\d+\]\.bind\.(.+)$/.exec(location)?.[1] ?? null;
}

function rowIndex(d: TaskDiagnostic): number | null {
  return d.target.kind === "row" ? d.target.index : null;
}

function rowName(def: SpineDefinition, r: number): string {
  return def.rows[r]?.name || `trial type ${r + 1}`;
}

/** A line for one diagnostic in the sidecar's words, with no fix. */
function plain(d: TaskDiagnostic, link: ProblemLine["link"] = null): ProblemLine {
  return { code: d.code, instruction: d.message, detail: [d.message], diagnostics: [d], fix: null, link };
}

function unboundLine(def: SpineDefinition, r: number, mine: TaskDiagnostic[], rig: RigDocument | null): ProblemLine {
  const slots = mine.map((d) => boundSlot(d.location)).filter((s): s is string => s !== null);
  const missing = mine.filter((d) => /no channel/.test(d.message));
  const lacking = mine.filter((d) => !/no channel/.test(d.message));
  const parts: string[] = [];
  if (missing.length === 1) parts.push(`Pick the channel that plays ${boundSlot(missing[0]!.location)}.`);
  else if (missing.length > 1) parts.push(`${missing.length} roles have no channel yet: pick one for each.`);
  for (const d of lacking) {
    const name = /no channel '([^']+)'/.exec(d.message)?.[1];
    parts.push(`${boundSlot(d.location)} is bound to ${name ? channelWord(name, rig) : "a channel"} this rig does not have: pick another.`);
  }
  // Bind like another row that binds every slot this one lacks: the one edit
  // that fills a seed's second row in one click.
  const donor = def.rows.findIndex((row, i) => i !== r && slots.every((s) => row.bind[s] !== undefined));
  const fix: ProblemFix | null =
    donor < 0
      ? null
      : {
          label: `Bind like ${rowName(def, donor)}`,
          apply: (current) => {
            const row = current.rows[r];
            const from = current.rows[donor];
            if (!row || !from) return current;
            const bind = { ...row.bind };
            for (const s of slots) if (from.bind[s] !== undefined) bind[s] = from.bind[s];
            return { ...current, rows: current.rows.map((x, i) => (i === r ? { ...x, bind } : x)) };
          },
        };
  return { code: "SPN101", instruction: parts.join(" "), detail: mine.map((d) => d.message), diagnostics: mine, fix, link: null };
}

function oneLine(def: SpineDefinition, d: TaskDiagnostic): ProblemLine {
  const r = rowIndex(d);
  switch (d.code) {
    case "SPN108":
      return { ...plain(d), instruction: "Name this trial type: its name titles every readout of it." };
    case "SPN104":
      return plain(d, "strobes");
    case "SPN106": {
      if (d.location === "sessionTrials") {
        return {
          ...plain(d),
          instruction:
            "Only End Session would end this session: its blocks loop, or one never ends. Add a session cap, or give every block an end rule and the last one nothing to go on to.",
          fix: {
            label: "Add a cap of 400 trials",
            apply: (current) => ({ ...current, sessionTrials: 400 }),
          },
        };
      }
      if (r !== null && /^rows\[\d+\]\.id$/.test(d.location) && /no block draws/.test(d.message)) {
        return {
          ...plain(d),
          instruction: `No block presents ${rowName(def, r)}: add it to a block, or remove it.`,
          fix: {
            label: "Add to block 1",
            apply: (current) => {
              const row = current.rows[r];
              const block = current.blocks[0];
              if (!row || !block || block.rows.includes(row.id)) return current;
              const next = { ...block, rows: [...block.rows, row.id] };
              if (block.weights) next.weights = [...block.weights, 1];
              return { ...current, blocks: current.blocks.map((b, i) => (i === 0 ? next : b)) };
            },
          },
        };
      }
      return plain(d);
    }
    case "SPN110": {
      const key = /^params\.(.+)$/.exec(d.location)?.[1];
      if (!key) return plain(d);
      return {
        ...plain(d),
        instruction: `Nothing in this task reads the stored value ${key}: drop it, or it stays silently unused.`,
        fix: {
          label: "Drop it",
          apply: (current) => {
            const { [key]: _dropped, ...params } = current.params;
            return { ...current, params };
          },
        },
      };
    }
    case "SPN105":
      if (d.target.kind === "ram") {
        return { ...plain(d), instruction: `The task does not fit the board: ${d.message}. Fewer trial types, steps or answers that pay make it smaller.` };
      }
      return plain(d);
    case "SPN109": {
      const key = /^rows\[\d+\]\.map\.([^.]+)/.exec(d.location)?.[1];
      return key ? { ...plain(d), instruction: `${key === "timeout" ? "No answer" : key}: ${d.message}.` } : plain(d);
    }
    default:
      return plain(d);
  }
}

/** The diagnostics about a role's binding: SPN101, SPN102 and SPN107 on `rows[r].bind.<slot>`. */
const BINDING_CODES = new Set(["SPN101", "SPN102", "SPN107"]);

/**
 * The problem lines for one row (`row` given), or for the task as a whole
 * (every diagnostic whose target is not a row, plus SPN103 from every row,
 * which is one line for the whole task). A binding problem on a role in
 * `shared` is the Wiring line's (`wiringLines`), not the row's. Order is the
 * sidecar's.
 */
export function problemLines(
  diagnostics: readonly TaskDiagnostic[],
  def: SpineDefinition,
  rig: RigDocument | null,
  row: number | null,
  shared: readonly string[] = [],
): ProblemLine[] {
  const lines: ProblemLine[] = [];
  if (row !== null) {
    const mine = diagnostics.filter((d) => {
      if (rowIndex(d) !== row || d.code === "SPN103") return false;
      const slot = boundSlot(d.location);
      return !(slot !== null && BINDING_CODES.has(d.code) && shared.includes(slot));
    });
    const unbound = mine.filter((d) => d.code === "SPN101" && boundSlot(d.location) !== null);
    let unboundDone = false;
    for (const d of mine) {
      if (unbound.includes(d)) {
        if (!unboundDone) {
          lines.push(unboundLine(def, row, unbound, rig));
          unboundDone = true;
        }
        continue;
      }
      lines.push(oneLine(def, d));
    }
    return lines;
  }
  const codeless = diagnostics.filter((d) => d.code === "SPN103");
  if (codeless.length) {
    lines.push({
      code: "SPN103",
      instruction: `${codeless.length} channel edge${codeless.length === 1 ? " has" : "s have"} no strobe code yet, so a run would record numbers nothing decodes. Save the wiring on the Rig page to issue them.`,
      detail: codeless.map((d) => d.message),
      diagnostics: codeless,
      fix: null,
      link: "wiring",
    });
  }
  for (const d of diagnostics) {
    if (d.code === "SPN103" || rowIndex(d) !== null) continue;
    if (d.target.kind === "row" && d.target.index === null) lines.push(oneLine(def, d));
    else if (d.target.kind === "task" || d.target.kind === "vocabulary") lines.push(oneLine(def, d));
  }
  return lines;
}

/** The lines for one target that is not a row: a phase, a block, the session cap, a slot or the RAM. */
export function targetLines(
  diagnostics: readonly TaskDiagnostic[],
  def: SpineDefinition,
  kind: TaskDiagnostic["target"]["kind"],
  index: number | null,
): ProblemLine[] {
  return diagnostics.filter((d) => d.target.kind === kind && d.target.index === index).map((d) => oneLine(def, d));
}

/**
 * The Wiring line's problems: every binding problem on a shared role, said
 * once per role whatever the number of trial types that repeat it. The
 * unbound roles are one line naming them; a wrong channel keeps the
 * sidecar's words, once.
 */
export function wiringLines(
  diagnostics: readonly TaskDiagnostic[],
  rig: RigDocument | null,
  shared: readonly string[],
): ProblemLine[] {
  const lines: ProblemLine[] = [];
  const mine = diagnostics.filter((d) => {
    const slot = boundSlot(d.location);
    return slot !== null && BINDING_CODES.has(d.code) && shared.includes(slot);
  });
  const unbound = mine.filter((d) => d.code === "SPN101" && /no channel$/.test(d.message));
  const slots = [...new Set(unbound.map((d) => boundSlot(d.location)!))];
  if (slots.length) {
    lines.push({
      code: "SPN101",
      instruction: slots.length === 1 ? `Pick the channel that plays ${slots[0]}.` : `${slots.length} roles have no channel yet: ${slots.join(", ")}.`,
      detail: [...new Set(unbound.map((d) => d.message))],
      diagnostics: unbound,
      fix: null,
      link: null,
    });
  }
  const seen = new Set<string>();
  for (const d of mine) {
    if (unbound.includes(d) || seen.has(d.message)) continue;
    seen.add(d.message);
    const name = /no channel '([^']+)'/.exec(d.message)?.[1];
    const line = plain(d);
    if (name) line.instruction = `${boundSlot(d.location)} is bound to ${channelWord(name, rig)}, which this rig does not have: pick another.`;
    lines.push(line);
  }
  return lines;
}

/**
 * Every line for these diagnostics, each said once where the editor would say
 * it: the shared roles' Wiring line, the task-wide lines, each row's, then each
 * phase, block, session, slot and RAM target's. For a view with no panels of
 * its own, such as one step of the guide.
 */
export function everyLine(
  diagnostics: readonly TaskDiagnostic[],
  def: SpineDefinition,
  rig: RigDocument | null,
  shared: readonly string[],
): ProblemLine[] {
  const lines = [...wiringLines(diagnostics, rig, shared), ...problemLines(diagnostics, def, rig, null)];
  def.rows.forEach((_, r) => lines.push(...problemLines(diagnostics, def, rig, r, shared)));
  const targets = new Map<string, TaskDiagnostic["target"]>();
  for (const d of diagnostics) {
    if (["phase", "block", "session", "slot", "ram"].includes(d.target.kind)) targets.set(`${d.target.kind}:${d.target.index}`, d.target);
  }
  for (const t of targets.values()) lines.push(...targetLines(diagnostics, def, t.kind, t.index));
  return lines;
}
