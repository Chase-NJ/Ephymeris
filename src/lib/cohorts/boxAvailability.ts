/**
 * Which boxes a cohort can actually be assigned to on *this* machine.
 *
 * The stored `boxNumber` stays what `DATA.md#validation` says it is — an abstract
 * slot 1–6, validated against that range and nothing else, so a cohort written
 * on one lab machine still loads and saves on the other with different
 * bindings. What this module adds is a *machine-local* opinion layered on top:
 * the editor should only ever **offer** a box the rig in front of you has, and
 * should say something when a stored assignment can no longer be honoured.
 *
 * Those two halves must stay separate. Narrowing the stored range would make a
 * cohort un-editable on the machine with fewer boxes bound; widening what's
 * offered is how you get an animal assigned to a box that doesn't exist and
 * find out halfway down the flash sequence.
 *
 * Three tiers, and the deliberate choice between them:
 *
 * * **available** — bound in settings *and* its board is currently detected.
 * * **disconnected** — bound, but nothing is answering for it right now.
 * * **unbound** — no board is configured for that number at all.
 *
 * The dropdown is gated on *bound*, not on *detected*. Bindings are shell-owned
 * settings that load from disk with no sidecar involved, so the editor keeps
 * working with the backend down and the rig unplugged — configuring a cohort at
 * a desk is a real workflow. Detection only ever downgrades a label and raises
 * a warning; it never removes an option, because a box blinking out as USB
 * re-enumerates must not pull the control out from under a click.
 */

import { useMemo } from "react";

import { useBoardPresence } from "@/lib/hardware/context";
import { useBoundBoxes } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import type { Animal, Group } from "./types";

export type BoxAvailability = "available" | "disconnected" | "unbound";

export interface BoxOffer {
  box: number;
  availability: BoxAvailability;
  /** What a selector shows: a bare number, or one carrying its caveat. */
  label: string;
}

export interface BoxAvailabilityView {
  /** Bound boxes in ascending order — everything a selector may offer. */
  offers: BoxOffer[];
  statusOf: (box: number) => BoxAvailability;
  /**
   * Whether detection can be trusted. False with the sidecar down, where every
   * board looks absent — reporting that as "disconnected" would be inventing a
   * fault out of our own blindness.
   */
  known: boolean;
}

/** How an unavailable box explains itself, wherever it's named. */
export const AVAILABILITY_NOTE: Record<BoxAvailability, string> = {
  available: "",
  disconnected: "not connected",
  unbound: "not set up",
};

export function boxLabel(box: number, availability: BoxAvailability): string {
  const note = AVAILABILITY_NOTE[availability];
  return note ? `Box ${box} · ${note}` : `Box ${box}`;
}

export function useBoxAvailability(): BoxAvailabilityView {
  const bound = useBoundBoxes();
  const boards = useBoardPresence();
  const { status } = useSidecar();
  const known = status === "connected";

  return useMemo(() => {
    const boundSet = new Set(bound);
    // `boxId` is resolved sidecar-side against the pushed bindings, so this is
    // already "bound *and* plugged in" rather than two facts to join here.
    const detected = new Set(
      boards.map((b) => b.boxId).filter((id): id is number => id !== null),
    );

    const statusOf = (box: number): BoxAvailability => {
      if (!boundSet.has(box)) return "unbound";
      // Unknown detection reads as available: the box is configured, and that
      // is the most we can honestly claim while the backend is away.
      if (!known || detected.has(box)) return "available";
      return "disconnected";
    };

    const offers: BoxOffer[] = [...bound]
      .sort((a, b) => a - b)
      .map((box) => {
        const availability = statusOf(box);
        return { box, availability, label: boxLabel(box, availability) };
      });

    return { offers, statusOf, known };
  }, [bound, boards, known]);
}

export interface AssignmentProblem {
  animalId: string;
  animalName: string;
  groupName: string;
  box: number;
  availability: Exclude<BoxAvailability, "available">;
}

/**
 * Every animal whose stored box can't currently be honoured — the input to
 * both the editor's banner and the browser grid's badge.
 *
 * Pure and sorted by box so the two surfaces can never disagree about what's
 * wrong or in what order. Returns an empty list rather than null for "nothing
 * to say", so callers just check `.length`.
 */
export function assignmentProblems(
  animals: Animal[],
  groups: Group[],
  statusOf: (box: number) => BoxAvailability,
): AssignmentProblem[] {
  const groupNames = new Map(groups.map((g) => [g.id, g.name]));
  const problems: AssignmentProblem[] = [];

  for (const animal of animals) {
    if (animal.boxNumber === null) continue;
    const availability = statusOf(animal.boxNumber);
    if (availability === "available") continue;
    problems.push({
      animalId: animal.id,
      animalName: animal.name.trim() || "Unnamed animal",
      groupName: groupNames.get(animal.groupId) ?? "",
      box: animal.boxNumber,
      availability,
    });
  }

  return problems.sort((a, b) => a.box - b.box);
}

/**
 * One sentence naming what's wrong, for a banner headline.
 *
 * Split by cause rather than lumped together: "not set up" is fixed in Config
 * by binding a board, "not connected" usually by plugging one in, and telling
 * someone to do the wrong one of those wastes a trip to the rig.
 */
export function problemSummary(problems: AssignmentProblem[]): string {
  const unbound = problems.filter((p) => p.availability === "unbound");
  const offline = problems.filter((p) => p.availability === "disconnected");
  const parts: string[] = [];
  if (unbound.length > 0) {
    parts.push(
      `${boxList(unbound)} ${unbound.length === 1 ? "isn't" : "aren't"} set up on this machine`,
    );
  }
  if (offline.length > 0) {
    parts.push(
      `${boxList(offline)} ${offline.length === 1 ? "isn't" : "aren't"} connected right now`,
    );
  }
  return parts.join(", and ");
}

function boxList(problems: AssignmentProblem[]): string {
  const boxes = [...new Set(problems.map((p) => p.box))].sort((a, b) => a - b);
  if (boxes.length === 1) return `Box ${boxes[0]}`;
  return `Boxes ${boxes.slice(0, -1).join(", ")} and ${boxes[boxes.length - 1]}`;
}
