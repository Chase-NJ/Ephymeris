import { memo, useMemo } from "react";

import type { SessionListItem } from "@/lib/analytics/types";
import { longDate, shortDate } from "@/lib/logbook/clock";
import { oldestFirst, type ContentsMonth } from "@/lib/logbook/pages";
import { GRADE_LABEL, sessionTotals, sessionVerdicts, type RunVerdict } from "@/lib/logbook/signal";
import type { LogbookEntry } from "@/lib/logbook/store";

import type { RosterAnimal } from "../tags";
import { AnimalMark, Caption, SectionHead } from "./parts";

/** How many recordings the title page ranks. */
const RANKED = 6;

interface Ranked {
  session: SessionListItem;
  verdict: RunVerdict;
}

/** Every measured recording of the cohort, the most unit-like sites first. */
function rankRecordings(entry: LogbookEntry): Ranked[] {
  const byId = new Map(entry.sessions.map((s) => [s.id, s]));
  const ranked: Ranked[] = [];
  for (const [sessionId, runs] of entry.signalsBySession) {
    const session = byId.get(sessionId);
    if (!session) continue;
    for (const verdict of sessionVerdicts(runs).values()) {
      if (verdict.basis === "waveforms" && verdict.unitLike > 0) ranked.push({ session, verdict });
    }
  }
  return ranked.sort(
    (a, b) =>
      b.verdict.unitLike - a.verdict.unitLike ||
      b.verdict.unitLike / b.verdict.total - a.verdict.unitLike / a.verdict.total ||
      b.session.ordinal - a.session.ordinal,
  );
}

/**
 * The notebook's title page: whose it is, what it spans, who is in it, and,
 * for a cohort that records, which days are most worth sorting first
 * (`RECORDING.md#unit-like-sites`). The one place that question is answered
 * across the whole notebook, which is why it is the first page.
 */
