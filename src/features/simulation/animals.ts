/**
 * The simulated animals the Simulate view offers (`TASKS.md#the-simulated-animal`).
 *
 * The sidecar owns what an animal *does*; this file only names starting points
 * and says how each setting is shown. A preset is a whole animal, so picking
 * one leaves nothing of the last.
 */
import type { SimulatedAnimal } from "@/lib/ws/protocol";

export type Animal = Required<SimulatedAnimal>;
export type Fallback = Animal["fallback"];

export const TRAINED: Animal = {
  followsOdor: 0.9,
  followsOdorEnd: 0.9,
  learningTrials: 0,
  fallback: "side",
  sideBias: 0,
  initiates: 0.97,
  satiatesAfter: 0,
  answers: 0.98,
  leavesEarly: 0.03,
  dropsHold: 0.03,
  holdMs: 2500,
  reactionMs: 600,
};

export interface AnimalPreset {
  id: string;
  label: string;
  /** What it stands for, under the chips. */
  blurb: string;
  animal: Animal;
  /** It ignores the odor, so what it earns is what the task gives away. */
  exploit: boolean;
}

function preset(id: string, label: string, blurb: string, edits: Partial<Animal>, exploit = false): AnimalPreset {
  return { id, label, blurb, animal: { ...TRAINED, ...edits }, exploit };
}

const GUESSING = { followsOdor: 0, followsOdorEnd: 0 } as const;

/** What every other animal is measured against. */
export const TRAINED_PRESET = preset("trained", "Trained", "Answers by the odor nine times in ten.", {});

export const PRESETS: readonly AnimalPreset[] = [
  TRAINED_PRESET,
  preset("learner", "Learner", "Starts at chance and learns over 150 trials.", {
    followsOdor: 0,
    followsOdorEnd: 0.9,
    learningTrials: 150,
  }),
  preset("naive", "Naive", "Picks a well at random.", GUESSING, true),
  preset("side", "Side-biased", "Goes right nine times in ten, whatever the odor.", { ...GUESSING, sideBias: 0.8 }, true),
  preset("winstay", "Win-stay", "Returns to the well that paid, leaves the one that did not.", { ...GUESSING, fallback: "winStay" }, true),
  preset("alternate", "Alternator", "Left, right, left, right.", { ...GUESSING, fallback: "alternate" }, true),
  preset("impulsive", "Impulsive", "Often pulls out of the port and the well early.", { leavesEarly: 0.3, dropsHold: 0.25, holdMs: 1200 }),
  preset("sated", "Satiating", "Slows after 60 rewards and stops by 90.", { satiatesAfter: 60 }),
  preset("disengaged", "Disengaged", "Starts fewer than half its trials.", { initiates: 0.45, answers: 0.8 }),
];

export function presetOf(animal: Animal): AnimalPreset | null {
  return PRESETS.find((p) => sameAnimal(p.animal, animal)) ?? null;
}

export function sameAnimal(a: Animal, b: Animal): boolean {
  return (Object.keys(a) as (keyof Animal)[]).every((key) => a[key] === b[key]);
}

export const FALLBACKS: ReadonlyArray<{ value: Fallback; label: string }> = [
  { value: "side", label: "A side" },
  { value: "winStay", label: "Win-stay" },
  { value: "alternate", label: "Alternate" },
  { value: "repeat", label: "Repeat" },
];

export type AnimalNumberKey = Exclude<keyof Animal, "fallback">;

export interface AnimalField {
  key: AnimalNumberKey;
  label: string;
  group: "Strategy" | "Engagement" | "Impulsivity and speed";
  min: number;
  max: number;
  step: number;
  show: (value: number) => string;
  help: string;
}

const share = (value: number) => `${Math.round(value * 100)}%`;
const seconds = (value: number) => `${(value / 1000).toFixed(1)} s`;

export const ANIMAL_FIELDS: readonly AnimalField[] = [
  {
    key: "followsOdorEnd", label: "Follows the odor", group: "Strategy", min: 0, max: 1, step: 0.05, show: share,
    help: "How often it answers by the odor once it knows the task.",
  },
  {
    key: "learningTrials", label: "Learns over", group: "Strategy", min: 0, max: 500, step: 10,
    show: (v) => (v === 0 ? "knows it" : `${v} trials`),
    help: "Sampled trials it takes to get there from chance. 0: it already knows.",
  },
  {
    key: "sideBias", label: "Side bias", group: "Strategy", min: -1, max: 1, step: 0.1,
    show: (v) => (v === 0 ? "none" : `${v < 0 ? "L" : "R"} ${Math.round(Math.abs(v) * 100)}`),
    help: "Which well it favours when it is not answering by the odor.",
  },
  {
    key: "initiates", label: "Starts trials", group: "Engagement", min: 0, max: 1, step: 0.05, show: share,
    help: "How often it pokes the odor port when the light comes on.",
  },
  {
    key: "answers", label: "Answers", group: "Engagement", min: 0, max: 1, step: 0.05, show: share,
    help: "How often it goes to a well once it has sampled.",
  },
  {
    key: "satiatesAfter", label: "Sates after", group: "Engagement", min: 0, max: 400, step: 10,
    show: (v) => (v === 0 ? "never" : `${v} rewards`),
    help: "Rewards after which it starts to stop; it has stopped at one and a half times this.",
  },
  {
    key: "leavesEarly", label: "Leaves port early", group: "Impulsivity and speed", min: 0, max: 1, step: 0.05, show: share,
    help: "How often it pulls out of the odor port on impulse.",
  },
  {
    key: "dropsHold", label: "Leaves well early", group: "Impulsivity and speed", min: 0, max: 1, step: 0.05, show: share,
    help: "How often it leaves a well before water could come.",
  },
  {
    key: "holdMs", label: "Can hold for", group: "Impulsivity and speed", min: 200, max: 8000, step: 100, show: seconds,
    help: "About how long it can hold a poke. A task that asks for more fails it.",
  },
  {
    key: "reactionMs", label: "Reaction time", group: "Impulsivity and speed", min: 100, max: 4000, step: 50, show: seconds,
    help: "About how long it takes to reach the port or a well.",
  },
];

/** `animal` with one setting moved. An animal that is not learning starts where it ends. */
export function withSetting(animal: Animal, key: AnimalNumberKey, value: number): Animal {
  const next = { ...animal, [key]: value };
  if (next.learningTrials === 0) next.followsOdor = next.followsOdorEnd;
  else if (key === "learningTrials" && animal.learningTrials === 0) next.followsOdor = 0;
  return next;
}
