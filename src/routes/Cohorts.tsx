import { motion } from "framer-motion";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { Archive, RotateCcw, Trash2, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";

import {
  Button,
  Select,
  TextInput,
  Toggle,
} from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { CohortCard } from "@/components/cohorts/CohortCard";
import { CohortIcon } from "@/components/cohorts/CohortIcon";
import { NewCohortTile } from "@/components/cohorts/NewCohortTile";
import {
  deleteCohort,
  errorMessage,
  restoreCohort,
} from "@/lib/cohorts/commands";
import { useCohorts, useCohortsLoaded } from "@/lib/cohorts/context";
import type { CohortSummary } from "@/lib/cohorts/types";
import { springPanel } from "@/lib/motion";
import { useSidecar } from "@/lib/ws/context";

/**
 * Cohort browser — `cohorts.md` §4.
 *
 * A card grid rather than a list: this view is for visually scanning and
 * selecting, not reading top to bottom. Archived cohorts are hidden behind a
 * toggle so the main grid stays a view of *available* cohorts (§4, §9).
 */

type SortKey = "recent" | "name";

export function Cohorts() {
  const navigate = useNavigate();
  const { client, status } = useSidecar();
  const cohorts = useCohorts();
  const loaded = useCohortsLoaded();

  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("recent");
  const [showArchived, setShowArchived] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CohortSummary | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = cohorts.filter(
      (c) =>
        c.archived === showArchived &&
        (needle === "" || c.name.toLowerCase().includes(needle)),
    );
    return [...filtered].sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name)
        : b.updatedAt.localeCompare(a.updatedAt),
    );
  }, [cohorts, query, sort, showArchived]);

  const archivedCount = cohorts.filter((c) => c.archived).length;
  const connected = status === "connected";

  async function run(action: () => Promise<unknown>) {
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  return (
    // Every route sits on the rig's sky. Not decoration: a route that mounts no
    // constellation is the only thing that releases the shared canvas, and that
    // teardown is what made a sidebar round trip snap (`SkyBackdrop`).
    <div className="relative h-full">
      <SkyBackdrop />

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit: the shell holds every page opaque on the way out
        // now, so anything that should fade has to say so (`AppShell`).
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        <section className="pointer-events-auto mx-auto max-w-5xl px-8 py-8">
          <div className="flex items-center justify-between gap-4">
            <h1 className="font-display text-[22px] text-starlight">Cohorts</h1>

            <div className="flex items-center gap-2">
              <TextInput
                label="Search cohorts"
                value={query}
                onChange={setQuery}
                placeholder="Search…"
                className="w-48"
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
          </div>

          {(archivedCount > 0 || showArchived) && (
            <div className="mt-4 flex items-center gap-2.5">
              <Toggle
                label="Show archived"
                checked={showArchived}
                onChange={setShowArchived}
              />
              <span className="text-[12px] text-static">
                Show archived
                {archivedCount > 0 && (
                  <span className="font-mono"> ({archivedCount})</span>
                )}
              </span>
            </div>
          )}

          {actionError && (
            <p
              className="mt-4 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              {actionError}
            </p>
          )}

          {!connected ? (
            <Notice>
              Cohorts live in the backend, which isn't connected right now.
            </Notice>
          ) : !loaded ? (
            <Notice>Loading cohorts…</Notice>
          ) : showArchived ? (
            <ArchivedList
              cohorts={visible}
              onRestore={(c) => void run(() => restoreCohort(client, c.id))}
              onDelete={setPendingDelete}
            />
          ) : (
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              <NewCohortTile onClick={() => navigate("/cohorts/new")} />
              {visible.map((cohort) => (
                <CohortCard
                  key={cohort.id}
                  cohort={cohort}
                  onOpen={() => navigate(`/cohorts/${cohort.id}`)}
                />
              ))}
            </div>
          )}

          {showArchived && visible.length === 0 && loaded && connected && (
            <Notice>No archived cohorts.</Notice>
          )}

          <DeleteConfirm
            cohort={pendingDelete}
            onCancel={() => setPendingDelete(null)}
            onConfirm={async () => {
              const target = pendingDelete;
              setPendingDelete(null);
              if (target) await run(() => deleteCohort(client, target.id));
            }}
          />
        </section>
      </motion.div>
    </div>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-8 flex items-start gap-3">
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
 * Archived cohorts get a list rather than the card grid: this is a recovery
 * surface, not a browsing one, and permanent delete is only reachable here
 * (§9's two-step guard).
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
          <CohortIcon
            cohortId={cohort.id}
            animalCount={cohort.animalCount}
            size={32}
          />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] text-starlight">
              {cohort.name}
            </span>
            <span className="font-mono text-[11px] text-static">
              {cohort.animalCount}{" "}
              {cohort.animalCount === 1 ? "animal" : "animals"}
            </span>
          </span>
          <Button
            onClick={() => onRestore(cohort)}
            title="Restore to the active grid"
          >
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
    <Modal
      open={cohort !== null}
      onClose={onCancel}
      title="Delete permanently?"
    >
      {cohort && (
        <div className="flex flex-col gap-4">
          <p className="text-[13px] leading-relaxed text-static">
            <span className="text-starlight">{cohort.name}</span> will be
            removed from Ephymeris for good, along with its animals and groups.
          </p>
          {/* §9 — the app removes its own bookkeeping, never the user's data. */}
          <p className="rounded-sm border border-halo bg-void/40 px-3 py-2 text-[12px] leading-relaxed text-static">
            Its data folder on disk is{" "}
            <span className="text-starlight">not</span> touched — recorded
            session files stay exactly where they are.
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
