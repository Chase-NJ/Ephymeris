import { useEffect, useState } from "react";

import { FolderButton } from "@/components/common/FolderButton";
import type { SessionListItem } from "@/lib/analytics/types";
import {
  elapsedSeconds,
  formatDuration,
  formatOffset,
  longDate,
  wallClock,
} from "@/lib/logbook/clock";
import type { SessionNote } from "@/lib/logbook/types";

import { ReadoutFade } from "./ReadoutFade";
import { tagOf } from "./tags";

const STATUS: Record<SessionListItem["status"], { label: string; tone: string }> = {
  running: { label: "Running", tone: "text-status-ok" },
  configuring: { label: "Setting up", tone: "text-static" },
  completed: { label: "Completed", tone: "text-static" },
  aborted: { label: "Abandoned", tone: "text-status-warning" },
};

/**
 * The session's clock, as the instrument the page is built around
 * (`DATA.md#the-session-clock`): date, start, end and elapsed in mono, elapsed
 * the largest. Start and elapsed count from the first group run, never from
 * when Step 1 created the record — that time is named separately, small, for
 * whoever needs to know how long set-up took. A session recovered from files
 * has no recorded end: its clock closes at the last file's stream end, which
 * is derived, so End and Elapsed carry a `~` (`DATA.md#the-session-clock`).
 *
 * The session's folder opens from here — the page the operator is reading is
 * the one whose files they want to look at.
 *
 * Under the readouts, the session as a strip: each group run a segment, each
 * note a tick at its moment, so "the spout was cleaned an hour in" is visible
 * before it is read.
 */
export function SessionClockHeader({
  session,
  notes,
  animalCount,
  onNote,
}: {
  session: SessionListItem;
  notes: SessionNote[];
  animalCount: number;
  onNote: (noteId: string) => void;
}) {
  const open = session.clockEndedAt === null;
  const live = session.status === "running";
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  const elapsed = elapsedSeconds(session.clockStartedAt, session.clockEndedAt, now);
  const status = STATUS[session.status];
  const recovered = session.id.startsWith("adopted:");
  const ran = session.groupRuns.length > 0;
  const derived = recovered && !open;
  const [, , day] = session.date.split("-");

  return (
    <section className="hud overflow-hidden rounded-lg">
      {/* The glass stays; its contents change channel (`ReadoutFade`). */}
      <ReadoutFade key={session.id}>
        <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
          <div className="min-w-0">
            <h2 className="truncate font-display text-[24px] leading-tight text-starlight" data-selectable>
              {session.prefixName}_{session.sessionNumber}
            </h2>
            <p className="mt-0.5 text-[12px] text-static">{longDate(session.date)}</p>
          </div>
          <div className="flex items-center gap-2">
            {session.folderPath && (
              <FolderButton path={session.folderPath} label="Session folder" size="sm" />
            )}
            <span
              className={`flex items-center gap-1.5 rounded-sm border border-halo px-2 py-1 font-mono text-[10px] tracking-[0.12em] uppercase ${status.tone}`}
            >
              {live && <span className="size-1.5 rounded-full bg-status-ok" aria-hidden />}
              {recovered ? "Recovered from files" : status.label}
            </span>
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-[1fr_1fr_1fr_1.35fr] border-y border-halo">
          <Readout label="Date" value={`${day} ${monthOf(session.date)}`} sub={session.date.slice(0, 4)} />
          <Readout
            label="Start"
            value={wallClock(session.clockStartedAt)}
            sub={ran ? "first group" : recovered ? "first file" : "record created"}
          />
          <Readout
            label="End"
            value={open ? (live ? "Live" : "—") : wallClock(session.clockEndedAt)}
            sub={
              open
                ? live
                  ? "still running"
                  : recovered
                    ? "not recorded"
                    : "not ended"
                : derived
                  ? "last stream ended"
                  : ran
                    ? "last group"
                    : "record closed"
            }
            approx={derived}
            tone={live ? "text-status-ok" : undefined}
          />
          <Readout
            label="Elapsed"
            value={elapsed === null || (open && !live) ? "—" : formatDuration(elapsed)}
            sub={live ? "and counting" : `${animalCount} animal${animalCount === 1 ? "" : "s"}`}
            approx={derived}
            large
          />
        </dl>

        <FlightStrip session={session} notes={notes} now={now} onNote={onNote} />

        {session.startedAt !== session.clockStartedAt && (
          <p className="px-5 pb-3 font-mono text-[10px] text-static/80">
            Set-up began {wallClock(session.startedAt)} ·{" "}
            {session.groupRuns.length} group run{session.groupRuns.length === 1 ? "" : "s"}
          </p>
        )}
      </ReadoutFade>
    </section>
  );
}

