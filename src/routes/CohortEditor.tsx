import { open } from "@tauri-apps/plugin-dialog";
import { AnimatePresence, motion } from "framer-motion";
import {
  Archive,
  ArrowLeft,
  Check,
  Circle,
  CircleAlert,
  FolderOpen,
  Radio,
  RotateCcw,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router";

import { Button, TextInput } from "@/components/common/controls";
import { SettingGroup } from "@/components/settings/SettingRow";
import { AnimalTable } from "@/components/cohorts/AnimalTable";
import { CohortIcon } from "@/components/cohorts/CohortIcon";
import { DataFolderField } from "@/components/cohorts/DataFolderField";
import { GroupsPanel } from "@/components/cohorts/GroupsPanel";
import {
  assignmentProblems,
  problemSummary,
  useBoxAvailability,
} from "@/lib/cohorts/boxAvailability";
import {
  archiveCohort,
  createCohort,
  errorMessage,
  fieldErrors,
  getCohort,
  restoreCohort,
  setDataFolder,
  updateCohort,
} from "@/lib/cohorts/commands";
import type { Animal, Cohort, Group } from "@/lib/cohorts/types";
import { springPanel, springSnappy } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { useReduceMotion } from "@/lib/useReduceMotion";
import { useSidecar } from "@/lib/ws/context";

/** Seeds the one group every cohort has, even before its first save (§2). */
function newLocalGroupId(): string {
  return `group-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

/**
 * Create / edit / manage — `cohorts.md` §6.
 *
 * A full route rather than a modal: the roster, groups panel and Auto-Balance
 * preview together are more than a dialog can hold comfortably. The cohort's
 * icon shares a `layoutId` with its grid card, so opening one morphs the icon
 * into this header instead of cutting.
 *
 * **Creating and editing share this component but not its shape.** A new
 * cohort is a flow: name, then roster, then groups and boxes, each revealing
 * the next as it's satisfied, so there is exactly one thing to do at a time
 * and the order is legible without reading anything. An existing cohort shows
 * everything at once — you came back to change one thing, and being walked
 * past the other three would be an obstacle rather than guidance. Splitting
 * these into two components would duplicate the roster, group and box logic
 * to express a difference that is purely presentational.
 */
export function CohortEditor() {
  const { id } = useParams<{ id: string }>();
  const isNew = id === undefined;
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const { settings } = useSettings();

  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [name, setName] = useState("");
  const [animals, setAnimals] = useState<Animal[]>([]);
  // Groups are real, editable state from the very start — even a brand-new
  // cohort gets its one implicit group locally, so group management and box
  // assignment (`GroupsPanel`) work identically before and after the first
  // save, rather than being gated on the cohort existing server-side.
  const [groups, setGroups] = useState<Group[]>(() =>
    isNew ? [{ id: newLocalGroupId(), name: "Group 1", order: 0 }] : [],
  );
  const [dataFolder, setDataFolderPath] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const connected = status === "connected";
  const reduceMotion = useReduceMotion();
  const { statusOf } = useBoxAvailability();
  // Falls back to a placeholder only in the brief window an existing cohort
  // hasn't finished loading yet — `adopt()` replaces it with the real groups.
  const defaultGroupId =
    [...groups].sort((a, b) => a.order - b.order)[0]?.id ?? "pending";
  const named = name.trim() !== "";
  const readyToRun = animals.some((a) => a.boxNumber !== null);

  /**
   * How far down the create flow to reveal. An existing cohort is always fully
   * open; a new one earns each section by satisfying the one above it, and
   * never closes a section again once opened — a name cleared mid-edit
   * shouldn't yank the roster out from under the cursor.
   */
  const [reached, setReached] = useState(0);
  const stage = isNew ? Math.max(reached, named ? (animals.length > 0 ? 2 : 1) : 0) : 2;
  useEffect(() => {
    setReached((r) => Math.max(r, stage));
  }, [stage]);

  /** Assignments this machine can't currently honour (`boxAvailability.ts`). */
  const problems = useMemo(
    () => assignmentProblems(animals, groups, statusOf),
    [animals, groups, statusOf],
  );

  const adopt = useCallback((next: Cohort) => {
    setCohort(next);
    setName(next.name);
    setAnimals(next.animals);
    setGroups(next.groups);
    setDataFolderPath(next.dataFolder);
  }, []);

  useEffect(() => {
    if (isNew || !connected || !id) return;
    let active = true;
    void (async () => {
      try {
        const loaded = await getCohort(client, id);
        if (active) adopt(loaded);
      } catch (err) {
        if (active) setLoadError(errorMessage(err));
      }
    })();
    return () => {
      active = false;
    };
  }, [client, id, isNew, connected, adopt]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setErrors({});
    setMessage(null);
    try {
      await action();
      return true;
    } catch (err) {
      const fields = fieldErrors(err);
      if (fields) setErrors(fields);
      else setMessage(errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (isNew) {
      // §8 — the folder is resolved once at creation. With a configured data
      // directory the sidecar derives and collision-suffixes it; without one
      // there's no basis for a default, so an explicit choice is required
      // rather than guessed at.
      if (!dataFolder && !settings.dataDirectory) {
        setErrors({ dataFolder: "Choose where this cohort's data should live." });
        return;
      }
      const created = await run(async () => {
        // One call, roster included. Groups and animals were built entirely
        // client-side with their own ids before this cohort existed, and the
        // sidecar validates them before writing anything — so a rejected
        // roster leaves no half-made cohort and no orphaned folder.
        const fresh = await createCohort(client, name, {
          ...(dataFolder ? { dataFolder } : {}),
          animals,
          groups,
        });
        navigate(`/cohorts/${fresh.id}`, { replace: true });
      });
      if (created) setMessage("Cohort created.");
      return;
    }

    if (!cohort) return;
    const ok = await run(async () => {
      const saved = await updateCohort(client, cohort.id, { name, animals, groups });
      adopt(saved);
    });
    if (ok) setMessage("Saved.");
  }

  const heading = isNew ? "New Cohort" : (cohort?.name ?? "Cohort");
  const iconId = cohort?.id ?? "new-cohort";

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-5xl px-8 py-8"
    >
      <Button variant="ghost" onClick={() => navigate("/cohorts")}>
        <ArrowLeft size={13} strokeWidth={1.75} />
        All cohorts
      </Button>

      <div className="mt-3 flex items-center gap-4">
        <motion.span layoutId={`cohort-icon-${iconId}`} transition={springSnappy}>
          <CohortIcon cohortId={iconId} animalCount={animals.length} size={64} />
        </motion.span>
        <div className="min-w-0">
          <h1 className="font-display text-[22px] text-starlight">{heading}</h1>
          <p className="font-mono text-[11px] text-static">
            {animals.length} {animals.length === 1 ? "animal" : "animals"}
            {groups.length > 1 && ` · ${groups.length} groups`}
            {cohort?.archivedAt && " · archived"}
          </p>
        </div>
      </div>

      {!cohort?.archivedAt && (
        <ReadinessStrip named={named} animalCount={animals.length} readyToRun={readyToRun} />
      )}

      {loadError && <Banner tone="error">{loadError}</Banner>}
      {!connected && (
        <Banner tone="error">
          The backend isn't connected — cohort changes can't be saved right now.
        </Banner>
      )}
      {message && <Banner tone="info">{message}</Banner>}
      {errors["name"] && <Banner tone="error">{errors["name"]}</Banner>}
      {errors["_"] && <Banner tone="error">{errors["_"]}</Banner>}

      <SettingGroup title="Cohort">
        <div className="flex items-start justify-between gap-8 px-4 py-3.5">
          <div className="min-w-0 pt-0.5">
            <div className="text-[13px] font-medium text-starlight">Name</div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-static">
              Must be unique among active cohorts.
            </p>
          </div>
          <TextInput
            label="Cohort name"
            value={name}
            placeholder="Batch A"
            autoFocus={isNew}
            attention={isNew && !named}
            onChange={setName}
            className="w-[280px]"
          />
        </div>

        {isNew ? (
          // Only a rig with no configured data directory has a decision to make
          // here — otherwise §8 derives the folder and asking would be noise in
          // the middle of the flow.
          <Reveal open={stage >= 1 && settings.dataDirectory === null} still={reduceMotion}>
            <NewCohortFolder
              value={dataFolder}
              error={errors["dataFolder"]}
              dataDirectory={settings.dataDirectory}
              onChange={setDataFolderPath}
            />
          </Reveal>
        ) : (
          cohort && (
            <DataFolderField
              path={cohort.dataFolder}
              onRelocate={(destination, moveExisting) =>
                void run(async () => {
                  const moved = await setDataFolder(
                    client,
                    cohort.id,
                    destination,
                    moveExisting,
                  );
                  adopt(moved);
                  setMessage("Data folder changed.");
                })
              }
            />
          )
        )}
      </SettingGroup>

      <Reveal open={stage >= 1} still={reduceMotion}>
        <SettingGroup title="Animals">
          <AnimalTable
            animals={animals}
            defaultGroupId={defaultGroupId}
            errors={errors}
            attention={isNew && stage === 1}
            onChange={setAnimals}
          />
        </SettingGroup>
      </Reveal>

      <Reveal open={stage >= 2} still={reduceMotion}>
        {/* Above the section that fixes it, not at the top of the page: the
            remedy is a box selector twelve inches below this sentence. */}
        {problems.length > 0 && (
          <div className="mt-7 flex items-start justify-between gap-4 rounded-sm border border-halo px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-[12px]" style={{ color: "var(--color-status-warning)" }}>
                {problemSummary(problems)}.
              </p>
              <p className="mt-0.5 text-[12px] leading-relaxed text-static">
                {problems.length === 1
                  ? `${problems[0]!.animalName} is assigned to it`
                  : `${problems.length} animals are assigned to ${
                      problems.length === 2 ? "them" : "those"
                    }`}
                {" — "}
                {problems
                  .slice(0, 4)
                  .map((p) => `${p.animalName} (box ${p.box})`)
                  .join(", ")}
                {problems.length > 4 && `, and ${problems.length - 4} more`}. A session
                can't start those animals until the boxes are back, or they're moved to
                boxes that are.
              </p>
            </div>
            <div className="shrink-0">
              <Button onClick={() => navigate("/config")}>
                <Radio size={13} strokeWidth={1.75} />
                Open Config
              </Button>
            </div>
          </div>
        )}

        <SettingGroup title="Groups & boxes">
          <GroupsPanel
            groups={groups}
            animals={animals}
            onChange={(nextGroups, nextAnimals) => {
              setGroups(nextGroups);
              setAnimals(nextAnimals);
            }}
          />
        </SettingGroup>
      </Reveal>

      <div className="mt-6 flex items-center justify-between">
        <div className="flex gap-2">
          {/* A nameless cohort is rejected server-side, so the round trip only
              exists to deliver news we already have. */}
          <Button
            variant="primary"
            onClick={() => void save()}
            disabled={busy || !connected || !named}
            {...(!named ? { title: "Give the cohort a name first" } : {})}
          >
            {busy ? "Saving…" : isNew ? "Create cohort" : "Save changes"}
          </Button>
          <Button variant="ghost" onClick={() => navigate("/cohorts")}>
            Cancel
          </Button>
        </div>

        {/* §9 — archive is the everyday action; permanent delete lives only in
            the archived view, never on a live cohort. */}
        {cohort &&
          (cohort.archivedAt ? (
            <Button
              onClick={() =>
                void run(async () => {
                  adopt(await restoreCohort(client, cohort.id));
                  setMessage("Restored.");
                })
              }
              disabled={busy || !connected}
            >
              <RotateCcw size={13} strokeWidth={1.75} />
              Restore
            </Button>
          ) : (
            <Button
              onClick={() =>
                void run(async () => {
                  await archiveCohort(client, cohort.id);
                  navigate("/cohorts");
                })
              }
              disabled={busy || !connected}
              title="Keeps the record and its data folder intact"
            >
              <Archive size={13} strokeWidth={1.75} />
              Archive
            </Button>
          ))}
      </div>
    </motion.section>
  );
}

/**
 * A section that arrives when its precondition is met.
 *
 * The create flow's whole shape: one thing to do at a time, and the next thing
 * sliding in as evidence you finished the last. `still` collapses it to a
 * plain conditional under reduced motion — the *ordering* is the information,
 * and that survives without the movement.
 */
function Reveal({
  open,
  still,
  children,
}: {
  open: boolean;
  still: boolean;
  children: ReactNode;
}) {
  if (still) return open ? <>{children}</> : null;
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={springSnappy}
          className="overflow-hidden"
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * Lightweight coaching, not a gate — three quiet checkpoints against what a
 * cohort actually needs before it can start a session (`starting-a-session.md`
 * §1: at least one group with at least one box-assigned animal). A cohort can
 * still be saved and left incomplete at any point (`cohorts.md` §1 — real lab
 * setup rarely happens in one sitting); this just orients the user on what's
 * left without blocking anything.
 *
 * Doubles as the create flow's spine: each checkpoint corresponds to a section
 * below, so the strip reads as "where am I" and not only "what's missing". The
 * current step's bar widens the way the setup wizard's step dots do — one
 * shared idiom for the same idea.
 */
function ReadinessStrip({
  named,
  animalCount,
  readyToRun,
}: {
  named: boolean;
  animalCount: number;
  readyToRun: boolean;
}) {
  const items: Array<{ label: string; done: boolean }> = [
    { label: named ? "Named" : "Name this cohort", done: named },
    {
      label:
        animalCount > 0
          ? `${animalCount} ${animalCount === 1 ? "animal" : "animals"}`
          : "Add animals",
      done: animalCount > 0,
    },
    {
      label: readyToRun ? "Ready to run" : "Assign a box to make it session-ready",
      done: readyToRun,
    },
  ];
  // The first unfinished checkpoint is where the user is standing.
  const current = items.findIndex((item) => !item.done);

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((item, index) => (
        <span
          key={item.label}
          className="flex items-center gap-1.5 text-[11px]"
          style={{
            color: item.done
              ? "var(--color-status-ok)"
              : index === current
                ? "var(--color-starlight)"
                : "var(--color-static)",
          }}
        >
          {item.done ? (
            <Check size={12} strokeWidth={2} />
          ) : index === current ? (
            <motion.span
              layout
              initial={false}
              animate={{ width: 16, backgroundColor: "var(--color-pulsar)" }}
              transition={springSnappy}
              className="h-1.5 rounded-full"
            />
          ) : (
            <Circle size={7} strokeWidth={0} fill="currentColor" className="opacity-50" />
          )}
          {item.label}
        </span>
      ))}
    </div>
  );
}

/**
 * §8's creation-time folder. Required rather than optional: with no configured
 * `dataDirectory` there's nothing to derive a default from, so the user picks
 * explicitly and the value is never null.
 */
function NewCohortFolder({
  value,
  error,
  dataDirectory,
  onChange,
}: {
  value: string | null;
  error: string | undefined;
  dataDirectory: string | null;
  onChange: (path: string | null) => void;
}) {
  async function choose() {
    try {
      const picked = await open({
        directory: true,
        multiple: false,
        title: "Choose this cohort's data folder",
        ...(dataDirectory ? { defaultPath: dataDirectory } : {}),
      });
      if (typeof picked === "string") onChange(picked);
    } catch (err) {
      console.error("directory picker failed", err);
    }
  }

  return (
    <div className="px-4 py-3.5">
      <div className="flex items-start justify-between gap-8">
        <div className="min-w-0 pt-0.5">
          <div className="text-[13px] font-medium text-starlight">Data folder</div>
          <p className="mt-0.5 text-[12px] leading-relaxed text-static">
            {dataDirectory
              ? "Defaults to a folder named after the cohort inside your data directory."
              : "No data directory is set in Settings, so choose a folder for this cohort."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            data-selectable
            className={`max-w-[280px] truncate rounded-sm border border-halo bg-nebula px-2.5 py-1.5 font-mono text-[12px] ${
              value ? "text-starlight" : "text-static/70"
            }`}
          >
            {value ?? (dataDirectory ? "Default location" : "Not chosen")}
          </span>
          <Button onClick={() => void choose()}>
            <FolderOpen size={13} strokeWidth={1.75} />
            Choose…
          </Button>
        </div>
      </div>
      {error && (
        <p className="mt-2 text-[11px]" style={{ color: "var(--color-status-error)" }}>
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * Tones follow the app's convention: **error** is something that failed or
 * will fail on save, **warning** is a precondition the user can still choose
 * to live with, **info** is confirmation. Colour lands on the text; the border
 * stays Halo so a banner never reads as a differently-shaped surface (§2.2).
 */
const BANNER_TONE: Record<"error" | "warning" | "info", string> = {
  error: "var(--color-status-error)",
  warning: "var(--color-status-warning)",
  info: "var(--color-static)",
};

function Banner({
  tone,
  children,
}: {
  tone: "error" | "warning" | "info";
  children: ReactNode;
}) {
  return (
    <div
      className="mt-4 flex items-start gap-2 rounded-sm border border-halo px-3 py-2 text-[12px] leading-relaxed"
      style={{ color: BANNER_TONE[tone] }}
    >
      {tone !== "info" && (
        <CircleAlert size={14} strokeWidth={1.75} className="mt-px shrink-0" />
      )}
      <span>{children}</span>
    </div>
  );
}
