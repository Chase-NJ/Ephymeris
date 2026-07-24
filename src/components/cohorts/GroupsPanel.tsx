import { ChevronDown, ChevronUp, Minus, Plus, Wand2 } from "lucide-react";
import { useState } from "react";

import { Button, Select, TextInput } from "@/components/common/controls";
import { AutoBalancePanel } from "@/components/cohorts/AutoBalancePanel";
import { MAX_BOX, MAX_GROUP_SIZE, MIN_BOX, type Animal, type Group } from "@/lib/cohorts/types";

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
 */

let localSeq = 0;
function newGroupId(): string {
  localSeq += 1;
  return `newgroup-${Date.now().toString(36)}-${localSeq}`;
}

const BOX_NUMBERS = Array.from({ length: MAX_BOX - MIN_BOX + 1 }, (_, i) => MIN_BOX + i);

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
  const [autoBalanceOpen, setAutoBalanceOpen] = useState(false);
  const ordered = [...groups].sort((a, b) => a.order - b.order);
  const multiGroup = ordered.length > 1;

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

  return (
    <div className="px-4 py-3.5">
      <div>
        <Button variant="ghost" onClick={() => setAutoBalanceOpen((v) => !v)}>
          <Wand2 size={13} strokeWidth={1.75} />
          {autoBalanceOpen ? "Hide suggested grouping" : "Suggest a grouping…"}
        </Button>
        {autoBalanceOpen && (
          <div className="mt-2 rounded-sm border border-halo bg-void/40">
            <AutoBalancePanel
              animals={animals}
              onApply={(nextGroups, nextAnimals) => {
                onChange(nextGroups, nextAnimals);
                setAutoBalanceOpen(false);
              }}
            />
          </div>
        )}
      </div>

      <div className="mt-3 flex flex-col gap-3">
        {ordered.map((group, index) => {
          const members = animals.filter((a) => a.groupId === group.id);
          const overCapacity = members.length > MAX_GROUP_SIZE;
          const columns = multiGroup ? "grid-cols-[1fr_88px_1fr]" : "grid-cols-[1fr_88px]";

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
                {multiGroup && (
                  <span className="ml-auto flex gap-1">
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
                  </span>
                )}
              </div>

              {overCapacity && (
                <p className="mt-1.5 text-[11px]" style={{ color: "var(--color-status-warning)" }}>
                  {members.length} animals in this group — box numbers only span{" "}
                  {MIN_BOX}–{MAX_BOX}, so at most {MAX_GROUP_SIZE} can be uniquely assigned.
                </p>
              )}

              {members.length === 0 ? (
                <p className="mt-2 text-[11px] leading-relaxed text-static/70">
                  No animals in this group yet — move some in below, or add
                  animals in the Animals section above.
                </p>
              ) : (
                <div className="mt-2 flex flex-col gap-1">
                  {members.map((animal) => {
                    // A box already taken by someone else in *this* group is
                    // simply not offered — prevention rather than a save-time
                    // error. The same box is fine across different groups.
                    const takenByOthers = new Set(
                      members
                        .filter((m) => m.id !== animal.id && m.boxNumber !== null)
                        .map((m) => m.boxNumber),
                    );
                    const boxOptions = [
                      { value: "", label: "—" },
                      ...BOX_NUMBERS.filter((n) => !takenByOthers.has(n)).map((n) => ({
                        value: String(n),
                        label: String(n),
                      })),
                    ];

                    return (
                      <div
                        key={animal.id}
                        className={`grid ${columns} items-center gap-x-2`}
                      >
                        <span className="truncate text-[12px] text-starlight">
                          {animal.name || "Unnamed animal"}
                        </span>
                        <Select
                          label={`Box for ${animal.name || "this animal"}`}
                          value={animal.boxNumber === null ? "" : String(animal.boxNumber)}
                          options={boxOptions}
                          onChange={(v) =>
                            setBox(animal.id, v === "" ? null : Number(v))
                          }
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
                    );
                  })}
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
