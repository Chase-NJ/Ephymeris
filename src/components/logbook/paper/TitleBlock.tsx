import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import { errorMessage } from "@/lib/analytics/commands";
import type { SessionListItem } from "@/lib/analytics/types";
import {
  elapsedSeconds,
  formatDuration,
  longDate,
  proseDuration,
  shortTime,
} from "@/lib/logbook/clock";
import type { SessionLog } from "@/lib/logbook/types";
import { shell } from "@/lib/shell";

/**
 * The head of a session's left page: the day as the title, then who ran it,
 * when, and what they made of it, set as a paper's title, byline and abstract
 * (`DATA.md#the-session-clock`, `DATA.md#notes`).
 *
 * The times are the session clock's: start and elapsed count from the first
 * round, and a session recovered from files ends where its last stream did,
 * which is derived and so carries a `~`.
 *
 * Operator and summary save when the field is left, and only if it changed:
 * there is no Save to forget at the end of a long day.
 */
export function TitleBlock({
  session,
  log,
  animalCount,
  readOnly,
  onSave,
}: {
  session: SessionListItem;
  log: SessionLog | null;
  animalCount: number;
  readOnly: boolean;
  onSave: (fields: { operator?: string | null; summary?: string | null }) => Promise<void>;
}) {
  const live = session.status === "running";
  const open = session.clockEndedAt === null;
  const recovered = session.id.startsWith("adopted:");
  const approx = recovered && !open ? "~" : "";
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);
  const elapsed = elapsedSeconds(session.clockStartedAt, session.clockEndedAt, now);

  return (
    <header className="pt-1 pb-1">
      <p className="smallcaps flex flex-wrap items-baseline gap-x-2 text-[12px] text-ink-blue">
        <span data-selectable>
          {session.prefixName} · session {session.sessionNumber}
        </span>
        <StatusMark session={session} recovered={recovered} />
      </p>
      <h2 className="mt-0.5 text-[31px] leading-[1.12] font-normal" data-selectable>
        {longDate(session.date)}
      </h2>

      <p className="mt-2 text-[14.5px] text-ink-soft italic">
        {shortTime(session.clockStartedAt)}
        {open ? (
          live ? (
            <>
              {" "}
              onward, running{" "}
              <span className="text-ink-teal not-italic">
                {elapsed === null ? "" : formatDuration(elapsed)}
              </span>
            </>
          ) : (
            ", no end on record"
          )
        ) : (
          <>
            –{approx}
            {shortTime(session.clockEndedAt)}
            {elapsed !== null && `, ${approx}${proseDuration(elapsed)}`}
          </>
        )}
        {animalCount > 0 && ` · ${animalCount} animal${animalCount === 1 ? "" : "s"}`}
        {session.startedAt !== session.clockStartedAt &&
          ` · set-up began ${shortTime(session.startedAt)}`}
      </p>
      {session.rounds.length > 1 && (
        <p className="text-[13px] text-ink-soft">
          {session.rounds.map((round, index) => (
            <span key={round.order}>
              {index > 0 && " · "}
              {round.label ?? `Round ${round.order + 1}`} {shortTime(round.startedAt)}–
              {round.endedAt ? shortTime(round.endedAt) : "…"}
            </span>
          ))}
        </p>
      )}

      <Byline
        key={session.id}
        log={log}
        readOnly={readOnly}
        folder={session.folderPath || null}
        onSave={onSave}
      />
    </header>
  );
}

function StatusMark({ session, recovered }: { session: SessionListItem; recovered: boolean }) {
  if (recovered) return <span className="text-ink-ochre">recovered from files</span>;
  if (session.status === "running") {
    return (
      <span className="inline-flex items-baseline gap-1.5 text-ink-teal">
        <span aria-hidden className="inline-block size-[7px] rounded-full bg-ink-teal" />
        running
      </span>
    );
  }
  if (session.status === "aborted") return <span className="text-ink-red">abandoned</span>;
  if (session.status === "configuring") return <span className="text-ink-soft">setting up</span>;
  return null;
}

function Byline({
  log,
  readOnly,
  folder,
  onSave,
}: {
  log: SessionLog | null;
  readOnly: boolean;
  folder: string | null;
  onSave: (fields: { operator?: string | null; summary?: string | null }) => Promise<void>;
}) {
  const operatorId = useId();
  const summaryId = useId();
  const [operator, setOperator] = useState(log?.operator ?? "");
  const [summary, setSummary] = useState(log?.summary ?? "");
  const [error, setError] = useState<string | null>(null);
  const [folderFailed, setFolderFailed] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);

  // Follow the sidecar: another window's edit, or a tidy merge, arrives here.
  useEffect(() => setOperator(log?.operator ?? ""), [log?.operator]);
  useEffect(() => setSummary(log?.summary ?? ""), [log?.summary]);

  // The abstract is as tall as what is written in it, like text on a page.
  useLayoutEffect(() => {
    const element = area.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [summary]);

  async function commit(field: "operator" | "summary", value: string) {
    const current = (field === "operator" ? log?.operator : log?.summary) ?? "";
    if (value.trim() === current.trim()) return;
    try {
      await onSave({ [field]: value });
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="mt-3">
      <p className="flex flex-wrap items-baseline gap-x-2 text-[15px]">
        <label htmlFor={operatorId} className="text-ink-soft">
          Run by
        </label>
        <input
          id={operatorId}
          type="text"
          value={operator}
          disabled={readOnly}
          placeholder={readOnly ? "not recorded" : "who ran it"}
          onChange={(e) => setOperator(e.target.value)}
          onBlur={() => void commit("operator", operator)}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
          }}
          className="ink-field w-[190px]"
        />
        {folder && (
          <button
            type="button"
            className="ink-link ml-auto text-[13px]"
            title={folder}
            onClick={() => {
              shell.openPath(folder).then(
                () => setFolderFailed(false),
                () => setFolderFailed(true),
              );
            }}
          >
            {folderFailed ? "folder couldn't be opened" : "session folder"}
          </button>
        )}
      </p>

      <div className="mx-5 mt-3.5">
        <label htmlFor={summaryId} className="smallcaps block text-center text-[11.5px] font-bold">
          Summary
        </label>
        <textarea
          id={summaryId}
          ref={area}
          value={summary}
          rows={1}
          disabled={readOnly}
          placeholder={readOnly ? "No summary on record." : "How did it go, overall?"}
          onChange={(e) => setSummary(e.target.value)}
          onBlur={() => void commit("summary", summary)}
          className="ink-field mt-0.5 block w-full resize-none overflow-hidden border-b-0 text-[14.5px] leading-[1.42]"
        />
      </div>
      {error && (
        <p role="alert" className="mt-1 text-[13px] text-ink-red">
          {error}
        </p>
      )}
    </div>
  );
}
