import { motion } from "framer-motion";
import { Archive, RotateCcw, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";

import { Button, Select, TextInput, Toggle } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { AppearancePanel } from "@/components/cohorts/AppearancePanel";
import { CohortSky } from "@/components/cohorts/CohortSky";
import { PlanetDisc } from "@/components/cohorts/PlanetDisc";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { HowToRead } from "@/components/charts/HowToRead";
import {
  deleteCohort,
  errorMessage,
  getCohort,
  restoreCohort,
  updateCohort,
} from "@/lib/cohorts/commands";
import {
  resolveAppearance,
  type ResolvedAppearance,
} from "@/lib/cohorts/appearance";
import { useCohorts, useCohortsLoaded } from "@/lib/cohorts/context";
import type { Animal, CohortSummary } from "@/lib/cohorts/types";
import { springPanel } from "@/lib/motion";
import { useSidecar } from "@/lib/ws/context";

/**
 * Cohort browser — `ARCHITECTURE.md#cohort-browser`.
 *
 * **A sky of worlds, not a card grid.** The grid was a fine list and an inert
 * one; this view is for *visually scanning and selecting*, and the app already
 * owned a constellation stage that every route but the rig views mounted as
 * dead wallpaper. Each cohort is a planet whose size is its roster, whose spin
 * and daylight are how recently anyone worked on it, and whose home cages orbit
 * it as ships — with type, hue and ring the operator's own.
 *
 * **The browser IS this route's constellation.** It mounts `CohortSky` instead
 * of `SkyBackdrop`, the way the Dashboard mounts `DebugConstellation`, which
 * keeps the invariant that every route mounts *some* constellation and so keeps
 * the shared canvas from ever being released (`SharedCanvas.tsx`). The archived
 * branch below is the one place `SkyBackdrop` is still needed, because that
 * branch is a 2D list.
 *
 * **Search dims rather than filters.** Spatial memory is the whole return on
 * spending a layout: once you know where a cohort lives, it stays there while
 * you type. Sort is what decides slot order, so changing it genuinely
 * rearranges the sky — a deliberate act, unlike a keystroke.
 *
 * Archived cohorts stay behind a toggle and stay a list: that is a recovery
 * surface rather than a browsing one, and permanent delete is only reachable
 * there (the two-step guard, `DATA.md#archive-and-delete`).
 */

type SortKey = "recent" | "name";

export function Cohorts() {
  const navigate = useNavigate();
  // Stable, because `CohortSky` builds its node list in a memo keyed on this:
  // an inline arrow here rebuilt every world's scene node on every render of
  // this route — each keystroke in the search box included.
  const createCohort = useCallback(() => navigate("/cohorts/new"), [navigate]);
  const { client, status } = useSidecar();
  const cohorts = useCohorts();
  const loaded = useCohortsLoaded();

  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("recent");
  const [showArchived, setShowArchived] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CohortSummary | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);

  /** The world the panel is editing, before it is saved. Null = untouched. */
  const [draft, setDraft] = useState<ResolvedAppearance | null>(null);
  const [saving, setSaving] = useState(false);
  /** The focused cohort's roster — the one `cohorts.get` the panel costs.
   *  Keyed by cohort so a stale answer for the last planet never lands on
   *  this one. */
  const [roster, setRoster] = useState<{ id: string; animals: Animal[] } | null>(null);

  const connected = status === "connected";
  const archivedCount = cohorts.filter((c) => c.archived).length;

  /** Slot order. The sort control decides it, so it holds every cohort in the
   *  set — search does not shorten this list, it only dims members of it. */
  const inSky = useMemo(() => {
    const active = cohorts.filter((c) => !c.archived);
    return [...active].sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name)
        : b.updatedAt.localeCompare(a.updatedAt),
    );
  }, [cohorts, sort]);

  /** Who the search has ruled out — still drawn, still in place. */
  const dimmed = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return EMPTY_SET;
    return new Set(
      inSky.filter((c) => !c.name.toLowerCase().includes(needle)).map((c) => c.id),
    );
  }, [inSky, query]);

  const archived = useMemo(
    () =>
      cohorts
        .filter((c) => c.archived)
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    [cohorts],
  );

  const focused = useMemo(
    () => inSky.find((c) => c.id === focusedId) ?? null,
    [inSky, focusedId],
  );

  // What the planet is drawing right now: the unsaved draft if there is one,
  // otherwise whatever the store says. One expression, so the scene and the
  // panel can never disagree about which world is on screen.
  const shown = useMemo(
    () =>
      focused ? (draft ?? resolveAppearance(focused.id, focused.appearance)) : null,
    [focused, draft],
  );

  /** The sky, with the focused cohort's unsaved world patched in. */
  const sky = useMemo(() => {
    if (!focused || !draft) return inSky;
    return inSky.map((c) => (c.id === focused.id ? { ...c, appearance: draft } : c));
  }, [inSky, focused, draft]);

  const run = useCallback(async (action: () => Promise<unknown>) => {
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    if (!focusedId || !connected) return;
    let cancelled = false;
    void getCohort(client, focusedId)
      .then((full) => {
        if (!cancelled) setRoster({ id: full.id, animals: full.animals });
      })
      .catch((err) => {
        if (!cancelled) setActionError(errorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client, connected, focusedId]);

  const chooseFocus = useCallback((id: string | null) => {
    // Leaving a planet drops the draft. Deliberate: an unsaved hue is a thing
    // you were trying, not a thing you decided, and carrying it invisibly to
    // the next planet you open would be a surprise later.
    setDraft(null);
    setSaving(false);
    setFocusedId(id);
  }, []);

  // Escape leaves the planet, the way it leaves a modal. Only while one is
  // focused, so the key keeps whatever meaning the rest of the page gives it.
  useEffect(() => {
    if (!focusedId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") chooseFocus(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedId, chooseFocus]);

  const save = useCallback(async () => {
    if (!focused || !draft) return;
    setSaving(true);
    setActionError(null);
    try {
      await updateCohort(client, focused.id, { appearance: draft });
      setDraft(null);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }, [client, focused, draft]);

  const reset = useCallback(async () => {
    if (!focused) return;
    setSaving(true);
    try {
      // Explicit null, not an omitted key — that is what the sidecar reads as
      // "back to the world this cohort's id draws" rather than "leave it".
      await updateCohort(client, focused.id, { appearance: null });
      setDraft(null);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }, [client, focused]);

  // The archived branch is a 2D list, so it needs the inert sky under it. The
  // browser branch mounts its own constellation instead.
  if (showArchived) {
    return (
      <div className="relative h-full">
        <SkyBackdrop />
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={springPanel}
          className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
        >
          <section className="pointer-events-auto mx-auto max-w-5xl px-8 py-8">
            <div className="flex items-center justify-between gap-4">
              <h1 className="font-display text-[22px] text-starlight">Archived</h1>
              <ArchivedToggle
                showArchived={showArchived}
                archivedCount={archivedCount}
                onChange={setShowArchived}
              />
            </div>

            {actionError && <ErrorLine>{actionError}</ErrorLine>}

            {!connected ? (
              <Notice>
                Cohorts live in the backend, which isn&apos;t connected right now.
              </Notice>
            ) : !loaded ? (
              <Notice>Loading cohorts…</Notice>
            ) : archived.length === 0 ? (
              <Notice>No archived cohorts.</Notice>
            ) : (
              <ArchivedList
                cohorts={archived}
                onRestore={(c) => void run(() => restoreCohort(client, c.id))}
                onDelete={setPendingDelete}
              />
            )}
          </section>
        </motion.div>

        <DeleteConfirm
          cohort={pendingDelete}
          onCancel={() => setPendingDelete(null)}
          onConfirm={async () => {
            const target = pendingDelete;
            setPendingDelete(null);
            if (target) await run(() => deleteCohort(client, target.id));
          }}
        />
      </div>
    );
  }

  return (
    // No `overflow-hidden`: the stage host reaches back under the sidebar
    // (`Scene.tsx`), exactly as on every other constellation route.
    <div className="relative h-full">
      {/* Outside the entrance animation on purpose. The shared canvas lives in
          here, so fading this subtree would fade the sky itself — and since the
          neighbouring routes show the same sky, that reads as the constellation
          blinking out on every arrival. Only the chrome animates. */}
      <CohortSky
        cohorts={sky}
        focusedId={focusedId}
        onFocus={chooseFocus}
        dimmed={dimmed}
        {...(connected && loaded ? { onCreate: createCohort } : {})}
        frameShift={PANEL_FRAME_SHIFT}
      />

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="pointer-events-none absolute inset-0"
      >
        {/* The rail: identity and the two controls that still mean something in
            a sky. It floats over the scene rather than sitting above it — the
            planets need the whole frame, and the rail is chrome. */}
        <div className="pointer-events-auto absolute left-8 top-4 flex max-w-[420px] flex-col gap-2.5">
          <h1 className="font-display text-[22px] text-starlight">Cohorts</h1>
          <p className="-mt-1 text-[12px] leading-relaxed text-static">
            Every world is a cohort. Click one to inspect it; drag to look around.
          </p>

          <div className="flex items-center gap-2">
            <TextInput
              label="Search cohorts"
              value={query}
              onChange={setQuery}
              placeholder="Search…"
              className="w-44"
            />
            <Select
              label="Sort cohorts"
              value={sort}
              options={[
                { value: "recent", label: "Recent" },
                { value: "name", label: "Name" },
              ]}
              onChange={(v) => setSort(v as SortKey)}
            />
          </div>

          {query.trim() !== "" && (
            <p className="font-mono text-[10px] text-static/70">
              {inSky.length - dimmed.size} of {inSky.length} — the rest are dimmed
              where they are
            </p>
          )}

          {(archivedCount > 0 || showArchived) && (
            <ArchivedToggle
              showArchived={showArchived}
              archivedCount={archivedCount}
              onChange={setShowArchived}
            />
          )}

          {actionError && <ErrorLine>{actionError}</ErrorLine>}

          {!connected ? (
            <Notice>
              Cohorts live in the backend, which isn&apos;t connected right now.
            </Notice>
          ) : !loaded ? (
            <Notice>Loading cohorts…</Notice>
          ) : inSky.length === 0 ? (
            <Notice>
              No cohorts yet. The unformed disc in the middle of the sky makes
              the first one.
            </Notice>
          ) : null}

          {/* The reading key, folded away until asked — a world carries three
              readings and nobody should have to guess them, but nobody needs
              telling twice either (`HowToRead`'s reasoning). */}
          <div className="hud max-w-[360px] rounded-md px-3 pb-2 pt-1">
            <HowToRead>
              <span className="text-starlight">Size</span> is the roster.{" "}
              <span className="text-starlight">Brightness and spin</span> are how
              recently anyone worked on it — a dormant cohort sits in its own
              shadow. <span className="text-starlight">Ships</span> are its home
              cages. Type, colour and ring are yours to set: focus a world and
              open its panel.
            </HowToRead>
          </div>
        </div>

        {focused && shown && (
          <AppearancePanel
            cohort={focused}
            animals={roster?.id === focused.id ? roster.animals : null}
            appearance={shown}
            dirty={draft !== null}
            saving={saving}
            error={actionError}
            onChange={setDraft}
            onReset={() => void reset()}
            onSave={() => void save()}
            onDiscard={() => setDraft(null)}
            onOpen={() => navigate(`/cohorts/${focused.id}`)}
            onClose={() => chooseFocus(null)}
          />
        )}
      </motion.div>
    </div>
  );
}

/** The panel is 400px inset 16px; the sidebar is 200px. The camera slides the
 *  rendered window so the focused world sits clear of it, without moving the
 *  orbit pivot off the planet (`CameraRig`'s framing bias). */
const PANEL_FRAME_SHIFT = (400 + 16 - 200) / 2;

const EMPTY_SET: ReadonlySet<string> = new Set();

function ArchivedToggle({
  showArchived,
  archivedCount,
  onChange,
}: {
  showArchived: boolean;
  archivedCount: number;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Toggle label="Show archived" checked={showArchived} onChange={onChange} />
      <span className="text-[12px] text-static">
        Show archived
        {archivedCount > 0 && <span className="font-mono"> ({archivedCount})</span>}
      </span>
    </div>
  );
}

function ErrorLine({ children }: { children: ReactNode }) {
  return (
    <p
      className="rounded-sm border border-halo bg-void/40 px-3 py-2 text-[12px]"
      style={{ color: "var(--color-status-error)" }}
    >
      {children}
    </p>
  );
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="mt-4 flex items-start gap-3">
      <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
        <Users size={18} strokeWidth={1.75} className="text-pulsar" />
      </span>
      <p className="max-w-prose pt-2 text-[13px] leading-relaxed text-static">
        {children}
      </p>
    </div>
  );
}

/**
 * Archived cohorts get a list rather than the sky: this is a recovery surface,
 * not a browsing one, and permanent delete is only reachable here (the
 * two-step guard). The disc still appears, so a cohort is recognisable here as
 * the world it is everywhere else.
 */
function ArchivedList({
  cohorts,
  onRestore,
  onDelete,
}: {
  cohorts: CohortSummary[];
  onRestore: (cohort: CohortSummary) => void;
  onDelete: (cohort: CohortSummary) => void;
}) {
  if (cohorts.length === 0) return null;
  return (
    <div className="surface mt-5 rounded-md">
      {cohorts.map((cohort) => (
        <div
          key={cohort.id}
          className="flex items-center gap-3 border-b border-halo px-4 py-3 last:border-b-0"
        >
          <PlanetDisc cohortId={cohort.id} appearance={cohort.appearance} size={32} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] text-starlight">
              {cohort.name}
            </span>
            <span className="font-mono text-[11px] text-static">
              {cohort.animalCount}{" "}
              {cohort.animalCount === 1 ? "animal" : "animals"}
            </span>
          </span>
          <Button onClick={() => onRestore(cohort)} title="Restore to the browser">
            <RotateCcw size={13} strokeWidth={1.75} />
            Restore
          </Button>
          <Button
            variant="outline"
            onClick={() => onDelete(cohort)}
            title="Delete permanently"
          >
            <Trash2 size={13} strokeWidth={1.75} />
          </Button>
        </div>
      ))}
    </div>
  );
}

function DeleteConfirm({
  cohort,
  onCancel,
  onConfirm,
}: {
  cohort: CohortSummary | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Modal open={cohort !== null} onClose={onCancel} title="Delete permanently?">
      {cohort && (
        <div className="flex flex-col gap-4">
          <p className="text-[13px] leading-relaxed text-static">
            <span className="text-starlight">{cohort.name}</span> will be removed
            from Ephymeris for good, along with its animals and groups.
          </p>
          {/* `DATA.md#archive-and-delete` — the app removes its own bookkeeping, never the user's data. */}
          <p className="rounded-sm border border-halo bg-void/40 px-3 py-2 text-[12px] leading-relaxed text-static">
            Its data folder on disk is <span className="text-starlight">not</span>{" "}
            touched — recorded session files stay exactly where they are.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button variant="primary" onClick={onConfirm}>
              <Archive size={13} strokeWidth={1.75} />
              Delete permanently
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
