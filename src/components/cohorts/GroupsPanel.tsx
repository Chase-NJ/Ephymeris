import { AnimatePresence, motion } from "framer-motion";
import {
  CircleAlert,
  Minus,
  Plus,
  Radio,
  Wand2,
} from "lucide-react";
import { useEffect, useMemo, useState, type DragEvent } from "react";
import { useNavigate } from "react-router";

import { Button, TextInput } from "@/components/common/controls";
import { AutoBalancePanel } from "@/components/cohorts/AutoBalancePanel";
import {
  useBoxAvailability,
  type BoxAvailability,
  type BoxOffer,
} from "@/lib/cohorts/boxAvailability";
import { MAX_BOX, MAX_GROUP_SIZE, MIN_BOX, type Animal, type Group } from "@/lib/cohorts/types";
import { springSnappy } from "@/lib/motion";

/**
 * Group management, membership, and box assignment —
 * `DATA.md#cohorts-animals-and-groups`.
 *
 * This is the *only* place box numbers get set. Box uniqueness is scoped per
 * group (`DATA.md#validation`: an animal can legitimately share a box number
 * with an animal in a different group, since groups run consecutively), so
 * assigning boxes only makes sense with a group's full membership visible at
 * once — which is exactly what each card below shows. `AnimalTable` stays pure
 * biographical data for that reason.
 *
 * ## Why this is a board and not a list of dropdowns
 *
 * It used to be one row per animal carrying two `<select>`s: one for the box,
 * one for the group. Both halves fought the task.
 *
 * Moving an animal between groups meant opening a dropdown *inside the group it
 * was leaving*, and the row then vanished from under the cursor and reappeared
 * in a different card further down the page — so filling a new group was N
 * round trips, each one losing your place. An empty group's own copy said "move
 * some in below" while offering nothing to do it with, because the control that
 * fills it lives in the *other* card. And assigning boxes was a column of
 * identical dropdowns, which is a spatial question answered one popup at a time.
 *
 * So membership and box assignment are now the same gesture as the cage panel
 * directly above (`CageAssignment`), which had the right model all along:
 * **chips you drag into the place they belong**, with click-to-carry as the
 * trackpad-friendly fallback. A group is a rack of box slots plus a bench for
 * members that don't have one yet; dragging between cards moves an animal
 * between groups, dragging onto a slot assigns the box, and the two panels on
 * this screen finally read as one interaction language rather than two.
 *
 * Always rendered, even for a cohort with only the implicit single group: box
 * assignment has to happen somewhere regardless of group count, so there is
 * always at least one card. A single group hides its rename/remove
 * chrome — that only appears once the user actually splits the cohort.
 *
 * **Boxes offered come from the rig, not from a constant.** The selector used
 * to list 1–6 unconditionally, which let an animal be assigned to a box the
 * machine had never had — discovered only when the session flash sequence hit
 * it. `boxAvailability.ts` owns that judgement now; see its header for why the
 * gate is "bound" rather than "currently detected".
 */

let localSeq = 0;
function newGroupId(): string {
  localSeq += 1;
  return `newgroup-${Date.now().toString(36)}-${localSeq}`;
}

/** Where a chip can land: a box slot in a group, or that group's bench. */
interface Target {
  groupId: string;
  /** null = the bench — in this group, no box yet. */
  box: number | null;
}

function targetKey(target: Target): string {
  return `${target.groupId}:${target.box ?? "bench"}`;
}

