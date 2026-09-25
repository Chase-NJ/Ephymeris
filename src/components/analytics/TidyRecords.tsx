import { Combine, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage, tidyRecords } from "@/lib/analytics/commands";
import type { TidyPlan, TidySession } from "@/lib/analytics/types";
import { useSidecar } from "@/lib/ws/context";

/**
 * The preview-and-confirm for `sessions.tidy` (`data.md` §8.8).
 *
 * Opens on a preview the sidecar computed and changed nothing to produce, and
 * acts only on **Tidy**. It says what happens in the terms that matter to an
 * operator worried about data: records merge and records go, and **no data
 * file is touched** — a folder is removed only when it holds nothing.
 *
 * The apply re-plans sidecar-side rather than replaying this preview, so what
 * is done is what is true at that moment; the note that follows reports the
 * applied plan, not this one.
 */
export function TidyRecords({
  open,
  cohortId,
  groupNames,
  onClose,
  onDone,
}: {
  open: boolean;
  cohortId: string;
  /** Group id → name, for the "ran Morning, Afternoon" lines. */
  groupNames: Map<string, string>;
  onClose: () => void;
  onDone: (result: TidyPlan) => void;
}) {
  const { client } = useSidecar();
  const [plan, setPlan] = useState<TidyPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    setPlan(null);
    setError(null);
    void tidyRecords(client, cohortId, false)
      .then((result) => alive && setPlan(result))
      .catch((err) => alive && setError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, [open, client, cohortId]);

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      onDone(await tidyRecords(client, cohortId, true));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const nothing = plan !== null && plan.merges.length === 0 && plan.empty.length === 0;
  const describe = (session: TidySession) => describeSession(session, groupNames);

  return (
    <Modal open={open} onClose={onClose} title="Tidy session records" size="lg">
      <p className="text-[13px] leading-relaxed text-static">
        Records of one session that were split across a day that went wrong are
        merged into one, and records with nothing behind them are removed.{" "}
        <span className="text-starlight">No data file is moved, renamed or deleted.</span>
      </p>

      {error && <p className="mt-3 text-[12px] text-status-error">{error}</p>}
      {!plan && !error && <p className="mt-4 text-[12px] text-static">Looking…</p>}

      {nothing && (
        <p className="mt-4 text-[12px] text-static">
          Nothing to tidy — every record here is one session with data behind it.
        </p>
      )}

      {plan && plan.merges.length > 0 && (
        <section className="mt-4">
          <h3 className="flex items-center gap-1.5 text-[12px] font-medium text-starlight">
            <Combine size={13} strokeWidth={1.75} className="text-pulsar" />
            Merge {plan.merges.length} split session{plural(plan.merges.length)}
          </h3>
          <ul className="mt-2 flex flex-col gap-2">
            {plan.merges.map((merge) => (
              <li
                key={merge.keep.sessionId}
                className="rounded-sm border border-halo px-3 py-2"
              >
                <div className="font-mono text-[12px] text-starlight">
                  {merge.keep.label} · {merge.keep.date}
                  <span className="ml-2 text-static">
                    {merge.absorb.length + 1} records → 1
                  </span>
                </div>
                <ul className="mt-1 flex flex-col gap-0.5 font-mono text-[11px] text-static">
                  <li>keeps · {describe(merge.keep)}</li>
                  {merge.absorb.map((s) => (
                    <li key={s.sessionId}>folds in · {describe(s)}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </section>
      )}

      {plan && plan.empty.length > 0 && (
        <section className="mt-4">
          <h3 className="flex items-center gap-1.5 text-[12px] font-medium text-starlight">
            <Trash2 size={13} strokeWidth={1.75} className="text-static" />
            Remove {plan.empty.length} empty record{plural(plan.empty.length)}
          </h3>
          <ul className="mt-2 flex flex-col gap-0.5 font-mono text-[11px] text-static">
            {plan.empty.map((entry) => (
              <li key={entry.session.sessionId}>
                <span className="text-starlight">{entry.session.label}</span> ·{" "}
                {entry.session.date} · {statusWord(entry.session.status)}
                {entry.removesFolder && " · and its empty folder"}
              </li>
            ))}
          </ul>
        </section>
      )}

      {plan && plan.skipped.length > 0 && (
        <p className="mt-4 text-[11px] leading-relaxed text-static/80">
          Left alone:{" "}
          {plan.skipped
            .map((s) => `${s.session.label} (${s.session.date}) — ${s.reason}`)
            .join("; ")}
          .
        </p>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          {nothing ? "Close" : "Cancel"}
        </Button>
        {!nothing && (
          <Button variant="primary" onClick={() => void apply()} disabled={busy || !plan}>
            {busy ? "Tidying…" : "Tidy"}
          </Button>
        )}
      </div>
    </Modal>
  );
}

function describeSession(session: TidySession, groupNames: Map<string, string>): string {
  const parts = [
    `${session.runCount} run${plural(session.runCount)}`,
    statusWord(session.status),
  ];
  if (session.groupIds.length > 0) {
    parts.push(
      `ran ${session.groupIds.map((id) => groupNames.get(id) ?? "a removed group").join(", ")}`,
    );
  }
  return parts.join(" · ");
}

function statusWord(status: TidySession["status"]): string {
  switch (status) {
    case "configuring":
      return "set-up never started";
    case "running":
      return "ended unexpectedly";
    case "aborted":
      return "discarded";
    default:
      return "ended";
  }
}

function plural(n: number): string {
  return n === 1 ? "" : "s";
}

/** The note the page shows once a tidy has been applied. */
export function describeTidy(result: TidyPlan): string {
  const merged = result.merges.length;
  const removed = result.empty.length;
  if (merged === 0 && removed === 0) return "Nothing to tidy — the records were already clean.";
  const parts: string[] = [];
  if (merged > 0) {
    const folded = result.merges.reduce((n, m) => n + m.absorb.length, 0);
    parts.push(
      `merged ${folded} split record${plural(folded)} into ${merged} session${plural(merged)}`,
    );
  }
  if (removed > 0) parts.push(`removed ${removed} empty record${plural(removed)}`);
  const text = parts.join(" and ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}. No data file was touched.`;
}
