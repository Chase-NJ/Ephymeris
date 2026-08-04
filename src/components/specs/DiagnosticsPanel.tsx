import { CircleAlert, Info, TriangleAlert } from "lucide-react";

import type { SpecDiagnostic } from "@/lib/specs/types";

/**
 * Every diagnostic, unconditionally — the safety net under the inline errors.
 *
 * The inline placements are the fast path; this panel is the guarantee. A
 * diagnostic that reaches nobody is the failure mode the whole placement
 * design exists to avoid, so this list never filters: matched ones are marked
 * "shown above" rather than dropped, and the ones with nowhere better to land
 * (unparseable document, registry problems) appear here first and only here.
 *
 * `help` and `decision` are rendered because the compiler put them there to be
 * read: help says what to do, decision names the design note that says why.
 *
 * A node-placed diagnostic is a link to its state on the canvas. `placement`
 * and `anchor` arrive precomputed from the compiler's own `placement()`, so
 * this is a regex over `S\d+` and never a parse of the location string.
 */
export function DiagnosticsPanel({
  diagnostics,
  onSelectNode,
}: {
  diagnostics: SpecDiagnostic[];
  /** Given, a node-anchored diagnostic becomes a button that selects it. */
  onSelectNode?: (index: number) => void;
}) {
  if (diagnostics.length === 0) return null;

  const ordered = [...diagnostics].sort(
    (a, b) => severityRank(b.severity) - severityRank(a.severity),
  );

  return (
    <section className="flex flex-col gap-1.5">
      <header className="border-b border-halo pb-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-static">
          Diagnostics
        </span>
      </header>
      {ordered.map((d, i) => {
        const node = onSelectNode ? nodeIndex(d) : null;
        return (
        <div
          key={`${d.code}-${i}`}
          className={`flex items-start gap-2 rounded-sm border border-halo px-2.5 py-2 ${
            node !== null ? "cursor-pointer hover:border-static/60" : ""
          }`}
          onClick={node !== null ? () => onSelectNode!(node) : undefined}
        >
          <span className="mt-px shrink-0" style={{ color: color(d.severity) }}>
            {d.severity === "ERROR" ? (
              <CircleAlert size={13} strokeWidth={1.75} />
            ) : d.severity === "WARN" ? (
              <TriangleAlert size={13} strokeWidth={1.75} />
            ) : (
              <Info size={13} strokeWidth={1.75} />
            )}
          </span>
          <div className="min-w-0 flex-1 text-[11px] leading-relaxed">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="font-mono text-[10px] text-static/70">{d.code}</span>
              {d.location && (
                <span className="font-mono text-[10px] text-static/70">{d.location}</span>
              )}
              {d.placement === "node" && node !== null ? (
                <span className="text-[10px] text-pulsar">show on the graph</span>
              ) : (
                d.placement !== "document" && (
                  <span className="text-[10px] text-static/50">shown above</span>
                )
              )}
              {d.decision && (
                <span className="font-mono text-[10px] text-pulsar/80" title="See docs/taskgraph-decisions.md">
                  {d.decision}
                </span>
              )}
            </div>
            <p className="text-starlight">{d.message}</p>
            {d.help && <p className="mt-0.5 text-[10px] text-static">{d.help}</p>}
            {d.detail && (
              <pre className="mt-1 overflow-x-auto font-mono text-[10px] whitespace-pre-wrap text-static/70">
                {d.detail}
              </pre>
            )}
          </div>
        </div>
        );
      })}
    </section>
  );
}

/** `S07` → 7. Null for anything not anchored on a state. */
function nodeIndex(d: SpecDiagnostic): number | null {
  if (d.placement !== "node" || !d.anchor) return null;
  const match = /^S(\d+)$/.exec(d.anchor);
  return match ? Number(match[1]) : null;
}

function severityRank(severity: string): number {
  return severity === "ERROR" ? 2 : severity === "WARN" ? 1 : 0;
}

function color(severity: string): string {
  return severity === "ERROR"
    ? "var(--color-status-error)"
    : severity === "WARN"
      ? "var(--color-status-warning)"
      : "var(--color-static)";
}
