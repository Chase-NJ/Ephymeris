import { ArrowRightLeft, FileStack, Notebook } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button, Select } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage, getCohort, moveAnimals, refusedPlan } from "@/lib/cohorts/commands";
import { useCohorts } from "@/lib/cohorts/context";
import type { Group } from "@/lib/cohorts/types";
import type { AnimalMovePlan } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";

/**
 * The preview-and-confirm for `cohorts.moveAnimals`
 * (`DATA.md#moving-animals-between-cohorts`).
 *
 * Opens on a preview the sidecar computed and changed nothing to produce, and
 * re-previews whenever the destination or group changes. It says what will
 * happen in the operator's terms — who this animal becomes there, which
 * sessions move whole and which are shared, how many files move — and, when
 * it can't be done, why, in the sidecar's own words.
 */
export function MoveAnimals({
  open,
  sourceId,
  sourceName,
  animal,
  onClose,
  onDone,
}: {
  open: boolean;
  sourceId: string;
  sourceName: string;
  animal: { id: string; name: string } | null;
  onClose: () => void;
  onDone: (result: AnimalMovePlan, destinationName: string) => void;
}) {
  const { client } = useSidecar();
  const cohorts = useCohorts();
  const destinations = useMemo(
    () =>
      cohorts
        .filter((c) => c.id !== sourceId && !c.archived)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [cohorts, sourceId],
  );
  const [destId, setDestId] = useState("");
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupId, setGroupId] = useState("");
  const [plan, setPlan] = useState<AnimalMovePlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDestId((current) => current || destinations[0]?.id || "");
  }, [open, destinations]);

  useEffect(() => {
    if (!open || !destId) return;
    let alive = true;
    setGroups([]);
    void getCohort(client, destId)
      .then((cohort) => {
        if (!alive) return;
        const sorted = [...cohort.groups].sort((a, b) => a.order - b.order);
        setGroups(sorted);
        setGroupId(sorted[0]?.id ?? "");
      })
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [open, client, destId]);

  useEffect(() => {
    if (!open || !animal || !destId || !groupId) return;
    let alive = true;
    setPlan(null);
    setError(null);
    void moveAnimals(client, {
      cohortId: sourceId,
      animalIds: [animal.id],
      destinationCohortId: destId,
      destinationGroupId: groupId,
      apply: false,
    })
      .then((result) => alive && setPlan(result))
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [open, client, sourceId, animal, destId, groupId]);

  async function apply() {
    if (!animal) return;
    setBusy(true);
    setError(null);
    try {
      const result = await moveAnimals(client, {
        cohortId: sourceId,
        animalIds: [animal.id],
        destinationCohortId: destId,
        destinationGroupId: groupId,
        apply: true,
      });
      onDone(result, destinations.find((d) => d.id === destId)?.name ?? "the other cohort");
    } catch (err) {
      const refused = refusedPlan(err);
      if (refused) setPlan(refused);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const destName = destinations.find((d) => d.id === destId)?.name ?? "";
  const refused = plan?.refused ?? [];
  const mover = plan?.animals[0];
  const whole = plan?.sessions.filter((s) => s.kind === "whole").length ?? 0;
  const split = plan?.sessions.filter((s) => s.kind === "split").length ?? 0;
  const notesMoved = plan?.sessions.reduce((n, s) => n + s.notesMoved, 0) ?? 0;
  const notesCopied = plan?.sessions.reduce((n, s) => n + s.notesCopied, 0) ?? 0;

  return (
    <Modal open={open} onClose={onClose} title={`Move ${animal?.name ?? "animal"}`} size="lg">
      <p className="text-[13px] leading-relaxed text-static">
        Moves {animal?.name ?? "this animal"} out of {sourceName}, with its whole history: its data
        files go to the other cohort's data folder, and its sessions and notes follow.{" "}
        <span className="text-starlight">Nothing changes until you click Move.</span>
      </p>

      {destinations.length === 0 ? (
        <p className="mt-4 text-[12px] text-static">
          There is no other active cohort to move to. Create the destination cohort first — it can
          be empty.
        </p>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-4 text-[12px] text-static">
          <span className="flex items-center gap-2">
            To
            <Select
              label="Destination cohort"
              value={destId}
              options={destinations.map((d) => ({ value: d.id, label: d.name }))}
              onChange={(value) => setDestId(value)}
            />
          </span>
          {groups.length > 1 && (
            <span className="flex items-center gap-2">
              Group
              <Select
                label="Group there"
                value={groupId}
                options={groups.map((g) => ({ value: g.id, label: g.name }))}
                onChange={(value) => setGroupId(value)}
              />
            </span>
          )}
        </div>
      )}

      {error && <p className="mt-3 text-[12px] text-status-error">{error}</p>}
      {destId && !plan && !error && <p className="mt-4 text-[12px] text-static">Looking…</p>}

      {plan && mover && (
        <section className="mt-4 flex flex-col gap-2 text-[12px] text-static">
          <p className="flex items-center gap-1.5 text-starlight">
            <ArrowRightLeft size={13} strokeWidth={1.75} className="text-pulsar" />
            {mover.outcome === "joins"
              ? `Joins ${destName}'s ${mover.name}: the history becomes that animal's.`
              : mover.status === "active"
                ? `Arrives on ${destName}'s roster as ${mover.name}, with its history.`
                : `Arrives in ${destName} as a former member, with its history.`}
          </p>
          <p className="flex items-center gap-1.5">
            <Notebook size={13} strokeWidth={1.75} />
            {mover.runs} run{plural(mover.runs)}
            {whole > 0 && ` · ${whole} session${plural(whole)} it ran alone move whole`}
            {split > 0 &&
              ` · ${split} shared session${plural(split)} each get${split === 1 ? "s" : ""} a record in ${destName}`}
            {plan.recoveredSessions > 0 &&
              ` · ${plan.recoveredSessions} recovered session${plural(plan.recoveredSessions)}`}
          </p>
          <p className="flex items-center gap-1.5">
            <FileStack size={13} strokeWidth={1.75} />
            {plan.files.count} file{plural(plan.files.count)} ({formatBytes(plan.files.bytes)})
            {plan.files.alreadyThere > 0 && ` · ${plan.files.alreadyThere} already in place`}
            {plan.files.missing > 0 &&
              ` · ${plan.files.missing} run${plural(plan.files.missing)} whose file is missing — the record still moves`}
          </p>
          {(notesMoved > 0 || notesCopied > 0) && (
            <p>
              {notesMoved > 0 && `${notesMoved} note${plural(notesMoved)} move`}
              {notesMoved > 0 && notesCopied > 0 && " · "}
              {notesCopied > 0 &&
                `${notesCopied} note${plural(notesCopied)} about shared sessions copied, so both logs read in full`}
            </p>
          )}
        </section>
      )}

      {refused.length > 0 && (
        <ul className="mt-4 flex flex-col gap-1 text-[12px]" style={{ color: "var(--color-status-warning)" }}>
          {refused.map((r) => (
            <li key={`${r.code}:${r.message}`}>{r.message}</li>
          ))}
        </ul>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={() => void apply()}
          disabled={busy || !plan || refused.length > 0}
        >
          {busy ? "Moving…" : "Move"}
        </Button>
      </div>
    </Modal>
  );
}

function plural(n: number): string {
  return n === 1 ? "" : "s";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
