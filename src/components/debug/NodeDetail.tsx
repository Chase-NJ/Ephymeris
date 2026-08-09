import { save } from "@tauri-apps/plugin-dialog";
import { writeTextFile } from "@tauri-apps/plugin-fs";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Check,
  ChevronsLeftRight,
  ChevronsRightLeft,
  CircleAlert,
  Copy,
  Download,
  RotateCcw,
  Send,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useBoxHealth } from "@/components/chrome/ConstellationStatus";
import { Button, Select } from "@/components/common/controls";
import { HudPanel, HudSection } from "@/components/common/HudPanel";
import { FlashDialog } from "./FlashDialog";
import { DEFAULT_STATUS_MATCH, Scrollback, isStatusLine } from "./Scrollback";
import { StateBadge } from "./StateBadge";
import { UtilityControls } from "./UtilityControls";
import {
  useBoardPresence,
  useBoxOutput,
  useFlashedSketch,
  useHardwareStore,
  usePortStatus,
  useUtilityStatus,
} from "@/lib/hardware/context";
import { springSnappy } from "@/lib/motion";
import { getTaskProfile } from "@/lib/sessions/commands";
import { useSettings } from "@/lib/settings/context";
import { BAUD_RATES } from "@/lib/settings/schema";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";
import type { UtilityBaselineState } from "@/lib/ws/protocol";
import type { TaskProfile } from "@/lib/sessions/types";

/**
 * One box, up close (dashboard.md §4).
 *
 * Docked and translucent over the still-rendering constellation rather than
 * replacing it, exactly as Mission Control's `StarPanel` is: arrival means the
 * camera is now close to that box's star with an instrument panel open, not a
 * cut to a different screen. That is also why the panel no longer carries a 3D
 * star of its own — the real one is right there behind it, in the box's own
 * health colour, still turning.
 *
 * Every debugging utility is here, grouped by what the user is trying to do —
 * identity, **Connection** (open/close, baud, reset, acknowledge), **Sketch**
 * (flash, utility controls), **Console** (scrollback, send, copy). The old
 * ConsolePanel packed all of this into one header row; the groups are the same
 * capabilities, organized instead of compressed.
 *
 * The console itself is two tabs. A utility sketch emits a `STATUS` line on
 * every state change *and* a ~1 s heartbeat, which interleaved buries the
 * command echoes and error text the console exists to show — so telemetry gets
 * its own scrollback and the main one carries everything else.
 *
 * The UI disables what the current state forbids, but that's a courtesy — the
 * sidecar enforces the rules, and any rejection it returns is surfaced in the
 * Connection group rather than swallowed (§6.3).
 *
 * **Two columns, sized so nothing needs scrolling.** Identity, Connection and
 * the console stack in a fixed-width left column — the console takes whatever
 * height those two leave, which keeps it a working scrollback without letting
 * it dominate the panel. The Sketch tile owns the flexible right column,
 * because it is the one section whose size is the sketch's to declare: a
 * profile with eighteen channel controls needs the room, and the wide toggle
 * gives that column (and its grids a third column) more of it.
 *
 * The body grid pins its single row to the panel's free space
 * (`grid-rows-[minmax(0,1fr)]`) — an `auto` row sizes to its tallest item's
 * *content*, so a tall utility grid silently grew the row past the panel's
 * bottom edge and the viewport (which never scrolls) clipped it. With the row
 * pinned, each column is genuinely height-constrained and handles its own
 * overflow: the console scrolls because a scrollback is a scrolling thing, and
 * the Sketch tile scrolls only as a last resort on a window too short for its
 * grid — the wide toggle is the intended answer there.
 *
 * **The panel widens on request.** Widening is a deliberate toggle rather than
 * something that happens on its own: the panel covers the constellation it is
 * docked over, so how much of the scene to trade for control real estate is
 * the operator's call, not a heuristic on a sketch's control count.
 */

