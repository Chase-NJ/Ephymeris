import { AnimatePresence, motion } from "framer-motion";
import { Flag, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/common/controls";
import { errorMessage } from "@/lib/analytics/commands";
import { formatOffset, wallClock } from "@/lib/logbook/clock";
import type { NoteDraft } from "@/lib/logbook/commands";
import type { SessionNote } from "@/lib/logbook/types";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

import { NoteComposer } from "./NoteComposer";
import { byMoment, scopeLabel, tagOf, type RosterAnimal } from "./tags";

/**
 * A session's notes in the order they happened. The gutter carries the T+
 * offset — the session clock's reading — over the wall-clock time, so a note
 * reads against the run and against the room at once. A note written after
 * the session has only the wall clock: it has no honest offset.
 */
export function NotesTimeline({
  notes,
  names,
  sessionDate,
  roster,
  boxes,
  readOnly,
  onEdit,
  onDelete,
  onResolve,
}: {
  notes: SessionNote[];
  names: Map<string, string>;
  sessionDate: string;
  roster: RosterAnimal[];
  boxes: number[];
  readOnly: boolean;
  onEdit: (note: SessionNote, changes: NoteDraft) => Promise<void>;
  onDelete: (note: SessionNote) => Promise<void>;
  onResolve: (note: SessionNote, resolved: boolean) => Promise<void>;
}) {
  const ordered = [...notes].sort(byMoment);
  const reduce = useReduceMotion();

  if (ordered.length === 0) {
    return (
      <p className="px-4 py-5 text-[12px] text-static">
        No notes yet.{readOnly ? "" : " Anything worth remembering about this session goes here."}
      </p>
    );
  }

  return (
    <ol className="divide-y divide-halo/70">
      <AnimatePresence initial={false}>
        {ordered.map((note) => (
          <motion.li
            key={note.id}
            id={noteAnchor(note.id)}
            layout={!reduce}
            initial={reduce ? false : { opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, height: 0 }}
            transition={springSnappy}
            className="scroll-mt-4"
          >
            <NoteRow
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
          </motion.li>
        ))}
      </AnimatePresence>
    </ol>
  );
}

export function noteAnchor(noteId: string): string {
  return `log-note-${noteId}`;
}

function NoteRow({
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
  onEdit: (note: SessionNote, changes: NoteDraft) => Promise<void>;
  onDelete: (note: SessionNote) => Promise<void>;
  onResolve: (note: SessionNote, resolved: boolean) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tag = tagOf(note.tag);
  const Icon = tag.icon;

  async function run(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="group grid grid-cols-[76px_1fr] gap-4 px-4 py-3">
      <div className="pt-0.5 text-right font-mono tabular-nums">
        <div className="text-[12px] text-pulsar">{formatOffset(note.offsetMs) || "—"}</div>
        <div className="mt-0.5 text-[10px] text-static">{wallClock(note.at)}</div>
      </div>

      {editing ? (
        <NoteComposer
          sessionDate={sessionDate}
          roster={roster}
          boxes={boxes}
          initial={note}
          submitLabel="Save"
          onCancel={() => setEditing(false)}
          onSubmit={async (draft) => {
            await onEdit(note, draft);
            setEditing(false);
          }}
        />
      ) : (
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-static">
            <span className="flex items-center gap-1.5 text-starlight">
              <Icon size={12} strokeWidth={1.75} className="text-pulsar" aria-hidden />
              {tag.label}
            </span>
            <span aria-hidden>·</span>
            <span>{scopeLabel(note.scope, names)}</span>
            {note.carryForward && (
              <span
                className={`flex items-center gap-1 rounded-sm border px-1.5 py-px font-mono text-[10px] ${
                  note.resolvedAt
                    ? "border-halo text-static"
                    : "border-status-warning/50 text-status-warning"
                }`}
              >
                <Flag size={10} strokeWidth={1.75} aria-hidden />
                {note.resolvedAt ? `resolved ${wallClock(note.resolvedAt)}` : "carry forward"}
              </span>
            )}
            {note.editedAt && <span className="text-static/70">edited</span>}

            {!readOnly && (
              <span className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                {note.carryForward && (
                  <Button variant="ghost" onClick={() => void run(() => onResolve(note, !note.resolvedAt))}>
                    {note.resolvedAt ? "Reopen" : "Resolve"}
                  </Button>
                )}
                <Button variant="ghost" shape="icon" label="Edit note" onClick={() => setEditing(true)}>
                  <Pencil size={13} strokeWidth={1.75} />
                </Button>
                <Button variant="ghost" shape="icon" label="Delete note" onClick={() => setConfirming(true)}>
                  <Trash2 size={13} strokeWidth={1.75} />
                </Button>
              </span>
            )}
          </div>
          <p className="mt-1 text-[13px] leading-relaxed whitespace-pre-wrap text-starlight" data-selectable>
            {note.body}
          </p>
          {confirming && (
            <div className="mt-2 flex items-center gap-2 text-[11px] text-static" role="alert">
              Delete this note?
              <Button
                variant="secondary"
                onClick={() =>
                  void run(async () => {
                    await onDelete(note);
                    setConfirming(false);
                  })
                }
              >
                Delete
              </Button>
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                Keep
              </Button>
            </div>
          )}
          {error && (
            <p role="alert" className="mt-1 text-[11px] text-status-error">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
