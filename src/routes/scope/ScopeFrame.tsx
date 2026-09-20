import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, X } from "lucide-react";
import type { ReactNode } from "react";

import { Dropdown } from "@/components/common/Dropdown";
import { useIntanStatus } from "@/lib/intan/context";
import { channelNumber } from "@/lib/intan/scopeMath";
import { useSidecar } from "@/lib/ws/context";

/**
 * The chrome every recording pop-up shares: a drag bar that says what the
 * window is, a row of options, the view, and one line of status underneath.
 *
 * The windows are frameless like the main one, so this IS the title bar —
 * `data-tauri-drag-region` makes it draggable and the two buttons are the only
 * window controls a scope needs.
 */
export function ScopeFrame({
  title,
  subtitle,
  options,
  status,
  error,
  children,
}: {
  title: string;
  subtitle?: string | null | undefined;
  options?: ReactNode;
  /** One mono line under the view: counts, rates, what it is waiting for. */
  status?: ReactNode;
  error?: string | null | undefined;
  children: ReactNode;
}) {
  const { status: link } = useSidecar();
  const intan = useIntanStatus();
  const frozen = link !== "connected" ? "Reconnecting to Ephymeris…" : !intan.recording ? "No recording is running — this view is frozen." : null;

  return (
    <div className="flex h-screen flex-col bg-void text-starlight">
      <header
        data-tauri-drag-region
        className="flex h-9 shrink-0 items-center justify-between border-b border-halo pl-3"
      >
        <div data-tauri-drag-region className="pointer-events-none flex min-w-0 items-baseline gap-2">
          <span className="font-display text-[13px] font-semibold tracking-tight">{title}</span>
          {subtitle && <span className="truncate font-mono text-[11px] text-static">{subtitle}</span>}
        </div>
        <div className="flex h-full items-stretch">
          <FrameButton label="Minimize" onClick={() => void getCurrentWindow().minimize()}>
            <Minus size={14} strokeWidth={1.5} />
          </FrameButton>
          <FrameButton label="Close" onClick={() => void getCurrentWindow().close()}>
            <X size={15} strokeWidth={1.5} />
          </FrameButton>
        </div>
      </header>

      {options && (
        <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-halo px-3 py-2">
          {options}
        </div>
      )}

      <main className="relative min-h-0 flex-1">{children}</main>

      <footer className="flex h-7 shrink-0 items-center gap-3 border-t border-halo px-3 font-mono text-[11px] text-static">
        {error ? (
          <span style={{ color: "var(--color-status-error)" }}>{error}</span>
        ) : frozen ? (
          <span style={{ color: "var(--color-status-warning)" }}>{frozen}</span>
        ) : (
          status
        )}
      </footer>
    </div>
  );
}

function FrameButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex w-10 items-center justify-center text-static transition-colors hover:bg-halo/60 hover:text-starlight"
    >
      {children}
    </button>
  );
}

/** A labelled option in the frame's options row. */
export function ScopeOption({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] text-static">
      {label}
      {children}
    </label>
  );
}

/** A compact picker over a fixed numeric option set — RHX's own sets, mostly. */
export function NumberPick({
  label,
  value,
  options,
  unit,
  onChange,
}: {
  label: string;
  value: number;
  options: readonly number[];
  unit?: string;
  onChange: (next: number) => void;
}) {
  return (
    <ScopeOption label={label}>
      <Dropdown
        label={label}
        value={String(value)}
        placeholder="—"
        options={options.map((n) => ({ value: String(n), label: unit ? `${n} ${unit}` : String(n) }))}
        onChange={(v) => onChange(Number(v))}
      />
    </ScopeOption>
  );
}

/** The channels this box records, in RHX's order. */
export function ChannelPick({
  channels,
  value,
  onChange,
}: {
  channels: readonly string[];
  value: string | null;
  onChange: (next: string) => void;
}) {
  const sorted = [...channels].sort((a, b) => a.localeCompare(b) || channelNumber(a) - channelNumber(b));
  return (
    <ScopeOption label="Channel">
      <Dropdown
        label="Channel"
        value={value ?? ""}
        placeholder="— channel —"
        options={sorted.map((name) => ({ value: name, label: name }))}
        onChange={onChange}
      />
    </ScopeOption>
  );
}
