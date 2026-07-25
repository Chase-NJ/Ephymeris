import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, CircleAlert, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Button, Select } from "@/components/common/controls";
import { RatPlacementBanner } from "@/components/sessions/RatPlacementBanner";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import { SketchPicker, TaskConfigForm } from "@/components/sessions/TaskConfigForm";
import { errorMessage, getCohort } from "@/lib/cohorts/commands";
import type { Cohort } from "@/lib/cohorts/types";
import { springPanel, springSnappy } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import {
  abandonSession,
  confirmMapping,
  endSession,
  flashForSession,
  getTaskProfile,
  sessionStatus,
} from "@/lib/sessions/commands";
import { useSessionStore } from "@/lib/sessions/context";
import {
  animalsInGroup,
  defaultConfig,
  populatedGroups,
  type BoxMapping,
  type Session,
  type TaskProfile,
} from "@/lib/sessions/types";
import { useSidecar } from "@/lib/ws/context";
import { NODE_ACCENT, NODE_PRIMARY } from "@/components/chrome/constellationStyle";

/**
 * Step 2 — animal→box mapping confirmation, then the flash sequence
 * (`starting-a-session.md` §3–§4).
 *
 * Edits here are **session-local**: they never write back to the cohort's
 * stored mapping (§3). Permanent changes go through Cohort management.
 */

type FlashState = "idle" | "flashing" | "done" | "failed";

