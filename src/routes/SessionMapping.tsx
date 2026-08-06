import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Check,
  CircleAlert,
  Lightbulb,
  Undo2,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Button, Select } from "@/components/common/controls";
import { RatPlacementBanner } from "@/components/sessions/RatPlacementBanner";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import {
  SketchPicker,
  TaskConfigForm,
} from "@/components/sessions/TaskConfigForm";
import { errorMessage, getCohort } from "@/lib/cohorts/commands";
import type { Cohort } from "@/lib/cohorts/types";
import { useAllPortStatuses, useUtilityStatus } from "@/lib/hardware/context";
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
  sketchName,
  type BoxMapping,
  type Session,
  type TaskProfile,
} from "@/lib/sessions/types";
import { CMD } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";
import {
  NODE_ACCENT,
  NODE_PRIMARY,
} from "@/components/chrome/constellationStyle";

/**
 * Step 2 — animal→box mapping confirmation, the guided placement walk, then
 * the flash sequence (`dashboard.md` §7.3–§4).
 *
 * Edits here are **session-local**: they never write back to the cohort's
 * stored mapping (§3). Permanent changes go through Cohort management.
 *
 * The three phases are one screen rather than three, because they are three
 * views of the same six rows: choose (which sketch, which box), place (one
 * animal at a time, with that box lit — §3.5), then flash. Splitting them into
 * routes would mean re-establishing which row you were on twice.
 */

type FlashState = "idle" | "flashing" | "done" | "failed";

/** `review` edits the mapping, `placing` walks the rig, `placed` flashes. */
type Phase = "review" | "placing" | "placed";

/** What the current box's identify light is doing, as far as we know. */
type Light = {
  box: number;
  status: "pending" | "on" | "failed";
  note: string | null;
};

