import { motion } from "framer-motion";
import {
  ArrowLeft,
  Check,
  CircleAlert,
  Copy,
  RotateCcw,
  Send,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useBoxHealth } from "@/components/chrome/ConstellationStatus";
import { Button, Select } from "@/components/common/controls";
import { FlashDialog } from "./FlashDialog";
import { DEFAULT_STATUS_MATCH, Scrollback, isStatusLine } from "./Scrollback";
import { Star3D } from "./Star3D";
import { StateBadge } from "./StateBadge";
import { UtilityControls } from "./UtilityControls";
import {
  useBoardPresence,
  useBoxOutput,
  useFlashedSketch,
  usePortStatus,
} from "@/lib/hardware/context";
import { springPanel, springSnappy } from "@/lib/motion";
import { getTaskProfile } from "@/lib/sessions/commands";
import { useSettings } from "@/lib/settings/context";
import { BAUD_RATES } from "@/lib/settings/schema";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";
import type { TaskProfile } from "@/lib/sessions/types";

/**
 * One box, up close (ephymeris_v1.0.md §4.3): the animated 3D star on the
 * left, identity beside it, and every debugging utility below, grouped by what
 * the user is trying to do — **Connection** (open/close, baud, reset,
 * acknowledge), **Sketch** (flash, utility controls), **Console** (scrollback,
 * send, copy). The old ConsolePanel packed all of this into one header row;
 * the groups are the same capabilities, organized instead of compressed.
 *
 * The console itself is two tabs. A utility sketch emits a `STATUS` line on
 * every state change *and* a ~1 s heartbeat, which interleaved buries the
 * command echoes and error text the console exists to show — so telemetry gets
 * its own scrollback and the main one carries everything else.
 *
 * The UI disables what the current state forbids, but that's a courtesy — the
 * sidecar enforces the rules, and any rejection it returns is surfaced in the
 * Connection group rather than swallowed (§6.3).
 */

const LINE_ENDING_OPTIONS = [
  { value: "none", label: "None" },
  { value: "lf", label: "LF" },
  { value: "cr", label: "CR" },
  { value: "crlf", label: "CRLF" },
] as const;

export function NodeDetail({ box, onBack }: { box: number; onBack: () => void }) {
  const { client, status: connStatus } = useSidecar();
  const { settings } = useSettings();
  const port = usePortStatus(box);
  const lines = useBoxOutput(box);
  const boards = useBoardPresence();
  const flashed = useFlashedSketch(box);
  const health = useBoxHealth()[box] ?? "absent";

  const binding = settings.boxes.find((b) => b.box === box);
  const board = boards.find((b) => b.boxId === box) ?? null;
  const connected = connStatus === "connected";

  const [flashOpen, setFlashOpen] = useState(false);
  const [baud, setBaud] = useState<number>(settings.defaultBaud);
  const [lineEnding, setLineEnding] = useState<"none" | "lf" | "cr" | "crlf">("lf");
  const [draft, setDraft] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
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

  // Load the flashed sketch's Task Profile so a *utility* sketch gets its
  // controls/telemetry strip. A behavior or profile-less sketch clears it.
  useEffect(() => {
    if (!flashed) {
      setProfile(null);
      return;
    }
    let cancelled = false;
    getTaskProfile(client, flashed.path)
      .then((p) => {
        if (!cancelled) setProfile(p);
      })
      .catch(() => {
        if (!cancelled) setProfile(null);
      });
    return () => {
      cancelled = true;
    };
  }, [client, flashed]);

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

  const openPort = () => void run(() => client.call(CMD.PORT_PASSTHROUGH_OPEN, { box, baud }));
  const closePort = () => void run(() => client.call(CMD.PORT_PASSTHROUGH_CLOSE, { box }));
  const ackError = () => void run(() => client.call(CMD.PORT_ERROR_ACK, { box }));
  const resetBoard = () => void run(() => client.call(CMD.PORT_RESET, { box }));

  async function send() {
    const text = draft;
    const ok = await run(() => client.call(CMD.PORT_SEND, { box, text, lineEnding }));
    if (ok) setDraft("");
  }

  /** Copies whichever tab you're looking at — the one you meant. */
  function copyLog() {
    const body = shown
      .map((l) => `${l.dir === "tx" ? "› " : "  "}${l.text}`)
      .join("\n");
    void navigator.clipboard.writeText(body).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  const canOpen = connected && port.state === "IDLE" && board !== null;
  const canSend = connected && port.state === "PASSTHROUGH";
  // Flash/reset are legal from IDLE and PASSTHROUGH — §3.3's auto-release
  // covers the passthrough case, so the UI shouldn't force a manual close.
  const canOperate =
    connected && board !== null && (port.state === "IDLE" || port.state === "PASSTHROUGH");

  return (
    <div>
      <div className="flex items-center gap-3">
        <Button variant="ghost" onClick={onBack} title="Back to the constellation (Esc)">
          <ArrowLeft size={13} strokeWidth={1.75} />
          Constellation
        </Button>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(0,10fr)]">
        {/* Left: the star, identity beneath it. */}
        <div className="flex flex-col gap-3">
          <motion.div
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={springPanel}
            className="overflow-hidden rounded-md border border-halo"
          >
            <div className="h-[300px]">
              <Star3D health={health} />
            </div>
          </motion.div>

          <section className="surface rounded-md">
            <IdentityRow label="Box" value={String(box)} mono />
            <IdentityRow label="Nickname" value={binding?.label ?? `Box ${box}`} />
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
              value={flashed ? flashed.name : "none flashed this session"}
              mono={!!flashed}
              dim={!flashed}
              last
            />
          </section>
        </div>

        {/* Right: the utilities, grouped by intent. */}
        <div className="flex flex-col gap-3">
          <Group title="Connection">
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
          </Group>

          <Group title="Sketch">
            <div className="flex flex-wrap items-center gap-1.5 px-3 py-2.5">
              <span className="min-w-0 truncate font-mono text-[11px] text-static">
                {flashed ? flashed.name : "nothing flashed this session"}
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
              <UtilityControls box={box} profile={profile} canSend={canSend} />
            )}
          </Group>

          <section className="surface overflow-hidden rounded-md">
            <div className="flex items-center gap-1 border-b border-halo px-2 py-1.5">
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
              <div className="ml-auto">
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
              </div>
            </div>

            <Scrollback
              lines={shown}
              className="h-56"
              emptyLabel={
                tab === "status"
                  ? `— no ${statusMatch} lines yet —`
                  : "— no output —"
              }
            />

            <div className="flex items-center gap-1.5 border-t border-halo px-2.5 py-1.5">
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
      </div>

      <FlashDialog box={box} open={flashOpen} onClose={() => setFlashOpen(false)} />
    </div>
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

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="surface overflow-hidden rounded-md">
      <h3 className="border-b border-halo px-3 py-2 text-[11px] font-medium tracking-[0.08em] text-static uppercase">
        {title}
      </h3>
      {children}
    </section>
  );
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