export function SessionMapping() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const groupId = params.get("group") ?? "";
  const cohortId = params.get("cohort") ?? "";
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const { discovery } = useSettings();
  const sessionStore = useSessionStore();

  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [mappings, setMappings] = useState<BoxMapping[]>([]);
  const [profiles, setProfiles] = useState<Record<string, TaskProfile | null>>({});
  const [flashStates, setFlashStates] = useState<Record<number, FlashState>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const connected = status === "connected";
  const sketches = discovery.sketches;

  // Seed the mapping from the cohort's standing box assignments.
  useEffect(() => {
    if (!connected || !cohortId) return;
    let active = true;
    void (async () => {
      try {
        const loaded = await getCohort(client, cohortId);
        if (!active) return;
        setCohort(loaded);
        setMappings(
          animalsInGroup(loaded, groupId).map((a) => ({
            box: a.boxNumber as number,
            animalId: a.id,
            sketchPath: null,
            config: {},
          })),
        );
      } catch (err) {
        if (active) setError(errorMessage(err));
      }
    })();
    return () => {
      active = false;
    };
  }, [client, connected, cohortId, groupId]);

  // What "back" means depends on whether the session has run yet (§3): the
  // record's status distinguishes first entry (`configuring`) from re-entry
  // via Switch Group (`running`).
  useEffect(() => {
    if (!connected || !sessionId) return;
    let active = true;
    void sessionStatus(client, sessionId)
      .then((snapshot) => active && setSession(snapshot.session))
      .catch(() => undefined); // non-blocking — worst case Back behaves as before
    return () => {
      active = false;
    };
  }, [client, connected, sessionId]);

  const midSession = session?.status === "running";

  // First entry: abandon the never-run record rather than stranding it in
  // `configuring`. Best-effort — a failed abandon is no worse than the
  // orphan it replaces, so it never blocks leaving the step.
  async function backToConfig() {
    if (sessionId) await abandonSession(client, sessionId).catch(() => undefined);
    navigate("/session/new");
  }

  // Re-entry via Switch Group: the previous groups already ran, so the only
  // honest exits are onward (flash) or ending the session outright.
  async function endFromHere() {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const ended = await endSession(client, sessionId);
      navigate("/analytics", {
        state: { endedSession: `${ended.prefixName}_${ended.sessionNumber}` },
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  // Load each chosen sketch's Task Profile and seed its config defaults (§3).
  // Rows are identified by animal, not by box — box numbers are editable here
  // and may collide mid-edit.
  const loadProfile = useCallback(
    async (animalId: string, sketchPath: string | null) => {
      if (!sketchPath) return;
      if (profiles[sketchPath] !== undefined) {
        setMappings((prev) =>
          prev.map((m) =>
            m.animalId === animalId
              ? { ...m, config: defaultConfig(profiles[sketchPath] ?? null) }
              : m,
          ),
        );
        return;
      }
      try {
        const profile = await getTaskProfile(client, sketchPath);
        setProfiles((prev) => ({ ...prev, [sketchPath]: profile }));
        setMappings((prev) =>
          prev.map((m) =>
            m.animalId === animalId ? { ...m, config: defaultConfig(profile) } : m,
          ),
        );
      } catch (err) {
        // A malformed task.json is surfaced but doesn't block: the sketch is
        // treated as profile-less (bare START).
        setError(errorMessage(err));
        setProfiles((prev) => ({ ...prev, [sketchPath]: null }));
      }
    },
    [client, profiles],
  );

  const names = useMemo(
    () => Object.fromEntries((cohort?.animals ?? []).map((a) => [a.id, a])),
    [cohort],
  );

  // Two animals can't share a box — reassigning one here has to displace the
  // other, and the user is the one who decides which.
  const duplicateBox = useMemo(() => {
    const seen = new Set<number>();
    for (const m of mappings) {
      if (seen.has(m.box)) return m.box;
      seen.add(m.box);
    }
    return null;
  }, [mappings]);

  const allChosen =
    mappings.length > 0 &&
    mappings.every((m) => m.sketchPath !== null) &&
    duplicateBox === null;

  // Which group this is, for the rail's chip — only meaningful multi-group.
  const groupInfo = useMemo(() => {
    if (!cohort) return null;
    const groups = populatedGroups(cohort);
    const i = groups.findIndex((g) => g.id === groupId);
    const found = groups[i];
    if (!found || groups.length < 2) return null;
    return { index: i + 1, count: groups.length, name: found.name };
  }, [cohort, groupId]);

  const hint = busy
    ? "Flashing each box in turn — keep the boards plugged in."
    : duplicateBox !== null
      ? `Two animals share box ${duplicateBox} — move one first.`
      : !allChosen
        ? "Pick a sketch for every box, then confirm."
        : "Confirm and flash, then place the animals.";

  async function confirmAndFlash() {
    if (!sessionId || !allChosen) return;
    setBusy(true);
    setError(null);
    try {
      await confirmMapping(client, sessionId, groupId, mappings);

      // A confirmed mapping begins a fresh group run — drop the previous
      // group's telemetry and finished-run messages so Mission Control
      // doesn't show them against the new animals.
      sessionStore.resetRun();

      // §4 — flashed in sequence, one box after another, never in parallel.
      for (const mapping of mappings) {
        setFlashStates((s) => ({ ...s, [mapping.box]: "flashing" }));
        try {
          await flashForSession(client, mapping.box, mapping.sketchPath!);
          setFlashStates((s) => ({ ...s, [mapping.box]: "done" }));
        } catch (err) {
          setFlashStates((s) => ({ ...s, [mapping.box]: "failed" }));
          throw err;
        }
      }
      navigate(`/session/${sessionId}/control?cohort=${cohort?.id ?? ""}&group=${groupId}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-5xl px-8 py-8"
    >
      <SessionJourney step="boxes" hint={hint} group={groupInfo} />
      <h1 className="font-display text-[22px] text-starlight">Confirm boxes</h1>
      <p className="mt-1 text-[12px] text-static">
        Changes here apply to this run only.
      </p>

      {error && (
        <div
          className="mt-4 flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
          style={{ color: "var(--color-status-error)" }}
        >
          <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
          {error}
        </div>
      )}

      {mappings.length === 0 ? (
        <p className="mt-6 text-[13px] text-static">
          No box-assigned animals in this group.
        </p>
      ) : (
        <RatPlacementBanner boxes={mappings.map((m) => m.box)} />
      )}

      {mappings.length > 0 && (
        // `items-start`: a card growing its config form must not stretch the
        // compact cards sharing its row.
        <div className="mt-3 grid grid-cols-1 items-start gap-3 lg:grid-cols-2">
          {mappings.map((mapping) => {
            const animal = names[mapping.animalId];
            const profile = mapping.sketchPath
              ? (profiles[mapping.sketchPath] ?? null)
              : null;
            return (
              <div key={mapping.animalId} className="surface rounded-md p-4">
                {/* Identity line: the animal's full name is the point of the
                    card, so it never truncates — an unusually long one wraps
                    instead. */}
                <div className="flex items-start gap-3">
                  <BoxStar state={flashStates[mapping.box] ?? "idle"} />
                  <div className="min-w-0 flex-1 break-words text-[15px] font-semibold leading-snug text-starlight">
                    {animal?.name ?? "—"}
                    {animal?.sex && animal.sex !== "unknown" && (
                      <span className="ml-2 align-middle font-mono text-[11px] font-normal text-static">
                        {animal.sex}
                      </span>
                    )}
                  </div>
                </div>

                {/* Mapping line, reading left to right: sketch → arrow → box.
                    The picker takes the slack and ellipsizes long sketch
                    names; the arrow's slot is reserved so its arrival moves
                    nothing. */}
                <div className="mt-3 flex items-center gap-3">
                  <SketchPicker
                    label={`Sketch for ${animal?.name ?? `box ${mapping.box}`}`}
                    sketches={sketches}
                    value={mapping.sketchPath}
                    onChange={(path) => {
                      setMappings((prev) =>
                        prev.map((m) =>
                          m.animalId === mapping.animalId
                            ? { ...m, sketchPath: path, config: {} }
                            : m,
                        ),
                      );
                      void loadProfile(mapping.animalId, path);
                    }}
                    className="min-w-0 flex-1 truncate"
                  />
                  <div className="flex w-5 shrink-0 items-center justify-center">
                    {mapping.sketchPath !== null && <FlowArrow />}
                  </div>
                  <Select
                    label={`Box for ${animal?.name ?? "animal"}`}
                    value={String(mapping.box)}
                    options={[1, 2, 3, 4, 5, 6].map((n) => ({
                      value: String(n),
                      label: `Box ${n}`,
                    }))}
                    onChange={(v) =>
                      setMappings((prev) =>
                        prev.map((m) =>
                          m.animalId === mapping.animalId ? { ...m, box: Number(v) } : m,
                        ),
                      )
                    }
                  />
                </div>

                {/* Per-run parameters slide the tile open with the app's
                    snappy spring; only a chosen sketch with a profile has
                    any — an unchosen tile never expands. */}
                <AnimatePresence initial={false}>
                  {profile && profile.config.length > 0 && (
                    <motion.div
                      key="task-config"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={springSnappy}
                      className="overflow-hidden"
                    >
                      <TaskConfigForm
                        profile={profile}
                        config={mapping.config}
                        onChange={(config) =>
                          setMappings((prev) =>
                            prev.map((m) =>
                              m.animalId === mapping.animalId ? { ...m, config } : m,
                            ),
                          )
                        }
                      />
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>
      )}

      {duplicateBox !== null && (
        <p
          className="mt-4 text-[12px]"
          style={{ color: "var(--color-status-warning)" }}
        >
          Two animals are assigned to box {duplicateBox}. Give one of them a
          different box before continuing.
        </p>
      )}

      <div className="mt-6 flex items-center gap-2">
        <Button
          variant="primary"
          onClick={() => void confirmAndFlash()}
          disabled={!allChosen || busy || !connected}
        >
          <Zap size={13} strokeWidth={1.75} />
          {busy ? "Flashing…" : "Confirm and flash"}
          {!busy && <ArrowRight size={13} strokeWidth={2} />}
        </Button>
        {midSession ? (
          <Button variant="ghost" disabled={busy} onClick={() => void endFromHere()}>
            End session
          </Button>
        ) : (
          <Button variant="ghost" disabled={busy} onClick={() => void backToConfig()}>
            Back
          </Button>
        )}
      </div>
    </motion.section>
  );
}

/**
 * The animal→box flow cue: a quiet arrow drifting from the name toward the
 * box selector, same rightward "into the box" motion as the rat banner.
 */
function FlowArrow() {
  return (
    <motion.span
      aria-hidden
      className="shrink-0 text-static"
      initial={{ opacity: 0 }}
      animate={{ x: [0, 5, 0], opacity: [0.45, 1, 0.45] }}
      transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
    >
      <ArrowRight size={14} strokeWidth={1.75} />
    </motion.span>
  );
}

/**
 * §4 — a box mid-flash shows its star "flaring" rather than a generic spinner,
 * keeping the visual language consistent with the rest of the app.
 */
function BoxStar({ state }: { state: FlashState }) {
  const fill =
    state === "done" ? NODE_ACCENT : state === "failed" ? "var(--color-status-error)" : NODE_PRIMARY;
  return (
    <svg viewBox="0 0 40 40" width={28} height={28} aria-hidden>
      <motion.circle
        cx={20}
        cy={20}
        r={5}
        fill={fill}
        animate={
          state === "flashing"
            ? { r: [4, 9, 4], opacity: [0.9, 0.35, 0.9] }
            : { r: 5, opacity: state === "idle" ? 0.5 : 1 }
        }
        transition={
          state === "flashing"
            ? { duration: 0.9, repeat: Infinity, ease: "easeInOut" }
            : springSnappy
        }
      />
    </svg>
  );
}
