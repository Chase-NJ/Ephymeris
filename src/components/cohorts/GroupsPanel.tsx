import { AnimatePresence, motion } from "framer-motion";
import {
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Minus,
  Plus,
  Radio,
  Wand2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { Button, Select, TextInput } from "@/components/common/controls";
import { AutoBalancePanel } from "@/components/cohorts/AutoBalancePanel";
import {
  useBoxAvailability,
  type BoxAvailability,
  type BoxOffer,
} from "@/lib/cohorts/boxAvailability";
import { MAX_BOX, MAX_GROUP_SIZE, MIN_BOX, type Animal, type Group } from "@/lib/cohorts/types";
import { springSnappy } from "@/lib/motion";

/**
 * Group management, membership, and box assignment — `cohorts.md` §6, §7.
 *
 * This is the *only* place box numbers get set. Box uniqueness is scoped per
 * group (§2, an animal can legitimately share a box number with an animal in
 * a different group, since groups run consecutively), so assigning boxes only
 * makes sense with a group's full membership visible at once — which is
 * exactly what each card below shows. `AnimalTable` stays pure biographical
 * data for that reason.
 *
 * Always rendered, even for a cohort with only the implicit single group:
 * box assignment has to happen somewhere regardless of group count, so there
 * is always at least one card. A single group renders as a quiet, unlabeled
 * card rather than exposing rename/reorder/remove chrome nobody needs yet —
 * that chrome (and the second+ card) only appears once the user actually
 * splits the cohort.
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
   * instead of leaving it to be discovered one empty dropdown at a time.
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

  function renumber(list: Group[]): Group[] {
    return list.map((g, index) => ({ ...g, order: index }));
  }

  function rename(id: string, name: string) {
    onChange(
      groups.map((g) => (g.id === id ? { ...g, name } : g)),
      animals,
    );
  }

  function move(id: string, delta: number) {
    const index = ordered.findIndex((g) => g.id === id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= ordered.length) return;
    const next = [...ordered];
    const [moved] = next.splice(index, 1);
    next.splice(target, 0, moved!);
    onChange(renumber(next), animals);
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
    // Every animal belongs to exactly one group (§1), so orphans are rehomed
    // into the first remaining group rather than left dangling.
    const rehomed = animals.map((a) =>
      a.groupId === id ? { ...a, groupId: fallback.id } : a,
    );
    onChange(remaining, rehomed);
  }

  function moveAnimal(animalId: string, groupId: string) {
    onChange(
      groups,
      animals.map((a) => (a.id === animalId ? { ...a, groupId } : a)),
    );
  }

  function setBox(animalId: string, box: number | null) {
    onChange(
      groups,
      animals.map((a) => (a.id === animalId ? { ...a, boxNumber: box } : a)),
    );
  }

  /**
   * Fill this group's unassigned animals with whatever boxes are free, in
   * roster order. The common case is "eight animals, six boxes, just put them
   * somewhere" — doing it by hand is eight dropdowns for a decision nobody
   * actually has a preference about.
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

  return (
    <div className="px-4 py-3.5">
      {/* Nothing to assign to. Not an error — a cohort with no box assignments
          is legal and saves fine — but silently offering an empty dropdown
          would look like a bug rather than a rig that isn't set up yet. */}
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
              Open Config
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

      <div>
        <Button variant="ghost" onClick={() => setAutoBalanceOpen((v) => !v)}>
          <Wand2 size={13} strokeWidth={1.75} />
          {autoBalanceOpen ? "Hide suggested grouping" : "Suggest a grouping…"}
        </Button>
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
      </div>

      <div className="mt-3 flex flex-col gap-3">
        {ordered.map((group, index) => {
          const members = animals.filter((a) => a.groupId === group.id);
          const overCapacity = members.length > MAX_GROUP_SIZE;
          // Distinct from the hard cap: this group would fit in the protocol's
          // six slots but not on the boxes this rig actually has.
          const overRig =
            !overCapacity && usableBoxes.length > 0 && members.length > usableBoxes.length;
          const unassigned = members.filter((a) => a.boxNumber === null).length;
          const freeBoxes = usableBoxes.filter(
            (b) => !members.some((m) => m.boxNumber === b),
          ).length;
          const columns = multiGroup ? "grid-cols-[1fr_170px_1fr]" : "grid-cols-[1fr_170px]";

          return (
            <div key={group.id} className="rounded-sm border border-halo bg-void/40 p-3">
              <div className="flex items-center gap-x-2">
                {multiGroup ? (
                  <TextInput
                    label={`Name for ${group.name}`}
                    value={group.name}
                    placeholder={`Group ${index + 1}`}
                    onChange={(name) => rename(group.id, name)}
                    className="w-full max-w-[220px]"
                  />
                ) : (
                  <span className="text-[12px] font-medium text-starlight">{group.name}</span>
                )}
                <span className="font-mono text-[11px] text-static">
                  {members.length} {members.length === 1 ? "animal" : "animals"}
                </span>

                <span className="ml-auto flex gap-1">
                  {unassigned > 0 && freeBoxes > 0 && (
                    <Button
                      onClick={() => fillBoxes(group.id)}
                      title={`Give the ${unassigned} unassigned ${
                        unassigned === 1 ? "animal" : "animals"
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
                        onClick={() => move(group.id, -1)}
                        disabled={index === 0}
                        title={`Move ${group.name} earlier`}
                      >
                        <ChevronUp size={14} strokeWidth={2} />
                      </Button>
                      <Button
                        variant="outline"
                        shape="icon"
                        onClick={() => move(group.id, 1)}
                        disabled={index === ordered.length - 1}
                        title={`Move ${group.name} later`}
                      >
                        <ChevronDown size={14} strokeWidth={2} />
                      </Button>
                      <Button
                        variant="outline"
                        shape="icon"
                        onClick={() => removeGroup(group.id)}
                        disabled={ordered.length <= 1}
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
                  {members.length} animals in this group — box numbers only span{" "}
                  {MIN_BOX}–{MAX_BOX}, so at most {MAX_GROUP_SIZE} can be uniquely assigned.
                </p>
              )}
              {overRig && (
                <p className="mt-1.5 text-[11px]" style={{ color: "var(--color-status-warning)" }}>
                  {members.length} animals but only {usableBoxes.length}{" "}
                  {usableBoxes.length === 1 ? "box" : "boxes"} on this machine —{" "}
                  {members.length - usableBoxes.length} will run without one unless you
                  split this group.
                </p>
              )}

              {members.length === 0 ? (
                <p className="mt-2 text-[11px] leading-relaxed text-static/70">
                  No animals in this group yet — move some in below, or add
                  animals in the Animals section above.
                </p>
              ) : (
                <div className="mt-2 flex flex-col gap-1">
                  {members.map((animal) => (
                    <div
                      key={animal.id}
                      className={`grid ${columns} items-center gap-x-2`}
                    >
                      <span className="truncate text-[12px] text-starlight">
                        {animal.name || "Unnamed animal"}
                      </span>
                      <BoxSelect
                        animal={animal}
                        members={members}
                        offers={offers}
                        statusOf={statusOf}
                        onChange={(box) => setBox(animal.id, box)}
                      />
                      {multiGroup && (
                        <Select
                          label={`Move ${animal.name || "this animal"} to a different group`}
                          value={group.id}
                          options={ordered.map((g) => ({ value: g.id, label: g.name }))}
                          onChange={(groupId) => moveAnimal(animal.id, String(groupId))}
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {multiGroup && (
        <p className="mt-2 text-[11px] leading-relaxed text-static">
          Groups run consecutively, so box numbers may repeat between them.
        </p>
      )}

      <div className="mt-3">
        <Button onClick={addGroup}>
          <Plus size={13} strokeWidth={1.75} />
          {multiGroup ? "Add group" : "Split into groups"}
        </Button>
      </div>
    </div>
  );
}

/**
 * One animal's box selector.
 *
 * Two rules meet here. A box already taken by someone else in *this* group is
 * simply not offered — prevention rather than a save-time error, and the same
 * box stays fine in a different group. And a box this machine can't offer is
 * still shown *if this animal already holds it*: dropping it silently would
 * erase a real assignment because a USB hub was unplugged, which is exactly
 * the data loss the keep-and-warn rule exists to prevent.
 */
function BoxSelect({
  animal,
  members,
  offers,
  statusOf,
  onChange,
}: {
  animal: Animal;
  members: Animal[];
  offers: BoxOffer[];
  statusOf: (box: number) => BoxAvailability;
  onChange: (box: number | null) => void;
}) {
  const takenByOthers = new Set(
    members.filter((m) => m.id !== animal.id && m.boxNumber !== null).map((m) => m.boxNumber),
  );

  const options = [
    { value: "", label: "—" },
    ...offers
      .filter((o) => !takenByOthers.has(o.box))
      .map((o) => ({ value: String(o.box), label: o.label })),
  ];

  // The animal's own stored box, when the rig no longer offers it.
  const held = animal.boxNumber;
  const heldStatus = held === null ? "available" : statusOf(held);
  if (held !== null && !options.some((o) => o.value === String(held))) {
    options.push({
      value: String(held),
      label: heldStatus === "unbound" ? `Box ${held} · not set up` : `Box ${held} · not connected`,
    });
  }

  return (
    <Select
      label={`Box for ${animal.name || "this animal"}`}
      value={held === null ? "" : String(held)}
      options={options}
      tone={heldStatus === "available" ? "normal" : "warning"}
      onChange={(v) => onChange(v === "" ? null : Number(v))}
      className="w-full"
    />
  );
}
