import { Eye, Hand, HeartPulse, Split, Wrench, type LucideIcon } from "lucide-react";

import type { NoteScope, NoteTag, SessionNote } from "@/lib/logbook/types";

/**
 * The note vocabulary (`DATA.md#notes`). Told apart by icon and word, never by
 * colour alone: the palette has no decorative hues to spend
 * (`ARCHITECTURE.md#theme`), and a tag is a kind, not a state.
 */
export const TAGS: ReadonlyArray<{
  value: NoteTag;
  label: string;
  short: string;
  icon: LucideIcon;
}> = [
  { value: "observation", label: "Observation", short: "Observation", icon: Eye },
  { value: "intervention", label: "Intervention", short: "Intervention", icon: Hand },
  { value: "hardware", label: "Hardware", short: "Hardware", icon: Wrench },
  { value: "animal-health", label: "Animal health", short: "Health", icon: HeartPulse },
  { value: "protocol-deviation", label: "Protocol deviation", short: "Deviation", icon: Split },
];

export function tagOf(tag: NoteTag) {
  return TAGS.find((t) => t.value === tag) ?? TAGS[0]!;
}

export interface RosterAnimal {
  id: string;
  name: string;
  box: number | null;
}

/** What a note is about, in words. */
export function scopeLabel(scope: NoteScope, names: Map<string, string>): string {
  if (scope.kind === "animal" && scope.animalId) return names.get(scope.animalId) ?? "unknown animal";
  if (scope.kind === "box" && scope.box !== null) return `Box ${scope.box}`;
  return "Session";
}

/** Notes in the order they happened, ties by when they were written. */
export function byMoment(a: SessionNote, b: SessionNote): number {
  return a.at.localeCompare(b.at) || a.createdAt.localeCompare(b.createdAt);
}
