import { memo, useMemo } from "react";
import { useNavigate } from "react-router";

import { useLoadState, useSummary } from "@/features/analytics/context";
import {
  conditionColumns,
  sessionFalseStartsOf,
  sessionRunsOf,
} from "@/features/analytics/session";
import type { AnalyticsSummary, SessionListItem } from "@/features/analytics/types";
import {
  addNote,
  deleteNote,
  editNote,
  resolveFlag,
  setHealth,
  setSessionLog,
} from "../commands";
import { sessionVerdicts, unitTrend } from "../signal";
import type { LogbookEntry } from "../store";
import { useSidecar } from "@/lib/ws/context";

import type { RosterAnimal } from "../tags";
import { Changes } from "./Changes";
import { Notes, type ComposeRequest } from "./Notes";
import { SectionHead, paperAnimalColors } from "./parts";
import { StickyFlags } from "./StickyFlags";
import {
  PerformanceTable,
  SignalTable,
  WeighInTable,
  type SignalRow,
  type WeighRow,
} from "./Tables";
import { TitleBlock } from "./TitleBlock";

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
const NONE: never[] = [];

interface PageProps {
  cohortId: string;
  session: SessionListItem;
  entry: LogbookEntry;
  roster: RosterAnimal[];
  names: Map<string, string>;
}

/**
 * What both pages of a session's spread read: who ran, under which names and
 * colours. One place, so the left page's "about" list and the right page's
 * rows can never name different animals.
 */
function useSpread({ cohortId, session, entry, roster, names }: PageProps) {
  const summary = useSummary(cohortId);
  const changes = entry.changesBySession.get(session.id) ?? NONE;
  const runs = useMemo(
    () => (summary ? sessionRunsOf(summary, session.id) : NONE),
    [summary, session.id],
  );
  // Roster order picks an animal's colour, as it does on every other screen;
  // an animal the summary has not listed yet takes the next one.
  const colors = useMemo(() => {
    const known = (summary?.animals ?? []).map((a) => ({ id: a.id }));
    const seen = new Set(known.map((a) => a.id));
    return paperAnimalColors([...known, ...roster.filter((a) => !seen.has(a.id))]);
  }, [summary, roster]);
  const allNames = useMemo(() => {
    const merged = new Map((summary?.animals ?? []).map((a) => [a.id, a.name]));
    for (const [id, name] of names) merged.set(id, name);
    return merged;
  }, [summary, names]);
  const ran = useMemo(
    () => new Set([...runs.map((r) => r.animalId), ...changes.map((c) => c.animalId)]),
    [runs, changes],
  );
  // A former member who ran in this session can still be written about and
  // weighed (`DATA.md#former-members`); one who didn't is not offered.
  const pickable = useMemo(() => {
    const onRoster = new Set(roster.map((a) => a.id));
    const former = [...ran]
      .filter((id) => !onRoster.has(id) && allNames.has(id))
      .map((id) => ({ id, name: allNames.get(id)!, box: null }));
    return former.length > 0 ? [...roster, ...former] : roster;
  }, [roster, ran, allNames]);
  const boxes = useMemo(() => {
    const used = new Set<number>(changes.flatMap((c) => (c.box === null ? [] : [c.box])));
    for (const run of runs) if (run.boxNumber !== null) used.add(run.boxNumber);
    return used.size > 0 ? [...used].sort((a, b) => a - b) : [1, 2, 3, 4, 5, 6];
  }, [changes, runs]);
  return { summary, changes, runs, colors, allNames, ran, pickable, boxes };
}

/**
 * A session's left page: what a person wrote. The day as its title, who ran
 * it and what they made of it, anything carried forward, and the notes.
 */
export const SessionVerso = memo(function SessionVerso(
  props: PageProps & {
    request: ComposeRequest | null;
    onOpen: (sessionId: string) => void;
  },
) {
  const { session, entry, request, onOpen } = props;
  const { client } = useSidecar();
  const { allNames, ran, pickable, boxes } = useSpread(props);
  const notes = entry.notesBySession.get(session.id) ?? NONE;
  const readOnly = session.id.startsWith("adopted:");

  return (
    <article>
      <TitleBlock
        session={session}
        log={entry.logs.get(session.id) ?? null}
        animalCount={ran.size}
        readOnly={readOnly}
        onSave={async (fields) => {
          await setSessionLog(client, session.id, fields);
        }}
      />
      <StickyFlags
        flags={entry.openFlags}
        sessions={entry.sessions}
        sessionId={session.id}
        names={allNames}
        onOpen={onOpen}
        onResolve={async (note) => {
          await resolveFlag(client, note.id, true, null);
        }}
      />
      <SectionHead
        number={1}
        aside={notes.length > 0 ? `${notes.length} note${notes.length === 1 ? "" : "s"}` : undefined}
      >
        Notes
      </SectionHead>
      <Notes
        notes={notes}
        names={allNames}
        sessionDate={session.date}
        roster={pickable}
        boxes={boxes}
        readOnly={readOnly}
        request={request}
        onAdd={async (draft) => {
          await addNote(client, session.id, draft);
        }}
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
    </article>
  );
});