export function GroupsPanel({
  groups,
  animals,
  onChange,
}: {
  groups: Group[];
  animals: Animal[];
  /** Animals move too: removing a group has to rehome its members. */
  onChange: (groups: Group[], animals: Animal[]) => void;
}) {
  const navigate = useNavigate();
  const { offers, statusOf } = useBoxAvailability();
  const [autoBalanceOpen, setAutoBalanceOpen] = useState(false);
  /** Click-to-carry fallback: the chip picked up, awaiting a target click. */
  const [carried, setCarried] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);

  const ordered = useMemo(() => [...groups].sort((a, b) => a.order - b.order), [groups]);
  const multiGroup = ordered.length > 1;

  const usableBoxes = useMemo(
    () => offers.filter((o) => o.availability !== "unbound").map((o) => o.box),
    [offers],
  );

  /**
   * The one misconfiguration that actually bites: more animals in a single
   * group than the rig has boxes. It can't be resolved by assigning more
   * carefully — the cohort has to be split — so the panel says so up front
   * instead of leaving it to be discovered one empty slot at a time.
   */
  const needsSplit =
    !multiGroup && usableBoxes.length > 0 && animals.length > usableBoxes.length;
  const suggestedGroups = needsSplit
    ? Math.ceil(animals.length / usableBoxes.length)
    : 0;

  // Opening Auto-Balance for them is the point of noticing: the fix is a split,
  // and the panel that performs splits is one they'd otherwise have to know to
  // go looking for. Only ever opens it — never closes one they opened.
  useEffect(() => {
    if (needsSplit) setAutoBalanceOpen(true);
  }, [needsSplit]);

  // A carried chip that stops existing (its animal removed upstream) would
  // leave the panel in a pick-up state nothing can complete.
  useEffect(() => {
    if (carried !== null && !animals.some((a) => a.id === carried)) setCarried(null);
  }, [animals, carried]);

  function renumber(list: Group[]): Group[] {
    return list.map((g, index) => ({ ...g, order: index }));
  }

  function rename(id: string, name: string) {
    onChange(
      groups.map((g) => (g.id === id ? { ...g, name } : g)),
      animals,
    );
  }

  function addGroup() {
    const next = renumber([
      ...ordered,
      { id: newGroupId(), name: `Group ${ordered.length + 1}`, order: ordered.length },
    ]);
    onChange(next, animals);
  }

  function removeGroup(id: string) {
    if (ordered.length <= 1) return;
    const remaining = renumber(ordered.filter((g) => g.id !== id));
    const fallback = remaining[0]!;
    // Every animal belongs to exactly one group (`DATA.md#data-model`), so
    // orphans are rehomed into the first remaining group rather than left
    // dangling. They arrive without a box: the box that was theirs belonged to
    // the group that just went away, and silently carrying the number over
    // could collide with whoever already holds it in the group they land in.
    const rehomed = animals.map((a) =>
      a.groupId === id ? { ...a, groupId: fallback.id, boxNumber: null } : a,
    );
    onChange(remaining, rehomed);
  }

  /**
   * Put `animalId` in `target` — the one mutation every gesture in this panel
   * funnels through, whether it came from a drag or a click.
   *
   * Landing on an occupied slot **displaces** rather than refusing. Refusing is
   * the worse answer: the user has already said where they want this animal,
   * and a drop that silently does nothing reads as a broken control. Where the
   * occupant goes depends on where the incoming animal came from — a move
   * *within* one group is a true swap into the slot just vacated, while a move
   * *across* groups only bumps the occupant off its box, because dragging one
   * animal must never quietly move a second one into a different group.
   */
  function place(animalId: string, target: Target) {
    const moving = animals.find((a) => a.id === animalId);
    if (!moving) return;
    const fromGroup = moving.groupId;
    const fromBox = moving.boxNumber;

    let next = animals.map((a) =>
      a.id === animalId ? { ...a, groupId: target.groupId, boxNumber: target.box } : a,
    );

    if (target.box !== null) {
      const occupant = animals.find(
        (a) =>
          a.id !== animalId && a.groupId === target.groupId && a.boxNumber === target.box,
      );
      if (occupant) {
        const giveBack = fromGroup === target.groupId ? fromBox : null;
        next = next.map((a) => (a.id === occupant.id ? { ...a, boxNumber: giveBack } : a));
      }
    }

    onChange(groups, next);
    setCarried(null);
    setDragOver(null);
  }

  function dropHandlers(target: Target) {
    const key = targetKey(target);
    return {
      onDragOver: (event: DragEvent) => {
        // Required: without preventDefault the browser treats this element as
        // an invalid drop target and never fires `onDrop`.
        event.preventDefault();
        setDragOver(key);
      },
      onDragLeave: () => setDragOver((over) => (over === key ? null : over)),
      onDrop: (event: DragEvent) => {
        event.preventDefault();
        const id = event.dataTransfer.getData("text/plain");
        if (id) place(id, target);
      },
      onClick: () => {
        if (carried !== null) place(carried, target);
      },
    };
  }

  /**
   * Fill this group's benched animals with whatever slots are free, in roster
   * order. The common case is "six animals, six boxes, just put them
   * somewhere" — doing it by hand is six drags for a decision nobody actually
   * has a preference about.
   */
  function fillBoxes(groupId: string) {
    const members = animals.filter((a) => a.groupId === groupId);
    const taken = new Set(members.map((m) => m.boxNumber).filter((b) => b !== null));
    const free = usableBoxes.filter((b) => !taken.has(b));
    let next = 0;
    onChange(
      groups,
      animals.map((a) => {
        if (a.groupId !== groupId || a.boxNumber !== null) return a;
        const box = free[next];
        if (box === undefined) return a;
        next += 1;
        return { ...a, boxNumber: box };
      }),
    );
  }

  const carriedAnimal = carried === null ? null : animals.find((a) => a.id === carried) ?? null;

  return (
    <div className="px-4 py-3.5">
      {/* Nothing to assign to. Not an error — a cohort with no box assignments
          is legal and saves fine — but silently offering an empty rack would
          look like a bug rather than a rig that isn't set up yet. */}
      {offers.length === 0 && (
        <div className="mb-3 flex items-start justify-between gap-4 rounded-sm border border-halo px-3 py-2.5">
          <div className="min-w-0">
            <p className="text-[12px]" style={{ color: "var(--color-status-warning)" }}>
              No boxes are set up on this machine yet.
            </p>
            <p className="mt-0.5 text-[12px] leading-relaxed text-static">
              Box assignment needs at least one box bound to a board. You can
              still name animals and split them into groups now, and assign
              boxes once the rig is configured.
            </p>
          </div>
          <div className="shrink-0">
            <Button onClick={() => navigate("/config")}>
              <Radio size={13} strokeWidth={1.75} />
              Open Rig
            </Button>
          </div>
        </div>
      )}

      <AnimatePresence initial={false}>
        {needsSplit && (
          <motion.div
            key="needs-split"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={springSnappy}
            className="overflow-hidden"
          >
            <div className="mb-3 flex items-start gap-2 rounded-sm border border-halo px-3 py-2.5">
              <CircleAlert
                size={14}
                strokeWidth={1.75}
                className="mt-px shrink-0"
                style={{ color: "var(--color-status-warning)" }}
              />
              <div className="min-w-0">
                <p className="text-[12px]" style={{ color: "var(--color-status-warning)" }}>
                  {animals.length} animals, {usableBoxes.length}{" "}
                  {usableBoxes.length === 1 ? "box" : "boxes"} — they can't all run
                  at once.
                </p>
                <p className="mt-0.5 text-[12px] leading-relaxed text-static">
                  Split them into {suggestedGroups} groups that run one after the
                  other. Each group gets its own boxes, so the numbers repeat
                  between them.
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <p className="text-[12px] leading-relaxed text-static">
        {multiGroup
          ? "Groups run one after the other, so each one gets the whole rig and box numbers repeat between them. Drag an animal onto a box — or into another group — or click it, then its destination."
          : "Drag each animal onto the box it runs in, or click it, then the box. Split into groups if there are more animals than boxes; groups run one after the other."}
      </p>

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <Button onClick={addGroup}>
          <Plus size={13} strokeWidth={1.75} />
          {multiGroup ? "Add a group" : "Split into groups"}
        </Button>
        <Button variant="ghost" onClick={() => setAutoBalanceOpen((v) => !v)}>
          <Wand2 size={13} strokeWidth={1.75} />
          {autoBalanceOpen ? "Hide auto-balance" : "Auto-balance…"}
        </Button>
      </div>

      <AnimatePresence initial={false}>
        {autoBalanceOpen && (
          <motion.div
            key="auto-balance"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={springSnappy}
            className="overflow-hidden"
          >
            <div className="mt-2 rounded-sm border border-halo bg-void/40">
              <AutoBalancePanel
                animals={animals}
                {...(suggestedGroups > 0 ? { suggestedGroupCount: suggestedGroups } : {})}
                onApply={(nextGroups, nextAnimals) => {
                  onChange(nextGroups, nextAnimals);
                  setAutoBalanceOpen(false);
                }}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-3 flex flex-col gap-3">
        {ordered.map((group, index) => (
          <GroupCard
            key={group.id}
            group={group}
            index={index}
            total={ordered.length}
            multiGroup={multiGroup}
            members={animals.filter((a) => a.groupId === group.id)}
            usableBoxes={usableBoxes}
            offers={offers}
            statusOf={statusOf}
            carried={carried}
            dragOver={dragOver}
            onCarry={(id) => setCarried((c) => (c === id ? null : id))}
            dropHandlers={dropHandlers}
            onRename={(name) => rename(group.id, name)}
            onRemove={() => removeGroup(group.id)}
            onFillBoxes={() => fillBoxes(group.id)}
          />
        ))}
      </div>

      {/* The carried-chip banner. Sticky-feeling rather than a modal: the
          gesture is abandonable at any time, and saying so is what keeps
          click-to-carry from feeling like a mode you're trapped in. */}
      {carriedAnimal && (
        <p className="mt-2 text-[11px] text-static">
          Carrying <span className="font-mono text-starlight">{carriedAnimal.name || "unnamed"}</span> — click a
          box or a group to place it,{" "}
          <button
            type="button"
            onClick={() => setCarried(null)}
            className="underline decoration-dotted underline-offset-2 hover:text-starlight"
          >
            or put it down
          </button>
          .
        </p>
      )}
    </div>
  );
}

/**
 * One group: its name, its rack of box slots, and a bench for members
 * that don't hold a box yet.
 */
function GroupCard({
  group,
  index,
  total,
  multiGroup,
  members,
  usableBoxes,
  offers,
  statusOf,
  carried,
  dragOver,
  onCarry,
  dropHandlers,
  onRename,
  onRemove,
  onFillBoxes,
}: {
  group: Group;
  index: number;
  total: number;
  multiGroup: boolean;
  members: Animal[];
  usableBoxes: number[];
  offers: BoxOffer[];
  statusOf: (box: number) => BoxAvailability;
  carried: string | null;
  dragOver: string | null;
  onCarry: (id: string) => void;
  dropHandlers: (target: Target) => Record<string, unknown>;
  onRename: (name: string) => void;
  onRemove: () => void;
  onFillBoxes: () => void;
}) {
  const bench = members.filter((a) => a.boxNumber === null);
  const overCapacity = members.length > MAX_GROUP_SIZE;
  // Distinct from the hard cap: this group would fit in the protocol's six
  // slots but not on the boxes this rig actually has.
  const overRig =
    !overCapacity && usableBoxes.length > 0 && members.length > usableBoxes.length;

  /**
   * Which slots this rack draws. The rig's boxes, plus any box a member is
   * *already* holding that the rig no longer offers — dropping that slot would
   * hide a real assignment because a binding changed on this machine, which is
   * the data loss `boxAvailability`'s keep-and-warn rule exists to prevent.
   */
  const slots = useMemo(() => {
    const set = new Set(usableBoxes);
    for (const m of members) if (m.boxNumber !== null) set.add(m.boxNumber);
    return [...set].sort((a, b) => a - b);
  }, [usableBoxes, members]);

  const freeSlots = slots.filter((b) => !members.some((m) => m.boxNumber === b)).length;

  return (
    <div className="rounded-sm border border-halo bg-void/40 p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        {multiGroup ? (
          <TextInput
            label={`Name for ${group.name}`}
            value={group.name}
            placeholder={`Group ${index + 1}`}
            onChange={onRename}
            className="w-full max-w-[200px]"
          />
        ) : (
          <span className="text-[12px] font-medium text-starlight">{group.name}</span>
        )}
        <span className="font-mono text-[11px] text-static">
          {members.length} {members.length === 1 ? "animal" : "animals"}
          {bench.length > 0 && slots.length > 0 && (
            <span style={{ color: "var(--color-status-warning)" }}>
              {" "}
              · {bench.length} without a box
            </span>
          )}
        </span>

        <span className="ml-auto flex gap-1">
          {bench.length > 0 && freeSlots > 0 && (
            <Button
              onClick={onFillBoxes}
              title={`Give the ${bench.length} unassigned ${
                bench.length === 1 ? "animal" : "animals"
              } here the free boxes`}
            >
              Fill boxes
            </Button>
          )}
          {multiGroup && (
            <>
              <Button
                variant="outline"
                shape="icon"
                onClick={onRemove}
                disabled={total <= 1}
                title={`Remove ${group.name}`}
              >
                <Minus size={14} strokeWidth={2} />
              </Button>
            </>
          )}
        </span>
      </div>

      {overCapacity && (
        <p className="mt-1.5 text-[11px]" style={{ color: "var(--color-status-warning)" }}>
          {members.length} animals in this group — box numbers only span {MIN_BOX}–{MAX_BOX},
          so at most {MAX_GROUP_SIZE} can be uniquely assigned.
        </p>
      )}
      {overRig && (
        <p className="mt-1.5 text-[11px]" style={{ color: "var(--color-status-warning)" }}>
          {members.length} animals but only {usableBoxes.length}{" "}
          {usableBoxes.length === 1 ? "box" : "boxes"} on this machine —{" "}
          {members.length - usableBoxes.length} will run without one unless you split
          this group.
        </p>
      )}

      {slots.length > 0 && (
        <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-6">
          {slots.map((box) => {
            const holder = members.find((m) => m.boxNumber === box) ?? null;
            const status = statusOf(box);
            const offer = offers.find((o) => o.box === box);
            const target: Target = { groupId: group.id, box };
            const active = dragOver === targetKey(target);
            return (
              <div
                key={box}
                {...dropHandlers(target)}
                title={
                  status === "available"
                    ? `Box ${box}`
                    : offer?.label ?? `Box ${box} · not set up on this machine`
                }
                className="flex min-h-[58px] cursor-pointer flex-col gap-1 rounded-sm border px-2 py-1.5 transition-colors"
                style={{
                  borderColor: active ? "var(--color-pulsar)" : "var(--color-halo)",
                  background: active
                    ? "color-mix(in srgb, var(--color-pulsar) 10%, transparent)"
                    : "transparent",
                }}
              >
                <span
                  className="font-mono text-[10px] uppercase tracking-wider"
                  style={{
                    color:
                      status === "available"
                        ? "var(--color-static)"
                        : "var(--color-status-warning)",
                  }}
                >
                  Box {box}
                </span>
                {holder ? (
                  <MemberChip
                    animal={holder}
                    carried={carried === holder.id}
                    onCarry={() => onCarry(holder.id)}
                  />
                ) : (
                  <span className="text-[11px] text-static/50">empty</span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* The bench. Always a drop target, even when empty — it is how an animal
          gets its box taken away again, and how a member joins a group whose
          rack is full. */}
      {(() => {
        const target: Target = { groupId: group.id, box: null };
        const active = dragOver === targetKey(target);
        return (
          <div
            {...dropHandlers(target)}
            className="mt-1.5 cursor-pointer rounded-sm border border-dashed px-2.5 py-2 transition-colors"
            style={{
              borderColor: active ? "var(--color-pulsar)" : "var(--color-halo)",
            }}
          >
            <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-static/70">
              {slots.length === 0 ? "In this group" : "No box yet"}
            </div>
            <div className="flex min-h-[24px] flex-wrap items-center gap-1.5">
              {bench.length === 0 ? (
                <span className="text-[11px] text-static/50">
                  {members.length === 0
                    ? "Empty — drag an animal here."
                    : "Everyone here has a box."}
                </span>
              ) : (
                bench.map((animal) => (
                  <MemberChip
                    key={animal.id}
                    animal={animal}
                    carried={carried === animal.id}
                    onCarry={() => onCarry(animal.id)}
                  />
                ))
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
}

/**
 * One animal, as a draggable chip. `layout` animates the hop between slots and
 * groups on the app's spring rather than teleporting, which is what makes a
 * drag across cards read as the animal moving rather than two lists redrawing.
 */
function MemberChip({
  animal,
  carried,
  onCarry,
}: {
  animal: Animal;
  carried: boolean;
  onCarry: () => void;
}) {
  return (
    // A plain <button> carries the HTML5 drag: on a motion component,
    // `onDragStart` is framer's pan-gesture prop and the native event would
    // never be heard. The motion wrapper owns only the layout hop.
    // (Drag also requires `dragDropEnabled: false` in tauri.conf.json — see
    // `CageAssignment` for why.)
    <motion.span layout layoutId={`member-${animal.id}`} transition={springSnappy}>
      <button
        type="button"
        draggable
        onDragStart={(event) => event.dataTransfer.setData("text/plain", animal.id)}
        onClick={(event) => {
          // The slot underneath is a drop target that would otherwise read this
          // same click as "place the carried chip here".
          event.stopPropagation();
          onCarry();
        }}
        title={
          carried
            ? "Click a box or a group to place it"
            : "Drag to a box or another group, or click to pick up"
        }
        className="max-w-full cursor-grab truncate rounded-full border px-2 py-0.5 font-mono text-[11px] leading-tight transition-colors active:cursor-grabbing"
        style={{
          borderColor: carried ? "var(--color-pulsar)" : "var(--color-halo)",
          color: carried ? "var(--color-starlight)" : "var(--color-static)",
          background: carried
            ? "color-mix(in srgb, var(--color-pulsar) 18%, transparent)"
            : "var(--color-void)",
        }}
      >
        {animal.name || "unnamed"}
      </button>
    </motion.span>
  );
}
