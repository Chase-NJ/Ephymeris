import { motion } from "framer-motion";
import { ChartLine, ClipboardList, GitCompareArrows, Loader2, NotebookPen, UserRound } from "lucide-react";
import { useEffect, useMemo, type Ref } from "react";
import { useNavigate } from "react-router";

import { SessionTable } from "@/components/analytics/session/SessionTable";
import { Button } from "@/components/common/controls";
import { HudTile } from "@/components/common/HudTile";
import {
  useAnalyticsStore,
  useDataVersion,
  useLoadState,
  useSummary,
} from "@/lib/analytics/context";
import { conditionColumns, sessionRunsOf } from "@/lib/analytics/session";
import type { SessionListItem } from "@/lib/analytics/types";
import { buildAnimalColors } from "@/lib/analytics/view";
import { addNote, deleteNote, editNote, resolveFlag, setSessionLog } from "@/lib/logbook/commands";
import type { LogbookEntry } from "@/lib/logbook/store";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";
import { useSidecar } from "@/lib/ws/context";

import { ChangesList } from "./ChangesList";
import { NoteComposer } from "./NoteComposer";
import { NotesTimeline, noteAnchor } from "./NotesTimeline";
import { SessionClockHeader } from "./SessionClockHeader";
import { SessionLogForm } from "./SessionLogForm";
import type { RosterAnimal } from "./tags";

/**
 * One session's page of the log: its clock, its notes, how each animal did,
 * what changed since last time, and who ran it. The selected tick on the rail
 * opens this; switching sessions fades the new page in over the same place, so
 * it reads as one readout changing channel rather than a new page.
 *
 * Everything shown is what the sidecar reported — a note appears when the
 * `logbook.updated` it caused comes back, never optimistically.
 */
export function SessionReadout({
  cohortId,
  session,
  entry,
  roster,
  names,
  composerRef,
}: {
  cohortId: string;
  session: SessionListItem;
  entry: LogbookEntry;
  roster: RosterAnimal[];
  names: Map<string, string>;
  composerRef?: Ref<HTMLTextAreaElement> | undefined;
}) {
  const { client, status } = useSidecar();
  const reduce = useReduceMotion();
  const navigate = useNavigate();
  const analytics = useAnalyticsStore();
  const summary = useSummary(cohortId);
  const summaryState = useLoadState(cohortId);
  const version = useDataVersion();

  // The performance table reads the Analytics summary — the same numbers, the
  // same cache. A cold one can index the whole archive, so it is asked for
  // only once the Log is actually showing a session.
  useEffect(() => {
    if (status !== "connected") return;
    void analytics.load(client, cohortId);
  }, [analytics, client, cohortId, status, version]);

  const notes = entry.notesBySession.get(session.id) ?? NONE;
  const changes = entry.changesBySession.get(session.id) ?? [];
  const log = entry.logs.get(session.id) ?? null;
  const readOnly = session.id.startsWith("adopted:");

  const runs = useMemo(
    () => (summary ? sessionRunsOf(summary, session.id) : []),
    [summary, session.id],
  );
  const columns = useMemo(
    () => (summary ? conditionColumns(runs, summary.profileGroups) : []),
    [runs, summary],
  );
  const colors = useMemo(() => buildAnimalColors(summary?.animals ?? []), [summary]);
  const tableNames = useMemo(() => {
    const merged = new Map((summary?.animals ?? []).map((a) => [a.id, a.name]));
    for (const [id, name] of names) merged.set(id, name);
    return merged;
  }, [summary, names]);
  const boxes = useMemo(() => {
    const used = new Set<number>(changes.map((c) => c.box));
    for (const run of runs) if (run.boxNumber !== null) used.add(run.boxNumber);
    return used.size > 0 ? [...used].sort((a, b) => a - b) : [1, 2, 3, 4, 5, 6];
  }, [changes, runs]);
  const animalCount = new Set([...runs.map((r) => r.animalId), ...changes.map((c) => c.animalId)])
    .size;

  function focusNote(noteId: string) {
    document
      .getElementById(noteAnchor(noteId))
      ?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
  }

  return (
    // Keyed, entering only — no exit. Stepping the rail quickly must never
    // show an empty page between two sessions, which a wait-for-exit would.
    <motion.div
        key={session.id}
        initial={reduce ? false : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springSnappy}
        className="flex flex-col gap-4"
      >
        <SessionClockHeader
          session={session}
          notes={notes}
          animalCount={animalCount}
          onNote={focusNote}
        />

        <HudTile
          icon={NotebookPen}
          label="Notes"
          status={`${notes.length} note${notes.length === 1 ? "" : "s"}`}
        >
          {readOnly ? (
            <p className="border-b border-halo px-4 py-3 text-[12px] text-static">
              This session was recovered from files and has no record to write notes against.
            </p>
          ) : (
            <div className="border-b border-halo px-4 py-3">
              <NoteComposer
                key={session.id}
                sessionDate={session.date}
                roster={roster}
                boxes={boxes}
                textareaRef={composerRef}
                onSubmit={async (draft) => {
                  await addNote(client, session.id, draft);
                }}
              />
            </div>
          )}
          <NotesTimeline
            notes={notes}
            names={tableNames}
            sessionDate={session.date}
            roster={roster}
            boxes={boxes}
            readOnly={readOnly}
            onEdit={async (note, draft) => {
              await editNote(client, note.id, draft);
            }}
            onDelete={async (note) => {
              await deleteNote(client, note.id);
            }}
            onResolve={async (note, resolved) => {
              await resolveFlag(client, note.id, resolved, null);
            }}
          />
        </HudTile>

        <HudTile
          icon={ClipboardList}
          label="Performance"
          status={
            <Button
              variant="ghost"
              onClick={() =>
                navigate("/analytics", { state: { cohortId, sessionId: session.id } })
              }
            >
              <ChartLine size={12} strokeWidth={1.75} />
              Open in Analytics
            </Button>
          }
        >
          {summary && runs.length > 0 ? (
            <div className="p-3">
              <SessionTable
                runs={runs}
                columns={columns}
                names={tableNames}
                colors={colors}
                minCounted={summary.minCountedTrials}
                onSelect={null}
              />
            </div>
          ) : (
            <p className="flex items-center gap-2 px-4 py-4 text-[12px] text-static">
              {summaryState === "loading" || (!summary && summaryState !== "error") ? (
                <>
                  <Loader2 size={13} strokeWidth={1.75} className="animate-spin" aria-hidden />
                  Reading this cohort's runs…
                </>
              ) : summaryState === "error" ? (
                "The runs couldn't be read — Analytics says why."
              ) : session.status === "running" ? (
                "Each animal appears here as its box finishes."
              ) : (
                "No runs were recorded in this session."
              )}
            </p>
          )}
        </HudTile>

        <HudTile icon={GitCompareArrows} label="What changed" status="since each animal's previous run">
          <ChangesList changes={changes} names={tableNames} colors={colors} recovered={readOnly} />
        </HudTile>

        <HudTile icon={UserRound} label="Operator and summary">
          <SessionLogForm
            key={session.id}
            log={log}
            readOnly={readOnly}
            onSave={async (fields) => {
              await setSessionLog(client, session.id, fields);
            }}
          />
        </HudTile>
      </motion.div>
  );
}

const NONE: never[] = [];
