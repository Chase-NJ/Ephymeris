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

/** `1 h 29 min`, `42 min`, `under a minute`: a duration as a sentence would say it. */
export function proseDuration(totalSeconds: number): string {
  const minutes = Math.floor(Math.max(0, totalSeconds) / 60);
  if (minutes < 1) return "under a minute";
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest} min`;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

/** Local `HH:MM`, for a time set in running text. */
export function shortTime(iso: string | null): string {
  const full = wallClock(iso);
  return full === "—" ? full : full.slice(0, 5);
}

/** `19 Nov` from an ISO date, read as a calendar day (no zone). */
export function shortDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
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
