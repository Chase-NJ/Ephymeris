import { motion } from "framer-motion";
import { ArrowRight, CircleAlert, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { Button, TextInput } from "@/components/common/controls";
import { Dropdown } from "@/components/common/Dropdown";
import { Modal } from "@/components/common/Modal";
import { ChangeCohort } from "@/components/analytics/ChangeCohort";
import { CohortManifest } from "@/components/cohorts/CohortManifest";
import { PlanetDisc } from "@/components/cohorts/PlanetDisc";
import { CarryForwardPanel } from "@/components/logbook/CarryForwardPanel";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import { SettingGroup } from "@/components/settings/SettingRow";
import { errorMessage } from "@/lib/cohorts/commands";
import { useActiveCohorts } from "@/lib/cohorts/context";
import { getCohort } from "@/lib/cohorts/commands";
import type { Cohort } from "@/lib/cohorts/types";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import {
  createPrefix,
  createSession,
  deletePrefix,
  resumeSession,
  suggestSessionNumber,
} from "@/lib/sessions/commands";
import { listSessions } from "@/lib/analytics/commands";
import type { SessionListItem } from "@/lib/analytics/types";
import { resolveFlag } from "@/lib/logbook/commands";
import { useLogbook, useLogbookStore } from "@/lib/logbook/context";
import { useActiveSessions, usePrefixes } from "@/lib/sessions/context";
import { stepUrl } from "@/lib/sessions/flow";
import {
  clearSetupDraft,
  clearSetupResume,
  getSetupDraft,
  setSetupDraft,
} from "@/lib/sessions/setupResume";
import {
  isContinuable,
  isReadyToRun,
  localToday,
} from "@/lib/sessions/types";
import { useSidecar } from "@/lib/ws/context";

/**
 * Step 1 — Configuration (`ARCHITECTURE.md#configuration`).
 *
 * The cohort is picked from the same list Analytics and Log open on
 * (`CohortManifest`), held to a panel's height here because it is one section
 * of a form; once picked it folds down to a breadcrumb that leads back to the
 * list. Which animals run, and in which boxes, is the next step's question.
 *
 * A cohort with one of TODAY's sessions that already ran a round (the app was
 * closed between rounds, or the session was ended too early) offers to continue
 * that session with another round instead (`sessions.resume`,
 * `ARCHITECTURE.md#between-rounds`).
 *
 * The form survives a trip to another tab: it is kept as a draft
 * (`setupResume.ts`) and seeds the fields on the way back in, one draft per
 * mode so a behavior set-up never fills in a recording one.
 */

interface ConfigDraft {
  cohortId: string | null;
  prefixId: string;
  sessionNumber: string;
  durationText: string;
}
export function SessionConfig() {
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const cohorts = useActiveCohorts();
  const prefixes = usePrefixes();
  // The Dashboard's Start Recording tile arrives here with `?mode=recording`:
  // the same first step, creating a session that is also an Intan recording.
  const [search] = useSearchParams();
  const recording = search.get("mode") === "recording";
  const draftKey = `configure:${recording ? "recording" : "behavior"}`;
  const [draft] = useState(() => getSetupDraft<ConfigDraft>(draftKey));

  const [cohortId, setCohortId] = useState<string | null>(draft?.cohortId ?? null);
  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [todays, setTodays] = useState<SessionListItem[]>([]);
  const active = useActiveSessions();
  const [prefixId, setPrefixId] = useState<string>(draft?.prefixId ?? "");
  const [sessionNumber, setSessionNumber] = useState(draft?.sessionNumber ?? "");
  const [durationText, setDurationText] = useState(draft?.durationText ?? "");
  const [sameDayNumbers, setSameDayNumbers] = useState<string[]>([]);
  const [newPrefix, setNewPrefix] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const connected = status === "connected";

  useEffect(() => {
    setSetupDraft<ConfigDraft>(draftKey, {
      cohortId,
      prefixId,
      sessionNumber,
      durationText,
    });
  }, [draftKey, cohortId, prefixId, sessionNumber, durationText]);

  // Full cohort detail is needed for the readiness check (`ARCHITECTURE.md#configuration`).
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

  // What the last session asked the next one to check
  // (`DATA.md#carry-forward-flags`) — read before anyone touches the rig.
  const logStore = useLogbookStore();
  const logEntry = useLogbook(cohortId);
  useEffect(() => {
    if (cohortId && connected) void logStore.load(cohortId);
  }, [cohortId, connected, logStore]);
  const animalNames = useMemo(
    () => new Map((cohort?.animals ?? []).map((a) => [a.id, a.name])),
    [cohort],
  );

  // Today's sessions for this cohort that another round can still run under.
  // The one currently held is left to the Dashboard's dock and Mission Control.
  const heldId = active?.running?.session.id ?? null;
  useEffect(() => {
    setTodays([]);
    if (!cohortId || !connected) return;
    let alive = true;
    const today = localToday();
    void listSessions(client, cohortId)
      .then((list) => {
        if (!alive) return;
        setTodays(list.filter((s) => s.id !== heldId && isContinuable(s, today)));
      })
      .catch(() => undefined); // an offer, never a blocker
    return () => {
      alive = false;
    };
  }, [client, connected, cohortId, heldId]);

  useEffect(() => {
    if (!prefixId && prefixes[0]) setPrefixId(prefixes[0].id);
  }, [prefixes, prefixId]);

  // Pre-fill the next number for the chosen prefix, and learn which
  // numbers it already used today so reuse can be warned about softly.
  useEffect(() => {
    if (!prefixId || !connected) return;
    let active = true;
    void suggestSessionNumber(client, prefixId)
      .then(({ suggestion, sameDayNumbers }) => {
        if (!active) return;
        setSameDayNumbers(sameDayNumbers);
        // A suggestion only fills an untouched field — never overwrites typing.
        setSessionNumber((current) =>
          current === "" ? (suggestion ?? "") : current,
        );
      })
      .catch((err) => active && setError(errorMessage(err)));
    return () => {
      active = false;
    };
  }, [client, connected, prefixId]);

  const ready = cohort ? isReadyToRun(cohort) : false;
  const picked = cohorts.find((c) => c.id === cohortId) ?? null;
  // Empty = no limit; otherwise a positive whole number of minutes.
  const durationTrim = durationText.trim();
  const durationMinutes = /^\d+$/.test(durationTrim)
    ? Number(durationTrim)
    : null;
  const durationValid =
    durationTrim === "" || (durationMinutes !== null && durationMinutes > 0);
  const canContinue =
    connected &&
    cohort !== null &&
    ready &&
    prefixId !== "" &&
    sessionNumber.trim() !== "" &&
    durationValid;
  const sameDayReuse = sameDayNumbers.includes(sessionNumber.trim());
  const prefixName = prefixes.find((p) => p.id === prefixId)?.name ?? "";
  const reusedToday = todays.find(
    (s) => s.sessionNumber === sessionNumber.trim() && s.prefixName === prefixName,
  );

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
          ? "This cohort has no animals — add them in Cohorts."
          : prefixes.length === 0
            ? "Add a prefix — it names this task's data files."
            : sessionNumber.trim() === ""
              ? "Number the session — the next one is suggested."
              : reusedToday
                ? "That session already ran today — continue it above instead."
                : sameDayReuse
                ? "That number already ran today — continue only to append."
                : "Ready — continue to choose who runs, and where.";

  async function continueToMapping() {
    if (!cohort) return;
    await run(async () => {
      const session = await createSession(
        client,
        cohort.id,
        prefixId,
        sessionNumber.trim(),
        durationTrim === "" ? undefined : (durationMinutes ?? undefined),
        recording,
      );
      // The session exists now; from here the way back is the Boxes step.
      clearSetupDraft(draftKey);
      navigate(stepUrl.boxes(session.id));
    });
  }

  return (
    // The guided steps sit on the same sky the Dashboard and Mission Control do,
    // so the flow reads as one continuous scene rather than three screens with a
    // constellation at either end. No `overflow-hidden`: the shared canvas
    // reaches left under the sidebar (`Scene.tsx`) and clipping here would cut it
    // back to the content region.
    <div className="relative h-full">
      <SkyBackdrop />

      {/* The chrome, floating over it. `pointer-events-none` on the scroller so
          the sky behind stays orbitable where the panels don't cover it; the
          column takes the pointer back. `scrollbar-none` because this rail's
          scrollbar would otherwise consume 10px of the column and shift
          everything in it (`index.css`). */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit: between two sky routes the shell stops fading the
        // page (`AppShell`), so anything that should fade has to say so.
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-4xl px-8 py-8">
          <SessionJourney step="configure" hint={hint} recording={recording} />
          <h1 className="font-display text-[22px] text-starlight">
            {recording ? "Start a Recording" : "Start a Session"}
          </h1>

          {error && (
            <div
              className="mt-4 flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert
                size={14}
                strokeWidth={1.75}
                className="mt-px shrink-0"
              />
              {error}
            </div>
          )}

          {/* The two groups and the actions cascade in — the walkthrough's
              first screen assembling top-down, in the order it is filled. */}
          <motion.div variants={CASCADE} initial="hidden" animate="shown">
          <motion.div variants={RISE}>
          {cohorts.length === 0 ? (
            <SettingGroup title="Cohort" variant="hud">
              <p className="p-4 text-[12px] leading-relaxed text-static">
                No cohorts yet. Create one first — sessions run against a cohort.
              </p>
            </SettingGroup>
          ) : picked ? (
            <SettingGroup title="Cohort" variant="hud">
              <div className="px-4 py-3">
                <ChangeCohort
                  name={picked.name}
                  disc={<PlanetDisc cohortId={picked.id} appearance={picked.appearance} size={16} />}
                  onBack={() => {
                    setCohortId(null);
                    setCohort(null);
                  }}
                />
                <p className="mt-2 font-mono text-[11px] text-static">
                  {picked.animalCount} {picked.animalCount === 1 ? "animal" : "animals"}
                  {picked.cageCount > 0 &&
                    ` · ${picked.cageCount} ${picked.cageCount === 1 ? "cage" : "cages"}`}
                </p>
                {/* Readiness, checked before the user can go further. */}
                {cohort && !ready && (
                  <p
                    className="mt-2 text-[12px] leading-relaxed"
                    style={{ color: "var(--color-status-warning)" }}
                  >
                    This cohort has no animals yet, so there's nothing to run. Add them
                    in Cohorts first.
                  </p>
                )}
              </div>
            </SettingGroup>
          ) : (
            // The list Analytics and Log open on, capped: here it is one
            // section of a form, not the page.
            <div className="mt-7">
              <CohortManifest
                cohorts={cohorts}
                className="max-h-[340px]"
                onPick={(id) => {
                  setCohortId(id);
                  setCohort(null);
                }}
              />
            </div>
          )}
          </motion.div>

          {cohortId && logEntry.openFlags.length > 0 && (
            // `mt-4`, under the cohort it belongs to rather than a group's
            // full `mt-7`: it is about the cohort just picked.
            <motion.div variants={RISE} className="mt-4">
              {/* Resolved against no session: this one doesn't exist yet,
                  and a flag dealt with before it starts was dealt with
                  outside one. */}
              <CarryForwardPanel
                title="Before you start"
                flags={logEntry.openFlags}
                sessions={logEntry.sessions}
                names={animalNames}
                onResolve={async (note) => {
                  await resolveFlag(client, note.id, true, null);
                }}
              />
            </motion.div>
          )}

          {todays.length > 0 && (
            <motion.div variants={RISE}>
              <SettingGroup title="Continue today" variant="hud">
                <div className="flex flex-col gap-2 p-4">
                  <p className="text-[12px] leading-relaxed text-static">
                    Closed between rounds, or ended too early? Pick the session back up
                    and run more animals under it — same folder, same session number.
                  </p>
                  {todays.map((s) => (
                    <div
                      key={s.id}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-sm border border-halo px-3 py-2"
                    >
                      <div className="min-w-0">
                        <div className="font-mono text-[13px] text-starlight">
                          {s.prefixName}_{s.sessionNumber}
                        </div>
                        <div className="mt-0.5 font-mono text-[11px] text-static">
                          ran {s.rounds.length} round{s.rounds.length === 1 ? "" : "s"}
                          {s.status === "running" && " · the app closed during it"}
                        </div>
                      </div>
                      <Button
                        disabled={busy || !connected}
                        onClick={() =>
                          void run(async () => {
                            await resumeSession(client, s.id);
                            navigate(stepUrl.boxes(s.id));
                          })
                        }
                      >
                        Continue
                        <ArrowRight size={13} strokeWidth={2} />
                      </Button>
                    </div>
                  ))}
                </div>
              </SettingGroup>
            </motion.div>
          )}

          <motion.div variants={RISE}>
          <SettingGroup title="Session" variant="hud">
            <div className="flex items-start justify-between gap-8 px-4 py-3.5">
              <div className="min-w-0 pt-0.5">
                <div className="text-[13px] font-medium text-starlight">
                  Prefix
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-static">
                  Names the task or paradigm, shared across cohorts.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Dropdown
                  label="Session prefix"
                  size="regular"
                  value={prefixId}
                  options={prefixes.map((p) => ({ value: p.id, label: p.name }))}
                  placeholder="— none yet —"
                  className="w-[200px]"
                  onChange={(v) => {
                    setPrefixId(v);
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
                <div className="text-[13px] font-medium text-starlight">
                  Add a prefix
                </div>
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
                      const created = await createPrefix(
                        client,
                        newPrefix.trim(),
                      );
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
                <div className="text-[13px] font-medium text-starlight">
                  Session number
                </div>
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
                <div className="text-[13px] font-medium text-starlight">
                  Time limit
                </div>
                <p className="mt-0.5 text-[12px] leading-relaxed text-static">
                  Minutes per box, counted from each box&apos;s own start. The
                  box is stopped at its next trial boundary once time is up.
                  Leave empty for no limit.
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

            {/* Soft warning only (`ARCHITECTURE.md#configuration`). Reusing a number is legal: it appends into the same folder.
            It's just usually accidental. */}
            {sameDayReuse && (
              <div className="px-4 pb-3.5">
                <p
                  className="text-[12px] leading-relaxed"
                  style={{ color: "var(--color-status-warning)" }}
                >
                  Session {sessionNumber.trim()} for this prefix already has
                  data from today — continuing will write into the same folder.
                  {reusedToday &&
                    " To run more animals under it, use Continue today above instead."}
                </p>
              </div>
            )}
          </SettingGroup>
          </motion.div>

          <motion.div variants={RISE} className="mt-6 flex items-center gap-2">
            <Button
              variant="primary"
              onClick={() => void continueToMapping()}
              disabled={!canContinue || busy}
            >
              Continue
              <ArrowRight size={13} strokeWidth={2} />
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                clearSetupResume();
                navigate("/");
              }}
            >
              Cancel
            </Button>
          </motion.div>
          </motion.div>

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
              <Button
                variant="ghost"
                onClick={() => setConfirmingDelete(false)}
              >
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
        </section>
      </motion.div>
    </div>
  );
}
