import { motion } from "framer-motion";
import { ArrowRight, Compass, Trash2, Workflow } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { LibraryStatusNote } from "@/components/task/LibraryStatusNote";
import { NewTaskRow } from "@/components/task/NewTaskRow";
import { StrobeDoor } from "@/components/task/StrobeDoor";
import { TaskRow } from "@/components/task/TaskRow";
import { errorMessage } from "@/lib/cohorts/commands";
import { CASCADE, RISE, springPanel, springSnappy } from "@/lib/motion";
import {
  deleteTask,
  getTask,
  idFromName,
  listTasks,
  uniqueCopyName,
} from "@/lib/taskdef/commands";
import type { TaskDefinition, TaskEntry } from "@/lib/taskdef/types";
import { useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { EVT } from "@/lib/ws/protocol";

/**
 * Task — the landing. What this rig can run, and the way in to changing it.
 *
 * `/task` WAS the editor, with the library as a 300px rail beside it. That
 * worked while a task was born from a preset — the list and the five starting
 * points were one column, and the editor opened whichever you touched.
 * Building from scratch does not fit that shape: there is no longer a menu of
 * things to pick, and the first question became "what have I got", which a text
 * rail answered badly. So the library became the page and the editor moved
 * behind it (`/task/new`, `/task/:taskId`).
 *
 * The layout is the RIG landing's, not the Dashboard's: a centred scrolling
 * column of tiles over the sky. Both pages answer "what is set up here, and
 * where do I go to change it" — and the two doors at the foot of this one are
 * literally the pair Rig used to carry, since the strobe vocabulary moved with
 * the subject it belongs to (`settings.md` §5.0).
 *
 * The saved tasks are a LIST, most recently edited first, not a grid of cards:
 * a shelf of near-identical variants is compared column by column, and a grid
 * scatters the one fact that differs across a different spot in each cell
 * (`TaskRow`). Colour still does real work: every dot on a row's glyph is one
 * condition, in the same six-colour ramp that identifies an animal across
 * Analytics (`TaskGlyph`).
 *
 * **Duplicate** opens an unsaved copy in the editor, for the common case of a
 * small variation on a task that already runs. Named clear of every existing
 * task (`uniqueCopyName`) and WITHOUT the source's legacy names: a legacy name
 * resolves to exactly one sketch (`tasks.md` §3.7), so a copy carrying them
 * would silently take over — or lose — the historical runs they decode.
 */
export function Task() {
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const { discovery, refreshSketches } = useSettings();
  const connected = status === "connected";

  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  /** False until the first `tasks.list` answers. What separates "nothing to
   *  show yet" from "nothing exists" — the empty-state hero would otherwise
   *  flash for the instant before the list arrives, right before the grid pops
   *  in over it. */
  const [tasksLoaded, setTasksLoaded] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<TaskEntry | null>(null);

  const refresh = useCallback(async () => {
    try {
      const reply = await listTasks(client);
      setTasks(reply.tasks);
      setListError(null);
    } catch (err) {
      setListError(errorMessage(err));
    } finally {
      // Either way, "is there anything here?" now has an answer.
      setTasksLoaded(true);
    }
  }, [client]);

  useEffect(() => {
    if (!connected) return;
    void refresh();
  }, [connected, refresh]);

  useEffect(
    () =>
      client.on(EVT.TASKS_UPDATED, (data) =>
        setTasks((data as { tasks: TaskEntry[] }).tasks),
      ),
    [client],
  );

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setPendingDelete(null);
    try {
      await deleteTask(client, target.id);
      await refresh();
    } catch (err) {
      setListError(errorMessage(err));
    }
  }, [client, pendingDelete, refresh]);

  const duplicate = useCallback(
    async (task: TaskEntry) => {
      try {
        const reply = await getTask(client, task.id);
        const source = reply.definition as TaskDefinition;
        const name = uniqueCopyName(source.name, tasks.map((t) => t.name));
        const seed: TaskDefinition = {
          ...structuredClone(source),
          // A fresh id from the start, never the source's: the editor would
          // re-derive one, but not before a first preview went out under it.
          id: idFromName(name, tasks.map((t) => t.id)),
          name,
          legacyNames: [],
        };
        navigate("/task/new", { state: { seed } });
      } catch (err) {
        setListError(errorMessage(err));
      }
    },
    [client, navigate, tasks],
  );

  // Most recently edited first: the task being worked on this week is the one
  // most likely wanted, and "never saved" (null) sinks to the bottom.
  const ordered = useMemo(
    () =>
      [...tasks].sort((a, b) => (b.editedAt ?? "").localeCompare(a.editedAt ?? "")),
    [tasks],
  );

  const needingAttention = useMemo(
    () => tasks.reduce((n, t) => n + (t.problems > 0 ? 1 : 0), 0),
    [tasks],
  );

  // Nothing exists AND we know it. Both halves matter: the hero is an
  // invitation, and showing it over a list still on its way reads as the app
  // having lost the library.
  const empty = tasksLoaded && tasks.length === 0;

  return (
    // No `overflow-hidden`: the shared canvas reaches under the sidebar
    // (`Scene.tsx`), exactly as on the Dashboard and the Rig landing.
    <div className="relative h-full">
      <SkyBackdrop />

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        // Owns its own exit: the shell holds every page opaque on the way out,
        // so anything that should fade has to say so (`AppShell`).
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-5xl px-10 py-9">
          {/* The Rig landing's header idiom — icon chip, title, one mono fact
              line — so the two setup tabs read as siblings. The chip's icon is
              the Dashboard's Task tile icon, which is how this page is entered. */}
          <div className="flex items-center gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-halo bg-nebula">
              <Workflow size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <div className="min-w-0">
              <h1 className="font-display text-[22px] text-starlight">Task</h1>
              <p className="font-mono text-[10px] text-static/70">
                {!tasksLoaded || tasks.length === 0
                  ? "what the animal does — trial types, a ramp, and the numbers"
                  : (
                    <>
                      {tasks.length} task{tasks.length === 1 ? "" : "s"} ·{" "}
                      <span style={{ color: "var(--color-status-ok)" }}>
                        {tasks.length - needingAttention} ready
                      </span>
                      {needingAttention > 0 && (
                        <>
                          {" · "}
                          <span className="text-status-error">
                            {needingAttention} need attention
                          </span>
                        </>
                      )}
                    </>
                  )}
              </p>
            </div>
          </div>
          <p className="mt-3 max-w-prose text-[12px] leading-relaxed text-static">
            What the animal does — the trial types, the shaping ramp, and every
            number the firmware takes. Saving a task writes a flashable sketch.
          </p>

          <motion.div
            variants={CASCADE}
            initial="hidden"
            animate="shown"
            className="mt-6 flex flex-col gap-5"
          >
            {/* Nothing at all until the list has answered. A lone "new task" row
                over "waiting for the backend" invites a click that cannot
                work — a new task needs `tasks.preview` to compile anything. */}
            {!tasksLoaded ? null : empty ? (
              <motion.div variants={RISE}>
                <FirstTask onStart={() => navigate("/task/new")} />
              </motion.div>
            ) : (
              <motion.div
                variants={RISE}
                className="hud flex flex-col divide-y divide-halo overflow-hidden rounded-md"
              >
                <NewTaskRow onClick={() => navigate("/task/new")} />
                {ordered.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    onOpen={() => navigate(`/task/${task.id}`)}
                    onDuplicate={() => void duplicate(task)}
                    onDelete={() => setPendingDelete(task)}
                  />
                ))}
              </motion.div>
            )}

            {/* The two reference doors, side by side: one is where a trial
                row's onset code comes from, the other is the way back into the
                walkthrough. A pair of half-width doors reads as a pair —
                stacked full-width they read as two more forms. */}
            <motion.div variants={RISE} className="grid grid-cols-2 items-stretch gap-5">
              <StrobeDoor onOpen={() => navigate("/task/strobes")} />
              <WalkthroughDoor onOpen={() => navigate("/task/new?guide=1")} />
            </motion.div>

            {/* The library's health. A task is GENERATED from the bundled root
                sketch, so "the install is damaged" is the one thing that stops
                a task existing at all — and this is the only place it shows. */}
            <motion.div variants={RISE}>
              <LibraryStatusNote
                discovery={discovery}
                onRefresh={() => void refreshSketches()}
                canRefresh={connected}
              />
            </motion.div>

            {listError && (
              <motion.p variants={RISE} className="text-[11px] text-status-error">
                {listError}
              </motion.p>
            )}
            {!connected && (
              <motion.p variants={RISE} className="text-[12px] text-static">
                Waiting for the backend — the task library comes from it.
              </motion.p>
            )}
          </motion.div>
        </section>
      </motion.div>

      <DeleteConfirm
        task={pendingDelete}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}