/** Why a derived reading is marked — on hover, where the `~` is. */
const DERIVED_TITLE =
  "No end was recorded for this session — this is the last file's start plus its stream's own span";

function Readout({
  label,
  value,
  sub,
  large = false,
  approx = false,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  large?: boolean;
  /** Derived rather than recorded: marked `~`, as the session table marks a
      recovered run's end. */
  approx?: boolean;
  tone?: string | undefined;
}) {
  return (
    <div className="border-l border-halo px-5 py-3 first:border-l-0">
      <dt className="font-mono text-[10px] tracking-[0.14em] text-static uppercase">{label}</dt>
      <dd
        className={`mt-1 font-mono tabular-nums leading-none ${large ? "text-[30px]" : "text-[20px]"} ${
          tone ?? (large ? "text-pulsar" : "text-starlight")
        }`}
        title={approx ? DERIVED_TITLE : undefined}
        data-selectable
      >
        {approx && <span className="text-static">~</span>}
        {value}
      </dd>
      <dd className="mt-1.5 font-mono text-[10px] text-static/80">{sub}</dd>
    </div>
  );
}

function monthOf(isoDate: string): string {
  const [y, m] = isoDate.split("-").map(Number);
  if (!y || !m) return "";
  return new Date(Date.UTC(y, m - 1, 1))
    .toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" })
    .toUpperCase();
}

/**
 * The session from first group start to last group end: group runs as
 * segments, notes with an offset as ticks. A note outside the running window
 * has no place on it, by definition — it is listed below, not drawn.
 */
function FlightStrip({
  session,
  notes,
  now,
  onNote,
}: {
  session: SessionListItem;
  notes: SessionNote[];
  now: Date;
  onNote: (noteId: string) => void;
}) {
  const start = Date.parse(session.clockStartedAt);
  const end = session.clockEndedAt ? Date.parse(session.clockEndedAt) : now.getTime();
  const span = end - start;
  const placed = notes.filter((n) => n.offsetMs !== null);
  if (Number.isNaN(start) || !(span > 0) || session.groupRuns.length === 0) return null;
  const at = (ms: number) => `${Math.min(100, Math.max(0, ((ms - start) / span) * 100))}%`;

  return (
    <div className="px-5 py-3">
      <div className="relative h-5" role="group" aria-label="Session timeline">
        <div className="absolute inset-x-0 top-1/2 h-px bg-halo" aria-hidden />
        {session.groupRuns.map((run) => {
          const from = Date.parse(run.startedAt);
          const to = run.endedAt ? Date.parse(run.endedAt) : now.getTime();
          if (Number.isNaN(from) || Number.isNaN(to)) return null;
          return (
            <div
              key={`${run.groupId}-${run.order}`}
              className="absolute top-1/2 h-2 -translate-y-1/2 rounded-[2px] bg-halo"
              style={{ left: at(from), width: `calc(${at(to)} - ${at(from)})` }}
              title={`Group run ${run.order + 1}: ${wallClock(run.startedAt)} – ${wallClock(run.endedAt)}`}
              aria-hidden
            />
          );
        })}
        {placed.map((note) => {
          const tag = tagOf(note.tag);
          return (
            <button
              key={note.id}
              type="button"
              onClick={() => onNote(note.id)}
              className="group absolute top-0 flex h-5 w-3 -translate-x-1/2 justify-center"
              style={{ left: `${Math.min(100, Math.max(0, ((note.offsetMs ?? 0) / span) * 100))}%` }}
              title={`${formatOffset(note.offsetMs)} · ${tag.label} · ${note.body}`}
              aria-label={`${tag.label} note at ${formatOffset(note.offsetMs)}`}
            >
              <span className="h-full w-[2px] bg-pulsar/70 transition-colors group-hover:bg-pulsar" />
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] text-static/80" aria-hidden>
        <span>{wallClock(session.clockStartedAt)}</span>
        <span>{session.clockEndedAt ? wallClock(session.clockEndedAt) : "now"}</span>
      </div>
    </div>
  );
}
