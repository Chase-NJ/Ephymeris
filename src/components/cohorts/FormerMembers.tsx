import { ArrowRightLeft, Undo2 } from "lucide-react";

import { Button } from "@/components/common/controls";
import type { Animal, FormerAnimal, Group } from "@/lib/cohorts/types";

/**
 * Animals with history in this cohort that are no longer on its roster
 * (`DATA.md#former-members`).
 *
 * Two kinds, one list. A **removed** animal was taken off the roster and kept,
 * so its history still reads under its name. One **found in files** was removed
 * before former members were kept: nothing remembers it but the runs and notes
 * still carrying its id, and its name is read from those runs' file names.
 *
 * **Restore** puts the animal back on the roster under its own id, so its
 * history rejoins it on save. **Move history** sends the animal and everything
 * it ran to another cohort — what a split should have been.
 */
export function FormerMembers({
  former,
  animals,
  groups,
  defaultGroupId,
  onRestore,
  onMove,
}: {
  former: FormerAnimal[];
  /** The editor's roster as it stands, unsaved changes included. */
  animals: Animal[];
  groups: Group[];
  defaultGroupId: string;
  onRestore: (animal: Animal) => void;
  /** Absent hides the action — a new cohort, or one with unsaved changes. */
  onMove?: ((animal: FormerAnimal) => void) | undefined;
}) {
  // A restore waiting for Save is already in `animals`; listing it here too
  // would offer it twice.
  const onRoster = new Set(animals.map((a) => a.id));
  const takenNames = new Map(animals.map((a) => [a.name.trim().toLocaleLowerCase(), a.name]));
  const rows = former.filter((f) => !onRoster.has(f.id));
  if (rows.length === 0) return null;

  function restore(f: FormerAnimal) {
    const group = groups.find((g) => g.name === f.groupName);
    onRestore({
      id: f.id,
      name: f.name ?? "",
      groupId: group?.id ?? defaultGroupId,
      // Its old box may be someone else's now; the operator places it again.
      boxNumber: null,
      cage: f.cage,
      sex: f.sex,
      idNumber: f.idNumber,
      notes: f.notes,
    });
  }

  return (
    <div className="px-4 py-3.5">
      <p className="mb-2.5 text-[12px] leading-relaxed text-static">
        Off the roster, with sessions still in this cohort's history — shown under these names in
        Analytics and the Log.
      </p>
      <div className="flex flex-col divide-y divide-halo/60">
        {rows.map((f) => {
          const clash = f.name ? takenNames.get(f.name.trim().toLocaleLowerCase()) : undefined;
          return (
            <div key={f.id} className="flex items-center gap-3 py-2">
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] text-starlight">
                  {f.name ?? <span className="text-static">Unnamed · {f.id.slice(0, 6)}</span>}
                </div>
                <div className="font-mono text-[10.5px] text-static">
                  {f.source === "removed"
                    ? `removed ${f.removedAt?.slice(0, 10) ?? ""}`
                    : "found in files"}
                  {" · "}
                  {f.runCount} run{f.runCount === 1 ? "" : "s"}
                  {clash && ` · “${clash}” is on the roster`}
                </div>
              </div>
              <Button
                variant="ghost"
                onClick={() => restore(f)}
                disabled={f.name === null || clash !== undefined}
                title={
                  clash !== undefined
                    ? `An animal called “${clash}” is already on the roster`
                    : f.name === null
                      ? "Its files don't name it, so it can't be put back by name"
                      : `Put ${f.name} back on the roster with its history`
                }
              >
                <Undo2 size={13} strokeWidth={1.75} />
                Restore
              </Button>
              {onMove && (
                <Button
                  variant="ghost"
                  onClick={() => onMove(f)}
                  title={`Move ${f.name ?? "this animal"}'s sessions and files to another cohort`}
                >
                  <ArrowRightLeft size={13} strokeWidth={1.75} />
                  Move history…
                </Button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