/**
 * The empty state — a hero, rather than a list with one "new" row in it.
 *
 * A rig with no tasks is a rig that cannot run a session, so this is the most
 * important thing on the screen at that moment and it takes the page's one
 * primary control. `NewTaskRow` is the right size once there is something for
 * it to sit beside; alone in an empty list it reads as an afterthought.
 */
function FirstTask({ onStart }: { onStart: () => void }) {
  return (
    <div className="hud flex flex-col items-start gap-4 rounded-md px-6 py-7">
      <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
        <Compass size={18} strokeWidth={1.75} className="text-pulsar" />
      </span>
      <div className="max-w-prose">
        <h2 className="font-display text-[15px] text-starlight">
          No tasks on this rig yet
        </h2>
        <p className="mt-1.5 text-[12px] leading-relaxed text-static">
          A task is built here from scratch: name it, add a trial type for each
          stimulus you present, ease it in with a ramp if the animal needs one,
          then set the numbers. The first one comes with a walkthrough that
          points at each step in turn — it assumes the wiring and the strobe
          codes are already set up on Rig.
        </p>
      </div>
      <Button variant="primary" onClick={onStart}>
        Create your first task
        <ArrowRight size={13} strokeWidth={1.75} />
      </Button>
    </div>
  );
}

/**
 * The way back into the walkthrough once it has been dismissed.
 *
 * The coach shows itself unasked exactly once — on a rig with no tasks — and
 * then never again, which is right for something that would otherwise be in the
 * way every morning. But "never again" needs a handle, or the one person who
 * skipped it on their first day can never get it back. Same door grammar as
 * Strobes beside it; the motif is the coach's own step rail.
 */
