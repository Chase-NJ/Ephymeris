import { motion } from "framer-motion";
import { ArrowRight, CircleAlert, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Button, Select } from "@/components/common/controls";
import { SketchPicker, TaskConfigForm } from "@/components/sessions/TaskConfigForm";
import { errorMessage, getCohort } from "@/lib/cohorts/commands";
import type { Cohort } from "@/lib/cohorts/types";
import { springPanel, springSnappy } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import {
  confirmMapping,
  flashForSession,
  getTaskProfile,
} from "@/lib/sessions/commands";
import {
  animalsInGroup,
  defaultConfig,
  type BoxMapping,
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

  const [cohort, setCohort] = useState<Cohort | null>(null);
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

  async function confirmAndFlash() {
    if (!sessionId || !allChosen) return;
    setBusy(true);
    setError(null);
    try {
      await confirmMapping(client, sessionId, groupId, mappings);

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
      <h1 className="font-display text-[22px] text-starlight">Confirm boxes</h1>
      <p className="mt-1 text-[12px] text-static">
        Step 2 of 2 — mapping and sketches. Changes here apply to this run only.
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
        <div className="mt-5 grid grid-cols-1 gap-3 lg:grid-cols-2">
          {mappings.map((mapping) => {
            const animal = names[mapping.animalId];
            const profile = mapping.sketchPath
              ? (profiles[mapping.sketchPath] ?? null)
              : null;
            return (
              <div key={mapping.animalId} className="surface rounded-md p-4">
                <div className="flex items-center gap-3">
                  <BoxStar state={flashStates[mapping.box] ?? "idle"} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium text-starlight">
                      Box {mapping.box}
                    </div>
                    <div className="font-mono text-[11px] text-static">
                      {animal?.name ?? "—"}
                      {animal?.sex && animal.sex !== "unknown" && ` · ${animal.sex}`}
                    </div>
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

                <div className="mt-3">
                  <SketchPicker
                    label={`Sketch for box ${mapping.box}`}
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
                  />
                </div>

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
        <Button variant="ghost" onClick={() => navigate("/session/new")}>
          Back
        </Button>
      </div>
    </motion.section>
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