/**
 * A session's right page: what was measured. How each animal did, what each
 * weighed, what its electrodes carried, and what was different from last time.
 */
export const SessionRecto = memo(function SessionRecto(
  props: PageProps & {
    /** Start a health note about an animal on the facing page. */
    onHealthNote: (animalId: string) => void;
  },
) {
  const { cohortId, session, entry, onHealthNote } = props;
  const { client } = useSidecar();
  const navigate = useNavigate();
  const summaryState = useLoadState(cohortId);
  const { summary, changes, runs, colors, allNames, ran, pickable } = useSpread(props);
  const readOnly = session.id.startsWith("adopted:");
  const setAside = useMemo(
    () => (summary ? sessionFalseStartsOf(summary, session.id) : NONE),
    [summary, session.id],
  );
  const columns = useMemo(
    () => (summary ? conditionColumns(runs, summary.profileGroups) : NONE),
    [runs, summary],
  );

  const weighRows = useMemo<WeighRow[]>(
    () =>
      pickable
        .map((animal) => ({ id: animal.id, name: animal.name, ran: ran.has(animal.id) }))
        .sort((a, b) => Number(b.ran) - Number(a.ran) || collator.compare(a.name, b.name)),
    [pickable, ran],
  );

  const signalRows = useSignalRows(entry, session, allNames);
  const section = signalRows.length > 0 ? { changes: 5 } : { changes: 4 };

  return (
    <article>
      <SectionHead
        number={2}
        aside={
          <button
            type="button"
            className="ink-link"
            onClick={() => navigate("/analytics", { state: { cohortId, sessionId: session.id } })}
          >
            open in Analytics
          </button>
        }
      >
        Performance
      </SectionHead>
      {summary && (runs.length > 0 || setAside.length > 0) ? (
        <PerformanceTable
          label="Table 1"
          runs={runs}
          setAside={setAside}
          columns={columns}
          names={allNames}
          colors={colors}
          minCounted={summary.minCountedTrials}
        />
      ) : (
        <p className="text-[14.5px] text-ink-soft italic">
          {performanceBlank(summary, summaryState, session)}
        </p>
      )}

      <SectionHead number={3}>Weights</SectionHead>
      {weighRows.length > 0 ? (
        <WeighInTable
          label="Table 2"
          date={session.date}
          rows={weighRows}
          health={entry.healthByAnimal}
          colors={colors}
          onSet={async (animalId, fields) => {
            await setHealth(client, cohortId, animalId, session.date, fields);
          }}
          onNote={readOnly ? undefined : onHealthNote}
        />
      ) : (
        <p className="text-[14.5px] text-ink-soft italic">This cohort has no animals to weigh.</p>
      )}

      {signalRows.length > 0 && (
        <>
          <SectionHead number={4}>Recording</SectionHead>
          <SignalTable label="Table 3" rows={signalRows} colors={colors} />
        </>
      )}

      <SectionHead number={section.changes}>Changes since last time</SectionHead>
      <Changes
        changes={changes}
        setAside={entry.falseStartsBySession.get(session.id) ?? NONE}
        names={allNames}
        colors={colors}
      />
    </article>
  );
});

function performanceBlank(
  summary: AnalyticsSummary | null,
  state: ReturnType<typeof useLoadState>,
  session: SessionListItem,
): string {
  if (state === "loading" || (!summary && state !== "error")) return "Reading this cohort's runs…";
  if (state === "error") return "The runs couldn't be read. Analytics says why.";
  if (session.status === "running") return "Each animal appears here as its box finishes.";
  return "No runs were recorded in this session.";
}

/** The session's recorded animals, each against its own recorded history up to this day. */
function useSignalRows(
  entry: LogbookEntry,
  session: SessionListItem,
  names: Map<string, string>,
): SignalRow[] {
  return useMemo(() => {
    const verdicts = sessionVerdicts(entry.signalsBySession.get(session.id) ?? NONE);
    if (verdicts.size === 0) return [];
    const order = new Map(entry.sessions.map((s) => [s.id, s.ordinal]));
    const rows: SignalRow[] = [];
    for (const [animalId, verdict] of verdicts) {
      const history = unitTrend(entry.signals, animalId, order);
      const upTo = history.filter(
        (point) => (order.get(point.sessionId) ?? 0) <= session.ordinal,
      );
      const earlier = upTo.filter((point) => point.sessionId !== session.id);
      rows.push({
        animalId,
        name: names.get(animalId) ?? animalId,
        verdict,
        trend: upTo.slice(-12),
        best: earlier.every((point) => point.unitLike <= verdict.unitLike),
      });
    }
    return rows.sort((a, b) => collator.compare(a.name, b.name));
  }, [entry.signalsBySession, entry.signals, entry.sessions, session.id, session.ordinal, names]);
}