/**
 * Panel outer widths, mirrored in the literal `w-[min(...)]` classes on the
 * shell below — Tailwind's scanner needs static class strings, so these can't
 * be interpolated. `DebugMode` derives the camera's `frameShift` from them;
 * change one, change both.
 */
export const PANEL_WIDTH = 880;
export const PANEL_WIDTH_WIDE = 1180;

const LINE_ENDING_OPTIONS = [
  { value: "none", label: "None" },
  { value: "lf", label: "LF" },
  { value: "cr", label: "CR" },
  { value: "crlf", label: "CRLF" },
] as const;

export function NodeDetail({
  box,
  onBack,
  wide,
  onToggleWide,
}: {
  box: number;
  onBack: () => void;
  wide: boolean;
  onToggleWide: () => void;
}) {
  const { client, status: connStatus } = useSidecar();
  const { settings } = useSettings();
  const port = usePortStatus(box);
  const lines = useBoxOutput(box);
  const store = useHardwareStore();
  const boards = useBoardPresence();
  const flashed = useFlashedSketch(box);
  const utility = useUtilityStatus();
  const health = useBoxHealth()[box] ?? "absent";

  // What the board is actually carrying (`settings.md` §8): the
  // baseline keeps every idle bound box on the configured utility sketch, so
  // a box the sidecar reports `ready` has that sketch on it *now* — no manual
  // flash needed for its controls and telemetry to be live. The sidecar's
  // belief outranks the client-tracked flash, which goes stale the moment a
  // background restore re-flashes over the user's sketch; conversely, a user
  // flash of a different sketch moves the box off `ready`, so the tracked
  // flash correctly takes over until the baseline reclaims the port.
  const utilityBox = utility.boxes.find((b) => b.box === box);
  const atBaseline =
    utility.configured && utility.sketchPath !== null && utilityBox?.state === "ready";
  const effectiveSketch = atBaseline
    ? { path: utility.sketchPath!, name: utility.sketchName ?? "utility sketch" }
    : flashed;

  const binding = settings.boxes.find((b) => b.box === box);
  const board = boards.find((b) => b.boxId === box) ?? null;
  const connected = connStatus === "connected";

  const [flashOpen, setFlashOpen] = useState(false);
  const [baud, setBaud] = useState<number>(settings.defaultBaud);
  const [lineEnding, setLineEnding] = useState<"none" | "lf" | "cr" | "crlf">("lf");
  const [draft, setDraft] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const [logError, setLogError] = useState<string | null>(null);
  const [profile, setProfile] = useState<TaskProfile | null>(null);
  const [tab, setTab] = useState<"console" | "status">("console");

  // The sketch declares its own telemetry prefix; a profile-less sketch may
  // still emit the conventional one, so the split works either way.
  const statusMatch = profile?.telemetry?.match ?? DEFAULT_STATUS_MATCH;
  const [consoleLines, statusLines] = useMemo(() => {
    const chatter: typeof lines = [];
    const telemetry: typeof lines = [];
    for (const line of lines) {
      (isStatusLine(line, statusMatch) ? telemetry : chatter).push(line);
    }
    return [chatter, telemetry] as const;
  }, [lines, statusMatch]);
  const shown = tab === "console" ? consoleLines : statusLines;

  // Escape returns to the constellation — the gesture people try first.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !flashOpen) onBack();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack, flashOpen]);

  // A rejection message describes the state it was rejected in; once the state
  // moves on, it's stale.
  useEffect(() => setActionError(null), [port.state]);

  // Load the carried sketch's Task Profile so a *utility* sketch gets its
  // controls/telemetry strip — from the first open, when the baseline already
  // put it there. A behavior or profile-less sketch clears it.
  const effectivePath = effectiveSketch?.path ?? null;
  useEffect(() => {
    if (!effectivePath) {
      setProfile(null);
      return;
    }
    let cancelled = false;
    getTaskProfile(client, effectivePath)
      .then((p) => {
        if (!cancelled) setProfile(p);
      })
      .catch(() => {
        if (!cancelled) setProfile(null);
      });
    return () => {
      cancelled = true;
    };
  }, [client, effectivePath]);

  async function run(action: () => Promise<unknown>): Promise<boolean> {
    setActionError(null);
    try {
      await action();
      return true;
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
      return false;
    }
  }

  /*
   * **A console opened at a new baud must not show the old one's output.**
   *
   * The sidecar clears its decode buffer on every open (`handler.py`), but the
   * client-side scrollback accumulated across opens, so reopening at a
   * different rate left the previous session's legible lines sitting above the
   * new garbage. That inverts the one diagnosis this console exists to make: a
   * mismatched baud reads as *working* for as long as the stale lines are the
   * ones on screen, and mute-reads-as-dead is already the failure mode
   * `dashboard.md` §6.4 warns about.
   *
   * Only the explicit user-initiated open clears. A passthrough that resumes on
   * its own — after a flash, or after a bench upload — must keep what is
   * already there, since the uploader's mirror (`handler.echo`) is written into
   * this same scrollback and is the record of the upload the operator just ran.
   */
  const openPort = () => {
    store.clearLines(box);
    void run(() => client.call(CMD.PORT_PASSTHROUGH_OPEN, { box, baud }));
  };
  const closePort = () => void run(() => client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box }));

  /*
   * **A console left open must not outlive the panel that opened it.**
   *
   * Passthrough is opened from this panel and, until now, only ever closed
   * from it — so navigating away with a console open left the port in
   * `PASSTHROUGH` indefinitely. That is invisible from anywhere else and wrong
   * twice over: the box's star keeps wearing the "open box" instrument ring on
   * the Dashboard, and the port stays claimed by a panel nobody can see.
   *
   * The same shape as `useHandshakeTest`'s cleanup, which already closes
   * in-flight ports on unmount for exactly this reason. Best-effort: a failed
   * close on the way out is no worse than the leak it replaces, and there is
   * no longer a panel to report it to.
   *
   * Reads the live state through a ref so the effect runs on unmount only —
   * depending on `port.state` would close the port every time it changed.
   */
  const openStateRef = useRef(port.state);
  openStateRef.current = port.state;
  useEffect(() => {
    return () => {
      if (openStateRef.current === "PASSTHROUGH") {
        void client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box }).catch(() => {});
      }
    };
  }, [client, box]);
  const ackError = () => void run(() => client.call(CMD.PORT_ERROR_ACK, { box }));
  const resetBoard = () => void run(() => client.call(CMD.PORT_RESET, { box }));

  async function send() {
    const text = draft;
    const ok = await run(() => client.call(CMD.PORT_SEND, { box, text, lineEnding }));
    if (ok) setDraft("");
  }

  /** The visible tab's lines, rendered the same way for copy and save. */
  function logBody(): string {
    return shown
      .map((l) => `${l.dir === "tx" ? "› " : "  "}${l.text}`)
      .join("\n");
  }

  /** Copies whichever tab you're looking at — the one you meant. */
  function copyLog() {
    void navigator.clipboard.writeText(logBody()).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  /** Saves the visible tab to a file the user picks (§6.5's "save debug log").
   *
   * Deliberately shell-side, not a sidecar command: the dialog plugin adds the
   * chosen path to the fs scope at runtime, and the export keeps working when
   * the sidecar is down — which is exactly when a debug log matters most. Like
   * the clipboard, this never enters the data pipeline.
   */
  async function saveLog() {
    setLogError(null);
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    try {
      const path = await save({
        defaultPath: `ephymeris-box${box}-${tab}-${stamp}.log`,
        filters: [{ name: "Log", extensions: ["log", "txt"] }],
      });
      if (!path) return; // cancelled
      await writeTextFile(path, logBody());
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (err) {
      setLogError(err instanceof Error ? err.message : String(err));
    }
  }

  const canOpen = connected && port.state === "IDLE" && board !== null;
  const canSend = connected && port.state === "PASSTHROUGH";
  // Flash/reset are legal from IDLE and PASSTHROUGH — §3.3's auto-release
  // covers the passthrough case, so the UI shouldn't force a manual close.
  const canOperate =
    connected && board !== null && (port.state === "IDLE" || port.state === "PASSTHROUGH");

  return (
    <HudPanel
      // Docked over the scene, above the nameplates (drei renders those as DOM
      // at z-index <= 10) — a crisp plate drifting over a control would be
      // worse than the star it labels being hidden. `flex flex-col` with fixed
      // insets: the shell no longer scrolls; the columns inside manage their
      // own overflow. Both widths are capped against the scene rather than
      // fixed, so on a laptop the panel becomes "nearly the whole frame"
      // instead of overflowing it. The literal widths mirror
      // `PANEL_WIDTH`/`PANEL_WIDTH_WIDE` above.
      className={`absolute top-4 right-4 bottom-4 z-20 flex flex-col ${
        wide ? "w-[min(1180px,calc(100%-2rem))]" : "w-[min(880px,calc(100%-2rem))]"
      }`}
      // The width is a layout change, not a decorative one — animating it lets
      // the eye follow what moved instead of re-finding every control.
      layout
    >
      <header className="flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} title="Back to the constellation (Esc)">
          <ArrowLeft size={13} strokeWidth={1.75} />
          Constellation
        </Button>
        <h2 className="min-w-0 truncate font-display text-[18px] text-starlight">
          {binding?.label ?? `Box ${box}`}
        </h2>
        {/* The health word is the legend for the star's colour behind the
            panel; the Connection group reports the port state it derives
            from. */}
        <p className="shrink-0 font-mono text-[11px] text-static">
          box {box} · {health}
        </p>
        <div className="ml-auto">
          <Button
            variant="ghost"
            shape="icon"
            onClick={onToggleWide}
            title={
              wide
                ? "Narrow the panel, showing more of the constellation"
                : "Widen the panel, for sketches with many controls"
            }
          >
            {wide ? (
              <ChevronsRightLeft size={14} strokeWidth={1.75} />
            ) : (
              <ChevronsLeftRight size={14} strokeWidth={1.75} />
            )}
          </Button>
        </div>
      </header>

      {/* Identity, Connection and the console left; the Sketch tile right.
          The row is pinned to the panel's free space — see the header note —
          so nothing can outgrow the window, and widening the panel gives all
          the extra room to the sketch column, which is what the toggle
          exists for. */}
      <div className="mt-3 grid min-h-0 flex-1 grid-cols-[380px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] gap-4">
        <div className="flex min-h-0 flex-col gap-3">
        <section className="surface-inset shrink-0 rounded-md">
          <IdentityRow
            label="Board"
            value={binding?.hardwareId ?? "not bound"}
            mono
            dim={!binding?.hardwareId}
          />
          <IdentityRow
            label="Port"
            value={board ? board.address : "not detected"}
            mono
            dim={!board}
          />
          <IdentityRow
            label="Sketch"
            value={
              effectiveSketch
                ? atBaseline && !flashed
                  ? `${effectiveSketch.name} (baseline)`
                  : effectiveSketch.name
                : baselineWord(utilityBox?.state)
            }
            mono={!!effectiveSketch}
            dim={!effectiveSketch}
            last
          />
        </section>

        <HudSection title="Connection" className="shrink-0">
            <div className="flex flex-wrap items-center gap-1.5 px-3 py-2.5">
              <StateBadge state={port.state} detected={board !== null} />

              {port.state === "IDLE" && (
                <>
                  <Select
                    label={`Baud rate for box ${box}`}
                    value={baud}
                    options={BAUD_RATES.map((b) => ({ value: b, label: String(b) }))}
                    onChange={setBaud}
                  />
                  <Button
                    onClick={openPort}
                    disabled={!canOpen}
                    title={
                      canOpen
                        ? `Open passthrough at ${baud}`
                        : board
                          ? "Sidecar not connected"
                          : "No detected board bound to this box"
                    }
                  >
                    Open
                  </Button>
                </>
              )}

              {port.state === "PASSTHROUGH" && (
                <>
                  <span className="font-mono text-[10px] text-static">@ {baud}</span>
                  <Button onClick={closePort} disabled={!connected}>
                    Close
                  </Button>
                </>
              )}

              <Button
                variant="ghost"
                onClick={resetBoard}
                disabled={!canOperate}
                title={
                  canOperate ? "Reset (DTR toggle)" : "Needs a detected board, idle or in passthrough"
                }
              >
                <RotateCcw size={13} strokeWidth={1.75} />
                Reset
              </Button>
            </div>

            {port.state === "ERROR" && (
              <div
                className="flex items-center gap-2 border-t border-halo px-3 py-2 text-[12px]"
                style={{ color: "var(--color-status-error)" }}
              >
                <CircleAlert size={14} strokeWidth={1.75} className="shrink-0" />
                <span className="min-w-0 flex-1 truncate" title={port.reason}>
                  {port.reason}
                </span>
                <Button onClick={ackError} disabled={!connected}>
                  Acknowledge
                </Button>
              </div>
            )}

            {actionError && (
              <p
                className="border-t border-halo px-3 py-1.5 text-[11px]"
                style={{ color: "var(--color-status-error)" }}
              >
                {actionError}
              </p>
            )}
          </HudSection>

          {/* The console, in the height Identity and Connection leave: the
              scrollback flexes to it (with a floor so a tiny window still
              shows a readable strip) and the send row stays pinned at the
              bottom. The tab bar replaces the section header, so the console
              still reads as one of the intent groups. */}
          <section className="surface-inset flex min-h-0 flex-1 flex-col overflow-hidden rounded-md">
            <div className="flex shrink-0 items-center gap-1 border-b border-halo px-2 py-1.5">
              <ConsoleTab
                label="Console"
                count={consoleLines.length}
                active={tab === "console"}
                onClick={() => setTab("console")}
              />
              <ConsoleTab
                label="Status"
                count={statusLines.length}
                active={tab === "status"}
                onClick={() => setTab("status")}
              />
              <div className="ml-auto flex items-center gap-1">
                <Button
                  variant="ghost"
                  onClick={copyLog}
                  disabled={shown.length === 0}
                  title={`Copy the ${tab === "console" ? "console" : "status"} log to clipboard`}
                >
                  {copied ? (
                    <Check size={13} strokeWidth={2} />
                  ) : (
                    <Copy size={13} strokeWidth={1.75} />
                  )}
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => void saveLog()}
                  disabled={shown.length === 0}
                  title={`Save the ${tab === "console" ? "console" : "status"} log to a file`}
                >
                  {saved ? (
                    <Check size={13} strokeWidth={2} />
                  ) : (
                    <Download size={13} strokeWidth={1.75} />
                  )}
                </Button>
              </div>
            </div>

            {logError && (
              <p
                className="shrink-0 border-b border-halo px-3 py-1.5 text-[11px]"
                style={{ color: "var(--color-status-error)" }}
              >
                Couldn't save the log — {logError}
              </p>
            )}

            <Scrollback
              lines={shown}
              className="min-h-[120px] flex-1"
              emptyLabel={
                tab === "status"
                  ? `— no ${statusMatch} lines yet —`
                  : "— no output —"
              }
            />

            <div className="flex shrink-0 items-center gap-1.5 border-t border-halo px-2.5 py-1.5">
              <input
                type="text"
                aria-label={`Send to box ${box}`}
                value={draft}
                disabled={!canSend}
                placeholder={canSend ? "Send to board…" : "Open passthrough to send"}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void send();
                }}
                className="min-w-0 flex-1 bg-transparent font-mono text-[12px] text-starlight outline-none placeholder:text-static/50 disabled:cursor-not-allowed"
              />
              <Select
                label={`Line ending for box ${box}`}
                value={lineEnding}
                options={LINE_ENDING_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                onChange={setLineEnding}
              />
              <Button onClick={() => void send()} disabled={!canSend} title="Send (Enter)">
                <Send size={13} strokeWidth={1.75} />
              </Button>
            </div>
          </section>
        </div>

        {/* The Sketch tile, in the flexible column: sized by its content, not
            stretched to the panel — a sketch with no controls is a small card,
            a utility profile's channel grids get the room. The inner scroll is
            a last resort for a window too short for the grid; the wide toggle
            (a third grid column) is the intended answer. */}
        <div className="flex min-h-0 flex-col">
          <HudSection title="Sketch" className="flex min-h-0 flex-col">
            <div className="scrollbar-slim min-h-0 overflow-y-auto">
              <div className="flex flex-wrap items-center gap-1.5 px-3 py-2.5">
                <span className="min-w-0 truncate font-mono text-[11px] text-static">
                  {effectiveSketch
                    ? atBaseline && !flashed
                      ? `${effectiveSketch.name} · baseline`
                      : effectiveSketch.name
                    : baselineWord(utilityBox?.state)}
                </span>
                <div className="ml-auto">
                  <Button
                    onClick={() => setFlashOpen(true)}
                    disabled={!canOperate}
                    title={
                      canOperate ? "Flash a sketch" : "Needs a detected board, idle or in passthrough"
                    }
                  >
                    <Zap size={13} strokeWidth={1.75} />
                    Flash…
                  </Button>
                </div>
              </div>
              {profile?.kind === "utility" && (
                <UtilityControls
                  box={box}
                  profile={profile}
                  canSend={canSend}
                  wide={wide}
                  onRequestWidth={wide ? null : onToggleWide}
                />
              )}
            </div>
          </HudSection>
        </div>
      </div>

      <FlashDialog box={box} open={flashOpen} onClose={() => setFlashOpen(false)} />
    </HudPanel>
  );
}