function WalkthroughDoor({ onOpen }: { onOpen: () => void }) {
  return (
    <motion.button
      type="button"
      onClick={onOpen}
      initial="idle"
      animate="idle"
      whileHover="hover"
      whileTap={{ scale: 0.995 }}
      variants={{ idle: { y: 0 }, hover: { y: -2 } }}
      transition={springSnappy}
      className="hud group relative flex h-full w-full items-center gap-4 overflow-hidden rounded-md py-3.5 pl-4 pr-0 text-left transition-colors hover:border-static/40"
    >
      <Compass size={18} strokeWidth={1.75} className="shrink-0 self-start text-pulsar" />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1 text-[13px] font-medium text-starlight">
          Walkthrough
          <ArrowRight
            size={11}
            strokeWidth={2}
            className="text-static transition-transform group-hover:translate-x-0.5"
          />
        </span>
        <span className="mt-0.5 block text-[11px] leading-snug text-static">
          Build a task with each step called out in turn. Opens a new, unsaved
          task.
        </span>
      </span>
      <span
        aria-hidden
        className="pointer-events-none -my-3.5 shrink-0 self-center opacity-70 transition-opacity group-hover:opacity-100"
      >
        <WalkthroughMotif />
      </span>
    </motion.button>
  );
}

/** The Walkthrough door's motif: the coach's own step rail, the middle stop
 *  taking the accent and the spotlight arriving on it. */
function WalkthroughMotif() {
  const dots = [16, 34, 52, 70, 88];
  return (
    <svg width="104" height="62" viewBox="0 0 104 62" fill="none" aria-hidden>
      <path d="M16 31 H88" stroke="var(--color-halo)" strokeWidth="1" />
      {dots.map((x) => (
        <circle key={x} cx={x} cy={31} r={2.5} fill="var(--color-halo)" />
      ))}
      <motion.circle
        cx={52}
        cy={31}
        r={3.5}
        variants={{
          idle: { fill: "var(--color-static)", opacity: 0.5 },
          hover: { fill: "var(--color-pulsar)", opacity: 1 },
        }}
        transition={springSnappy}
      />
      {/* A flat expanding ring and no blur — the no-glow rule, and the same
          figure `SessionJourney`'s active step draws. */}
      <motion.circle
        cx={52}
        cy={31}
        fill="none"
        stroke="var(--color-pulsar)"
        strokeWidth="1"
        variants={{ idle: { r: 4, opacity: 0 }, hover: { r: 9, opacity: 0.45 } }}
        transition={springSnappy}
      />
    </svg>
  );
}

/**
 * Deleting takes the generated sketch with it, and the confirm says so.
 *
 * `TaskStore.delete` removes the definition AND `rmtree`s the folder under
 * `<data_dir>/tasks/`, which is what `port.flash` points at. The folder is
 * never visible from this screen, so it is worth a sentence — as is the thing
 * an operator will actually worry about, which is their recorded data.
 */
function DeleteConfirm({
  task,
  onCancel,
  onConfirm,
}: {
  task: TaskEntry | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Modal open={task !== null} onClose={onCancel} title="Delete this task?">
      {task && (
        <div className="flex flex-col gap-4">
          <p className="text-[13px] leading-relaxed text-static">
            <span className="text-starlight">{task.name}</span> and the sketch
            it generates will be removed from this rig.
          </p>
          <p className="rounded-sm border border-halo bg-void/40 px-3 py-2 text-[12px] leading-relaxed text-static">
            Sessions already recorded with it are{" "}
            <span className="text-starlight">not</span> touched — every session
            file carries its own copy of the task profile, so those runs keep
            decoding exactly as they do now.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button variant="primary" onClick={onConfirm}>
              <Trash2 size={13} strokeWidth={1.75} />
              Delete task
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
