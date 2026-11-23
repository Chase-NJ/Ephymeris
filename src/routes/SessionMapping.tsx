import { motion } from "framer-motion";
import {
  ArrowRight,
  Check,
  CheckCheck,
  CircleAlert,
  Copy,
  Lightbulb,
  SlidersHorizontal,
  Undo2,
  Zap,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { useNavigate, useParams } from "react-router";

import { Button } from "@/components/common/controls";
import { Dropdown } from "@/components/common/Dropdown";
import { RatPlacementBanner } from "@/components/sessions/RatPlacementBanner";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { SessionJourney } from "@/components/sessions/SessionJourney";
import {
  SketchPicker,
  TaskConfigForm,
} from "@/components/sessions/TaskConfigForm";
import { errorMessage } from "@/lib/cohorts/commands";
import { cancelFlashes } from "@/lib/hardware/commands";
import {
  useAllPortStatuses,
  useFlashQueue,
  useUtilityStatus,
} from "@/lib/hardware/context";
import { springPanel, springSnappy } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { offeredSketches } from "@/lib/settings/schema";
import {
  abandonSession,
  confirmMapping,
  endSession,
  flashSessionBoxes,
  getTaskProfile,
} from "@/lib/sessions/commands";
import {
  resumeWalkAt,
  sessionFlashCards,
  type FlashCard,
  type FlashCardState,
} from "@/lib/sessions/flashCards";
import { stepUrl } from "@/lib/sessions/flow";
import {
  WALK_START,
  assignBox,
  confirmPayload,
  copyOverrides,
  isPlaced,
  mappingReadiness,
  placementOrder as orderOfPlacement,
  rigDefaultsFor,
  seedRound,
  walkReducer,
  walkStop,
} from "@/lib/sessions/placementWalk";
import {
  clearSetupResume,
  getSetupDraft,
  setSetupDraft,
} from "@/lib/sessions/setupResume";
import { MAX_BOX, MIN_BOX, type Animal } from "@/lib/cohorts/types";
import {
  overriddenCount,
  type BoxMapping,
  type TaskProfile,
} from "@/lib/sessions/types";
import { useSessionFlow } from "@/lib/sessions/useSessionFlow";
import { CMD } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";
import {
  NODE_ACCENT,
  NODE_PRIMARY,
} from "@/components/chrome/constellationStyle";

/**
 * Step 2 — one round's set-up: which animals run, in which boxes, on which
 * task and parameters; then the guided placement walk and the flash sequence
 * (`ARCHITECTURE.md#mapping-and-the-placement-walk`,
 * `ARCHITECTURE.md#flash-sequence`).
 *
 * **Any animal, any box.** The rig is drawn as its six boxes, and each takes
 * any animal of the cohort. It opens on the animals that have not run in this
 * session yet, each on its usual box, and everything from there is the
 * operator's: swap two, leave a box empty, run an animal a second time.
 * Edits here are **session-local**: they never write back to the cohort's
 * usual boxes. Those change in Cohort management.
 *
 * **One place to tune.** The boxes are a list down the left and the selected
 * box's parameters fill the panel beside it, so the fields never move and
 * going from one animal to the next is one click, with "copy to the other
 * boxes on this task" for the edit that applies to several. A form inside
 * every box's card, in a two-column grid, made tuning across animals a matter
 * of opening, scrolling and closing six cards that kept pushing each other
 * around.
 *
 * The three phases are one screen rather than three, because they are three
 * views of the same six rows: choose (who, where, what), place (one animal at
 * a time, with that box lit), then flash. Splitting them into routes would
 * mean re-establishing which row you were on twice.
 *
 * **The flash rides the walk** (`ARCHITECTURE.md#flash-sequence`). The mapping is confirmed the moment the
 * walk starts, and each box is flashed the moment its enclosure is closed —
 * while the operator is already carrying the next animal. A six-box round used
 * to be placed and *then* flashed six times in a row, with the operator
 * watching a progress star; now the compile time hides inside the walk and the
 * last confirmation lands on a rig that is nearly ready. Two shortcuts sit
 * beside the walk for the operator who has already done it by hand: "They're
 * already in" from the review, and "All animals are in" from any step of it.
 *
 * **The sidecar flashes; this step asks and shows.** Each closed enclosure is
 * a `sessions.flash` for that box, and the cards read the sidecar's flash
 * queue (`ARCHITECTURE.md#the-flash-queue`), so leaving the step mid-walk or
 * reloading loses no flash, and coming back picks the walk up where it was.
 */

/** What the current box's identify light is doing, as far as we know. */
type Light = {
  box: number;
  status: "pending" | "on" | "failed";
  note: string | null;
};

export function SessionMapping() {
  const { id: sessionId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const { discovery, settings } = useSettings();

  // What the operator had chosen here before visiting another tab
  // (`setupResume.ts`) — keyed by session, and dropped when the round reaches
  // Mission Control, so one round's choices never seed the next.
  const draftKey = `boxes:${sessionId ?? ""}`;
  const [draft] = useState(() => getSetupDraft<BoxMapping[]>(draftKey));

  const {
    session,
    cohort,
    held,
    boxes: rigBoxes,
    ranAnimalIds,
    flow,
    error: loadError,
  } = useSessionFlow(sessionId);
  const [mappings, setMappings] = useState<BoxMapping[]>([]);
  /** The box whose parameters the tuning panel shows. */
  const [selectedBox, setSelectedBox] = useState<number>(MIN_BOX);
  const [profiles, setProfiles] = useState<Record<string, TaskProfile | null>>(
    {},
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // `review` edits the mapping, `placing` walks the rig, `placed` flashes
  // (`walkReducer`).
  const [walk, dispatchWalk] = useReducer(walkReducer, WALK_START);
  const { phase, index: placeIndex } = walk;
  const [light, setLight] = useState<Light | null>(null);

  const connected = status === "connected";
  const sketches = offeredSketches(discovery);
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

  // Open the round once per session visit, so a reconnect that reloads the
  // cohort never undoes the operator's edits: the draft they left, else the
  // mapping the rig already holds (a reload mid-walk), else the animals still
  // to run on their usual boxes (`seedRound`).
  const seeded = useRef<string | null>(null);
  useEffect(() => {
    if (!cohort || !sessionId || ranAnimalIds === null) return;
    if (seeded.current === sessionId) return;
    seeded.current = sessionId;
    const onTheRig: BoxMapping[] = rigBoxes.map((b) => ({
      box: b.box,
      animalId: b.animalId,
      sketchPath: b.sketchPath,
      overrides: {},
    }));
    const opening =
      draft === undefined && onTheRig.length > 0
        ? onTheRig
        : seedRound(cohort.animals, ranAnimalIds, draft);
    setMappings(opening);
    if (opening[0]) setSelectedBox(opening[0].box);
    // The draft and the rig are read once, at mount, as a starting point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cohort, sessionId, ranAnimalIds]);

  // Kept current, so a sidebar click at any moment leaves nothing behind. An
  // emptied rig is a choice too, once the round has been opened.
  useEffect(() => {
    if (seeded.current !== null) setSetupDraft(draftKey, mappings);
  }, [draftKey, mappings]);

  // What "back" means depends on whether the session has run yet (`ARCHITECTURE.md#mapping-and-the-placement-walk`): the
  // record's status distinguishes first entry (`configuring`) from re-entry
  // between rounds (`running` — after a round, or continued).
  const midSession = session?.status === "running";

  // First entry: abandon the never-run record rather than stranding it in
  // `configuring`. Best-effort — a failed abandon is no worse than the
  // orphan it replaces, so it never blocks leaving the step.
  async function backToConfig() {
    if (sessionId)
      await abandonSession(client, sessionId).catch(() => undefined);
    navigate(stepUrl.configure());
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

  // Re-entry between rounds: earlier rounds already ran, so the honest exits
  // are onward (flash) or ending the session.
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

  // This rig's saved defaults for a sketch, the merge's middle layer (`rigDefaultsFor`).
  const rigDefaults = useCallback(
    (sketchPath: string | null) =>
      rigDefaultsFor(settings.taskDefaults, sketchPath),
    [settings.taskDefaults],
  );

  /*
   * The chosen sketches' Task Profiles, for their config forms and for the
   * merge at confirm. A profile belongs to the sketch, so it is fetched once
   * per path, however many boxes chose it.
   *
   * Refetched when the set of chosen sketches changes and on every discovery
   * (a rescan, a saved task): a profile is regenerated in place by a task save,
   * a vocabulary edit or a wiring save, and the forms and the confirm must
   * read the one on disk now. Leaving for Open Task / Open Rig unmounts this
   * step, so returning refetches too.
   */
  const chosenPaths = useMemo(
    () =>
      [...new Set(mappings.flatMap((m) => (m.sketchPath ? [m.sketchPath] : [])))]
        .sort()
        .join("\u0000"),
    [mappings],
  );
  useEffect(() => {
    if (!chosenPaths) return;
    let active = true;
    for (const path of chosenPaths.split("\u0000")) {
      getTaskProfile(client, path).then(
        (profile) => {
          if (active) setProfiles((prev) => ({ ...prev, [path]: profile }));
        },
        (err) => {
          // A malformed task.json is surfaced but doesn't block: the sketch is
          // treated as profile-less (bare START).
          if (!active) return;
          setError(errorMessage(err));
          setProfiles((prev) => ({ ...prev, [path]: null }));
        },
      );
    }
    return () => {
      active = false;
    };
  }, [client, chosenPaths, discovery]);

  const names = useMemo(
    () => Object.fromEntries((cohort?.animals ?? []).map((a) => [a.id, a])),
    [cohort],
  );

  // Whether Confirm may be pressed (`mappingReadiness`). A failed flash leaves
  // its box in `ERROR`, which is acknowledged here: without that, the most
  // likely place to *hit* a flash failure was also the one place you couldn't
  // recover from it without a detour through Debug Mode.
  const readiness = useMemo(
    () => mappingReadiness(mappings, profiles, portStates, configuredBoxes),
    [mappings, profiles, portStates, configuredBoxes],
  );
  const { erroredBoxes, unconfiguredBoxes } = readiness;

  // Walked by box number, never by animal (`placementOrder`).
  const placementOrder = useMemo(() => orderOfPlacement(mappings), [mappings]);
  const current = walkStop(walk, placementOrder);
  const currentBox = current?.box ?? null;

  // The walk carries the selection with it, so the panel beside the list is
  // always about the box the operator is standing at.
  useEffect(() => {
    if (currentBox !== null) setSelectedBox(currentBox);
  }, [currentBox]);

  const roster = useMemo(
    () =>
      [...(cohort?.animals ?? [])].sort((a, b) =>
        a.name.localeCompare(b.name, undefined, { numeric: true }),
      ),
    [cohort],
  );
  const benched = useMemo(
    () => roster.filter((a) => !mappings.some((m) => m.animalId === a.id)),
    [roster, mappings],
  );
  const selected = mappings.find((m) => m.box === selectedBox) ?? null;
  /** The task every box is on, or null when they differ or none is chosen. */
  const commonSketch =
    mappings.length > 0 && mappings.every((m) => m.sketchPath === mappings[0]!.sketchPath)
      ? mappings[0]!.sketchPath
      : null;

  function patchBox(box: number, changes: Partial<BoxMapping>) {
    setMappings((prev) => prev.map((m) => (m.box === box ? { ...m, ...changes } : m)));
  }

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
   * --- the flashes ---------------------------------------------------------
   *
   * One box at a time, in the order their enclosures were closed, run by the
   * sidecar's one flash queue (`ARCHITECTURE.md#the-flash-queue`): it waits
   * for each port to come free — a baseline restore queued the instant the
   * walk began may still be flashing that very box — and reads each box's
   * sketch from the confirmed mapping when its turn comes. Before the mapping
   * is confirmed here, every card is idle.
   */
  const flashQueue = useFlashQueue();
  const flashes = useMemo(
    () =>
      sessionFlashCards(
        phase === "review" ? null : flashQueue,
        mappings.map((m) => m.box),
      ),
    [phase, flashQueue, mappings],
  );

  /**
   * Ask for boxes that aren't already flashed, flashing or waiting. After the
   * identify queue, as the walk lights with: the light for the box being left
   * goes out through the same serial port the flash is about to take.
   */
  const enqueue = useCallback(
    (boxes: number[]) => {
      if (!sessionId) return;
      const fresh = boxes.filter((box) => {
        const state = flashes.cards.get(box)?.state ?? "idle";
        return state === "idle" || state === "failed";
      });
      if (fresh.length === 0) return;
      void identifyChain.current
        .then(() => flashSessionBoxes(client, sessionId, fresh))
        .catch((err) => setError(`Box ${fresh.join(", ")} couldn't be queued: ${errorMessage(err)}`));
    },
    [client, sessionId, flashes],
  );

  /*
   * Back on this step with this round's mapping confirmed and flashes asked
   * for — a visit to another tab, or a reload, mid-walk: pick the walk up at
   * the first box nobody asked to flash, instead of offering to confirm again.
   * Once per visit, and only while the walk is still to resume (`walkReducer`
   * ignores it otherwise).
   */
  useEffect(() => {
    if (!held || rigBoxes.length === 0) return;
    dispatchWalk({
      type: "resume",
      at: resumeWalkAt(
        flashQueue,
        placementOrder.map((m) => m.box),
      ),
      count: placementOrder.length,
    });
  }, [placementOrder, held, rigBoxes.length, flashQueue]);

  /**
   * Confirm the mapping and start the walk — or, for the operator who has
   * already placed everyone, skip straight to flashing the lot.
   *
   * Confirming *first* is what lets the boxes be flashed as the walk goes:
   * the confirmed mapping puts the utility baseline on hold, and without that
   * a box falling idle after its task flash would be quietly restored to the
   * utility sketch before the session ever started (`ARCHITECTURE.md#three-rules-it-never-breaks`). The
   * baseline nudge goes out just before, for a box still carrying last
   * session's sketch; the hold that follows drops whatever of it hasn't
   * started, and a session flash of a box waits out a restore already in
   * flight.
   */
  async function startPlacement(skipWalk = false) {
    if (!sessionId || !readiness.allChosen) return;
    setBusy(true);
    setError(null);
    try {
      if (utility.configured) {
        void client
          .call(CMD.UTILITY_ENSURE, { boxes: placementOrder.map((m) => m.box) })
          .catch(() => undefined);
      }
      // Merged here, from the profiles as they are now (`confirmPayload`).
      await confirmMapping(
        client,
        sessionId,
        confirmPayload(mappings, profiles, settings.taskDefaults),
      );
      dispatchWalk({
        type: "confirmed",
        skipWalk,
        count: placementOrder.length,
      });
      if (skipWalk) {
        await flashSessionBoxes(
          client,
          sessionId,
          placementOrder.map((m) => m.box),
        );
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
    dispatchWalk({ type: "walkAgain" });
  }

  function advancePlacement() {
    if (current) enqueue([current.box]);
    if (placeIndex + 1 >= placementOrder.length) setLight(null);
    dispatchWalk({ type: "advance", count: placementOrder.length });
  }

  /** Every remaining box at once — the operator did the walk without us. */
  function placeAll() {
    enqueue(placementOrder.slice(placeIndex).map((m) => m.box));
    dispatchWalk({ type: "placeAll", count: placementOrder.length });
    setLight(null);
  }

  function retreatPlacement() {
    if (placeIndex === 0) {
      // Back to editing: the mapping can change under a flash that already
      // landed, so nothing flashed so far is trusted — the next walk confirms
      // and flashes afresh. Boxes still waiting simply stop waiting; one
      // already flashing finishes.
      void cancelFlashes(
        client,
        mappings.map((m) => m.box),
      ).catch(() => undefined);
      setLight(null);
    }
    dispatchWalk({ type: "retreat" });
  }

  async function acknowledge(box: number) {
    setError(null);
    try {
      // The card keeps reading "failed", now with its Retry offered.
      await client.call(CMD.PORT_ERROR_ACK, { box });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  // A recording session has one more step before Mission Control: the boxes
  // are mapped and flashed now, which is exactly what the recording setup
  // needs in order to ask which headstage port each one is on.
  const isRecording = flow.isRecording;
  const controlUrl = isRecording
    ? stepUrl.record(sessionId!)
    : stepUrl.control(sessionId!);
  const { flashedCount, allFlashed, pending: flashPending } = flashes;

  // Everyone placed and every box flashed: the rig is ready, and nothing on
  // this screen is the next step any more.
  useEffect(() => {
    if (phase !== "placed" || !allFlashed) return;
    navigate(controlUrl);
  }, [phase, allFlashed, controlUrl, navigate]);

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
        : // Before "pick a sketch": with the bundled library missing there are
          // none to pick, and the picker alone cannot say so.
          sketches.length === 0
          ? "No sketches found — the app's bundled sketch library is missing. Reinstall Ephymeris."
          : (readiness.problem ??
            "Check who runs where, then place the animals one at a time.");

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
        <section className="pointer-events-auto mx-auto max-w-6xl px-8 py-8">
          <SessionJourney
            step="boxes"
            hint={hint}
            round={flow.round}
            recording={isRecording}
          />
          <h1 className="font-display text-[22px] text-starlight">
            {phase === "placing"
              ? "Place the animals"
              : phase === "placed"
                ? "Flashing the boxes"
                : flow.round > 1
                  ? `Round ${flow.round}: who runs where`
                  : "Who runs where"}
          </h1>
          <p className="mt-1 text-[12px] text-static">
            {phase === "placing"
              ? "One at a time, in box order. Each box is flashed the moment you close it, while you fetch the next animal."
              : phase === "placed"
                ? "The boxes are flashing in the order you closed them. Mission Control opens when the last one lands."
                : "Any animal can take any box. Choices here apply to this round only; usual boxes are set in Cohorts."}
          </p>

          {(error ?? loadError) && (
            <div
              className="mt-4 flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert
                size={14}
                strokeWidth={1.75}
                className="mt-px shrink-0"
              />
              {error ?? loadError}
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

          {/* A box can be given an animal before its board is bound; this rig may
          never have had it. An unbound box fails its flash, and its animal
          cannot run, while the boxes around it flash as normal. */}
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
                  They can't be flashed, so their animals can't run, though the
                  other boxes flash as normal. Bind them on the Rig tab, or move
                  these animals to boxes that are set up.
                </p>
              </div>
              <div className="shrink-0">
                {/* The advice says "the Rig tab", so the button goes there —
                    it used to open Task, one tab past where the fix lives. */}
                <Button onClick={() => navigate("/config")}>Open Rig</Button>
              </div>
            </div>
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

          {/* **Leaves the way Mission Control's tiles arrive.** These rows and
          the box tiles that replace them on the next screen are the same six
          boxes; sliding one set out to the right as the other slides in from
          it makes that continuity legible, where a plain crossfade just reads
          as one screen replacing another. `items-start`, so the tuning panel
          is as tall as its form and never stretches the list. */}
          <motion.div
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 12 }}
            transition={springPanel}
            className={`${current !== null ? "mt-3" : "mt-6"} grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,430px)_minmax(0,1fr)]`}
          >
            <div className="hud rounded-md p-2">
              <div className="flex items-baseline justify-between px-2 pt-1.5 pb-2">
                <span className="font-mono text-[10px] tracking-[0.16em] text-static uppercase">
                  Boxes
                </span>
                <span className="font-mono text-[10px] text-static/80">
                  {mappings.length} of {MAX_BOX} in use
                </span>
              </div>
              {/* Most rounds run one task on every box: one pick instead of
              six. A box already on that task keeps its edits. */}
              {phase === "review" && mappings.length > 1 && (
                <div className="mb-2 flex items-center gap-2 px-2.5">
                  <span className="shrink-0 text-[11px] text-static">Every box on</span>
                  <SketchPicker
                    label="Task for every box"
                    sketches={sketches}
                    value={commonSketch}
                    quiet
                    onChange={(path) =>
                      setMappings((prev) =>
                        prev.map((m) =>
                          m.sketchPath === path ? m : { ...m, sketchPath: path, overrides: {} },
                        ),
                      )
                    }
                    className="min-w-0 flex-1 truncate"
                  />
                </div>
              )}
              <div className="flex flex-col gap-1">
                {ALL_BOXES.map((box) => {
                  const mapping = mappings.find((m) => m.box === box) ?? null;
                  const isCurrent = currentBox === box;
                  return (
                    <BoxRow
                      key={box}
                      box={box}
                      mapping={mapping}
                      roster={roster}
                      mappings={mappings}
                      ran={ranAnimalIds}
                      sketches={sketches}
                      tuned={
                        mapping
                          ? overriddenCount(
                              mapping.sketchPath ? (profiles[mapping.sketchPath] ?? null) : null,
                              rigDefaults(mapping.sketchPath),
                              mapping.overrides,
                            )
                          : 0
                      }
                      selected={selectedBox === box}
                      isCurrent={isCurrent}
                      // Everything that isn't the one row being pointed at
                      // recedes, and stops accepting clicks: mid-walk, changing
                      // a box the operator has already filled would silently
                      // invalidate the animals behind them. An empty box has
                      // nothing to show once the round is confirmed.
                      dimmed={phase === "placing" ? !isCurrent : phase === "placed" && !mapping}
                      placed={mapping !== null && isPlaced(walk, placementOrder, mapping.animalId)}
                      editable={phase === "review"}
                      bound={configuredBoxes.has(box)}
                      card={flashes.cards.get(box) ?? { state: "idle", detail: null }}
                      fault={
                        mapping && portStates[box]?.state === "ERROR"
                          ? faultReason(portStates[box]?.reason)
                          : null
                      }
                      canRetry={
                        connected && portStates[box]?.state !== "ERROR" && phase !== "review"
                      }
                      canAcknowledge={!busy && connected}
                      onSelect={() => setSelectedBox(box)}
                      onAnimal={(animalId) => setMappings((prev) => assignBox(prev, box, animalId))}
                      onSketch={(path) => patchBox(box, { sketchPath: path, overrides: {} })}
                      onRetry={() => enqueue([box])}
                      onAcknowledge={() => void acknowledge(box)}
                    />
                  );
                })}
              </div>
              {/* Who is left out, said: with free assignment an animal missing
              from the round is otherwise only an absence in six dropdowns. */}
              {roster.length > 0 && (
                <p className="px-2 pt-2.5 pb-1.5 text-[11px] leading-relaxed text-static">
                  {benched.length === 0
                    ? "Every animal of the cohort is in a box."
                    : `Not running this round: ${benched
                        .map((a) => (ranAnimalIds?.has(a.id) ? `${a.name} (ran)` : a.name))
                        .join(", ")}.`}
                </p>
              )}
            </div>

            <TuningPanel
              box={selectedBox}
              mapping={selected}
              animal={selected ? names[selected.animalId] : undefined}
              // `undefined` while its profile is still being read.
              profile={selected?.sketchPath ? profiles[selected.sketchPath] : null}
              rigDefaults={rigDefaults(selected?.sketchPath ?? null)}
              editable={phase === "review"}
              sameTask={
                selected?.sketchPath
                  ? mappings.filter(
                      (m) => m.box !== selectedBox && m.sketchPath === selected.sketchPath,
                    ).length
                  : 0
              }
              onOverrides={(overrides) => patchBox(selectedBox, { overrides })}
              onCopy={() => setMappings((prev) => copyOverrides(prev, selectedBox))}
            >
              {/* The instruction itself, on the panel about the box it names. */}
              {current !== null && current.box === selectedBox && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={springSnappy}
                  className="attention-border mb-3 flex items-center justify-between gap-3 rounded-sm border border-halo px-3 py-2.5"
                >
                  <div className="min-w-0">
                    <p className="text-[13px] leading-snug text-starlight">
                      Place this animal in{" "}
                      <span className="font-mono text-pulsar">box {current.box}</span>
                    </p>
                    <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-static">
                      <Lightbulb
                        size={12}
                        strokeWidth={1.75}
                        className="shrink-0"
                        style={light?.status === "on" ? { color: "var(--color-ion)" } : undefined}
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
            </TuningPanel>
          </motion.div>

          <div className="mt-6 flex items-center gap-2">
            {/* Placement sits between confirming the mapping and flashing on
            purpose: the boxes are still carrying the utility sketch, which is
            the only firmware that can be asked to light one. Flashing
            first would put the tasks on and the lights out of reach. */}
            {phase === "review" && (
              <>
                <Button
                  variant="primary"
                  onClick={() => void startPlacement()}
                  disabled={!readiness.ready || busy || !connected}
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
                  disabled={!readiness.ready || busy || !connected}
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
 * (`ARCHITECTURE.md#replay-on-connect` sends `reason: "initial state"`), which
 * explains nothing — so that case gets a sentence instead of a shrug.
 */
function faultReason(reason: string | undefined): string {
  if (!reason || reason === "initial state") {
    return "This box is in an error state from an earlier operation.";
  }
  return reason;
}

const ALL_BOXES = Array.from({ length: MAX_BOX - MIN_BOX + 1 }, (_, i) => MIN_BOX + i);

/**
 * One box of the rig: who is in it and on which task, and what the flash
 * queue and the port say about it. Selecting the row (a click, or focus
 * landing on one of its controls) puts its parameters in the tuning panel.
 *
 * The animal picker offers the whole roster, whatever box an animal is in:
 * picking one that is in another box swaps the two, and picking one off the
 * bench sends whoever was here to it (`assignBox`). Each option says where
 * that animal is now, so a swap is a deliberate act and not a surprise.
 */
function BoxRow({
  box,
  mapping,
  roster,
  mappings,
  ran,
  sketches,
  tuned,
  selected,
  isCurrent,
  dimmed,
  placed,
  editable,
  bound,
  card,
  fault,
  canRetry,
  canAcknowledge,
  onSelect,
  onAnimal,
  onSketch,
  onRetry,
  onAcknowledge,
}: {
  box: number;
  mapping: BoxMapping | null;
  /** The cohort's animals, by name. */
  roster: Animal[];
  mappings: readonly BoxMapping[];
  ran: ReadonlySet<string> | null;
  sketches: Array<{ category: string; name: string; path: string }>;
  /** Values that differ from the layers underneath (`overriddenCount`). */
  tuned: number;
  selected: boolean;
  /** The walk is standing at this box. */
  isCurrent: boolean;
  dimmed: boolean;
  placed: boolean;
  /** The mapping can still change: before it is confirmed. */
  editable: boolean;
  /** This machine has a board bound to the box. */
  bound: boolean;
  card: FlashCard;
  /** Why the port is in ERROR, or null. */
  fault: string | null;
  canRetry: boolean;
  canAcknowledge: boolean;
  onSelect: () => void;
  onAnimal: (animalId: string | null) => void;
  onSketch: (path: string | null) => void;
  onRetry: () => void;
  onAcknowledge: () => void;
}) {
  const animal = mapping ? roster.find((a) => a.id === mapping.animalId) : undefined;
  const where = new Map(mappings.map((m) => [m.animalId, m.box]));
  const options = [
    { value: "", label: "— empty —" },
    ...roster.map((a) => {
      const at = where.get(a.id);
      const detail =
        at !== undefined && at !== box
          ? `in box ${at}`
          : at === undefined && ran?.has(a.id)
            ? "ran"
            : a.boxNumber === box
              ? "usual box"
              : undefined;
      return { value: a.id, label: a.name, detail };
    }),
  ];

  return (
    <motion.div
      role="group"
      aria-label={`Box ${box}`}
      aria-current={isCurrent ? "step" : undefined}
      animate={{ opacity: dimmed ? 0.4 : 1 }}
      transition={springSnappy}
      onClick={onSelect}
      onFocusCapture={onSelect}
      className={`rounded-sm border px-2.5 py-2 transition-colors ${
        selected ? "border-pulsar bg-pulsar/12" : "border-transparent hover:border-halo"
      } ${isCurrent ? "attention-border" : ""}`}
      style={{ pointerEvents: dimmed ? "none" : "auto" }}
    >
      <div className="flex items-center gap-2">
        <BoxStar state={card.state} />
        <span className="w-[44px] shrink-0 font-mono text-[12px] text-starlight">Box {box}</span>
        <Dropdown
          label={`Animal in box ${box}`}
          size="regular"
          value={mapping?.animalId ?? ""}
          options={options}
          placeholder="empty"
          disabled={!editable}
          className="min-w-0 flex-1"
          onChange={(value) => onAnimal(value === "" ? null : value)}
        />
        {/* The walk's only persistent record of itself: which animals are
        already in their boxes. Its slot is held so its arrival moves nothing. */}
        <span className="flex w-4 shrink-0 justify-center">
          {placed && (
            <Check
              size={15}
              strokeWidth={2}
              style={{ color: "var(--color-ion)" }}
              aria-label="placed"
            />
          )}
        </span>
      </div>

      {mapping && (
        // Indented under the animal: star (28) + gap (8) + "Box N" (44) + gap (8).
        <div className="mt-1.5 pl-[88px]">
          <div className="flex items-center gap-2">
            <SketchPicker
              label={`Task for ${animal?.name ?? `box ${box}`}`}
              sketches={sketches}
              value={mapping.sketchPath}
              onChange={onSketch}
              disabled={!editable}
              className="min-w-0 flex-1 truncate"
            />
            <span
              className={`w-[52px] shrink-0 text-right font-mono text-[10px] ${
                tuned > 0 ? "text-pulsar" : "text-static/60"
              }`}
              title={
                tuned > 0
                  ? `${tuned} parameter${tuned === 1 ? "" : "s"} set for this animal`
                  : "Every parameter at its default"
              }
            >
              {tuned > 0 ? `${tuned} tuned` : ""}
            </span>
          </div>

          {!bound && (
            <p className="mt-1 font-mono text-[10px]" style={{ color: "var(--color-status-warning)" }}>
              no board is bound to box {box}
            </p>
          )}

          {/* What the flash queue is doing to this box, said on the box — the
          star beside the number draws it, this names it. */}
          <FlashLine card={card} canRetry={canRetry} onRetry={onRetry} />

          {/* Recovery in place: a box left in `ERROR` (usually by the flash
          that just failed) can't be flashed again until the fault is
          acknowledged, so the ack lives on the row that is stuck rather than
          only in Debug Mode. Same shape as `NodeDetail`'s row. */}
          {fault !== null && (
            <div
              className="mt-2 flex items-center gap-2 rounded-sm border border-halo px-2.5 py-2 text-[11px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert size={13} strokeWidth={1.75} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate" title={fault}>
                {fault}
              </span>
              <Button disabled={!canAcknowledge} onClick={onAcknowledge}>
                Acknowledge
              </Button>
            </div>
          )}
        </div>
      )}
    </motion.div>
  );
}

/**
 * The selected box's parameters, in one place that does not move
 * (`ARCHITECTURE.md#mapping-and-the-placement-walk`).
 *
 * It stays in view beside the list as the page scrolls and scrolls its own
 * form, so a forty-field task never pushes the boxes off the screen. Before
 * the box has an animal, a task, or a profile with anything to set, it says
 * which of those it is waiting on, since an empty panel reads as a fault.
 * `children` is the walk's instruction for this box, above the form.
 */
function TuningPanel({
  box,
  mapping,
  animal,
  profile,
  rigDefaults,
  editable,
  sameTask,
  onOverrides,
  onCopy,
  children,
}: {
  box: number;
  mapping: BoxMapping | null;
  animal: Animal | undefined;
  /** `undefined` while it is being read; null for a sketch with none. */
  profile: TaskProfile | null | undefined;
  rigDefaults: Record<string, unknown>;
  editable: boolean;
  /** Other boxes on this box's task: who "copy" would reach. */
  sameTask: number;
  onOverrides: (overrides: Record<string, unknown>) => void;
  onCopy: () => void;
  children?: React.ReactNode;
}) {
  const waiting =
    mapping === null
      ? `Box ${box} is empty. Put an animal in it to choose its task and parameters.`
      : mapping.sketchPath === null
        ? "Pick a task for this box to see its parameters."
        : profile === undefined
          ? "Reading the task's parameters…"
          : profile === null || profile.config.length === 0
            ? "This task has no parameters to set: it starts as it is written."
            : null;

  return (
    <div className="hud scrollbar-slim rounded-md p-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-7rem)] lg:overflow-y-auto">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 font-mono text-[10px] tracking-[0.16em] text-static uppercase">
            <SlidersHorizontal size={11} strokeWidth={1.75} />
            Parameters · box {box}
          </div>
          {/* The animal's full name is the point of the panel, so it never
          truncates — an unusually long one wraps instead. */}
          <div className="mt-1 break-words text-[15px] font-semibold leading-snug text-starlight">
            {animal?.name ?? "—"}
            {animal?.sex && animal.sex !== "unknown" && (
              <span className="ml-2 align-middle font-mono text-[11px] font-normal text-static">
                {animal.sex}
              </span>
            )}
          </div>
        </div>
        {editable && waiting === null && sameTask > 0 && (
          <Button
            variant="outline"
            onClick={onCopy}
            title="Give every other box on this task the values set here"
            className="shrink-0"
          >
            <Copy size={12} strokeWidth={1.75} />
            Copy to {sameTask} other {sameTask === 1 ? "box" : "boxes"}
          </Button>
        )}
      </div>

      <div className="mt-3">
        {children}
        {waiting !== null ? (
          <p className="text-[12px] leading-relaxed text-static">{waiting}</p>
        ) : (
          <TaskConfigForm
            pinned
            profile={profile ?? null}
            rigDefaults={rigDefaults}
            overrides={mapping?.overrides ?? {}}
            disabled={!editable}
            onOverridesChange={onOverrides}
          />
        )}
      </div>
    </div>
  );
}

/**
 * The queue's word on one box, under the name: waiting, flashing, flashed, or
 * failed with why and the way to try again. Nothing for an idle box — before
 * the walk reaches it there is nothing to say, and six "not yet" lines would
 * be noise.
 */
function FlashLine({
  card,
  canRetry,
  onRetry,
}: {
  card: FlashCard;
  canRetry: boolean;
  onRetry: () => void;
}) {
  const { state, detail } = card;
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
    <div className="mt-1.5 font-mono text-[10px]" style={{ color: colour }}>
      <div className="flex items-center gap-2">
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
      {/* Why it waits or failed: the sidecar's words, so a compile error
      reads here rather than only in a log. */}
      {detail && (state === "failed" || state === "queued") && (
        <div className="mt-1 break-words pl-[19px]">{detail}</div>
      )}
    </div>
  );
}

/**
 * A box mid-flash shows its star "flaring" rather than a generic spinner,
 * keeping the visual language consistent with the rest of the app. A queued
 * box holds a steady half-light: claimed, not yet burning.
 */
function BoxStar({ state }: { state: FlashCardState }) {
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
        initial={false}
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
