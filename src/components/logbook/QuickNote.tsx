import { Modal } from "@/components/common/Modal";
import { addNote } from "@/lib/logbook/commands";
import type { NoteScope } from "@/lib/logbook/types";
import { useSidecar } from "@/lib/ws/context";

import { NoteComposer } from "./NoteComposer";
import type { RosterAnimal } from "./tags";

/**
 * A note taken mid-session without leaving Mission Control
 * (`USER-GUIDE.md#writing-notes`). Always "now" — the moment is the point —
 * and closed on save, so the operator is back at the rig in one keystroke.
 * The note arrives in the log, and back here, through `logbook.updated`.
 */
export function QuickNote({
  open,
  onClose,
  sessionId,
  sessionName,
  sessionDate,
  roster,
  boxes,
  scope,
}: {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  sessionName: string;
  sessionDate: string;
  roster: RosterAnimal[];
  boxes: number[];
  scope?: NoteScope | undefined;
}) {
  const { client } = useSidecar();
  return (
    <Modal open={open} onClose={onClose} title={`Note · ${sessionName}`}>
      <div className="p-5">
        <NoteComposer
          // A fresh form per opening, so a preset box isn't overridden by the
          // last note's choice.
          key={open ? `${scope?.kind}:${scope?.box}:${scope?.animalId}` : "closed"}
          sessionDate={sessionDate}
          roster={roster}
          boxes={boxes}
          initialScope={scope}
          compact
          autoFocus
          onCancel={onClose}
          onSubmit={async (draft) => {
            await addNote(client, sessionId, draft);
            onClose();
          }}
        />
      </div>
    </Modal>
  );
}
