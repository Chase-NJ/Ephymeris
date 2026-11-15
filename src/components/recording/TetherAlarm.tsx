import { CircleAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import { useIntanStatus } from "@/lib/intan/context";
import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

const WHAT: Record<"silent" | "noisy", { headline: string; check: string }> = {
  silent: { headline: "every site went silent", check: "Check the tether and headstage." },
  noisy: { headline: "every site turned noisy", check: "Check the ground, connector and tether." },
};

/**
 * One recording box's tether alarm (`RECORDING.md#tether-alarm`), on its
 * Mission Control card. Loud until acknowledged, then a quiet line until the
 * box recovers. Only ever a warning: nothing stops, by the recording's rule.
 */
export function TetherAlarm({ box }: { box: number }) {
  const intan = useIntanStatus();
  const { client } = useSidecar();
  const [error, setError] = useState<string | null>(null);
  const stat = intan.tether.find((t) => t.box === box);
  if (!stat) return null;

  if (stat.state === "learning") {
    return <p className="mt-2 font-mono text-[10px] text-static">tether watch: learning this box's baseline…</p>;
  }
  if (stat.state === "ok") {
    return stat.watchesSilence ? null : (
      <p className="mt-2 font-mono text-[10px] text-static" title="Its baseline is too quiet to tell silence from quiet">
        tether watch: noise only — too quiet to watch for silence
      </p>
    );
  }

  const what = WHAT[stat.state];
  const since = stat.since ? new Date(stat.since).toLocaleTimeString() : null;
  if (stat.acknowledged) {
    return (
      <p className="mt-2 flex items-center gap-1.5 text-[11px]" style={{ color: "var(--color-status-warning)" }}>
        <CircleAlert size={12} strokeWidth={2} />
        Tether: {what.headline}
        {since ? ` since ${since}` : ""} · acknowledged
      </p>
    );
  }
  return (
    <div
      role="alert"
      className="mt-3 flex items-start gap-2.5 rounded-sm border px-3 py-2.5 text-[12px]"
      style={{ borderColor: "var(--color-status-error)", color: "var(--color-status-error)" }}
    >
      <CircleAlert size={14} strokeWidth={2} className="mt-px shrink-0" />
      <div className="flex-1">
        <div className="font-medium">
          Tether: {what.headline}
          {since ? ` at ${since}` : ""}.
        </div>
        <div className="text-static">{what.check} The recording continues; the session log notes when it began.</div>
        {error && <div className="mt-1">{error}</div>}
      </div>
      <Button
        variant="outline"
        onClick={() =>
          void client
            .call(CMD.INTAN_ACKNOWLEDGE_TETHER, { box })
            .then(() => setError(null))
            .catch((err: unknown) => setError(errorMessage(err)))
        }
      >
        Acknowledge
      </Button>
    </div>
  );
}
