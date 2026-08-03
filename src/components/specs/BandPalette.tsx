import type { ReactNode } from "react";

import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt } from "@/lib/specs/document";
import type {
  SpecCapabilities,
  SpecDocument,
  SpecGraph,
  SpecSchema,
} from "@/lib/specs/types";
import { SpecField } from "./SpecField";

/**
 * The topology editor as an EPOCH-BLOCK PALETTE — four fixed band cards
 * matching the four bands of the emitted graph, each holding the knobs that
 * shape that band and a live readout of what it will produce.
 *
 * Honesty first (the roadmap's own warning): `topology` is six scalars, so
 * "assembling epochs" IS "setting knobs and immediately seeing the generated
 * graph". Pretending otherwise — a free-form node canvas — is exactly the trap
 * D1 exists to forbid: it makes invalid state machines representable and pulls
 * the UI into solving graph validation interactively. The constraint of the
 * epoch model is what makes this tractable; this component keeps it at the UI
 * layer rather than throwing it away.
 *
 * Two gates answer INSTANTLY, before any compile returns, because
 * `capabilities()` is a pure function of the knobs:
 * - the Outcome card's chips ARE `caps.outcomeClasses` — no other source;
 * - flipping a knob re-gates the form's timing rows and outcome cards.
 * The state counts come from the last compiled graph and update one debounce
 * later — knob → shape is instant, shape → exact count is ~150 ms behind.
 */
export function BandPalette({
  doc,
  baseline,
  schema,
  caps,
  graph,
  placed,
  onChange,
}: {
  doc: SpecDocument;
  baseline: SpecDocument;
  schema: SpecSchema;
  caps: SpecCapabilities | null;
  graph: SpecGraph | null;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
}) {
  const field = (key: string) => {
    const meta = schema.overlay.fields[key];
    if (!meta) return null;
    return (
      <SpecField
        key={key}
        path={key}
        overlayKey={key}
        meta={meta}
        value={getAt(doc, key)}
        baseline={getAt(baseline, key)}
        schema={schema}
        doc={doc}
        placed={placed}
        onChange={(next) => onChange(setAt(doc, key, next))}
      />
    );
  };

  const statesIn = (band: number) =>
    graph ? graph.nodes.filter((n) => n.band === band).length : null;

  const commitHold = getAt(doc, "topology.commit_hold") !== false;
  const stages = getAt(doc, "topology.n_sampling_stages");
  const retention = getAt(doc, "topology.retention_delay") === true;
  const mode = getAt(doc, "topology.response_mode");
  const ports = getAt(doc, "topology.response_ports");
  const nStages = typeof stages === "number" ? stages : null;

  return (
    <div className="flex flex-col gap-2">
      {/* Template row: the one action here that re-derives EVERYTHING. The
      version select shows the source hash because a template is versioned by
      file and never edited once pinned — the hash is how a violation of that
      rule would be seen. */}
      <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
        {field("topology.template")}
        {field("topology.template_version")}
      </div>

      <div className="grid grid-cols-1 gap-2 md:grid-cols-4">
        <BandCard
          n={1}
          title="Engagement"
          readout={[
            count(statesIn(1)),
            commitHold ? "commitment hold on" : "no commitment hold",
          ]}
        >
          {field("topology.commit_hold")}
        </BandCard>

        <BandCard
          n={2}
          title="Sampling"
          readout={[
            count(statesIn(2)),
            nStages === 0
              ? "epoch skipped"
              : `${nStages ?? "?"} stage${nStages === 1 ? "" : "s"}` +
                (nStages !== null && nStages > 1 ? ` + ${nStages - 1} gap` : "") +
                (retention ? " + retention" : ""),
          ]}
        >
          {field("topology.n_sampling_stages")}
          {field("topology.retention_delay")}
        </BandCard>

        <BandCard
          n={3}
          title="Response"
          readout={[
            count(statesIn(3)),
            `${mode === "go_nogo" ? "go / no-go" : "n-alternative"} · ${
              Array.isArray(ports) ? ports.length : 0
            } port${Array.isArray(ports) && ports.length === 1 ? "" : "s"}`,
          ]}
        >
          {field("topology.response_mode")}
          {field("topology.response_ports")}
        </BandCard>

        <BandCard
          n={4}
          title="Outcome"
          readout={[
            count(statesIn(4)),
            !commitHold && nStages === 0 ? "no hold exists to break" : null,
          ]}
        >
          {/* No knobs — pure readout. Which outcome classes exist is a
          CONSEQUENCE of the other three cards; that is capabilities()'s whole
          argument for being a function. The chips link nowhere yet: the
          outcome cards they gate are directly below in the form. */}
          <div className="flex flex-wrap gap-1 pt-1">
            {(caps?.outcomeClasses ?? []).map((name) => (
              <span
                key={name}
                className="rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[9px] text-static"
              >
                {name}
              </span>
            ))}
          </div>
        </BandCard>
      </div>
    </div>
  );
}

function count(n: number | null): string | null {
  return n === null ? null : `${n} state${n === 1 ? "" : "s"}`;
}

function BandCard({
  n,
  title,
  readout,
  children,
}: {
  n: number;
  title: string;
  readout: Array<string | null>;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
      <header className="flex items-baseline justify-between border-b border-halo pb-1">
        <span className="font-mono text-[10px] uppercase tracking-wider text-static">
          {n} · {title}
        </span>
        <span className="font-mono text-[9px] text-static/70">
          {readout.filter(Boolean).join(" · ")}
        </span>
      </header>
      {children}
    </div>
  );
}
