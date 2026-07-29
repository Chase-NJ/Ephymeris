import { CircleAlert, RefreshCw } from "lucide-react";

import { Button } from "@/components/common/controls";
import { SketchPicker } from "@/components/sessions/TaskConfigForm";
import { baselineColor, baselineLabel } from "@/lib/hardware/utility";
import type { BoxBinding, SketchEntry } from "@/lib/settings/schema";
import type { UtilityStatus } from "@/lib/ws/protocol";

/**
 * The hardware utility sketch and what the baseline is currently doing
 * (`hardware-interaction.md` §8).
 *
 * The restores themselves are silent by design — this panel exists so that
 * "silent" never means "unaccountable". It answers the two questions a silent
 * background flash raises: which sketch is being pushed, and which boxes
 * actually took it.
 */
export function UtilitySketchPanel({
  sketches,
  boxes,
  value,
  status,
  busy,
  connected,
  onChange,
  onReflash,
}: {
  sketches: SketchEntry[];
  boxes: BoxBinding[];
  value: string | null;
  status: UtilityStatus;
  busy: boolean;
  connected: boolean;
  onChange: (path: string | null) => void;
  onReflash: () => void;
}) {
  const bound = boxes.filter((b) => b.hardwareId !== null).map((b) => b.box);
  const rows = status.boxes.filter((b) => bound.includes(b.box));
  const restoring = rows.some((b) => b.state === "restoring");

  return (
    <div className="border-b border-halo px-4 py-3.5">
      <div className="flex items-start justify-between gap-8">
        <div className="min-w-0 pt-0.5">
          <div className="text-[13px] font-medium text-starlight">
            Hardware utility sketch
          </div>
          <p className="mt-0.5 text-[12px] leading-relaxed text-static">
            The sketch every idle box is returned to, so the app can always talk
            to the rig — and can light one box while you place an animal in it.
            Flashed quietly in the background; you only hear about it if it
            fails.
          </p>
        </div>
        <SketchPicker
          label="Hardware utility sketch"
          sketches={sketches}
          value={value}
          onChange={onChange}
          className="w-[240px] shrink-0 truncate"
        />
      </div>

      {/* A configured sketch the sidecar can't use is the one state that must
          not be quiet: nothing would happen, and nothing would say why. */}
      {status.message && (
        <div
          className="mt-3 flex items-start gap-2 rounded-sm border border-halo px-2.5 py-2 text-[11px]"
          style={{ color: "var(--color-status-warning)" }}
        >
          <CircleAlert size={13} strokeWidth={1.75} className="mt-px shrink-0" />
          {status.message}
        </div>
      )}

      {value !== null && !status.message && (
        <div className="mt-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[11px] text-static">
              {status.held
                ? "Paused while a session owns the boxes — the baseline comes back when it ends."
                : status.canIdentify
                  ? "Boxes can be lit individually during animal placement."
                  : "This sketch declares no identify command, so placement will guide by box number only."}
            </p>
            <Button
              disabled={busy || restoring || !connected || status.held}
              onClick={onReflash}
              title={
                status.held
                  ? "A session owns the boxes right now"
                  : "Flash the utility sketch to every idle box again"
              }
            >
              <RefreshCw size={13} strokeWidth={1.75} />
              {restoring ? "Flashing…" : "Reflash boxes"}
            </Button>
          </div>

          {rows.length === 0 ? (
            <p className="mt-2 text-[11px] text-static/70">
              No boxes are bound to a board yet.
            </p>
          ) : (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {rows.map((row) => (
                <span
                  key={row.box}
                  title={row.detail ?? undefined}
                  className="flex items-center gap-1.5 rounded-sm border border-halo px-2 py-1 font-mono text-[11px] text-static"
                >
                  <span
                    className="size-1.5 rounded-xl"
                    style={{ background: baselineColor(row.state) }}
                    aria-hidden
                  />
                  Box {row.box}
                  <span className="text-static/70">{baselineLabel(row.state)}</span>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