/**
 * One console tab. Styled as a group heading rather than a chrome tab — it
 * replaces the `Group` header in that slot, so the console still reads as one
 * of the three intent groups rather than a nested widget. The active marker is
 * a shared `layoutId`, so it glides between tabs like the sidebar's does.
 */
function ConsoleTab({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`relative rounded-sm px-2 py-1 text-[11px] font-medium tracking-[0.08em] uppercase transition-colors ${
        active ? "text-starlight" : "text-static hover:text-starlight"
      }`}
    >
      {active && (
        <motion.span
          layoutId="console-tab"
          transition={springSnappy}
          className="absolute inset-0 rounded-sm bg-pulsar/18"
        />
      )}
      <span className="relative">
        {label}
        {count > 0 && (
          <span className="ml-1.5 font-mono text-[10px] tracking-normal text-static">
            {count}
          </span>
        )}
      </span>
    </button>
  );
}

/**
 * The empty-sketch readout, honest about *why* nothing is known: a baseline
 * restore mid-flight or a failed one says more than "none flashed" would.
 * Every other state genuinely means the board's firmware is unknown.
 */
function baselineWord(state: UtilityBaselineState | undefined): string {
  switch (state) {
    case "restoring":
      return "restoring baseline…";
    case "failed":
      return "baseline restore failed — see Config";
    default:
      return "none flashed this session";
  }
}

function IdentityRow({
  label,
  value,
  mono = false,
  dim = false,
  last = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  dim?: boolean;
  last?: boolean;
}) {
  return (
    <div
      className={`flex items-baseline justify-between gap-4 px-3 py-2 ${
        last ? "" : "border-b border-halo"
      }`}
    >
      <span className="text-[11px] text-static">{label}</span>
      <span
        className={`min-w-0 truncate text-right text-[12px] ${mono ? "font-mono" : ""} ${
          dim ? "text-static/60" : "text-starlight"
        }`}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}
