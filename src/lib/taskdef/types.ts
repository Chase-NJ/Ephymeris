import type { RigDocument } from "@/lib/hardware/types";
import type { TaskDiagnostic, TaskEntry } from "@/lib/ws/protocol";

export type { TaskDiagnostic, TaskEntry };

/**
 * The definition document, as the editor holds it.
 *
 * Deliberately loose where the sidecar is the authority: `params` is a bag of
 * whatever the field catalogue declares, and pinning its shape here would be a
 * second catalogue that drifts. The parts the EDITOR manipulates directly —
 * trials, stages, the selection mode — are typed, because the trial-table
 * editor builds them by hand and a typo there is a silently wrong task.
 *
 * The wire carries this as `ANY` for the same reason `hardware.preview` does:
 * the checks that matter run over the document as a whole (a reward line
 * serving the other well; two types on one onset code), and a typed patch
 * would make the sidecar reconstruct the thing it was about to check.
 */
export interface TrialTypeDef {
  /** A channel NAME, resolved against the rig's wiring — never a pin. */
  odorChannel: string;
  /** A vocabulary code NAME. Never derived from an odor index: the onsets run
   *  101-109 and then 114-116, because 110-113 are retired. */
  onsetStrobe: string;
  isGo: boolean;
  /** null on a no-go type only, where withholding is the correct answer. */
  responseChannel: string | null;
  rewardChannel: string | null;
  /** Pool and weighted modes. Ignored under plain anti-bias selection, which
   *  weights nothing; under weighted selection it is this type's share WITHIN
   *  its side. */
  weight: number;
  /** The operator's own words. Never generated from the channels — a derived
   *  label would overwrite what they typed on every edit. */
  label: string;
  /** Solenoid open time on a correct answer, ms — the reward volume. On the
   *  row, like `weight`, because it is a property of the condition: two types
   *  paying from one fluid line may pay differently. Compiled into the
   *  firmware's `TrialType` as the default and sent as `RW<slot+1>`, so the
   *  mapping step can override it per box. Meaningless on a no-go row. */
  rewardTime: number;
}

export interface StageRow {
  trials: number;
  odorPokeHold: number;
  fluidWellHold: number;
  fluidWellPoll: number;
  odorPortTimeout: number;
}

export type SelectionMode = "antibias" | "pool" | "weighted";

export interface TaskDefinition {
  id: string;
  name: string;
  category: string;
  selectionMode: SelectionMode;
  trials: TrialTypeDef[];
  /** Always at least one row. An empty ramp is not "no ramp" — it is a task
   *  with no holds at all, which the firmware cannot express. */
  stages: StageRow[];
  /** `metadataKey → value`, and only where it diverges from the catalogue. */
  params: Record<string, unknown>;
  legacyNames: string[];
  notes: string;
}

/** A trial type that presents nothing yet — the row an "Add" button creates. */
export function blankTrial(): TrialTypeDef {
  return {
    odorChannel: "",
    onsetStrobe: "",
    isGo: true,
    responseChannel: null,
    rewardChannel: null,
    weight: 1,
    label: "",
    rewardTime: 100,
  };
}

/**
 * A ramp row seeded from the one before it.
 *
 * NEVER FROM A DEFAULTS TABLE. A new stage that appeared with numbers nobody
 * chose is the same failure as a generated value: it looks deliberate. Copying
 * the previous row means the operator sees the schedule they have and edits the
 * one thing they meant to change, and `trials` is bumped so the new row is at
 * least legal (`liveStage()` scans down, so a non-ascending row never engages).
 */
export function nextStage(previous: StageRow | undefined): StageRow {
  if (!previous) {
    return {
      trials: 0,
      odorPokeHold: 500,
      fluidWellHold: 200,
      fluidWellPoll: 2000,
      odorPortTimeout: 4000,
    };
  }
  return { ...previous, trials: previous.trials + 20 };
}

/** Diagnostics that name this location or anything beneath it. */
export function diagnosticsAt(
  diagnostics: TaskDiagnostic[],
  prefix: string,
): TaskDiagnostic[] {
  return diagnostics.filter(
    (d) => d.location === prefix || d.location.startsWith(`${prefix}.`),
  );
}

/**
 * What this rig calls a channel.
 *
 * THE ONLY PLACE AN ODOR GETS A NAME. `odor_line_1` is sandalwood on one bench
 * and orange on the next, so the substance belongs to the WIRING, not to the
 * task and certainly not to a constant in the app. An operator sets it on the
 * Rig tab and every trial-type row reads it back.
 *
 * Falls back to the prettified channel name, which is also what a fresh rig
 * document seeds the label with — so a rig that has never been edited reads
 * "odor line 1" rather than going blank.
 */
export function channelLabel(rig: RigDocument | null, name: string): string {
  const label = rig?.channels?.[name]?.label?.trim();
  return label || name.replace(/_/g, " ");
}
