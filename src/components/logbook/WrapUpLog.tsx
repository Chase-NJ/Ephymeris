import { NotebookPen } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/common/controls";
import { addNote, setSessionLog } from "@/lib/logbook/commands";
import { useLogbook } from "@/lib/logbook/context";
import { useSidecar } from "@/lib/ws/context";

import { NoteComposer } from "./NoteComposer";
import { SessionLogForm } from "./SessionLogForm";
import type { RosterAnimal } from "./tags";

/**
 * The log's corner of the wrap-up (`USER-GUIDE.md#ending-the-session`): who ran
 * it, how it went, and one more note if there is one — while it is fresh.
 * Entirely optional; nothing here stands between the operator and End session.
 */
export function WrapUpLog({
  cohortId,
  sessionId,
  sessionDate,
  roster,
  boxes,
}: {
  cohortId: string;
  sessionId: string;
  sessionDate: string;
  roster: RosterAnimal[];
  boxes: number[];
}) {
  const { client } = useSidecar();
  const entry = useLogbook(cohortId);
  const [composing, setComposing] = useState(false);
  const notes = entry.notesBySession.get(sessionId)?.length ?? 0;

  return (
    <section className="mt-4 overflow-hidden rounded-md border border-halo" aria-label="For the log">
      <div className="flex items-center gap-2 border-b border-halo px-3 py-2">
        <NotebookPen size={13} strokeWidth={1.75} className="text-pulsar" aria-hidden />
        <span className="text-[12px] text-starlight">For the log</span>
        <span className="ml-auto font-mono text-[10px] text-static">
          {notes} note{notes === 1 ? "" : "s"} taken · optional
        </span>
      </div>
      <SessionLogForm
        log={entry.logs.get(sessionId) ?? null}
        readOnly={false}
        onSave={async (fields) => {
          await setSessionLog(client, sessionId, fields);
        }}
      />
      <div className="border-t border-halo px-4 py-3">
        {composing ? (
          <NoteComposer
            sessionDate={sessionDate}
            roster={roster}
            boxes={boxes}
            compact
            onCancel={() => setComposing(false)}
            onSubmit={async (draft) => {
              await addNote(client, sessionId, draft);
              setComposing(false);
            }}
          />
        ) : (
          <Button variant="ghost" onClick={() => setComposing(true)}>
            <NotebookPen size={13} strokeWidth={1.75} />
            Add a note
          </Button>
        )}
      </div>
    </section>
  );
}
