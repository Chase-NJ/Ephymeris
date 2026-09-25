import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowRight,
  Check,
  CheckCheck,
  CircleAlert,
  Lightbulb,
  Undo2,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { Button } from "@/components/common/controls";
import { Dropdown } from "@/components/common/Dropdown";
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
import { useIsRecordingSession, useSessionStore } from "@/lib/sessions/context";
import {
  clearSetupResume,
  getSetupDraft,
  setSetupDraft,
} from "@/lib/sessions/setupResume";
import {
  animalsInGroup,
  defaultConfig,
  groupsRunCount,
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
 *
 * **The flash rides the walk** (§7.4). The mapping is confirmed the moment the
 * walk starts, and each box is flashed the moment its enclosure is closed —
 * while the operator is already carrying the next animal. A six-box group used
 * to be placed and *then* flashed six times in a row, with the operator
 * watching a progress star; now the compile time hides inside the walk and the
 * last confirmation lands on a rig that is nearly ready. Two shortcuts sit
 * beside the walk for the operator who has already done it by hand: "They're
 * already in" from the review, and "All animals are in" from any step of it.
 */

type FlashState = "idle" | "queued" | "flashing" | "done" | "failed";

/**
 * How long a queued flash waits for its port to come free before giving up.
 * A baseline restore still in flight on that box is the usual reason — it was
 * queued the instant the walk began, and a compile is a minute or two.
 */
const PORT_WAIT_MS = 180_000;

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

  // What the operator had chosen here before visiting another tab
  // (`setupResume.ts`) — keyed by session AND group, so one group's sketches
  // can never seed another's.
  const draftKey = `boxes:${sessionId ?? ""}:${groupId}`;
  const [draft] = useState(() => getSetupDraft<BoxMapping[]>(draftKey));

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
        // A draft is only trusted while it still describes this group: an
        // animal moved or removed in Cohorts meanwhile starts the step over.
        const animals = animalsInGroup(loaded, groupId);
        const sameAnimals =
          draft !== undefined &&
          draft.length === animals.length &&
          draft.every((m) => animals.some((a) => a.id === m.animalId));
        if (sameAnimals) {
          setMappings(draft);
          // The chosen sketches' profiles, for their config forms — fetched
          // without re-seeding, which would undo the operator's edits.
          const paths = [...new Set(draft.flatMap((m) => (m.sketchPath ? [m.sketchPath] : [])))];
          for (const path of paths) {
            void getTaskProfile(client, path)
              .catch(() => null)
              .then((profile) => {
                if (active) setProfiles((prev) => ({ ...prev, [path]: profile }));
              });
          }
          return;
        }
        setMappings(
          animals.map((a) => ({
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
    // The draft is read once, at mount, as a starting point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, connected, cohortId, groupId]);

  // Kept current, so a sidebar click at any moment leaves nothing behind.
  useEffect(() => {
    if (mappings.length > 0) setSetupDraft(draftKey, mappings);
  }, [draftKey, mappings]);

  // What "back" means depends on whether the session has run yet (§3): the
  // record's status distinguishes first entry (`configuring`) from re-entry
  // from the group step (`running` — between groups, or continued).
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
    if (sessionId)
      await abandonSession(client, sessionId).catch(() => undefined);
    navigate("/session/new");
  }

  /*
   * **Leaving by any other door keeps the record.** A sidebar click, or the
   * Open Task / Open Rig doors below, is a visit — the operator checking
   * something mid-setup — and the Dashboard tab brings them back here
   * (`setupResume.ts`). This step used to abandon the `configuring` record on
   * unmount, to stop Continue-then-leave cycles stranding orphans; a record
   * left now is one the sidebar offers to resume, and the Dashboard dock lists
   * it with Discard, so it is never stranded out of sight.
   */

  // Re-entry from the group step: earlier groups already ran, so the honest
  // exits are onward (flash), back to the choice of group, or ending the session.
  async function endFromHere() {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const ended = await endSession(client, sessionId);
      clearSetupResume();
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

  /*
   * --- the flash queue -----------------------------------------------------
   *
   * One box at a time, in the order their enclosures were closed, never in
   * parallel (§7.4 — two `arduino-cli` builds at once on the lab machines is
   * slower than one after the other, and a half-flashed pair is worse than a
   * whole one). The queue and the worker live in refs because they outlive any
   * one render: a flash takes a minute, and the operator is three boxes down
   * the bench by the time it lands. The card states are the only thing React
   * sees.
   *
   * Each flash waits for two things first. The identify light on that box goes
   * out through the same serial queue the walk lights with, so the flash waits
   * behind it rather than racing it; and the port has to be free — a baseline
   * restore queued the instant the walk began may still be flashing that very
   * box. `PASSTHROUGH` counts as free: entering `FLASHING` force-releases a
   * console (`dashboard.md` §5.2), and a light whose console was just taken
   * goes out with the reset that follows anyway.
   */
  const portStatesRef = useRef(portStates);
  portStatesRef.current = portStates;
  const flashStatesRef = useRef(flashStates);
  flashStatesRef.current = flashStates;
  const mappingsRef = useRef(mappings);
  mappingsRef.current = mappings;
  const queueRef = useRef<number[]>([]);
  const drainingRef = useRef(false);

  const setFlashState = useCallback((box: number, state: FlashState) => {
    flashStatesRef.current = { ...flashStatesRef.current, [box]: state };
    setFlashStates(flashStatesRef.current);
  }, []);

  const waitForPort = useCallback((box: number) => {
    return new Promise<void>((resolve, reject) => {
      const started = Date.now();
      const tick = () => {
        const state = portStatesRef.current[box]?.state ?? "IDLE";
        if (state === "IDLE" || state === "PASSTHROUGH") return resolve();
        if (state === "ERROR") {
          return reject(
            new Error("the box is in an error state — acknowledge it, then retry the flash."),
          );
        }
        if (Date.now() - started > PORT_WAIT_MS) {
          return reject(
            new Error(`the port stayed ${state.toLowerCase()} for three minutes — retry once it is free.`),
          );
        }
        window.setTimeout(tick, 400);
      };
      tick();
    });
  }, []);

  const drain = useCallback(async () => {
    if (drainingRef.current) return;
    drainingRef.current = true;
    try {
      while (queueRef.current.length > 0) {
        const box = queueRef.current.shift()!;
        const sketchPath = mappingsRef.current.find((m) => m.box === box)?.sketchPath;
        if (!sketchPath) continue;
        await identifyChain.current;
        setFlashState(box, "flashing");
        try {
          await waitForPort(box);
          await flashForSession(client, box, sketchPath);
          setFlashState(box, "done");
        } catch (err) {
          setFlashState(box, "failed");
          setError(`Box ${box} didn't flash: ${errorMessage(err)}`);
        }
      }
    } finally {
      drainingRef.current = false;
    }
  }, [client, setFlashState, waitForPort]);

  /** Queue boxes that aren't already flashed, flashing or waiting. */
  const enqueue = useCallback(
    (boxes: number[]) => {
      const fresh = boxes.filter((box) => {
        const state = flashStatesRef.current[box] ?? "idle";
        return state === "idle" || state === "failed";
      });
      if (fresh.length === 0) return;
      for (const box of fresh) setFlashState(box, "queued");
      queueRef.current.push(...fresh);
      void drain();
    },
    [drain, setFlashState],
  );

  /**
   * Confirm the mapping and start the walk — or, for the operator who has
   * already placed everyone, skip straight to flashing the lot.
   *
   * Confirming *first* is what lets the boxes be flashed as the walk goes:
   * the confirmed mapping puts the utility baseline on hold, and without that
   * a box falling idle after its task flash would be quietly restored to the
   * utility sketch before the session ever started (`settings.md` §8.2). The
   * baseline nudge goes out just before, for a box still carrying last
   * session's sketch; the hold that follows drops whatever of it hasn't
   * started, and a restore already in flight is what `waitForPort` is for.
   */
  async function startPlacement(skipWalk = false) {
    if (!sessionId || !allChosen) return;
    setBusy(true);
    setError(null);
    try {
      if (utility.configured) {
        void client
          .call(CMD.UTILITY_ENSURE, { boxes: placementOrder.map((m) => m.box) })
          .catch(() => undefined);
      }
      await confirmMapping(client, sessionId, groupId, mappings);
      // A confirmed mapping begins a fresh group run — drop the previous
      // group's telemetry and finished-run messages so Mission Control
      // doesn't show them against the new animals.
      sessionStore.resetRun();
      queueRef.current = [];
      flashStatesRef.current = {};
      setFlashStates({});
      if (skipWalk) {
        setPlaceIndex(placementOrder.length);
        setPhase("placed");
        enqueue(placementOrder.map((m) => m.box));
      } else {
        setPlaceIndex(0);
        setPhase("placing");
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** The walk again, without re-confirming: boxes already flashed stay flashed. */
  function walkAgain() {
    setError(null);
    setPlaceIndex(0);
    setPhase("placing");
  }

  function advancePlacement() {
    if (current) enqueue([current.box]);
    if (placeIndex + 1 >= placementOrder.length) {
      setPhase("placed");
      setLight(null);
    } else {
      setPlaceIndex((n) => n + 1);
    }
  }

  /** Every remaining box at once — the operator did the walk without us. */
  function placeAll() {
    enqueue(placementOrder.slice(placeIndex).map((m) => m.box));
    setPlaceIndex(placementOrder.length);
    setPhase("placed");
    setLight(null);
  }

  function retreatPlacement() {
    if (placeIndex === 0) {
      // Back to editing: the mapping can change under a flash that already
      // landed, so nothing flashed so far is trusted — the next walk confirms
      // and flashes afresh. Boxes still waiting simply stop waiting.
      queueRef.current = [];
      flashStatesRef.current = {};
      setFlashStates({});
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
      setFlashState(box, "idle");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  // A recording session has one more step before Mission Control: the boxes
  // are mapped and flashed now, which is exactly what the recording setup
  // needs in order to ask which headstage port each one is on.
  const isRecording = useIsRecordingSession(sessionId);
  const controlUrl =
    `/session/${sessionId}/${isRecording ? "recording" : "control"}` +
    `?cohort=${cohort?.id ?? ""}&group=${groupId}`;
  const flashedCount = mappings.filter((m) => flashStates[m.box] === "done").length;
  const allFlashed = mappings.length > 0 && flashedCount === mappings.length;
  const flashPending = mappings.some((m) => {
    const state = flashStates[m.box];
    return state === "queued" || state === "flashing";
  });

  // Everyone placed and every box flashed: the rig is ready, and nothing on
  // this screen is the next step any more.
  useEffect(() => {
    if (phase !== "placed" || !allFlashed) return;
    navigate(controlUrl);
  }, [phase, allFlashed, controlUrl, navigate]);

  // Which group this is, for the rail's chip — only meaningful multi-group.
  const groupInfo = useMemo(() => {
    if (!cohort) return null;
    const groups = populatedGroups(cohort);
    const found = groups.find((g) => g.id === groupId);
    if (!found || groups.length < 2) return null;
    return { name: found.name, ran: groupsRunCount(cohort, session), count: groups.length };
  }, [cohort, groupId, session]);

  const hint = busy
    ? "Confirming the boxes…"
    : phase === "placing"
      ? `Placing ${placeIndex + 1} of ${placementOrder.length} — ${current ? (names[current.animalId]?.name ?? "this animal") : ""} into box ${currentBox}. Each box flashes as you close it.`
      : phase === "placed"
        ? allFlashed
          ? "Every box is flashed — opening Mission Control."
          : flashPending
            ? `Every animal is placed. Flashing ${flashedCount + 1} of ${mappings.length} — keep the boards plugged in.`
            : "A box didn't flash. Acknowledge it and retry, or walk the boxes again."
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
          <SessionJourney
            step="boxes"
            hint={hint}
            group={groupInfo}
            recording={isRecording}
          />
          <h1 className="font-display text-[22px] text-starlight">
            {phase === "placing"
              ? "Place the animals"
              : phase === "placed"
                ? "Flashing the boxes"
                : "Confirm boxes"}
          </h1>
          <p className="mt-1 text-[12px] text-static">
            {phase === "placing"
              ? "One at a time, in box order. Each box is flashed the moment you close it, while you fetch the next animal."
              : phase === "placed"
                ? "The boxes are flashing in the order you closed them. Mission Control opens when the last one lands."
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

          {/* A dead end otherwise: the picker can only show "— none —", the
          flow keeps asking for a sketch, and nothing says where sketches come
          from. The library ships with the app now, so an empty one means the
          install is damaged — and the fix an operator can actually reach is a
          saved task profile, which discovery serves like any other sketch. */}
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
                  The bundled library came up empty — the install may be
                  damaged. A task saved on the Task tab is flashable too, and
                  would appear here.
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
                {/* The advice says "the Rig tab", so the button goes there —
                    it used to open Task, one tab past where the fix lives. */}
                <Button onClick={() => navigate("/config")}>Open Rig</Button>
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

                    {/* What the flash queue is doing to this box, said on the
                    box — the star beside the name draws it, this names it. */}
                    <FlashLine
                      state={flashStates[mapping.box] ?? "idle"}
                      canRetry={
                        connected &&
                        portStates[mapping.box]?.state !== "ERROR" &&
                        phase !== "review"
                      }
                      onRetry={() => enqueue([mapping.box])}
                    />

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
                      <Dropdown
                        label={`Box for ${animal?.name ?? "animal"}`}
                        size="regular"
                        value={String(mapping.box)}
                        // All six stay selectable — a box can be assigned before
                        // its board is bound — but an unbound one says so here
                        // rather than only failing at flash time.
                        options={[1, 2, 3, 4, 5, 6].map((n) => ({
                          value: String(n),
                          label: `Box ${n}`,
                          ...(configuredBoxes.has(n) ? {} : { detail: "unbound" }),
                        }))}
                        placeholder="box"
                        disabled={phase !== "review"}
                        className="w-[110px] shrink-0"
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
              <>
                <Button
                  variant="primary"
                  onClick={() => void startPlacement()}
                  disabled={
                    !allChosen ||
                    busy ||
                    !connected ||
                    mappings.length === 0 ||
                    erroredBoxes.length > 0
                  }
                  {...(erroredBoxes.length > 0
                    ? {
                        title:
                          "Acknowledge the box error first — a box in ERROR can't be flashed",
                      }
                    : {})}
                >
                  {busy ? "Confirming…" : "Place the animals"}
                  {!busy && <ArrowRight size={13} strokeWidth={2} />}
                </Button>
                {/* The shortcut for a rig that was loaded before the screen
                    was opened: no walk, every box flashed in box order. */}
                <Button
                  variant="ghost"
                  onClick={() => void startPlacement(true)}
                  disabled={
                    !allChosen ||
                    busy ||
                    !connected ||
                    mappings.length === 0 ||
                    erroredBoxes.length > 0
                  }
                >
                  <CheckCheck size={13} strokeWidth={1.75} />
                  They&rsquo;re already in — flash all
                </Button>
              </>
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
                {/* The rest of the walk in one press — the operator who went
                    down the bench faster than the screen did. */}
                <Button variant="outline" disabled={busy} onClick={placeAll}>
                  <CheckCheck size={13} strokeWidth={1.75} />
                  All animals are in
                </Button>
              </>
            )}

            {phase === "placed" && (
              <>
                {/* Not a Confirm any more — the mapping was confirmed when the
                    walk began and the boxes are flashing on their own. This is
                    the door, and it opens itself the moment the last flash
                    lands; until then it reports the queue. */}
                <Button
                  variant="primary"
                  onClick={() => navigate(controlUrl)}
                  disabled={!allFlashed || !connected}
                >
                  <Zap size={13} strokeWidth={1.75} />
                  {allFlashed
                    ? "Open Mission Control"
                    : flashPending
                      ? `Flashing ${flashedCount + 1} of ${mappings.length}…`
                      : "Waiting on a failed box"}
                  {allFlashed && <ArrowRight size={13} strokeWidth={2} />}
                </Button>
                <Button variant="ghost" disabled={busy} onClick={walkAgain}>
                  <Undo2 size={13} strokeWidth={1.75} />
                  Walk the boxes again
                </Button>
              </>
            )}

            {phase !== "placing" &&
              (midSession ? (
                <>
                  {/* Before this page confirms, the session is between groups
                      and the choice can still be changed. */}
                  {phase === "review" && (
                    <Button
                      variant="ghost"
                      disabled={busy}
                      onClick={() =>
                        navigate(`/session/${sessionId}/group?cohort=${cohortId}`)
                      }
                    >
                      Pick another group
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() => void endFromHere()}
                  >
                    End session
                  </Button>
                </>
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
 * The queue's word on one box, under the name: waiting, flashing, flashed, or
 * failed with the way to try again. Nothing for an idle box — before the walk
 * reaches it there is nothing to say, and six "not yet" lines would be noise.
 */
function FlashLine({
  state,
  canRetry,
  onRetry,
}: {
  state: FlashState;
  canRetry: boolean;
  onRetry: () => void;
}) {
  if (state === "idle") return null;
  const colour =
    state === "done"
      ? "var(--color-ion)"
      : state === "failed"
        ? "var(--color-status-error)"
        : "var(--color-static)";
  const text =
    state === "queued"
      ? "waiting to flash"
      : state === "flashing"
        ? "flashing…"
        : state === "done"
          ? "flashed"
          : "flash failed";
  return (
    <div className="mt-2 flex items-center gap-2 font-mono text-[10px]" style={{ color: colour }}>
      <Zap size={11} strokeWidth={1.75} className="shrink-0" />
      <span>{text}</span>
      {state === "failed" && canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="ml-auto rounded-sm border border-halo px-2 py-0.5 text-starlight transition-colors hover:border-static/60"
        >
          Retry flash
        </button>
      )}
    </div>
  );
}

/**
 * §4 — a box mid-flash shows its star "flaring" rather than a generic spinner,
 * keeping the visual language consistent with the rest of the app. A queued
 * box holds a steady half-light: claimed, not yet burning.
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
            : { r: 5, opacity: state === "idle" ? 0.5 : state === "queued" ? 0.7 : 1 }
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
