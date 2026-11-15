import { Clock } from "lucide-react";
import { useId, useMemo, useState, type Ref } from "react";

import { Button, Toggle } from "@/components/common/controls";
import { Dropdown, type DropdownOption } from "@/components/common/Dropdown";
import { errorMessage } from "@/lib/analytics/commands";
import { atOnDay, timeField } from "@/lib/logbook/clock";
import type { NoteDraft } from "@/lib/logbook/commands";
import type { NoteScope, NoteTag, SessionNote } from "@/lib/logbook/types";

import { TAGS, type RosterAnimal } from "./tags";

/**
 * Writing a note: what kind, about what, when, and the words
 * (`DATA.md#notes`). One form for a new note and an edit.
 *
 * **When** defaults to now and stays out of the way; a time is typed only to
 * back-date an entry ("the spout was dripping from about 09:40"). It is read
 * on the session's own calendar day, in this machine's zone.
 *
 * Cmd/Ctrl+Enter saves, so a note can be taken without leaving the keyboard
 * mid-session.
 */
export function NoteComposer({
  sessionDate,
  roster,
  boxes,
  initial,
  initialScope,
  submitLabel = "Add note",
  compact = false,
  autoFocus = false,
  textareaRef,
  onSubmit,
  onCancel,
}: {
  sessionDate: string;
  roster: RosterAnimal[];
  /** Box numbers to offer — the ones this session used, else all six. */
  boxes: number[];
  initial?: SessionNote | undefined;
  /** Where a new note starts — a box's panel presets its own box. */
  initialScope?: NoteScope | undefined;
  submitLabel?: string;
  /** Drops the time row — the quick note is always "now". */
  compact?: boolean;
  autoFocus?: boolean;
  textareaRef?: Ref<HTMLTextAreaElement> | undefined;
  onSubmit: (draft: NoteDraft) => Promise<void>;
  onCancel?: (() => void) | undefined;
}) {
  const [tag, setTag] = useState<NoteTag>(initial?.tag ?? "observation");
  const [scope, setScope] = useState<string>(scopeKey(initial?.scope ?? initialScope));
  const [body, setBody] = useState(initial?.body ?? "");
  const [carry, setCarry] = useState(initial?.carryForward ?? false);
  const [time, setTime] = useState(initial ? timeField(initial.at) : "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bodyId = useId();

  const scopeOptions = useMemo<DropdownOption[]>(
    () => [
      { value: "session", label: "Whole session" },
      ...boxes.map((box) => ({ value: `box:${box}`, label: `Box ${box}` })),
      ...roster.map((animal) => ({
        value: `animal:${animal.id}`,
        label: animal.name,
        detail: animal.box !== null ? `box ${animal.box}` : undefined,
      })),
    ],
    [boxes, roster],
  );

  const blank = body.trim().length === 0;

  async function submit() {
    if (blank || saving) return;
    let at: string | undefined;
    if (time.trim()) {
      const parsed = atOnDay(sessionDate, time.trim());
      if (!parsed) {
        setError("That time isn't readable — use HH:MM.");
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
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <div role="radiogroup" aria-label="Kind of note" className="flex flex-wrap overflow-hidden rounded-sm border border-halo">
          {TAGS.map((option) => {
            const Icon = option.icon;
            const on = option.value === tag;
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setTag(option.value)}
                title={option.label}
                className={`flex items-center gap-1.5 px-2.5 py-1 text-[11px] transition-colors ${
                  on ? "bg-halo/70 text-starlight" : "text-static hover:text-starlight"
                }`}
              >
                <Icon size={12} strokeWidth={1.75} className={on ? "text-pulsar" : ""} />
                {option.short}
              </button>
            );
          })}
        </div>
        <div className="w-[170px]">
          <Dropdown
            value={scope}
            options={scopeOptions}
            placeholder="About"
            label="What the note is about"
            onChange={setScope}
          />
        </div>
      </div>

      <label htmlFor={bodyId} className="sr-only">
        Note
      </label>
      <textarea
        id={bodyId}
        ref={textareaRef}
        // eslint-disable-next-line jsx-a11y/no-autofocus -- the quick note opens
        // for exactly one thing, typing.
        autoFocus={autoFocus}
        value={body}
        rows={3}
        placeholder="What happened? ⌘↵ to save"
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void submit();
          }
          if (e.key === "Escape" && onCancel) {
            e.preventDefault();
            onCancel();
          }
        }}
        className="min-h-[68px] resize-y rounded-sm border border-halo bg-nebula px-3 py-2 text-[13px] leading-relaxed text-starlight transition-colors placeholder:text-static/60 hover:border-static/40 focus:border-pulsar focus:outline-none"
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {!compact && (
          <label className="flex items-center gap-2 text-[11px] text-static">
            <Clock size={12} strokeWidth={1.75} aria-hidden />
            <span>At</span>
            <input
              type="time"
              step={1}
              value={time}
              onChange={(e) => setTime(e.target.value)}
              aria-label="Time the note is about; empty means now"
              className="rounded-sm border border-halo bg-nebula px-2 py-1 font-mono text-[11px] text-starlight [color-scheme:dark] focus:border-pulsar focus:outline-none"
            />
            {!time && <span className="text-static/70">now</span>}
          </label>
        )}
        <label className="flex items-center gap-2 text-[11px] text-static">
          <Toggle checked={carry} onChange={setCarry} label="Carry forward to the next session" />
          Carry forward to next session
        </label>
        <span className="ml-auto flex items-center gap-2">
          {onCancel && (
            <Button variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
          )}
          <Button variant="primary" onClick={() => void submit()} disabled={blank || saving}>
            {saving ? "Saving…" : submitLabel}
          </Button>
        </span>
      </div>
      {error && (
        <p role="alert" className="text-[11px] text-status-error">
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
