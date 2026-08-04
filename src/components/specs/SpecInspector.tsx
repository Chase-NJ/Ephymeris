import { MousePointerSquareDashed } from "lucide-react";

import { RowDensityContext } from "@/components/common/rowDensity";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import { getAt, setAt } from "@/lib/specs/document";
import {
  BAND_TITLES,
  orphanKnobs,
  selectionView,
  type Anchor,
  type Selection,
} from "@/lib/specs/selection";
import type {
  SpecCapabilities,
  SpecDocument,
  SpecGraph,
  SpecSchema,
} from "@/lib/specs/types";
import { SpecField } from "./SpecField";
import { StructureBlocks } from "./StructureBlocks";

/**
 * The fields that produced whatever is selected on the canvas.
 *
 * This is where the topology knobs live now. They used to sit in a row of four
 * band cards stacked above the graph, restating in text what the graph's own
 * columns said in shape; here they are one click away from the lane they
 * govern, which is the relationship they always had. The rule from
 * `docs/specs.md` §5 is unchanged and is what stops this becoming a second
 * editor: THE PALETTE OWNS THE TOPOLOGY KNOBS OUTRIGHT — the form has no
 * topology section, so no field is editable in two places.
 *
 * A group with no fields is not rendered as an empty heading. Some nodes are
 * genuinely produced by nothing editable — a zero-duration marker exists
 * because the template pairs strobes at one instant (D2) and no spec edit
 * moves it — and saying so plainly beats an accordion that opens onto nothing.
 */
export function SpecInspector({
  selection,
  graph,
  doc,
  baseline,
  schema,
  caps,
  placed,
  onChange,
  onHoverPath,
}: {
  selection: Selection;
  graph: SpecGraph | null;
  doc: SpecDocument;
  baseline: SpecDocument;
  schema: SpecSchema;
  caps: SpecCapabilities | null;
  placed: PlacedDiagnostics | null;
  onChange: (next: SpecDocument) => void;
  /** Hovering a field lights the states it governs — the inverse link. */
  onHoverPath: (path: string | null) => void;
}) {
  const view = selectionView(selection, graph, doc);

  const field = (anchor: Anchor) => {
    const meta = schema.overlay.fields[anchor.overlayKey];
    if (!meta) return null;
    return (
      <div
        key={anchor.path}
        onPointerEnter={() => onHoverPath(anchor.path)}
        onPointerLeave={() => onHoverPath(null)}
      >
        <SpecField
          path={anchor.path}
          overlayKey={anchor.overlayKey}
          meta={meta}
          value={getAt(doc, anchor.path)}
          baseline={getAt(baseline, anchor.path)}
          schema={schema}
          doc={doc}
          placed={placed}
          onChange={(next) => onChange(setAt(doc, anchor.path, next))}
        />
      </div>
    );
  };

  if (!view) {
    return (
      <aside className="flex h-full flex-col gap-2 border-l border-halo px-3 py-3">
        <Header title="Inspector" subtitle={null} />
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-2 text-center">
          <MousePointerSquareDashed size={20} strokeWidth={1.5} className="text-static/50" />
          <p className="text-[11px] leading-relaxed text-static">
            Select a state, a transition, or an epoch lane to see the fields that
            produced it.
          </p>
          <p className="text-[10px] leading-relaxed text-static/60">
            The graph is compiled, not drawn — it changes when the spec does, not
            the other way round.
          </p>
        </div>
      </aside>
    );
  }

  const band = bandOf(selection, graph);

  return (
    <RowDensityContext.Provider value="stacked">
      <aside className="scrollbar-none flex h-full flex-col gap-3 overflow-y-auto border-l border-halo px-3 py-3">
        <Header title={view.title} subtitle={view.subtitle} />

        {view.knobs.length > 0 && (
          <Group
            title={`${BAND_TITLES[band ?? 0] ?? "Epoch"} shape`}
            why="These knobs decide which states exist at all. Changing one re-derives the graph."
          >
            {view.knobs.map((key) => field({ path: key, overlayKey: key }))}
          </Group>
        )}

        {/* The structural blocks for this epoch. They live here, beside the
        knobs they compound, because two editing surfaces for one field
        eventually disagree — docs/specs.md §5. */}
        {selection?.kind === "band" && (
          <StructureBlocks
            band={selection.band}
            doc={doc}
            baseline={baseline}
            caps={caps}
            schema={schema}
            placed={placed}
            onChange={onChange}
          />
        )}

        {/* A knob this build's BAND_KNOBS doesn't place, but the compiler
        reports. Better beside the wrong lane than nowhere at all. */}
        {selection?.kind === "band" &&
          selection.band === 4 &&
          orphanKnobs(caps?.knobs ?? []).length > 0 && (
            <Group
              title="Other knobs"
              why="This template version declares these; this build has no lane for them."
            >
              {orphanKnobs(caps?.knobs ?? []).map((knob) =>
                field({ path: `topology.${knob}`, overlayKey: `topology.${knob}` }),
              )}
            </Group>
          )}

        {/* Which outcome classes exist is a CONSEQUENCE of the knobs above, never
        a thing to set — that is capabilities()'s whole argument for being a
        function. Shown as a readout on the lane that produces them. */}
        {selection?.kind === "band" && selection.band === 4 && (
          <Group
            title="Produced outcomes"
            why="Not editable here: which classes exist follows from the other three lanes."
          >
            <div className="flex flex-wrap gap-1 pt-0.5">
              {caps === null ? (
                // An empty bordered box reads as "this task produces nothing",
                // which is a different claim from "the compiler hasn't said yet".
                <span className="font-mono text-[9px] text-static/60">
                  waiting for the compiler…
                </span>
              ) : (
                caps.outcomeClasses.map((name) => (
                  <span
                    key={name}
                    className="rounded-sm border border-halo px-1.5 py-0.5 font-mono text-[9px] text-static"
                  >
                    {name}
                  </span>
                ))
              )}
            </div>
          </Group>
        )}

        {view.groups.map((group) => (
          <Group key={group.title} title={group.title} why={group.why}>
            {group.anchors.map(field)}
          </Group>
        ))}

        {view.groups.length === 0 && view.knobs.length === 0 && selection?.kind !== "band" && (
          <p className="px-1 text-[11px] leading-relaxed text-static/70">
            Nothing in the spec sets this directly — the template emits it from the
            epoch shape. Select its lane to change that.
          </p>
        )}
      </aside>
    </RowDensityContext.Provider>
  );
}

function bandOf(selection: Selection, graph: SpecGraph | null): number | null {
  if (selection?.kind === "band") return selection.band;
  if (selection?.kind === "node") return graph?.nodes[selection.index]?.band ?? null;
  return null;
}

function Header({ title, subtitle }: { title: string; subtitle: string | null }) {
  return (
    <header className="border-b border-halo pb-1.5">
      <div className="font-mono text-[11px] text-starlight">{title}</div>
      {subtitle && (
        <div className="font-mono text-[9.5px] tracking-wide text-static/70 uppercase">
          {subtitle}
        </div>
      )}
    </header>
  );
}

function Group({
  title,
  why,
  children,
}: {
  title: string;
  why?: string | undefined;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-1.5 rounded-sm border border-halo px-2.5 py-2">
      <div className="border-b border-halo pb-1">
        <div className="font-mono text-[10px] tracking-wider text-static uppercase">
          {title}
        </div>
        {why && (
          <p className="mt-0.5 text-[10px] leading-relaxed text-static/70">{why}</p>
        )}
      </div>
      {children}
    </section>
  );
}