export function SessionMapping() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [params] = useSearchParams();
  const groupId = params.get("group") ?? "";
  const cohortId = params.get("cohort") ?? "";
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const { discovery, settings } = useSettings();
  const sessionStore = useSessionStore();

  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [mappings, setMappings] = useState<BoxMapping[]>([]);
  const [profiles, setProfiles] = useState<Record<string, TaskProfile | null>>(
    {},
  );
  const [flashStates, setFlashStates] = useState<Record<number, FlashState>>(
    {},
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<Phase>("review");
  const [placeIndex, setPlaceIndex] = useState(0);
  const [light, setLight] = useState<Light | null>(null);

  const connected = status === "connected";
  const sketches = discovery.sketches;
  const portStates = useAllPortStatuses();
  const utility = useUtilityStatus();

  /**
   * Boxes this machine can actually flash — configured *and* bound to a board.
   * A cohort's stored assignments are planning data and may name boxes this rig
   * has never had, so they are not evidence that a board exists.
   */
  const configuredBoxes = useMemo(
    () =>
      new Set(
        settings.boxes.filter((b) => b.hardwareId !== null).map((b) => b.box),
      ),
    [settings.boxes],
  );

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
    handledExit.current = true;
    if (sessionId)
      await abandonSession(client, sessionId).catch(() => undefined);
    navigate("/session/new");
  }

  /*
   * **Leaving by any other door abandons the record too.**
   *
   * `/session/new` creates the session server-side *before* navigating here, so
   * until this step confirms a mapping the record exists in `configuring` with
   * nothing behind it. Back handles that above — but a sidebar click doesn't,
   * and the orphan is permanent: it reappears under "Set-up in progress" on the
   * Dashboard forever, and every Continue-then-leave cycle adds another.
   *
   * Deliberately narrow. It abandons only a record we *positively know* is
   * still `configuring` and that this component never confirmed — never on a
   * failed status fetch, where `session` is null and the truth is unknown, and
   * never once `confirmMapping` has succeeded, because the fetched status is
   * from mount and would still read `configuring` for a session that now holds
   * the rig. Guessing in either direction ends a session someone is running.
   */
  const handledExit = useRef(false);
  const abandonOnExit = useRef<{ id: string | null; abandonable: boolean }>({
    id: null,
    abandonable: false,
  });
  abandonOnExit.current = {
    id: sessionId ?? null,
    abandonable: session?.status === "configuring",
  };
  useEffect(() => {
    return () => {
      const { id, abandonable } = abandonOnExit.current;
      if (handledExit.current || !id || !abandonable) return;
      void abandonSession(client, id).catch(() => undefined);
    };
  }, [client]);

  // Re-entry via Switch Group: the previous groups already ran, so the only
  // honest exits are onward (flash) or ending the session outright.
  async function endFromHere() {
    if (!sessionId) return;
    handledExit.current = true;
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

  /**
   * This rig's saved defaults for a sketch (`tasks.md` §6.1) — the layer
   * a box starts on, and what its overrides are measured against.
   */
  const rigDefaults = useCallback(
    (sketchPath: string | null) =>
      settings.taskDefaults[sketchName(sketchPath)] ?? {},
    [settings.taskDefaults],
  );

  // Load each chosen sketch's Task Profile and seed its config from the merged
  // defaults (§6.9: profile, then rig). Rows are identified by animal, not by
  // box — box numbers are editable here and may collide mid-edit.
  const loadProfile = useCallback(
    async (animalId: string, sketchPath: string | null) => {
      if (!sketchPath) return;
      const seed = (profile: TaskProfile | null) =>
        setMappings((prev) =>
          prev.map((m) =>
            m.animalId === animalId
              ? {
                  ...m,
                  config: defaultConfig(profile, rigDefaults(sketchPath)),
                }
              : m,
          ),
        );
      if (profiles[sketchPath] !== undefined) {
        seed(profiles[sketchPath] ?? null);
        return;
      }
      try {
        const profile = await getTaskProfile(client, sketchPath);
        setProfiles((prev) => ({ ...prev, [sketchPath]: profile }));
        seed(profile);
      } catch (err) {
        // A malformed task.json is surfaced but doesn't block: the sketch is
        // treated as profile-less (bare START).
        setError(errorMessage(err));
        setProfiles((prev) => ({ ...prev, [sketchPath]: null }));
      }
    },
    [client, profiles, rigDefaults],
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

  // A failed flash leaves its box in `ERROR`, and `ERROR → FLASHING` is
  // refused (`dashboard.md` §5) — so without an ack here, the most
  // likely place to *hit* a flash failure was also the one place you couldn't
  // recover from it without a detour through Debug Mode.
  const erroredBoxes = useMemo(
    () =>
      mappings
        .filter((m) => portStates[m.box]?.state === "ERROR")
        .map((m) => m.box),
    [mappings, portStates],
  );

  /**
   * Mapped boxes with no board behind them. Flashing one is a guaranteed
   * failure, and because §4 flashes in sequence the failure lands *after*
   * earlier boxes are already reflashed — so it is worth saying before the
   * button is pressed rather than discovering it halfway through the rig.
   */
  const unconfiguredBoxes = useMemo(
    () =>
      [...new Set(mappings.map((m) => m.box))]
        .filter((box) => !configuredBoxes.has(box))
        .sort((a, b) => a - b),
    [mappings, configuredBoxes],
  );

  /**
   * The walk order is by **box number**, never by animal: the operator is
   * walking down a bench, and sending them from box 5 to box 2 and back is how
   * an animal ends up in the wrong chamber.
   */
  const placementOrder = useMemo(
    () => [...mappings].sort((a, b) => a.box - b.box),
    [mappings],
  );
  const current =
    phase === "placing" ? (placementOrder[placeIndex] ?? null) : null;
  const currentBox = current?.box ?? null;

  // A rig with no utility sketch still gets the guided walk — it just names the
  // box instead of lighting it. The lights are the better version of the same
  // instruction, not a prerequisite for giving it.
  const canLight =
    utility.configured && utility.canIdentify && utility.message === null;

  /**
   * One serial queue for identify calls. Command handlers run concurrently
   * sidecar-side, so the "off" for the box being left and the "on" for the box
   * being arrived at could otherwise land out of order — and the loser of that
   * race is a box left lit with nothing pointing at it.
   */
  const identifyChain = useRef<Promise<unknown>>(Promise.resolve());
  const identify = useCallback(
    (box: number, on: boolean) => {
      const run = () => client.call(CMD.UTILITY_IDENTIFY, { box, on });
      const next = identifyChain.current.then(run, run);
      // A failed link must not poison the queue for the next box.
      identifyChain.current = next.catch(() => undefined);
      return next;
    },
    [client],
  );

  /**
   * Light the box the operator is being sent to, and put it out again on the
   * way past. The cleanup is the *only* thing that turns a light off, so every
   * exit — next animal, going back, cancelling, navigating away — is covered
   * by one path rather than four that each have to remember.
   */
  useEffect(() => {
    if (!connected || currentBox === null) return;
    if (!canLight) {
      setLight({ box: currentBox, status: "failed", note: null });
      return;
    }
    let active = true;
    setLight({ box: currentBox, status: "pending", note: null });
    void identify(currentBox, true)
      .then((result) => {
        if (!active) return;
        setLight({
          box: currentBox,
          status: result.delivered ? "on" : "failed",
          note: result.state.detail,
        });
      })
      .catch((err) => {
        if (active)
          setLight({
            box: currentBox,
            status: "failed",
            note: errorMessage(err),
          });
      });
    return () => {
      active = false;
      void identify(currentBox, false).catch(() => undefined);
    };
  }, [connected, currentBox, canLight, identify]);

  function startPlacement() {
    setError(null);
    setPlaceIndex(0);
    setPhase("placing");
    // Nudge these boxes toward baseline in case one still carries the last
    // session's task sketch. Deliberately not awaited: the walk starts now,
    // and a box that isn't ready yet is a box without a light, not a blocker.
    if (utility.configured) {
      void client
        .call(CMD.UTILITY_ENSURE, { boxes: placementOrder.map((m) => m.box) })
        .catch(() => undefined);
    }
  }

  function advancePlacement() {
    if (placeIndex + 1 >= placementOrder.length) {
      setPhase("placed");
      setLight(null);
    } else {
      setPlaceIndex((n) => n + 1);
    }
  }

  function retreatPlacement() {
    if (placeIndex === 0) {
      setPhase("review");
      setLight(null);
    } else {
      setPlaceIndex((n) => n - 1);
    }
  }

  async function acknowledge(box: number) {
    setError(null);
    try {
      await client.call(CMD.PORT_ERROR_ACK, { box });
      // The star stays red on a cleared fault otherwise — the card would
      // still read "failed" for a box that is now ready to flash.
      setFlashStates((s) => ({ ...s, [box]: "idle" }));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

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
    : phase === "placing"
      ? `Placing ${placeIndex + 1} of ${placementOrder.length} — ${current ? (names[current.animalId]?.name ?? "this animal") : ""} into box ${currentBox}.`
      : phase === "placed"
        ? "Every animal is placed. Confirm and flash to start."
        : // Before "pick a sketch": with an unset or moved Arduino Directory
          // there are none to pick, and the picker alone cannot say so.
          sketches.length === 0
          ? "No sketches found — set the Arduino Directory on the Task tab."
          : erroredBoxes.length > 0
            ? `Box ${erroredBoxes.join(", ")} needs acknowledging before it can flash.`
            : duplicateBox !== null
              ? `Two animals share box ${duplicateBox} — move one first.`
              : !allChosen
                ? "Pick a sketch for every box, then confirm."
                : "Confirm the boxes, then place the animals one at a time.";

  async function confirmAndFlash() {
    if (!sessionId || !allChosen) return;
    setBusy(true);
    setError(null);
    try {
      await confirmMapping(client, sessionId, groupId, mappings);
      // Past this point the record is no longer an abandonable orphan: it holds
      // the rig. The unmount cleanup must not touch it even if a flash below
      // fails and the operator leaves from here.
      handledExit.current = true;

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
      navigate(
        `/session/${sessionId}/control?cohort=${cohort?.id ?? ""}&group=${groupId}`,
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    // Same scaffold as the Dashboard and step 1: the sky is continuous across
    // the whole guided flow, and only the chrome over it changes.
    <div className="relative h-full">
      <SkyBackdrop />

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit — between sky routes the shell holds the page
        // opaque (`AppShell`).
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-5xl px-8 py-8">
          <SessionJourney step="boxes" hint={hint} group={groupInfo} />
          <h1 className="font-display text-[22px] text-starlight">
            {phase === "placing" ? "Place the animals" : "Confirm boxes"}
          </h1>
          <p className="mt-1 text-[12px] text-static">
            {phase === "placing"
              ? "One at a time, in box order. The mapping is locked while you walk the rig."
              : "Changes here apply to this run only."}
          </p>

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

          {/* A dead end otherwise: the picker can only show "— select a sketch —",
          the flow keeps asking for a sketch, and nothing says where sketches
          come from. This is the ordinary first-run state, and the state after
          the Arduino Directory moves. */}
          {connected && sketches.length === 0 && (
            <div className="mt-4 flex items-start justify-between gap-4 rounded-sm border border-halo px-3 py-2.5">
              <div className="min-w-0">
                <p
                  className="text-[12px]"
                  style={{ color: "var(--color-status-warning)" }}
                >
                  No sketches found.
                </p>
                <p className="mt-0.5 text-[12px] text-static">
                  Set the Arduino Directory to the folder holding your sketch
                  categories, then come back — there is nothing to flash until
                  then.
                </p>
              </div>
              <div className="shrink-0">
                <Button onClick={() => navigate("/task")}>Open Task</Button>
              </div>
            </div>
          )}

          {/* The cohort's stored box numbers are planning data; this rig may never
          have had those boxes. Flashing is sequential, so an unbound box fails
          only after the boxes before it have already been reflashed. */}
          {unconfiguredBoxes.length > 0 && (
            <div className="mt-4 flex items-start justify-between gap-4 rounded-sm border border-halo px-3 py-2.5">
              <div className="min-w-0">
                <p
                  className="text-[12px]"
                  style={{ color: "var(--color-status-warning)" }}
                >
                  {unconfiguredBoxes.length === 1
                    ? `Box ${unconfiguredBoxes[0]} has no board bound to it.`
                    : `Boxes ${unconfiguredBoxes.join(", ")} have no board bound to them.`}
                </p>
                <p className="mt-0.5 text-[12px] text-static">
                  Flashing stops at the first one that fails, after the boxes
                  before it have already been flashed. Bind them on the Rig tab, or
                  move these animals to boxes that are set up.
                </p>
              </div>
              <div className="shrink-0">
                <Button onClick={() => navigate("/task")}>Open Task</Button>
              </div>
            </div>
          )}

          {mappings.length === 0 && (
            <p className="mt-6 text-[13px] text-static">
              No box-assigned animals in this group.
            </p>
          )}

          {/* The drawing is the walk's instruction, not decoration: one animal, one
          chamber, the number the operator is looking for. Outside the walk it
          has nothing to say and would only pull attention off the settings
          being edited, so it isn't rendered at all. */}
          {current !== null && (
            <RatPlacementBanner
              boxes={[current.box]}
              caption={`Lift ${names[current.animalId]?.name ?? "this animal"} into box ${current.box}, then close the enclosure.`}
            />
          )}

          {mappings.length > 0 && (
            // `items-start`: a card growing its config form must not stretch the
            // compact cards sharing its row. The top margin picks up the slack the
            // banner leaves behind when it isn't rendered.
            //
            // **Leaves the way Mission Control's tiles arrive.** These cards and
            // the box tiles that replace them on the next screen are the same
            // six boxes; sliding one set out to the right as the other slides in
            // from it makes that continuity legible, where a plain crossfade
            // just reads as one screen replacing another. Same offset and same
            // spring as the tile ↔ star-panel swap, so the whole session flow
            // uses one gesture for "these boxes, seen another way".
            <motion.div
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 12 }}
              transition={springPanel}
              className={`${current !== null ? "mt-3" : "mt-6"} grid grid-cols-1 items-start gap-3 lg:grid-cols-2`}
            >
              {mappings.map((mapping) => {
                const animal = names[mapping.animalId];
                const profile = mapping.sketchPath
                  ? (profiles[mapping.sketchPath] ?? null)
                  : null;
                const isCurrent = current?.animalId === mapping.animalId;
                // Everything that isn't the one tile being pointed at recedes, and
                // stops accepting clicks: mid-walk, changing a box the operator has
                // already filled would silently invalidate the animals behind them.
                const dimmed = phase === "placing" && !isCurrent;
                const placed =
                  phase === "placed" ||
                  (phase === "placing" &&
                    placementOrder.findIndex(
                      (m) => m.animalId === mapping.animalId,
                    ) < placeIndex);
                return (
                  <motion.div
                    key={mapping.animalId}
                    animate={{ opacity: dimmed ? 0.4 : 1 }}
                    transition={springSnappy}
                    className={`hud rounded-md p-4 ${isCurrent ? "attention-border" : ""}`}
                    style={{ pointerEvents: dimmed ? "none" : "auto" }}
                    aria-current={isCurrent ? "step" : undefined}
                  >
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
                      {/* The walk's only persistent record of itself: which
                      animals are already in their boxes. Without it, coming
                      back to the screen means counting tiles. */}
                      {placed && (
                        <Check
                          size={15}
                          strokeWidth={2}
                          className="mt-1 shrink-0"
                          style={{ color: "var(--color-ion)" }}
                          aria-label="placed"
                        />
                      )}
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
                        disabled={phase !== "review"}
                        className="min-w-0 flex-1 truncate"
                      />
                      <div className="flex w-5 shrink-0 items-center justify-center">
                        {mapping.sketchPath !== null && <FlowArrow />}
                      </div>
                      <Select
                        label={`Box for ${animal?.name ?? "animal"}`}
                        value={String(mapping.box)}
                        // All six stay selectable — a box can be assigned before
                        // its board is bound — but an unbound one says so here
                        // rather than only failing at flash time.
                        options={[1, 2, 3, 4, 5, 6].map((n) => ({
                          value: String(n),
                          label: configuredBoxes.has(n)
                            ? `Box ${n}`
                            : `Box ${n} · unbound`,
                        }))}
                        disabled={phase !== "review"}
                        onChange={(v) =>
                          setMappings((prev) =>
                            prev.map((m) =>
                              m.animalId === mapping.animalId
                                ? { ...m, box: Number(v) }
                                : m,
                            ),
                          )
                        }
                      />
                    </div>

                    {/* The instruction itself, on the tile it is about. It sits
                    below the mapping line so the eye reads name → box → "put
                    it there", which is the order the sentence is spoken in. */}
                    {isCurrent && (
                      <motion.div
                        initial={{ opacity: 0, y: -4 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={springSnappy}
                        className="mt-3 flex items-center justify-between gap-3 rounded-sm border border-halo px-3 py-2.5"
                      >
                        <div className="min-w-0">
                          <p className="text-[13px] leading-snug text-starlight">
                            Place this animal in{" "}
                            <span className="font-mono text-pulsar">
                              box {mapping.box}
                            </span>
                          </p>
                          <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-static">
                            <Lightbulb
                              size={12}
                              strokeWidth={1.75}
                              className="shrink-0"
                              style={
                                light?.status === "on"
                                  ? { color: "var(--color-ion)" }
                                  : undefined
                              }
                            />
                            {lightHint(light, canLight)}
                          </p>
                        </div>
                        <Button
                          variant="primary"
                          disabled={busy}
                          onClick={advancePlacement}
                          className="shrink-0"
                        >
                          <Check size={13} strokeWidth={2} />
                          Enclosure closed
                        </Button>
                      </motion.div>
                    )}

                    {/* Recovery in place: a box left in `ERROR` (usually by the
                    flash that just failed) can't be flashed again until the
                    fault is acknowledged, so the ack lives on the card that
                    is stuck rather than only in Debug Mode. Same shape as
                    `NodeDetail`'s row. */}
                    {portStates[mapping.box]?.state === "ERROR" && (
                      <div
                        className="mt-3 flex items-center gap-2 rounded-sm border border-halo px-2.5 py-2 text-[11px]"
                        style={{ color: "var(--color-status-error)" }}
                      >
                        <CircleAlert
                          size={13}
                          strokeWidth={1.75}
                          className="shrink-0"
                        />
                        <span
                          className="min-w-0 flex-1 truncate"
                          title={faultReason(portStates[mapping.box]?.reason)}
                        >
                          {faultReason(portStates[mapping.box]?.reason)}
                        </span>
                        <Button
                          disabled={busy || !connected}
                          onClick={() => void acknowledge(mapping.box)}
                        >
                          Acknowledge
                        </Button>
                      </div>
                    )}

                    {/* Per-run overrides slide the tile open with the app's
                    snappy spring; only a chosen sketch with a profile has
                    any — an unchosen tile never expands. The form itself is
                    collapsed within that: it holds forty-odd fields now, and
                    six of those open at once would bury this screen's actual
                    job (§6.9). */}
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
                            baseline={defaultConfig(
                              profile,
                              rigDefaults(mapping.sketchPath),
                            )}
                            disabled={phase !== "review"}
                            onChange={(config) =>
                              setMappings((prev) =>
                                prev.map((m) =>
                                  m.animalId === mapping.animalId
                                    ? { ...m, config }
                                    : m,
                                ),
                              )
                            }
                          />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                );
              })}
            </motion.div>
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
            {/* Placement sits between confirming the mapping and flashing on
            purpose: the boxes are still carrying the utility sketch, which is
            the only firmware that can be asked to light one (§3.5). Flashing
            first would put the tasks on and the lights out of reach. */}
            {phase === "review" && (
              <Button
                variant="primary"
                onClick={startPlacement}
                disabled={
                  !allChosen || busy || !connected || mappings.length === 0
                }
              >
                Place the animals
                <ArrowRight size={13} strokeWidth={2} />
              </Button>
            )}

            {phase === "placing" && (
              <>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={retreatPlacement}
                >
                  {placeIndex === 0 ? "Back to boxes" : "Previous animal"}
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={advancePlacement}
                >
                  Skip this box
                </Button>
              </>
            )}

            {phase === "placed" && (
              <>
                <Button
                  variant="primary"
                  onClick={() => void confirmAndFlash()}
                  disabled={
                    !allChosen || busy || !connected || erroredBoxes.length > 0
                  }
                  {...(erroredBoxes.length > 0
                    ? {
                        title:
                          "Acknowledge the box error first — a box in ERROR can't be flashed",
                      }
                    : {})}
                >
                  <Zap size={13} strokeWidth={1.75} />
                  {busy ? "Flashing…" : "Confirm and flash"}
                  {!busy && <ArrowRight size={13} strokeWidth={2} />}
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={startPlacement}
                >
                  <Undo2 size={13} strokeWidth={1.75} />
                  Walk the boxes again
                </Button>
              </>
            )}

            {phase !== "placing" &&
              (midSession ? (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => void endFromHere()}
                >
                  End session
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => void backToConfig()}
                >
                  Back
                </Button>
              ))}
          </div>
        </section>
      </motion.div>
    </div>
  );
}

/**
 * What the box's light is doing, said in terms of what the operator should do.
 *
 * A box that can't be lit is not an error and must not read as one — the
 * instruction is still complete without it, because the box number is written
 * on the tile and on the chamber. The light is a confirmation, not the
 * message.
 */
function lightHint(light: Light | null, canLight: boolean): string {
  if (!canLight) {
    return "Match the number on the chamber — no utility sketch is set up to light it.";
  }
  if (light?.status === "pending") return "Lighting the box…";
  if (light?.status === "on")
    return "Its light is on, and goes out when you confirm.";
  return (
    light?.note ?? "Couldn't light this box — go by the number on the chamber."
  );
}

/**
 * What put this box in `ERROR`, in words the operator can act on.
 *
 * A fault that happened in this window carries the real cause ("flash failed:
 * …"). One inherited from before a reload carries only the replay placeholder
 * (`websocket-protocol.md` §1.2 sends `reason: "initial state"`), which
 * explains nothing — so that case gets a sentence instead of a shrug.
 */
function faultReason(reason: string | undefined): string {
  if (!reason || reason === "initial state") {
    return "This box is in an error state from an earlier operation.";
  }
  return reason;
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
    state === "done"
      ? NODE_ACCENT
      : state === "failed"
        ? "var(--color-status-error)"
        : NODE_PRIMARY;
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
