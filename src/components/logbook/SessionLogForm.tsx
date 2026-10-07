import { useEffect, useId, useState } from "react";

import { errorMessage } from "@/lib/analytics/commands";
import type { SessionLog } from "@/lib/logbook/types";

/**
 * Who ran the session and what they made of it (`DATA.md#notes`). Saved when a
 * field loses focus, and only if it changed — there is no Save button to
 * forget at the end of a long day.
 */
export function SessionLogForm({
  log,
  readOnly,
  onSave,
}: {
  log: SessionLog | null;
  readOnly: boolean;
  onSave: (fields: { operator?: string | null; summary?: string | null }) => Promise<void>;
}) {
  const operatorId = useId();
  const summaryId = useId();
  const [operator, setOperator] = useState(log?.operator ?? "");
  const [summary, setSummary] = useState(log?.summary ?? "");
  const [note, setNote] = useState<{ text: string; error: boolean } | null>(null);

  // Follow the sidecar: another window's edit, or a tidy merge, arrives here.
  useEffect(() => setOperator(log?.operator ?? ""), [log?.operator]);
  useEffect(() => setSummary(log?.summary ?? ""), [log?.summary]);

  async function commit(field: "operator" | "summary", value: string) {
    const current = (field === "operator" ? log?.operator : log?.summary) ?? "";
    if (value.trim() === current.trim()) return;
    try {
      await onSave({ [field]: value });
      setNote({ text: "Saved", error: false });
    } catch (err) {
      setNote({ text: errorMessage(err), error: true });
    }
  }

  const field =
    "rounded-sm border border-halo bg-nebula px-3 py-2 text-[13px] text-starlight transition-colors placeholder:text-static/60 hover:border-static/40 focus:border-pulsar focus:outline-none disabled:opacity-60";

  return (
    <div className="grid grid-cols-[200px_1fr] gap-4 px-4 py-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor={operatorId} className="font-mono text-[10px] tracking-[0.14em] text-static uppercase">
          Operator
        </label>
        <input
          id={operatorId}
          type="text"
          value={operator}
          disabled={readOnly}
          placeholder="Who ran it"
          onChange={(e) => setOperator(e.target.value)}
          onBlur={() => void commit("operator", operator)}
          className={field}
        />
        {note && (
          <span
            role={note.error ? "alert" : "status"}
            className={`text-[11px] ${note.error ? "text-status-error" : "text-static"}`}
          >
            {note.text}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={summaryId} className="font-mono text-[10px] tracking-[0.14em] text-static uppercase">
          Summary
        </label>
        <textarea
          id={summaryId}
          value={summary}
          rows={3}
          disabled={readOnly}
          placeholder="How did it go, overall?"
          onChange={(e) => setSummary(e.target.value)}
          onBlur={() => void commit("summary", summary)}
          className={`${field} resize-y leading-relaxed`}
        />
      </div>
    </div>
  );
}
