import { motion } from "framer-motion";
import { ArrowRight, CircleAlert, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { Button, Select, TextInput } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { CohortIcon } from "@/components/cohorts/CohortIcon";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import { SettingGroup } from "@/components/settings/SettingRow";
import { errorMessage } from "@/lib/cohorts/commands";
import { useActiveCohorts } from "@/lib/cohorts/context";
import { getCohort } from "@/lib/cohorts/commands";
import type { Cohort, CohortSummary } from "@/lib/cohorts/types";
import { springPanel, springSnappy } from "@/lib/motion";
import {
  createPrefix,
  createSession,
  deletePrefix,
  suggestSessionNumber,
} from "@/lib/sessions/commands";
import { usePrefixes } from "@/lib/sessions/context";
import { firstGroupToRun, isReadyToRun } from "@/lib/sessions/types";
import { useSidecar } from "@/lib/ws/context";

/**
 * Step 1 — Configuration (`dashboard.md` §7.2).
 *
 * Cohort is picked from the same card grid as the Cohorts tab (§2.1) rather
 * than a dropdown, since that's how the user already knows to pick one. All
 * three fields are required before continuing.
 */
export function SessionConfig() {
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const cohorts = useActiveCohorts();
  const prefixes = usePrefixes();

  const [cohortId, setCohortId] = useState<string | null>(null);
  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [prefixId, setPrefixId] = useState<string>("");
  const [sessionNumber, setSessionNumber] = useState("");
  const [durationText, setDurationText] = useState("");
  const [sameDayNumbers, setSameDayNumbers] = useState<string[]>([]);
  const [newPrefix, setNewPrefix] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const connected = status === "connected";

  // Full cohort detail is needed for the §1 readiness check.
  useEffect(() => {
    if (!cohortId || !connected) return;
    let active = true;
    void getCohort(client, cohortId)
      .then((c) => active && setCohort(c))
      .catch((err) => active && setError(errorMessage(err)));
    return () => {
      active = false;
    };
  }, [client, cohortId, connected]);

  useEffect(() => {
    if (!prefixId && prefixes[0]) setPrefixId(prefixes[0].id);
  }, [prefixes, prefixId]);

  // §2.2 — pre-fill the next number for the chosen prefix, and learn which
  // numbers it already used today so reuse can be warned about softly.
  useEffect(() => {
    if (!prefixId || !connected) return;
    let active = true;
    void suggestSessionNumber(client, prefixId)
      .then(({ suggestion, sameDayNumbers }) => {
        if (!active) return;
        setSameDayNumbers(sameDayNumbers);
        // A suggestion only fills an untouched field — never overwrites typing.
        setSessionNumber((current) => (current === "" ? (suggestion ?? "") : current));
      })
      .catch((err) => active && setError(errorMessage(err)));
    return () => {
      active = false;
    };
  }, [client, connected, prefixId]);

  const ready = cohort ? isReadyToRun(cohort) : false;
  const firstGroup = useMemo(() => (cohort ? firstGroupToRun(cohort) : null), [cohort]);
  // Empty = no limit; otherwise a positive whole number of minutes.
  const durationTrim = durationText.trim();
  const durationMinutes = /^\d+$/.test(durationTrim) ? Number(durationTrim) : null;
  const durationValid = durationTrim === "" || (durationMinutes !== null && durationMinutes > 0);
  const canContinue =
    connected &&
    cohort !== null &&
    ready &&
    prefixId !== "" &&
    sessionNumber.trim() !== "" &&
    durationValid;
  const sameDayReuse = sameDayNumbers.includes(sessionNumber.trim());

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  // The rail's one-line direction — always the single next action.
  const hint = !connected
    ? "Waiting for the hardware service…"
    : cohorts.length === 0
      ? "Create a cohort first — sessions run against one."
      : !cohort
        ? "Pick the cohort you're running."
        : !ready
          ? "This cohort needs box assignments — set them in Cohorts."
          : prefixes.length === 0
            ? "Add a prefix — it names this task's data files."
            : sessionNumber.trim() === ""
              ? "Number the session — the next one is suggested."
              : sameDayReuse
                ? "That number already ran today — continue only to append."
                : "Ready — continue to box mapping.";

  async function continueToMapping() {
    if (!cohort || !firstGroup) return;
    await run(async () => {
      const session = await createSession(
        client,
        cohort.id,
        prefixId,
        sessionNumber.trim(),
        durationTrim === "" ? undefined : (durationMinutes ?? undefined),
      );
      navigate(
        `/session/${session.id}/mapping?cohort=${cohort.id}&group=${firstGroup.id}`,
      );
    });
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-4xl px-8 py-8"
    >
      <SessionJourney step="configure" hint={hint} />
      <h1 className="font-display text-[22px] text-starlight">Start a Session</h1>

      {error && (
        <div
          className="mt-4 flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
          style={{ color: "var(--color-status-error)" }}
        >
          <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
          {error}
        </div>
      )}

      <SettingGroup title="Cohort">
        <div className="p-4">
          {cohorts.length === 0 ? (
            <p className="text-[12px] leading-relaxed text-static">
              No cohorts yet. Create one first — sessions run against a cohort.
            </p>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {cohorts.map((c) => (
                <CohortPick
                  key={c.id}
                  cohort={c}
                  selected={c.id === cohortId}
                  onSelect={() => {
                    setCohortId(c.id);
                    setCohort(null);
                  }}
                />
              ))}
            </div>
          )}

          {/* §1 readiness, checked before the user can go further. */}
          {cohort && !ready && (
            <p
              className="mt-3 text-[12px] leading-relaxed"
              style={{ color: "var(--color-status-warning)" }}
            >
              This cohort has no animal with a box assigned yet, so there's
              nothing to run. Assign boxes in Cohorts first.
            </p>
          )}
          {cohort && ready && firstGroup && (
            <p className="mt-3 text-[12px] text-static">
              Starts with{" "}
              <span className="text-starlight">{firstGroup.name}</span> — the
              lowest-order group that has box-assigned animals.
            </p>
          )}
        </div>
      </SettingGroup>

      <SettingGroup title="Session">
        <div className="flex items-start justify-between gap-8 px-4 py-3.5">
          <div className="min-w-0 pt-0.5">
            <div className="text-[13px] font-medium text-starlight">Prefix</div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-static">
              Names the task or paradigm, shared across cohorts.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Select
              label="Session prefix"
              value={prefixId}
              options={
                prefixes.length > 0
                  ? prefixes.map((p) => ({ value: p.id, label: p.name }))
                  : [{ value: "", label: "— none yet —" }]
              }
              onChange={(v) => {
                setPrefixId(String(v));
                // Numbers are per-prefix, so the old one carries no meaning
                // here — clearing lets the new prefix's suggestion land.
                setSessionNumber("");
              }}
            />
            <Button
              variant="outline"
              shape="icon"
              onClick={() => setConfirmingDelete(true)}
              disabled={!prefixId || busy}
              title="Remove this prefix (files already written are untouched)"
            >
              <Minus size={14} strokeWidth={2} />
            </Button>
          </div>
        </div>

        <div className="flex items-start justify-between gap-8 px-4 py-3.5">
          <div className="min-w-0 pt-0.5">
            <div className="text-[13px] font-medium text-starlight">Add a prefix</div>
          </div>
          <div className="flex items-center gap-2">
            <TextInput
              label="New prefix name"
              value={newPrefix}
              placeholder="2O-Bdisc"
              onChange={setNewPrefix}
              className="w-[200px]"
            />
            <Button
              onClick={() =>
                void run(async () => {
                  const created = await createPrefix(client, newPrefix.trim());
                  setPrefixId(created.id);
                  setNewPrefix("");
                })
              }
              disabled={!newPrefix.trim() || busy}
            >
              <Plus size={13} strokeWidth={1.75} />
              Add
            </Button>
          </div>
        </div>

        <div className="flex items-start justify-between gap-8 px-4 py-3.5">
          <div className="min-w-0 pt-0.5">
            <div className="text-[13px] font-medium text-starlight">Session number</div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-static">
              Free text — usually the next number for this prefix.
            </p>
          </div>
          <TextInput
            label="Session number"
            mono
            value={sessionNumber}
            placeholder="25"
            onChange={setSessionNumber}
            className="w-[120px]"
          />
        </div>

        <div className="flex items-start justify-between gap-8 px-4 py-3.5">
          <div className="min-w-0 pt-0.5">
            <div className="text-[13px] font-medium text-starlight">Time limit</div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-static">
              Minutes per box, counted from each box&apos;s own start. The box is
              stopped at its next trial boundary once time is up. Leave empty
              for no limit.
            </p>
          </div>
          <div className="flex items-center gap-2 pt-0.5">
            <TextInput
              label="Time limit in minutes"
              mono
              value={durationText}
              placeholder="—"
              onChange={setDurationText}
              className="w-[80px]"
            />
            <span className="text-[12px] text-static">min</span>
          </div>
        </div>

        {!durationValid && (
          <div className="px-4 pb-3.5">
            <p
              className="text-[12px] leading-relaxed"
              style={{ color: "var(--color-status-warning)" }}
            >
              The time limit must be a whole number of minutes, or empty for
              none.
            </p>
          </div>
        )}

        {/* §2.2 — soft warning only. Reusing a number is legal (data.md §1): it appends into the same folder, which is how an interrupted
            run is resumed. It's just usually accidental. */}
        {sameDayReuse && (
          <div className="px-4 pb-3.5">
            <p
              className="text-[12px] leading-relaxed"
              style={{ color: "var(--color-status-warning)" }}
            >
              Session {sessionNumber.trim()} for this prefix already has data
              from today — continuing will write into the same folder.
            </p>
          </div>
        )}
      </SettingGroup>

      <div className="mt-6 flex items-center gap-2">
        <Button
          variant="primary"
          onClick={() => void continueToMapping()}
          disabled={!canContinue || busy}
        >
          Continue
          <ArrowRight size={13} strokeWidth={2} />
        </Button>
        <Button variant="ghost" onClick={() => navigate("/")}>
          Cancel
        </Button>
      </div>

      <Modal
        open={confirmingDelete}
        onClose={() => setConfirmingDelete(false)}
        title="Remove prefix"
      >
        <p className="text-[13px] leading-relaxed text-static">
          Remove{" "}
          <span className="font-mono text-starlight">
            {prefixes.find((p) => p.id === prefixId)?.name ?? "this prefix"}
          </span>{" "}
          from the list? Folders and files already written under it stay on
          disk, but its numbering history will no longer be suggested here.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmingDelete(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await deletePrefix(client, prefixId);
                // Fall back to the first remaining prefix (the effect above
                // re-picks); a stale number would carry no meaning across it.
                setPrefixId("");
                setSessionNumber("");
                setConfirmingDelete(false);
              })
            }
          >
            Remove
          </Button>
        </div>
      </Modal>
    </motion.section>
  );
}

function CohortPick({
  cohort,
  selected,
  onSelect,
}: {
  cohort: CohortSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <motion.button
      type="button"
      onClick={onSelect}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.99 }}
      transition={springSnappy}
      className={`flex flex-col items-start gap-2 rounded-md border p-3 text-left transition-colors ${
        selected ? "border-pulsar bg-pulsar/12" : "border-halo bg-nebula"
      }`}
    >
      <CohortIcon cohortId={cohort.id} animalCount={cohort.animalCount} size={40} />
      <span className="min-w-0 w-full">
        <span className="block truncate text-[12px] font-medium text-starlight">
          {cohort.name}
        </span>
        <span className="font-mono text-[10px] text-static">
          {cohort.animalCount} {cohort.animalCount === 1 ? "animal" : "animals"}
        </span>
      </span>
    </motion.button>
  );
}
