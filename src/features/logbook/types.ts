/**
 * Session-log wire shapes (`PROTOCOL.md#session-log`), generated from
 * `protocol/schema.py` and re-exported so callers keep one import site.
 */

export type {
  HealthEntry,
  LogbookCohort,
  LogbookUpdated,
  NoteScope,
  NoteTag,
  ParamChange,
  RunChange,
  RunSignal,
  SessionLog,
  SessionNote,
  SiteSignal,
  ValueChange,
} from "@/lib/ws/protocol";
