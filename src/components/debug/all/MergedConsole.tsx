import { Send } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button, Select } from "@/components/common/controls";
import type { ConsoleLine } from "@/lib/hardware/store";

import { DEFAULT_STATUS_MATCH, isStatusLine } from "../Scrollback";

/** Lines kept on screen across every box. */
const KEEP = 200;

/**
 * Every targeted box's console as one stream, each line tagged with its box,
 * and one input that sends to all of them.
 *
 * Interleaved by arrival (`ConsoleLine.id` is assigned in arrival order), so a
 * command sent to the rig reads as one call and six answers. The `STATUS`
 * heartbeat is hidden by default — six boxes' worth is a wall — and the grid
 * above is where it is read.
 */
export function MergedConsole({
  outputs,
  boxes,
  canSend,
  statusMatch = DEFAULT_STATUS_MATCH,
  onSend,
}: {
  outputs: ReadonlyMap<number, ConsoleLine[]>;
  /** The boxes shown — the targets. */
  boxes: readonly number[];
  canSend: boolean;
  statusMatch?: string;
  onSend: (text: string, lineEnding: "none" | "lf" | "cr" | "crlf") => Promise<void>;
}) {
  const [showStatus, setShowStatus] = useState(false);
  const [draft, setDraft] = useState("");
  const [lineEnding, setLineEnding] = useState<"none" | "lf" | "cr" | "crlf">("lf");
  const scroller = useRef<HTMLDivElement>(null);

  const lines = useMemo(() => {
    const merged: Array<ConsoleLine & { box: number }> = [];
    for (const box of boxes) {
      for (const line of (outputs.get(box) ?? []).slice(-KEEP)) {
        if (!showStatus && isStatusLine(line, statusMatch)) continue;
        merged.push({ ...line, box });
      }
    }
    merged.sort((a, b) => a.id - b.id);
    return merged.slice(-KEEP);
  }, [outputs, boxes, showStatus, statusMatch]);

  // Follow the tail while the reader is at it; leave them be if they scrolled up.
  const pinned = useRef(true);
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [lines]);

  async function submit() {
    const text = draft;
    await onSend(text, lineEnding);
    setDraft("");
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1.5">
      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
        className="scrollbar-slim min-h-[120px] flex-1 overflow-y-auto rounded-sm border border-halo/70 bg-void/50 px-2 py-1.5 font-mono text-[10.5px] leading-[1.45]"
        data-selectable
      >
        {lines.length === 0 ? (
          <p className="text-static/50">— nothing yet — open the consoles above</p>
        ) : (
          lines.map((line) => (
            <div key={`${line.box}-${line.id}`} className="flex gap-2">
              <span className="w-6 shrink-0 text-right text-pulsar/80 tabular-nums">{line.box}</span>
              <span className={`shrink-0 ${line.dir === "tx" ? "text-ion/80" : "text-static/50"}`}>
                {line.dir === "tx" ? "→" : "←"}
              </span>
              <span className={`min-w-0 break-all ${line.dir === "tx" ? "text-ion/90" : "text-starlight/85"}`}>
                {line.text}
              </span>
            </div>
          ))
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canSend && draft) void submit();
          }}
          disabled={!canSend}
          placeholder={canSend ? "send to every open console…" : "open the consoles to send"}
          aria-label="Send a line to every open console"
          className="min-w-0 flex-1 rounded-sm border border-halo bg-void/40 px-2 py-1 font-mono text-[11px] text-starlight placeholder:text-static/40 focus:border-pulsar focus:outline-none disabled:opacity-50"
        />
        <Select
          label="Line ending"
          value={lineEnding}
          options={[
            { value: "lf", label: "LF" },
            { value: "crlf", label: "CRLF" },
            { value: "cr", label: "CR" },
            { value: "none", label: "none" },
          ]}
          onChange={(v) => setLineEnding(v)}
        />
        <Button variant="secondary" disabled={!canSend || !draft} onClick={() => void submit()}>
          <Send size={12} strokeWidth={1.75} />
          Send
        </Button>
        <label className="flex shrink-0 items-center gap-1 font-mono text-[10px] text-static">
          <input type="checkbox" checked={showStatus} onChange={(e) => setShowStatus(e.target.checked)} />
          status
        </label>
      </div>
    </div>
  );
}
