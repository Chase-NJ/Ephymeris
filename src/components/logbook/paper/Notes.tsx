import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";

import { errorMessage } from "@/lib/analytics/commands";
import { atOnDay, formatOffset, shortTime, timeField } from "@/lib/logbook/clock";
import type { NoteDraft } from "@/lib/logbook/commands";
import type { NoteScope, NoteTag, SessionNote } from "@/lib/logbook/types";

import { TAGS, byMoment, scopeLabel, tagOf, type RosterAnimal } from "../tags";
import { TAG_INK } from "./parts";

/** A note the page has been asked to start: the weights table's "note" link. */
export interface ComposeRequest {
  tag: NoteTag;
  scope: NoteScope;
  /** Changes with every request, so asking twice for the same thing still lands. */
  nonce: number;
}

/**
 * A session's notes in the order they happened, as entries down the page
 * (`DATA.md#notes`). The margin carries when: the session clock's T+ over the
 * room's time, so an entry reads against the run and the wall at once. An
 * entry written after the session has only the wall clock: it has no honest
 * offset.
 *
 * The next entry is the blank line under the last one. Typing and Enter is a
 * whole note (an observation about the session, now); what kind it is, what
 * it is about, when, and whether it carries forward appear under the line
 * only once it is being written.
 */
export function Notes({
  notes,
  names,
  sessionDate,
  roster,
  boxes,
  readOnly,
  request,
  onAdd,
  onEdit,
  onDelete,
  onResolve,
}: {
  notes: readonly SessionNote[];
  names: Map<string, string>;
  sessionDate: string;
  roster: RosterAnimal[];
  boxes: number[];
  readOnly: boolean;
  request: ComposeRequest | null;
  onAdd: (draft: NoteDraft) => Promise<void>;
  onEdit: (note: SessionNote, draft: NoteDraft) => Promise<void>;
  onDelete: (note: SessionNote) => Promise<void>;
  onResolve: (note: SessionNote, resolved: boolean) => Promise<void>;
}) {
  const ordered = useMemo(() => [...notes].sort(byMoment), [notes]);

  return (
    <div>
      {ordered.length > 0 && (
        <ol>
          {ordered.map((note) => (
            <li key={note.id} id={noteAnchor(note.id)} className="scroll-mt-4">
              <Entry
                note={note}
                names={names}
                sessionDate={sessionDate}
                roster={roster}
                boxes={boxes}
                readOnly={readOnly}
                onEdit={onEdit}
                onDelete={onDelete}
                onResolve={onResolve}
              />
            </li>
          ))}
        </ol>
      )}
      {readOnly ? (
        <p className="text-[14px] text-ink-soft italic">
          {ordered.length === 0 ? "No notes. " : ""}
          This session was recovered from files and has no record to write notes against.
        </p>
      ) : (
        <div className={`${MARGIN} ${ordered.length > 0 ? "mt-2" : ""}`}>
          <span aria-hidden className="pt-[3px] text-right text-[12.5px] text-ink-faint italic">
            now
          </span>
          <Composer
            sessionDate={sessionDate}
            roster={roster}
            boxes={boxes}
            request={request}
            onSubmit={onAdd}
          />
        </div>
      )}
    </div>
  );
}

/** The margin and the measure: every entry and the blank line share it. */
const MARGIN = "grid grid-cols-[62px_minmax(0,1fr)] gap-x-3.5";

export function noteAnchor(noteId: string): string {
  return `log-note-${noteId}`;
}

