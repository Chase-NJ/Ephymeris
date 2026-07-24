import { CircleAlert, Wand2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Button, Select, TextInput, Toggle } from "@/components/common/controls";
import { suggestGroupsLocal } from "@/lib/cohorts/grouping";
import { useBoardPresence } from "@/lib/hardware/context";
import { MAX_GROUP_SIZE, type Animal, type Group, type GroupProposal } from "@/lib/cohorts/types";

/**
 * Auto-Balance — `cohorts.md` §7.
 *
 * A **suggestion the user reviews**, never a silent bulk mutation. Computed
 * entirely client-side (`lib/cohorts/grouping.ts`, mirroring the sidecar's
 * `grouping.py`) against whatever roster is currently in the editor — so this
 * works identically whether the cohort has been saved yet or not, rather than
 * needing a real `cohortId` to round-trip through the sidecar. This renders
 * the proposal as a preview; Apply hands it to the caller, which folds it into
 * local state the same way any other edit here does (§7.4) — there's no
 * separate write route to reason about.
 *
 * Always a full re-proposal from the complete roster; it never merges with
 * whatever grouping already exists.
 */

let localSeq = 0;
function newGroupId(): string {
  localSeq += 1;
  return `balanced-${Date.now().toString(36)}-${localSeq}`;
}

type Mode = "count" | "size";

export function AutoBalancePanel({
  animals,
  onApply,
}: {
  animals: Animal[];
  onApply: (groups: Group[], animals: Animal[]) => void;
}) {
  const boards = useBoardPresence();

  const [mode, setMode] = useState<Mode>("count");
  // §7.1 — a courtesy default from live hardware, editable and never enforced;
  // cohort configuration stays decoupled from what's plugged in (§2).
  const suggestedSize = boards.length > 0 ? Math.min(boards.length, MAX_GROUP_SIZE) : 3;
  const [groupCount, setGroupCount] = useState("2");
  const [maxSize, setMaxSize] = useState(String(suggestedSize));
  const [balanceBySex, setBalanceBySex] = useState(false);
  const [proposal, setProposal] = useState<GroupProposal | null>(null);

  // §7.1 — the checkbox is only meaningful when there's sex data to balance.
  const canBalanceBySex = useMemo(
    () => animals.some((a) => a.sex === "M" || a.sex === "F"),
    [animals],
  );

  const byId = useMemo(() => new Map(animals.map((a) => [a.id, a])), [animals]);

  function propose() {
    const options =
      mode === "count"
        ? { groupCount: Number(groupCount) || 1 }
        : { maxGroupSize: Number(maxSize) || 1 };
    setProposal(
      suggestGroupsLocal(animals, {
        ...options,
        balanceBySex: balanceBySex && canBalanceBySex,
      }),
    );
  }

  function apply() {
    if (!proposal || proposal.rejected) return;
    const groups: Group[] = proposal.groups.map((g) => ({
      id: newGroupId(),
      name: g.name,
      order: g.order,
    }));
    const next: Animal[] = [];
    proposal.groups.forEach((proposed, index) => {
      const group = groups[index]!;
      for (const member of proposed.animals) {
        const animal = byId.get(member.animalId);
        if (!animal) continue;
        next.push({ ...animal, groupId: group.id, boxNumber: member.boxNumber });
      }
    });
    onApply(groups, next);
    setProposal(null);
  }

  return (
    <div className="px-4 py-3.5">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-static">Split by</span>
          <Select
            label="Split by"
            value={mode}
            options={[
              { value: "count", label: "Number of groups" },
              { value: "size", label: "Max group size" },
            ]}
            onChange={(v) => setMode(v as Mode)}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-static">
            {mode === "count" ? "Groups" : "Max per group"}
          </span>
          <TextInput
            label={mode === "count" ? "Number of groups" : "Max group size"}
            mono
            value={mode === "count" ? groupCount : maxSize}
            onChange={mode === "count" ? setGroupCount : setMaxSize}
            className="w-20"
          />
        </label>

        <span className="flex items-center gap-2 pb-1.5">
          <Toggle
            label="Balance by sex"
            checked={balanceBySex && canBalanceBySex}
            onChange={setBalanceBySex}
          />
          <span
            className={`text-[12px] ${canBalanceBySex ? "text-static" : "text-static/50"}`}
            title={
              canBalanceBySex
                ? undefined
                : "Set at least one animal's sex to M or F to balance against it"
            }
          >
            Balance by sex
          </span>
        </span>

        <Button onClick={propose} disabled={animals.length === 0}>
          <Wand2 size={13} strokeWidth={1.75} />
          Suggest grouping
        </Button>
      </div>

      {proposal?.rejected && (
        <div
          className="mt-3 flex items-start gap-2 rounded-sm border border-halo bg-void/40 px-3 py-2 text-[12px] leading-relaxed"
          style={{ color: "var(--color-status-warning)" }}
        >
          <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
          <span>
            {proposal.rejected.reason}
            <Button
              variant="ghost"
              onClick={() => {
                setMode("count");
                setGroupCount(String(proposal.rejected!.minimumGroups));
              }}
            >
              Use {proposal.rejected.minimumGroups} groups
            </Button>
          </span>
        </div>
      )}

      {proposal && !proposal.rejected && (
        <div className="mt-4">
          <p className="mb-2 text-[12px] text-static">
            Preview — nothing is saved until you apply.
          </p>
          <div className="flex flex-col gap-2">
            {proposal.groups.map((group) => (
              <div key={group.order} className="rounded-sm border border-halo bg-void/40 p-3">
                <div className="text-[12px] font-medium text-starlight">{group.name}</div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                  {group.animals.map((member) => (
                    <span key={member.animalId} className="font-mono text-[11px] text-static">
                      <span className="text-pulsar">box {member.boxNumber}</span>{" "}
                      {byId.get(member.animalId)?.name ?? "—"}
                    </span>
                  ))}
                  {group.animals.length === 0 && (
                    <span className="font-mono text-[11px] text-static/60">empty</span>
                  )}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={apply}>
              Apply grouping
            </Button>
            <Button variant="ghost" onClick={() => setProposal(null)}>
              Cancel
            </Button>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-static">
            Applying replaces the current grouping entirely. You can still adjust
            groups and boxes by hand afterwards.
          </p>
        </div>
      )}
    </div>
  );
}
