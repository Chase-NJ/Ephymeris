/**
 * Typed wrappers over the session-log commands (`PROTOCOL.md#session-log`).
 * Same pattern as `analytics/commands.ts`.
 */

import type { SidecarClient } from "../ws/client";
import { CMD } from "../ws/protocol";
import type { LogbookCohort, NoteScope, NoteTag, SessionLog, SessionNote } from "./types";

export async function getLogbook(client: SidecarClient, cohortId: string): Promise<LogbookCohort> {
  return (await client.call(CMD.LOGBOOK_COHORT, { cohortId })) as LogbookCohort;
}

export interface NoteDraft {
  tag: NoteTag;
  body: string;
  scope?: NoteScope;
  carryForward?: boolean;
  /** ISO with an offset; absent means now. */
  at?: string;
}

export async function addNote(
  client: SidecarClient,
  sessionId: string,
  draft: NoteDraft,
): Promise<SessionNote> {
  const result = (await client.call(CMD.LOGBOOK_ADD_NOTE, { sessionId, ...draft })) as {
    note: SessionNote;
  };
  return result.note;
}

export async function editNote(
  client: SidecarClient,
  noteId: string,
  changes: Partial<NoteDraft>,
): Promise<SessionNote> {
  const result = (await client.call(CMD.LOGBOOK_EDIT_NOTE, { noteId, ...changes })) as {
    note: SessionNote;
  };
  return result.note;
}

export async function deleteNote(client: SidecarClient, noteId: string): Promise<void> {
  await client.call(CMD.LOGBOOK_DELETE_NOTE, { noteId });
}

export async function resolveFlag(
  client: SidecarClient,
  noteId: string,
  resolved: boolean,
  sessionId: string | null = null,
): Promise<SessionNote> {
  const result = (await client.call(CMD.LOGBOOK_RESOLVE_FLAG, {
    noteId,
    resolved,
    sessionId,
  })) as { note: SessionNote };
  return result.note;
}

export async function setSessionLog(
  client: SidecarClient,
  sessionId: string,
  fields: { operator?: string | null; summary?: string | null },
): Promise<SessionLog> {
  const result = (await client.call(CMD.LOGBOOK_SET_SESSION_LOG, { sessionId, ...fields })) as {
    log: SessionLog;
  };
  return result.log;
}

export async function openFlags(client: SidecarClient, cohortId: string): Promise<SessionNote[]> {
  const result = (await client.call(CMD.LOGBOOK_OPEN_FLAGS, { cohortId })) as {
    notes: SessionNote[];
  };
  return result.notes;
}
