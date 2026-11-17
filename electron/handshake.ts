/**
 * The sidecar's one stdout line that matters (`ARCHITECTURE.md#startup-handshake`):
 *
 *     EPHYMERIS_WS_PORT=<port> EPHYMERIS_WS_TOKEN=<token>
 *
 * Pure, so the parse is tested without a process. Any other line is an
 * ordinary log line.
 */

import type { SidecarEndpoint } from "./bridge.js";

export function parseHandshake(line: string): SidecarEndpoint | null {
  let port: number | null = null;
  let token: string | null = null;
  for (const field of line.trim().split(/\s+/)) {
    const eq = field.indexOf("=");
    if (eq < 0) continue;
    const key = field.slice(0, eq);
    const value = field.slice(eq + 1);
    if (key === "EPHYMERIS_WS_PORT") port = parsePort(value);
    else if (key === "EPHYMERIS_WS_TOKEN") token = value;
  }
  return port !== null && token !== null ? { port, token } : null;
}

function parsePort(value: string): number | null {
  if (!/^\d{1,5}$/.test(value)) return null;
  const port = Number(value);
  return port <= 65535 ? port : null;
}
