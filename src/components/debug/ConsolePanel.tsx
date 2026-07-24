import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronDown, CircleAlert, Copy, RotateCcw, Send, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button, Select } from "@/components/common/controls";
import { springPanel } from "@/lib/motion";
import {
  useBoardPresence,
  useBoxOutput,
  useFlashedSketch,
  usePortStatus,
} from "@/lib/hardware/context";
import { getTaskProfile } from "@/lib/sessions/commands";
import { useSettings } from "@/lib/settings/context";
import { BAUD_RATES } from "@/lib/settings/schema";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";
import { FlashDialog } from "./FlashDialog";
import { StateBadge } from "./StateBadge";
import { UtilityControls } from "./UtilityControls";
import type { ConsoleLine } from "@/lib/hardware/store";
import type { TaskProfile } from "@/lib/sessions/types";

/**
 * One box's console panel (`hardware-interaction.md` §6.6): state badge,
 * scrollback with sent commands interleaved, single-line input with
 * line-ending selector and Enter-to-send, per-box baud, copy-log affordance.
 *
 * The UI disables what the current state forbids, but that's a courtesy — the
 * sidecar enforces the rules, and any rejection it returns is surfaced beside
 * the input rather than swallowed (§6.3).
 */

const LINE_ENDING_OPTIONS = [
  { value: "none", label: "None" },
  { value: "lf", label: "LF" },
  { value: "cr", label: "CR" },
  { value: "crlf", label: "CRLF" },
] as const;

/** Pin-to-bottom tolerance: within this many px of the end counts as "at" it. */
const PIN_THRESHOLD_PX = 24;

export function ConsolePanel({ box }: { box: number }) {
  const { client, status: connStatus } = useSidecar();
  const { settings } = useSettings();
  const port = usePortStatus(box);
  const lines = useBoxOutput(box);
  const boards = useBoardPresence();
  const flashed = useFlashedSketch(box);

  const binding = settings.boxes.find((b) => b.box === box);
  const board = boards.find((b) => b.boxId === box) ?? null;
  const connected = connStatus === "connected";

  const [collapsed, setCollapsed] = useState(false);
  const [flashOpen, setFlashOpen] = useState(false);
  const [baud, setBaud] = useState<number>(settings.defaultBaud);
  const [lineEnding, setLineEnding] = useState<string>("lf");
  const [draft, setDraft] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [profile, setProfile] = useState<TaskProfile | null>(null);

  // A rejection message describes the state it was rejected in; once the state
  // moves on, it's stale.
  useEffect(() => setActionError(null), [port.state]);

  // Load the flashed sketch's Task Profile so a *utility* sketch gets its
  // controls/telemetry panel. A behavior or profile-less sketch clears it.
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
    if (ok) setDraft(""); // kept on failure so the user can retry
  }

  function copyLog() {
    const body = lines
      .map((l) => `${formatTs(l.ts)} ${l.dir === "tx" ? "›" : " "} ${l.text}`)
      .join("\n");
    void navigator.clipboard.writeText(body).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  const presenceLabel = board
    ? board.address
    : binding?.hardwareId
      ? "bound · not detected"
      : "not bound";

  const canOpen = connected && port.state === "IDLE" && board !== null;
  const canSend = connected && port.state === "PASSTHROUGH";
  // Flash/reset are legal from IDLE and PASSTHROUGH — §3.3's auto-release
  // covers the passthrough case, so the UI shouldn't force a manual close.
  const canOperate =
    connected && board !== null && (port.state === "IDLE" || port.state === "PASSTHROUGH");

  return (
    <section className="surface overflow-hidden rounded-md">
      <header className="flex h-11 items-center gap-2 px-2.5">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? `Expand box ${box}` : `Collapse box ${box}`}
          aria-expanded={!collapsed}
          className="text-static transition-colors hover:text-starlight"
        >
          <motion.span
            className="block"
            animate={{ rotate: collapsed ? -90 : 0 }}
            transition={springPanel}
          >
            <ChevronDown size={15} strokeWidth={1.75} />
          </motion.span>
        </button>

        <span className="text-[13px] font-medium text-starlight">
          {binding?.label ?? `Box ${box}`}
        </span>
        <span className="min-w-0 truncate font-mono text-[10px] text-static" title={presenceLabel}>
          {presenceLabel}
        </span>

        <div className="ml-auto flex shrink-0 items-center gap-1.5">
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
            onClick={() => setFlashOpen(true)}
            disabled={!canOperate}
            title={canOperate ? "Flash a sketch" : "Needs a detected board, idle or in passthrough"}
          >
            <Zap size={13} strokeWidth={1.75} />
          </Button>
          <Button
            variant="ghost"
            onClick={resetBoard}
            disabled={!canOperate}
            title={canOperate ? "Reset (DTR toggle)" : "Needs a detected board, idle or in passthrough"}
          >
            <RotateCcw size={13} strokeWidth={1.75} />
          </Button>
          <Button
            variant="ghost"
            onClick={copyLog}
            disabled={lines.length === 0}
            title="Copy log to clipboard"
          >
            {copied ? <Check size={13} strokeWidth={2} /> : <Copy size={13} strokeWidth={1.75} />}
          </Button>
        </div>
      </header>

      <FlashDialog box={box} open={flashOpen} onClose={() => setFlashOpen(false)} />

      <AnimatePresence initial={false}>
        {!collapsed && (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={springPanel}
            className="overflow-hidden"
          >
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

            {profile?.kind === "utility" && (
              <UtilityControls box={box} profile={profile} canSend={canSend} />
            )}

            <Scrollback lines={lines} />

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

            {actionError && (
              <p
                className="border-t border-halo px-3 py-1.5 text-[11px]"
                style={{ color: "var(--color-status-error)" }}
              >
                {actionError}
              </p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function Scrollback({ lines }: { lines: ConsoleLine[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);

  // Follow new output only while the user is at the bottom; scrolling up to
  // read must not be fought by the autoscroll.
  useEffect(() => {
    const el = ref.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  return (
    <div
      ref={ref}
      data-selectable
      onScroll={(e) => {
        const el = e.currentTarget;
        pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < PIN_THRESHOLD_PX;
      }}
      className="h-44 overflow-y-auto border-t border-halo bg-void/60 px-2.5 py-1.5 font-mono text-[11px] leading-[1.65]"
    >
      {lines.length === 0 ? (
        <span className="text-static/50">— no output —</span>
      ) : (
        lines.map((l) => (
          <div key={l.id} className="flex gap-2 break-all whitespace-pre-wrap">
            <span className="shrink-0 text-static/60">{formatTs(l.ts)}</span>
            <span className="w-2 shrink-0 text-pulsar">{l.dir === "tx" ? "›" : ""}</span>
            <span className={l.dir === "tx" ? "text-pulsar" : "text-starlight"}>
              {l.text || " "}
            </span>
          </div>
        ))
      )}
    </div>
  );
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  const pad = (n: number, width = 2) => String(n).padStart(width, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
}