export const TitlePage = memo(function TitlePage({
  cohortName,
  entry,
  roster,
  names,
  colors,
  onOpen,
}: {
  cohortName: string;
  entry: LogbookEntry;
  roster: RosterAnimal[];
  names: Map<string, string>;
  colors: Map<string, string>;
  onOpen: (id: string) => void;
}) {
  const ordered = useMemo(() => oldestFirst(entry.sessions), [entry.sessions]);
  const first = ordered[0];
  const last = ordered[ordered.length - 1];
  const noteCount = useMemo(
    () => [...entry.notesBySession.values()].reduce((n, list) => n + list.length, 0),
    [entry.notesBySession],
  );
  const weighIns = useMemo(
    () => [...entry.healthByAnimal.values()].reduce((n, list) => n + list.length, 0),
    [entry.healthByAnimal],
  );
  const ranked = useMemo(() => rankRecordings(entry).slice(0, RANKED), [entry]);

  return (
    <article className="flex min-h-full flex-col">
      <header className="pt-[9%] text-center">
        <p className="smallcaps text-[12.5px] tracking-[0.14em] text-ink-blue">Laboratory notebook</p>
        <h2 className="mt-3 text-[40px] leading-[1.1] font-normal" data-selectable>
          {cohortName}
        </h2>
        <p className="mt-4 text-[15.5px] text-ink-soft italic">
          {first && last
            ? first.date === last.date
              ? longDate(first.date)
              : `${longDate(first.date)} to ${longDate(last.date)}`
            : "No sessions yet"}
        </p>
        <div aria-hidden className="mx-auto mt-6 h-[1.5px] w-16 bg-ink" />
        <p className="mt-5 text-[14.5px] text-ink-soft">
          {plural(entry.sessions.length, "session")} · {plural(noteCount, "note")} ·{" "}
          {plural(weighIns, "weigh-in")}
          {entry.openFlags.length > 0 && (
            <>
              {" "}
              · <span className="text-ink-red">{plural(entry.openFlags.length, "open flag")}</span>
            </>
          )}
        </p>
      </header>

      {roster.length > 0 && (
        <section className="mx-auto mt-9 w-full max-w-[380px]">
          <p className="smallcaps mb-1.5 text-center text-[11.5px] font-bold">Animals</p>
          <ul className="grid grid-cols-3 gap-x-4 gap-y-1 text-[14.5px]">
            {roster.map((animal) => (
              <li key={animal.id}>
                <AnimalMark name={animal.name} color={colors.get(animal.id)} strong={false} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {ranked.length > 0 && (
        <section className="mt-9">
          <SectionHead>Recordings to sort first</SectionHead>
          <Caption label="Table i">
            The recorded days with the most unit-like sites. An estimate from spike amplitude
            over noise, to order the sorting by; not sorted units.
          </Caption>
          <table className="booktabs text-[14.5px]">
            <thead>
              <tr>
                <th scope="col">Animal</th>
                <th scope="col">Session</th>
                <th scope="col" className="num">
                  Unit-like
                </th>
                <th scope="col">For sorting</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map(({ session, verdict }) => (
                <tr key={verdict.runId}>
                  <td>
                    <AnimalMark
                      name={names.get(verdict.animalId) ?? verdict.animalId}
                      color={colors.get(verdict.animalId)}
                    />
                  </td>
                  <td>
                    <button type="button" className="ink-link" onClick={() => onOpen(session.id)}>
                      {shortDate(session.date)}, {session.prefixName}_{session.sessionNumber}
                    </button>
                  </td>
                  <td className="num whitespace-nowrap">
                    <span className="font-bold">{verdict.unitLike}</span>
                    <span className="text-ink-soft"> / {verdict.total}</span>
                  </td>
                  <td className="smallcaps text-[11.5px]">{verdict.grade ? GRADE_LABEL[verdict.grade] : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <p className="mt-auto pt-8 text-center text-[13px] text-ink-faint italic">
        Turn the page with ← and →, or pick a day from the contents.
      </p>
    </article>
  );
});

/**
 * The contents: every session under its month, a dotted leader out to its
 * page. What each line carries besides the day is what a reader scans a
 * notebook for: how much was written, whether anything is still flagged, and
 * how much the electrodes gave.
 */
export const ContentsPage = memo(function ContentsPage({
  months,
  entry,
  latestId,
  onOpen,
}: {
  months: readonly ContentsMonth[];
  entry: LogbookEntry;
  latestId: string | null;
  onOpen: (id: string) => void;
}) {
  const flagged = useMemo(
    () => new Set(entry.openFlags.map((note) => note.sessionId)),
    [entry.openFlags],
  );
  const totals = useMemo(() => {
    const bySession = new Map<string, { unitLike: number; total: number }>();
    for (const [sessionId, runs] of entry.signalsBySession) {
      const sum = sessionTotals(sessionVerdicts(runs).values());
      if (sum.graded) bySession.set(sessionId, sum);
    }
    return bySession;
  }, [entry.signalsBySession]);

  return (
    <article>
      <h2 className="pt-1 text-[26px] leading-tight font-bold">Contents</h2>
      {months.length === 0 && (
        <p className="mt-4 text-[14.5px] text-ink-soft italic">
          {entry.state === "loading"
            ? "Reading the notebook…"
            : (entry.error ?? "No sessions recorded for this cohort yet.")}
        </p>
      )}
      {months.map((month) => (
        <section key={month.key} className="mt-5">
          <h3 className="mb-1 text-[16.5px] font-bold">{month.label}</h3>
          <ol>
            {month.rows.map((row) => {
              const notes = entry.notesBySession.get(row.id)?.length ?? 0;
              const signal = totals.get(row.id);
              return (
                <li key={row.id}>
                  <button
                    type="button"
                    onClick={() => onOpen(row.id)}
                    className="group flex w-full items-baseline rounded-[2px] py-[2.5px] text-left text-[14.5px] hover:bg-paper-shade"
                  >
                    <span className="w-[26px] shrink-0 text-right">{row.day}</span>
                    <span className="ml-1.5 w-[32px] shrink-0 text-[13px] text-ink-faint">
                      {row.weekday}
                    </span>
                    <span className="truncate group-hover:text-ink-blue" data-selectable>
                      {row.title}
                    </span>
                    {row.id === latestId && (
                      <span className="smallcaps ml-2 shrink-0 text-[10.5px] text-ink-blue">
                        latest
                      </span>
                    )}
                    <RowStatus status={row.status} recovered={row.recovered} />
                    <span aria-hidden className="leader" />
                    <span className="flex shrink-0 items-baseline gap-2.5 text-[13px] text-ink-soft">
                      {signal && (
                        <span
                          className="text-ink-plum"
                          title={`${signal.unitLike} of ${signal.total} recorded sites unit-like`}
                        >
                          {signal.unitLike}/{signal.total} sites
                        </span>
                      )}
                      {notes > 0 && <span>{plural(notes, "note")}</span>}
                      {flagged.has(row.id) && (
                        <span className="text-ink-red" title="Has an open carry-forward flag">
                          ⚑
                        </span>
                      )}
                    </span>
                    <span className="ml-2.5 w-[30px] shrink-0 text-right">{row.page}</span>
                  </button>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </article>
  );
});

function RowStatus({
  status,
  recovered,
}: {
  status: SessionListItem["status"];
  recovered: boolean;
}) {
  const text = recovered
    ? "recovered"
    : status === "running"
      ? "running"
      : status === "aborted"
        ? "abandoned"
        : status === "configuring"
          ? "setting up"
          : null;
  if (!text) return null;
  const ink =
    status === "running" && !recovered
      ? "text-ink-teal"
      : status === "aborted" && !recovered
        ? "text-ink-red"
        : "text-ink-soft";
  return <span className={`ml-2 shrink-0 text-[13px] italic ${ink}`}>{text}</span>;
}

function plural(count: number, one: string): string {
  return `${count} ${one}${count === 1 ? "" : "s"}`;
}
