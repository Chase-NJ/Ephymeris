/**
 * The session clock, rendered (`DATA.md#the-session-clock`).
 *
 * The sidecar defines when a session ran (`clockStartedAt`, `clockEndedAt`);
 * these only format it. Pure, so the Log, Mission Control and the PDF read
 * one elapsed time.
 */

/** `mm:ss`, or `h:mm:ss` past the hour. Negative input reads as zero. */
export function formatDuration(totalSeconds: number): string {
  const whole = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const seconds = whole % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** A note's offset into its session — `T+12:04` — or empty when it has none. */
export function formatOffset(offsetMs: number | null): string {
  return offsetMs === null ? "" : `T+${formatDuration(offsetMs / 1000)}`;
}

/**
 * Whole seconds the session ran: start to end, or start to `now` while open.
 * Null when the start isn't a readable time.
 */
export function elapsedSeconds(
  startIso: string,
  endIso: string | null,
  now: Date,
): number | null {
  const start = Date.parse(startIso);
  if (Number.isNaN(start)) return null;
  const end = endIso === null ? now.getTime() : Date.parse(endIso);
  if (Number.isNaN(end)) return null;
  return Math.max(0, Math.floor((end - start) / 1000));
}

/** Local `HH:MM:SS` — the room's time, as every other clock in the app. */
export function wallClock(iso: string | null): string {
  if (!iso) return "—";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "—";
  return when.toLocaleTimeString("en-GB", { hour12: false });
}

/** `Tuesday 6 October 2026` from an ISO date, read as a calendar day (no zone). */
export function longDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/**
 * An ISO instant for `HH:MM[:SS]` on a session's calendar day, in this
 * machine's zone — how an operator back-dates a note to "09:30". Null for an
 * unreadable time.
 */
export function atOnDay(isoDate: string, time: string): string | null {
  const [y, m, d] = isoDate.split("-").map(Number);
  const parts = time.split(":").map(Number);
  if (!y || !m || !d || parts.length < 2 || parts.some((p) => Number.isNaN(p))) return null;
  const [hh = 0, mm = 0, ss = 0] = parts;
  if (hh > 23 || mm > 59 || ss > 59) return null;
  return new Date(y, m - 1, d, hh, mm, ss).toISOString();
}

/** `HH:MM:SS` in this machine's zone, for prefilling a time field. */
export function timeField(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(when.getHours())}:${pad(when.getMinutes())}:${pad(when.getSeconds())}`;
}