function Entry({
  note,
  names,
  sessionDate,
  roster,
  boxes,
  readOnly,
  onEdit,
  onDelete,
  onResolve,
}: {
  note: SessionNote;
  names: Map<string, string>;
  sessionDate: string;
  roster: RosterAnimal[];
  boxes: number[];
  readOnly: boolean;
  onEdit: (note: SessionNote, draft: NoteDraft) => Promise<void>;
  onDelete: (note: SessionNote) => Promise<void>;
  onResolve: (note: SessionNote, resolved: boolean) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tag = tagOf(note.tag);
  const Icon = tag.icon;
  const offset = formatOffset(note.offsetMs);

  async function run(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className={`group ${MARGIN} py-[7px]`}>
      <div className="pt-[2px] text-right leading-tight">
        {offset && <div className="text-[13px] text-ink-blue">{offset}</div>}
        <div className={offset ? "text-[12px] text-ink-faint" : "text-[13px] text-ink-soft"}>
          {shortTime(note.at)}
        </div>
      </div>

      {editing ? (
        <Composer
          sessionDate={sessionDate}
          roster={roster}
          boxes={boxes}
          initial={note}
          request={null}
          onCancel={() => setEditing(false)}
          onSubmit={async (draft) => {
            await onEdit(note, draft);
            setEditing(false);
          }}
        />
      ) : (
        <div className="relative min-w-0">
          <p className="flex flex-wrap items-baseline gap-x-2 text-[13px] leading-tight">
            <span
              className="smallcaps inline-flex items-baseline gap-1 text-[11px] font-bold"
              style={{ color: TAG_INK[note.tag] }}
            >
              <Icon size={11} strokeWidth={2} className="translate-y-[1px]" aria-hidden />
              {tag.label}
            </span>
            {note.scope.kind !== "session" && (
              <span className="text-ink-soft italic">{scopeLabel(note.scope, names)}</span>
            )}
            {note.carryForward && (
              <span
                className={`smallcaps text-[11px] ${note.resolvedAt ? "text-ink-soft" : "text-ink-red"}`}
                title={
                  note.resolvedAt
                    ? "This flag has been dealt with"
                    : "Stays on every page, in Step 1 and on the running session until resolved"
                }
              >
                {note.resolvedAt ? `resolved ${shortTime(note.resolvedAt)}` : "⚑ carry forward"}
              </span>
            )}
            {note.editedAt && <span className="text-ink-faint italic">edited</span>}
            {!readOnly && (
              <span className="absolute top-0 right-0 flex items-baseline gap-2.5 bg-paper pl-2.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                {note.carryForward && (
                  <button
                    type="button"
                    className="ink-link"
                    onClick={() => void run(() => onResolve(note, !note.resolvedAt))}
                  >
                    {note.resolvedAt ? "reopen" : "resolve"}
                  </button>
                )}
                <button type="button" className="ink-link" onClick={() => setEditing(true)}>
                  edit
                </button>
                <button type="button" className="ink-link" onClick={() => setConfirming(true)}>
                  delete
                </button>
              </span>
            )}
          </p>
          <p className="mt-0.5 text-[15px] leading-[1.42] whitespace-pre-wrap" data-selectable>
            {note.body}
          </p>
          {confirming && (
            <p role="alert" className="mt-1 flex items-baseline gap-2.5 text-[13px] text-ink-soft">
              Strike this note out?
              <button
                type="button"
                className="ink-link"
                style={{ color: "var(--color-ink-red)" }}
                onClick={() =>
                  void run(async () => {
                    await onDelete(note);
                    setConfirming(false);
                  })
                }
              >
                delete
              </button>
              <button type="button" className="ink-link" onClick={() => setConfirming(false)}>
                keep
              </button>
            </p>
          )}
          {error && (
            <p role="alert" className="mt-1 text-[13px] text-ink-red">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Writing a note, new or edited. Enter saves and Shift+Enter breaks the line:
 * a note is usually one line taken with a hand full, and the common case
 * should cost one key. The time is typed only to back-date an entry, and is
 * read on the session's own calendar day in this machine's zone.
 */
function Composer({
  sessionDate,
  roster,
  boxes,
  initial,
  request,
  onSubmit,
  onCancel,
}: {
  sessionDate: string;
  roster: RosterAnimal[];
  boxes: number[];
  initial?: SessionNote;
  request: ComposeRequest | null;
  onSubmit: (draft: NoteDraft) => Promise<void>;
  onCancel?: () => void;
}) {
  const [tag, setTag] = useState<NoteTag>(initial?.tag ?? "observation");
  const [scope, setScope] = useState<string>(scopeKey(initial?.scope));
  const [body, setBody] = useState(initial?.body ?? "");
  const [carry, setCarry] = useState(initial?.carryForward ?? false);
  // An edit starts from the note's own second; it is sent back only if the
  // field was touched, so saving a reworded note never rounds its time.
  const initialTime = initial ? timeField(initial.at) : "";
  const [time, setTime] = useState(initialTime);
  const [focused, setFocused] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const ids = useId();

  // A request from elsewhere on the spread: take its kind and subject, and
  // put the pen on the line.
  const answered = useRef<number | null>(request?.nonce ?? null);
  useEffect(() => {
    if (!request || answered.current === request.nonce) return;
    answered.current = request.nonce;
    setTag(request.tag);
    setScope(scopeKey(request.scope));
    area.current?.focus();
    area.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [request]);

  useLayoutEffect(() => {
    const element = area.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [body]);

  useEffect(() => {
    if (initial) area.current?.focus();
  }, [initial]);

  const blank = body.trim().length === 0;
  const open = Boolean(initial) || focused || !blank;
  // The line's options open under it: bring them onto the page with it.
  useEffect(() => {
    if (open && focused) frame.current?.scrollIntoView({ block: "nearest" });
  }, [open, focused]);

  async function submit() {
    if (blank || saving) return;
    let at: string | undefined;
    if (time.trim() && time !== initialTime) {
      const parsed = atOnDay(sessionDate, time.trim());
      if (!parsed) {
        setError("That time isn't readable. Use HH:MM.");
        return;
      }
      at = parsed;
    }
    setSaving(true);
    setError(null);
    try {
      await onSubmit({
        tag,
        body: body.trim(),
        scope: scopeOf(scope),
        carryForward: carry,
        ...(at !== undefined ? { at } : {}),
      });
      if (!initial) {
        setBody("");
        setTime("");
        setCarry(false);
        setTag("observation");
        setScope("session");
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      ref={frame}
      className="min-w-0 scroll-mb-3"
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
    >
      <label htmlFor={`${ids}-body`} className="sr-only">
        Note
      </label>
      <textarea
        id={`${ids}-body`}
        ref={area}
        data-note-composer={initial ? undefined : ""}
        value={body}
        rows={1}
        placeholder="Write a note…"
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            void submit();
          }
          if (e.key === "Escape") {
            e.preventDefault();
            if (onCancel) onCancel();
            else e.currentTarget.blur();
          }
        }}
        className="ink-field block w-full resize-none overflow-hidden text-[15px] leading-[1.42]"
      />

      {open && (
        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3.5 gap-y-1 text-[13px]">
          <div role="radiogroup" aria-label="Kind of note" className="flex flex-wrap gap-x-2.5">
            {TAGS.map((option) => {
              const on = option.value === tag;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  title={option.label}
                  onClick={() => setTag(option.value)}
                  className={`smallcaps rounded-[2px] px-0.5 text-[11px] ${on ? "font-bold" : "text-ink-faint hover:text-ink-soft"}`}
                  style={
                    on
                      ? {
                          color: TAG_INK[option.value],
                          boxShadow: `inset 0 -2px 0 ${TAG_INK[option.value]}`,
                        }
                      : undefined
                  }
                >
                  {option.short}
                </button>
              );
            })}
          </div>
          <label className="flex items-baseline gap-1.5 text-ink-soft">
            about
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              className="ink-field max-w-[130px] py-0 text-ink"
            >
              <option value="session">the session</option>
              {boxes.map((box) => (
                <option key={box} value={`box:${box}`}>
                  Box {box}
                </option>
              ))}
              {roster.map((animal) => (
                <option key={animal.id} value={`animal:${animal.id}`}>
                  {animal.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-baseline gap-1.5 text-ink-soft">
            at
            <input
              type="time"
              step={60}
              value={time.slice(0, 5)}
              onChange={(e) => setTime(e.target.value)}
              aria-label="Time the note is about; empty means now"
              className="ink-field w-[78px] py-0 text-ink [color-scheme:light]"
            />
          </label>
          <label
            className="flex items-baseline gap-1.5 text-ink-soft"
            title="Keep this in front of whoever runs the next session, until someone resolves it"
          >
            <input
              type="checkbox"
              checked={carry}
              onChange={(e) => setCarry(e.target.checked)}
              className="translate-y-[1px] accent-[var(--color-ink-red)]"
            />
            carry forward
          </label>
          <span className="ml-auto flex items-baseline gap-3">
            {onCancel && (
              <button type="button" className="ink-link" onClick={onCancel}>
                cancel
              </button>
            )}
            <button
              type="button"
              className="ink-link font-bold"
              disabled={blank || saving}
              onClick={() => void submit()}
            >
              {saving ? "saving…" : initial ? "save ↵" : "add ↵"}
            </button>
          </span>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-1 text-[13px] text-ink-red">
          {error}
        </p>
      )}
    </div>
  );
}

function scopeKey(scope: NoteScope | undefined): string {
  if (!scope || scope.kind === "session") return "session";
  if (scope.kind === "box") return `box:${scope.box}`;
  return `animal:${scope.animalId}`;
}

function scopeOf(key: string): NoteScope {
  if (key.startsWith("box:")) return { kind: "box", animalId: null, box: Number(key.slice(4)) };
  if (key.startsWith("animal:")) return { kind: "animal", animalId: key.slice(7), box: null };
  return { kind: "session", animalId: null, box: null };
}
