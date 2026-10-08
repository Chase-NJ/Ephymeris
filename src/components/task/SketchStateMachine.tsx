import { animate, motion, useMotionValue } from "framer-motion";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { DrawOn } from "@/components/charts/DrawOn";

import { NODE_PRIMARY } from "@/components/chrome/constellationStyle";
import { OUTCOME_STYLE, colorForIndex } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";
import type { TaskProfile } from "@/lib/sessions/types";
import { GENERATION_TAB, HOLDS_TAB, happyPath, tabOf } from "@/lib/tasks/topology";
import type {
  Condition,
  LiveCondition,
  TaskEdge,
  TaskGraphModel,
  TaskNode,
} from "@/lib/tasks/topology";
import {
  CHIP_ABOVE_DY,
  CHIP_GAP,
  CHIP_RIGHT_DY,
  EDITOR_MIN_W,
  LABEL_ABOVE_DY,
  LABEL_BELOW_DY,
  LABEL_RIGHT_DY,
  LIVE_GEOMETRY,
  R,
  TICK_ACTIVE_H,
  TICK_H,
  TICK_BLOCK,
  TICK_MAX,
  TICK_PITCH,
  TICK_W,
  VIEWER_GEOMETRY,
  frameFor,
  layoutWidthFor,
  spinePath,
  type Frame,
} from "@/lib/tasks/graphLayout";
import { useGlidingWidth } from "@/lib/tasks/useGlidingWidth";
import { useElementWidth } from "@/lib/useElementWidth";

/**
 * The sketch's state machine, as the page's centrepiece tile.
 *
 * The same drawing serves Mission Control's live panel as `LiveStateMachine`
 * below — one style for the machine everywhere it appears. The nodes and edges
 * come verbatim from `taskGraph()`, the derived-never-declared machine
 * (`TASKS.md#derived-state-machine`); the drawing is built around the mapping
 * between the trial and the parameters that govern it.
 *
 * **Every tunable group is pinned to the state it governs.** Each node carries
 * subtle mono chips naming the parameter groups that tune it (`governedBy`,
 * condensed: the six ramp groups collapse to one `holds` chip — six chips
 * saying "stage n" on every node was noise pretending to be information).
 * Chips are the map legend and the navigation: hovering one lights its group's
 * whole territory, clicking one jumps to the group's tile below.
 *
 * **The highlight dims the world instead of decorating the target.** Hovering
 * a parameter tile (or chip) drops everything the group does not govern to
 * near-invisible and rings what it does; hovering a state does the reverse —
 * the page lights the tiles that tune it — and the caption strip at the foot
 * says the relationship in words. One relationship, readable from either end,
 * stated three ways (geometry, colour, sentence).
 *
 * Outcome colours come from `fillFor`, the same mapping `OutcomeMix` and the
 * live panel use — "rewarded" is one colour everywhere in this app.
 *
 * **Drawn in CSS pixels, not a scaled viewBox.** The first version scaled a
 * fixed frame to the column's width, which made every window resize a
 * font-size change — the machine ballooned and shrank with the window. Here
 * type, node radii and strokes are constant, and the measured width goes into
 * the *layout*: columns spread to fill what the tile has, clamped to a band
 * (see the geometry section) so labels never collide at the narrow end and
 * edges never sprawl at the wide one. The width moves in steps and glides
 * between them (`useGlidingWidth`), so a resize slides the states to their new
 * places together; it never changes what a label reads like.
 */

/** Node fill by kind, with outcomes borrowing the analytics palette so the
 *  machine and `OutcomeMix` never disagree about what "rewarded" looks like. */
export function fillFor(node: TaskNode): string {
  if (node.kind === "abort") return "var(--color-halo)";
  if (node.kind !== "outcome") return NODE_PRIMARY;
  switch (node.id) {
    case "reward":
    case "withheld":
      return OUTCOME_STYLE.rewarded.fill;
    case "hold-fail":
      return OUTCOME_STYLE.holdFailed.fill;
    case "wrong-well":
      return OUTCOME_STYLE.wrongWell.fill;
    default:
      return OUTCOME_STYLE.noResponse.fill;
  }
}

export function SketchStateMachine({
  model,
  profile,
  hoverGroup,
  onHoverGroup,
  onHoverNode,
  onNodeClick,
  onSelectGroup,
  hoverCondition: hoverConditionProp,
  onHoverCondition,
  conditionRail = true,
}: {
  model: TaskGraphModel;
  profile: TaskProfile | null;
  /** The group under the pointer — a parameter tile's or a chip's. */
  hoverGroup: string | null;
  onHoverGroup: (group: string | null) => void;
  /** Reports the hovered state so the page can light its tiles. */
  onHoverNode: (node: TaskNode | null) => void;
  /** A state click selects the first group that tunes it. */
  onNodeClick: (node: TaskNode) => void;
  /** A chip click selects exactly the group it names. */
  onSelectGroup: (group: string) => void;
  /**
   * The condition under the pointer, when the PAGE owns it — the task editor's
   * trial rows and composition strip light a tick this way. Uncontrolled (the
   * drawing's own condition rail) when omitted.
   */
  hoverCondition?: string | null;
  onHoverCondition?: (id: string | null) => void;
  /**
   * The condition list under the drawing. The editor turns it off: its trial
   * rows are the accessible, keyboard-reachable condition list there.
   */
  conditionRail?: boolean;
}) {
  const [hoverNode, setHoverNode] = useState<TaskNode | null>(null);
  /**
   * The rail row under the pointer (or keyboard focus).
   *
   * Deliberately NOT folded into `litNodes`. The drawing's grammar is *dim the
   * world, ring the target*, and a second thing that dims would leave two
   * highlights arguing over one picture. A condition hover lights its tick and
   * takes the caption strip; it never touches the geometry. Precedence, when
   * more than one is live: group > node > condition.
   */
  const [ownHoverCondition, setOwnHoverCondition] = useState<string | null>(null);
  const hoverCondition = hoverConditionProp !== undefined ? hoverConditionProp : ownHoverCondition;
  const setHoverCondition = (id: string | null) => {
    setOwnHoverCondition(id);
    onHoverCondition?.(id);
  };
  const reduceMotion = useReduceMotion();
  /** The first frame draws itself on; later redraws do not. */
  const drawn = useRef(false);
  useEffect(() => {
    drawn.current = true;
  }, []);

  /** Groups this profile actually declares — a chip must never name a tile
   *  that doesn't exist below. */
  const declared = useMemo(() => {
    const out = new Set<string>();
    for (const field of profile?.config ?? []) {
      if (field.group) out.add(field.group);
    }
    return out;
  }, [profile]);

  const chipsByNode = useMemo(() => {
    const out = new Map<string, Chip[]>();
    for (const node of model.nodes) out.set(node.id, chipsFor(node, declared));
    return out;
  }, [model, declared]);

  /** The one hover, whichever end it came from.
   *
   *  `hoverGroup` is a rail TAB, not a declared group — the rail folds a few
   *  groups into one pill (`topology.tabOf`) and both ends of this link have to
   *  agree about which. Comparing it raw lit nothing for a folded pill. */
  const litNodes = useMemo(() => {
    if (hoverGroup) {
      return new Set(
        model.nodes
          .filter((n) => n.governedBy.some((g) => tabOf(g) === hoverGroup))
          .map((n) => n.id),
      );
    }
    if (hoverNode) return new Set([hoverNode.id]);
    return null; // rest — nothing dimmed
  }, [model, hoverGroup, hoverNode]);

  const [host, hostWidth] = useElementWidth<HTMLDivElement>();
  const layoutWidth = useGlidingWidth(layoutWidthFor(hostWidth, EDITOR_MIN_W), hostWidth !== null);
  const frame = useMemo(
    // The chip count is the whole reason the band can be derived — see
    // `measureNode`.
    () =>
      frameFor(model, layoutWidth, VIEWER_GEOMETRY, (node) =>
        (chipsByNode.get(node.id) ?? []).length,
      ),
    [model, layoutWidth, chipsByNode],
  );

  const hoveredCondition = useMemo(
    () => model.conditions.find((c) => c.id === hoverCondition) ?? null,
    [model, hoverCondition],
  );

  function enterNode(node: TaskNode) {
    setHoverNode(node);
    onHoverNode(node);
  }
  function leaveNode() {
    setHoverNode(null);
    onHoverNode(null);
  }

  return (
    <div ref={host}>
      {/* Always 1:1 — the drawing is never scaled. Inside the band its layout
          width follows the host in `WIDTH_STEP`s, gliding between them; wider
          than MAX_W it stops growing and centres. The page keeps the host at
          least EDITOR_MIN_W wide (`editorLayout`); on a host that somehow is
          not, the drawing scrolls sideways rather than shrinking its type. */}
      <div className="scrollbar-slim overflow-x-auto">
      <svg
        viewBox={`0 0 ${frame.width} ${frame.height}`}
        className="mx-auto block"
        style={{ width: frame.width, height: frame.height, maxWidth: "none" }}
        role="img"
        aria-label="The task's state machine, derived from its strobe vocabulary"
      >
        {/* Edges first, under the nodes — drawn on left to right with the
            trial on first sight, as a clip wipe (never `pathLength`, which
            breaks under non-scaling strokes; `DrawOn`). */}
        <DrawOn viewBox={[0, 0, frame.width, frame.height]} duration={drawn.current ? 0 : 0.9}>
          {distinctEdges(model, frame).map((edge) => (
            <EdgePath
              key={edge.id}
              edge={edge}
              model={model}
              lit={litNodes}
              frame={frame}
            />
          ))}
        </DrawOn>
        {model.usable && !reduceMotion && litNodes === null && hoverCondition === null && (
          <TransitToken d={spinePath(happyPath(model), frame)} />
        )}
        {model.nodes.map((node) => (
          <motion.g
            key={node.id}
            // Each state arrives as the wipe reaches it, on first sight only.
            initial={drawn.current ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: (frame.x(node) / frame.width) * 0.9, duration: 0.3 }}
          >
          <NodeGlyph
            key={node.id}
            node={node}
            chips={chipsByNode.get(node.id) ?? []}
            lit={litNodes === null ? null : litNodes.has(node.id)}
            hoverGroup={hoverGroup}
            frame={frame}
            activeCondition={hoverCondition}
            onEnter={() => enterNode(node)}
            onLeave={leaveNode}
            onClick={() => onNodeClick(node)}
            // A chip keeps its own short caption — it names the parameter
            // family, which the fold does not change. What it SELECTS is the
            // pill that family now lives under.
            onChipEnter={(group) => onHoverGroup(tabOf(group))}
            onChipLeave={() => onHoverGroup(null)}
            onChipClick={(group) => onSelectGroup(tabOf(group))}
          />
          </motion.g>
        ))}
      </svg>
      </div>

      {/* The caption strip: the hovered relationship, in words. A fixed slot
          rather than a tooltip so the eye learns one place to read and the
          diagram never reflows under the pointer. */}
      <p className="mt-1.5 truncate border-t border-halo/60 pt-1.5 font-mono text-[11px] leading-snug text-static">
        {/* Group first, node second: on a chip both hovers are live and the
            highlight is already showing the group's territory — the sentence
            has to describe the same thing the geometry does. */}
        {hoverGroup ? (
          <>
            <span className="text-starlight">{hoverGroup}</span> tunes{" "}
            {model.nodes
              .filter((n) => n.governedBy.some((g) => tabOf(g) === hoverGroup))
              .map((n) => n.label)
              .join(" · ") || "nothing on this task"}
          </>
        ) : hoverNode ? (
          <>
            <span className="text-starlight">{hoverNode.label}</span>
            {hoverNode.detail && <> — {hoverNode.detail}</>}
            {tunedByLine(hoverNode, declared)}
          </>
        ) : hoveredCondition ? (
          <>
            <span className="text-starlight">{hoveredCondition.label}</span>
            {hoveredCondition.metricLabel ? (
              <> — {hoveredCondition.metricLabel}</>
            ) : (
              <> — trials opened by {hoveredCondition.strobeName}</>
            )}
          </>
        ) : (
          <span className="text-static/60">
            Hover a state or a parameter group — each lights the other; click to jump.
          </span>
        )}
      </p>

      {/* The conditions, as real HTML.
          Not inside the SVG, and not optional: both drawings are `role="img"`,
          so every glyph, tick and chip in them is invisible to assistive tech
          and unreachable by keyboard. This list is the only readable form the
          condition set has, and the only way into the drawing without a mouse.
          It sits BELOW the caption strip — the strip is glued to the drawing
          and is where a rail hover writes, so putting the rail between them
          would separate the two halves of one gesture. */}
      {conditionRail && model.conditions.length > 1 && (
        <ConditionRail
          conditions={model.conditions}
          active={hoverCondition}
          onHover={setHoverCondition}
        />
      )}
    </div>
  );
}

/**
 * One row per condition — the identity the collapsed node no longer spends a
 * row of the diagram on.
 *
 * Mission Control's form of the list; the task editor turns it off, because
 * its trial rows are the condition list there. It does NOT print the
 * contingency: the trial rows already say *"sandalwood → right well · paid from
 * fluid_2"* in the rig's own words, and the metric label printed here contains
 * the well besides.
 */
function ConditionRail({
  conditions,
  active,
  onHover,
}: {
  conditions: readonly Condition[];
  active: string | null;
  onHover: (id: string | null) => void;
}) {
  return (
    <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
      {conditions.map((condition) => (
        <li key={condition.id}>
          <button
            type="button"
            className="flex items-baseline gap-1.5 rounded-sm px-1 py-0.5 text-left font-mono text-[10px] transition-colors hover:text-starlight focus:outline-none focus-visible:ring-1 focus-visible:ring-pulsar"
            style={{ color: active === condition.id ? "var(--color-starlight)" : undefined }}
            onPointerEnter={() => onHover(condition.id)}
            onPointerLeave={() => onHover(null)}
            // Focus mirrors hover exactly, so the keyboard path is the same
            // path — not a second, lesser one.
            onFocus={() => onHover(condition.id)}
            onBlur={() => onHover(null)}
          >
            <span className="tabular-nums text-static/50">{condition.index}</span>
            <span className={active === condition.id ? "text-starlight" : "text-static"}>
              {condition.label}
            </span>
            {condition.metricLabel && (
              <span className="text-static/60">· {condition.metricLabel}</span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

/**
 * The same machine, live — Mission Control's panel
 * (`ARCHITECTURE.md#live-session-views`).
 *
 * One drawing, two homes: this is `SketchStateMachine`'s geometry, glyphs and
 * palette with the parameter apparatus stripped away and a token added — the
 * running box's own state, decoded from its strobes (`useLiveNode`), wearing
 * the pulsing flat ring the session journey's current step wears. No chips
 * (mid-session is not the moment to tune parameters, and the vertical room
 * they needed belongs to the charts below — see `LIVE_GEOMETRY`), and the
 * caption strip reads the live state instead of a hover legend; hovering a
 * state still describes it, exactly as the viewer does.
 *
 * Counts are deliberately absent. The recorded figures come from derive.py
 * over a finished run; showing a half-session's partial tallies beside a
 * moving token would invite reading them as the run's result (`topology.ts`).
 */
export function LiveStateMachine({
  model,
  liveNode,
  liveCondition = null,
  observedConditions = null,
}: {
  model: TaskGraphModel;
  /** Node the token sits on — null before the first strobe of a trial. */
  liveNode: string | null;
  /**
   * Which condition this trial is presenting (`liveConditionId`). Three states,
   * kept apart on purpose — see that function.
   */
  liveCondition?: LiveCondition;
  /** Conditions seen at least once this session; their ticks fill in. */
  observedConditions?: ReadonlySet<string> | null;
}) {
  const reduceMotion = useReduceMotion();
  const [hoverNode, setHoverNode] = useState<TaskNode | null>(null);

  const litNodes = useMemo(
    () => (hoverNode ? new Set([hoverNode.id]) : null),
    [hoverNode],
  );

  const [host, hostWidth] = useElementWidth<HTMLDivElement>();
  const layoutWidth = useGlidingWidth(layoutWidthFor(hostWidth), hostWidth !== null);
  // No chip argument: this panel draws none, and the band is derived against
  // that fact rather than against the viewer's.
  const frame = useMemo(
    () => frameFor(model, layoutWidth, LIVE_GEOMETRY),
    [model, layoutWidth],
  );

  const current =
    liveNode === null ? null : (model.nodes.find((n) => n.id === liveNode) ?? null);

  const condition =
    liveCondition?.kind === "condition"
      ? (model.conditions.find((c) => c.id === liveCondition.id) ?? null)
      : null;

  return (
    <div ref={host}>
      {/* Like the viewer, but with the original floor regime: on a panel
          narrower than MIN_W the MIN_W layout shrinks uniformly via maxWidth
          — Mission Control's rail is narrow, and there a smaller correct
          drawing beats a sideways scroll. */}
      <svg
        viewBox={`0 0 ${frame.width} ${frame.height}`}
        className="mx-auto block"
        style={{ width: frame.width, maxWidth: "100%" }}
        role="img"
        aria-label="The task's state machine, with the box's current state lit"
      >
        {distinctEdges(model, frame).map((edge) => (
          <EdgePath
            key={edge.id}
            edge={edge}
            model={model}
            lit={litNodes}
            frame={frame}
          />
        ))}
        {model.nodes.map((node) => (
          <NodeGlyph
            key={node.id}
            node={node}
            chips={[]}
            lit={litNodes === null ? null : litNodes.has(node.id)}
            hoverGroup={null}
            frame={frame}
            activeCondition={condition?.id ?? null}
            activeLabel={condition ? condition.label : null}
            observedConditions={observedConditions}
            live={liveNode === node.id}
            reduceMotion={reduceMotion}
            onEnter={() => setHoverNode(node)}
            onLeave={() => setHoverNode(null)}
            onChipEnter={() => {}}
            onChipLeave={() => {}}
            onChipClick={() => {}}
          />
        ))}
      </svg>

      {/* The caption strip, repurposed as the live readout: the state the box
          is in, said in words under the drawing that shows it. A hover
          overrides it — the operator asking about a state outranks the
          narration — and it returns the moment the pointer leaves. */}
      <p className="mt-1.5 truncate border-t border-halo/60 pt-1.5 font-mono text-[11px] leading-snug text-static">
        {hoverNode ? (
          <>
            <span className="text-starlight">{hoverNode.label}</span>
            {hoverNode.detail && <> — {hoverNode.detail}</>}
          </>
        ) : liveCondition?.kind === "unlisted" ? (
          /* The fourth state, and the reason it is drawn apart from "nothing
             yet": the box announced an odor this profile does not declare —
             almost always the `liveMetrics` gate having silently dropped a
             trial type. Collapsing the fan turned that from a missing NODE
             into a nameless presence, so it has to be said in words or it is
             said nowhere. */
          <>
            <span style={{ color: "var(--color-status-warning)" }}>
              ⚠ {liveCondition.strobeName.replace(/_/g, " ").toLowerCase()}
            </span>{" "}
            — this box is presenting a condition the task profile doesn&apos;t
            declare, so nothing here can score it.
          </>
        ) : current ? (
          <>
            {/* The contingency, which Mission Control has NO other source for:
                there is no trial table on this screen. Derived from the
                metric's success code and omitted whenever that cannot prove
                one — a well printed on a guess would be the only false claim
                in the drawing.

                Which of the two forms depends on where the token is. On the
                odor node the condition IS the state, so it replaces the
                generic label; anywhere else in the trial it is context the
                operator still wants — "this is the answer window, and it's an
                Odor 3 trial" — so it trails the state instead. */}
            {condition && current.multiplicity ? (
              <span className="text-starlight">
                ● {condition.label}
                {answerPhrase(condition)}
              </span>
            ) : (
              <>
                <span className="text-starlight">● {current.label}</span>
                {condition && (
                  <span className="text-static">
                    {" · "}
                    {condition.label}
                    {answerPhrase(condition)}
                  </span>
                )}
              </>
            )}
            {current.detail && <> — {current.detail}</>}
          </>
        ) : (
          <span className="text-static/60">
            The lit state is where this box is in the trial — the token moves
            as strobes arrive.
          </span>
        )}
      </p>
    </div>
  );
}

/**
 * " → right well" / " → withholds", or nothing at all.
 *
 * Absence is a real answer here and the default one. `correctWellOf` returns
 * null whenever the profile cannot prove the answer, and this must not paper
 * over that with a guess: it is the only figure the drawing ADDS, so it is the
 * only one that can be false — silently, in a screenshot that outlives the
 * session that made it.
 */
function answerPhrase(condition: Condition): string {
  const answer = condition.correctAnswer;
  if (!answer) return "";
  if (answer.kind === "withhold") return " → withholds";
  if (answer.kind === "port") return ` → port ${answer.slot}`;
  return ` → ${answer.side} well`;
}

// --- the parameter chips ----------------------------------------------------

interface Chip {
  /** What the label says — short, mono, lower-case. */
  short: string;
  /** The declared group a hover/click resolves to. */
  group: string;
  /** Every declared group the chip stands for — lights when any is hovered. */
  covers: string[];
}

/**
 * Groups that travel together share one chip: the ramp's six as `holds`, and
 * the three selection-policy groups as `selection` — each opens one home in
 * the editor (`topology.tabOf`), so one chip per home. Everything else maps one
 * group to one short word.
 */
const FOLDED: Record<string, string> = { [HOLDS_TAB]: "holds", [GENERATION_TAB]: "selection" };
const SHORT: Record<string, string> = {
  Session: "session",
  "Trial timing": "timing",
  "Abstention penalty": "penalty",
  "Reward volume": "volume",
};

function chipsFor(node: TaskNode, declared: Set<string>): Chip[] {
  const chips: Chip[] = [];
  const byHome = new Map<string, Chip>();
  for (const group of node.governedBy.filter((g) => declared.has(g))) {
    const home = tabOf(group);
    const folded = FOLDED[home];
    if (folded) {
      const existing = byHome.get(home);
      if (existing) {
        existing.covers.push(group);
        continue;
      }
      const chip = { short: folded, group, covers: [group] };
      byHome.set(home, chip);
      chips.push(chip);
      continue;
    }
    chips.push({ short: SHORT[group] ?? group.toLowerCase(), group, covers: [group] });
  }
  return chips;
}

function tunedByLine(node: TaskNode, declared: Set<string>): ReactNode {
  const chips = chipsFor(node, declared);
  if (chips.length === 0) return null;
  return (
    <span className="text-static/70">
      {" "}
      · tuned by {chips.map((c) => c.short).join(", ")}
    </span>
  );
}

/**
 * One tick per declared condition, the active one taller and lit.
 *
 * `aria-hidden`, and honestly so: both SVGs are `role="img"`, which removes
 * every descendant from the accessibility tree. Pretending otherwise by hanging
 * ARIA on shapes inside would be worse than admitting it — the readable path is
 * the condition rail below the drawing, which is real HTML.
 */
function ConditionTicks({
  conditions,
  x,
  y,
  activeId,
  observed,
  litAll,
}: {
  conditions: readonly Condition[];
  x: number;
  y: number;
  activeId: string | null;
  observed: ReadonlySet<string> | null;
  /** The whole node is hovered — every tick lights, which is the disclosure the
   *  fan-out popover would have given, in place and at no extra layer. */
  litAll: boolean;
}) {
  const shown = conditions.slice(0, TICK_MAX);
  const overflow = conditions.length - shown.length;
  const span = shown.length * TICK_PITCH - (TICK_PITCH - TICK_W);
  const x0 = x - span / 2;
  return (
    <g aria-hidden>
      {shown.map((condition, index) => {
        const active = condition.id === activeId;
        const seen = observed === null || observed.has(condition.id);
        const height = active ? TICK_ACTIVE_H : TICK_H;
        // The condition's own colour — the same series slot its trial-table
        // row, its glyph node and its Analytics curve wear. A tick is the one
        // place the machine names a condition, so it names it in the colour
        // everything else already uses for it.
        const colour = colorForIndex(condition.index - 1);
        return (
          <rect
            key={condition.id}
            x={x0 + index * TICK_PITCH}
            y={y + (TICK_ACTIVE_H - height) / 2}
            width={TICK_W}
            height={height}
            rx={0.5}
            fill={seen ? colour : "none"}
            stroke={seen ? "none" : colour}
            strokeWidth={seen ? 0 : 0.7}
            opacity={active ? 1 : litAll ? 0.85 : seen ? 0.6 : 0.55}
            style={{ transition: "opacity 160ms" }}
          />
        );
      })}
      {overflow > 0 && (
        <text
          x={x0 + shown.length * TICK_PITCH + 2}
          y={y + TICK_ACTIVE_H}
          fontSize={9}
          className="fill-static"
          opacity={0.6}
        >
          ⋯
        </text>
      )}
    </g>
  );
}

// --- edges ------------------------------------------------------------------

/**
 * Edges that will draw a distinct path.
 *
 * On the congruence fallback the N `poke → arm` edges are N distinct paths, but
 * the moment anything collapses two nodes onto one point they become N copies
 * of one path — and at `base = 0.55` a stack of them composites to the
 * brightest stroke in the drawing, which reads as emphasis on the one edge that
 * has none. Keyed on the geometry rather than on the ids, because identical
 * geometry is exactly the condition that matters.
 */
function distinctEdges(model: TaskGraphModel, frame: Frame): TaskEdge[] {
  const seen = new Set<string>();
  return model.edges.filter((edge) => {
    const key = `${edge.kind}|${edge.label ?? ""}|${pathFor(edge, model, frame)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Return edges arc under everything; the rest are lateral beziers. */
function pathFor(edge: TaskEdge, model: TaskGraphModel, frame: Frame): string {
  const from = model.nodes.find((n) => n.id === edge.from);
  const to = model.nodes.find((n) => n.id === edge.to);
  if (!from || !to) return "";
  const x1 = frame.x(from);
  const y1 = frame.y(from);
  const x2 = frame.x(to);
  const y2 = frame.y(to);

  if (edge.kind === "return") {
    // Sweep beneath the whole machine, back to the start — the two returns
    // nest at different depths instead of overlapping. Both stay inside the
    // frame because `frameFor` pads by the return depth.
    const depth =
      frame.lowY + (edge.from === "iti" ? frame.returnDepth : frame.returnDepth - 16);
    return `M ${x1} ${y1 + R} C ${x1} ${depth}, ${x2} ${depth}, ${x2} ${y2 + R}`;
  }

  const dx = Math.max((x2 - x1) / 2, 20);
  return `M ${x1 + R} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2 - R} ${y2}`;
}

/** One set of tints for every drawing of the machine, so they — and
 *  `OutcomeMix` — agree about what an outcome looks like. */
function edgeStroke(edge: TaskEdge): string {
  switch (edge.kind) {
    case "reward":
      return OUTCOME_STYLE.rewarded.fill;
    case "error":
      return OUTCOME_STYLE.wrongWell.fill;
    case "abort":
    case "return":
      return "var(--color-halo)";
    default:
      return "var(--color-static)";
  }
}

/**
 * Where an edge's label sits. A level edge labels its midpoint, just above the
 * line. A diagonal one labels partway down the run, below the path — the raw
 * midpoint of a steep edge lands on the source node's own chip stack, which is
 * exactly where a label about *leaving* that node shouldn't sit.
 */
function labelPos(x1: number, y1: number, x2: number, y2: number) {
  if (Math.abs(y2 - y1) < 14) {
    return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 7 };
  }
  return { x: x1 + (x2 - x1) * 0.6, y: y1 + (y2 - y1) * 0.68 + 12 };
}

function EdgePath({
  edge,
  model,
  lit,
  frame,
}: {
  edge: TaskEdge;
  model: TaskGraphModel;
  lit: Set<string> | null;
  frame: Frame;
}) {
  const d = pathFor(edge, model, frame);
  // An edge is part of the lit territory only when both of its ends are — a
  // half-lit edge points out of the highlight and reads as leakage.
  const on = lit === null ? null : lit.has(edge.from) && lit.has(edge.to);
  const base = edge.kind === "return" ? 0.35 : 0.55;
  const opacity = on === null ? base : on ? 0.95 : 0.1;

  const from = model.nodes.find((n) => n.id === edge.from);
  const to = model.nodes.find((n) => n.id === edge.to);

  return (
    <g style={{ opacity, transition: "opacity 160ms" }}>
      <path
        d={d}
        fill="none"
        stroke={on ? "var(--color-pulsar)" : edgeStroke(edge)}
        strokeWidth={on ? 1.4 : 1}
        strokeDasharray={
          edge.kind === "abort" || edge.kind === "return" ? "6 7" : undefined
        }
        style={{ transition: "stroke 160ms" }}
      />
      {edge.label && from && to && (
        <text
          {...labelPos(frame.x(from), frame.y(from), frame.x(to), frame.y(to))}
          textAnchor="middle"
          className="fill-static font-mono"
          fontSize={9}
          opacity={0.75}
        >
          {edge.label}
        </text>
      )}
    </g>
  );
}

// --- nodes ------------------------------------------------------------------

function NodeGlyph({
  node,
  chips,
  lit,
  hoverGroup,
  frame,
  live = false,
  reduceMotion = false,
  activeCondition = null,
  activeLabel = null,
  observedConditions = null,
  onEnter,
  onLeave,
  onClick,
  onChipEnter,
  onChipLeave,
  onChipClick,
}: {
  node: TaskNode;
  chips: Chip[];
  /** null = resting (nothing highlighted anywhere). */
  lit: boolean | null;
  hoverGroup: string | null;
  frame: Frame;
  /** Which of a collapsed node's conditions is in play — the lit tick. */
  activeCondition?: string | null;
  /** What to call the node while that condition is in play. */
  activeLabel?: string | null;
  /**
   * Conditions seen at least once this session, or null in the viewer where
   * "observed" means nothing. A tick outside this set draws hollow — the live
   * panel's sparklines below enumerate only conditions that have ALREADY come
   * up, so this is the one place that answers "has odor 5 appeared yet?".
   */
  observedConditions?: ReadonlySet<string> | null;
  /** The running box is in this state right now (`LiveStateMachine`). */
  live?: boolean;
  /** Gates the token's `repeat: Infinity` pulse, which `MotionConfig`'s
   *  reduced-motion setting does not neutralise. */
  reduceMotion?: boolean;
  onEnter: () => void;
  onLeave: () => void;
  /** Absent in the live view, where a state is a reading, not a control. */
  onClick?: (() => void) | undefined;
  onChipEnter: (group: string) => void;
  onChipLeave: () => void;
  onChipClick: (group: string) => void;
}) {
  const x = frame.x(node);
  const y = frame.y(node);
  const dimmed = lit === false;
  const fill = fillFor(node);

  const anchor = node.labelAnchor ?? "below";
  const ticks = node.variants && node.variants.length > 1 ? node.variants : null;
  // The strip sits between the glyph and its label, so the label moves down by
  // exactly what the strip claims — the same number `measureNode` budgets.
  const tickBlock = ticks ? TICK_BLOCK : 0;
  const labelX = anchor === "right" ? x + R + 6 : x;
  const labelY =
    anchor === "right"
      ? y + LABEL_RIGHT_DY
      : anchor === "above"
        ? y + LABEL_ABOVE_DY
        : y + R + tickBlock + LABEL_BELOW_DY;
  const textAnchor = anchor === "right" ? "start" : "middle";

  // Chips stack under the label (or trail it, for right-anchored nodes).
  const chipX = anchor === "right" ? x + R + 6 : x;
  const chipY0 =
    anchor === "right"
      ? y + CHIP_RIGHT_DY
      : anchor === "above"
        ? y + CHIP_ABOVE_DY
        : labelY + CHIP_GAP;

  return (
    <g
      style={{
        opacity: dimmed ? 0.18 : 1,
        transition: "opacity 160ms",
        cursor: onClick ? "pointer" : "default",
      }}
      onPointerEnter={onEnter}
      onPointerLeave={onLeave}
      onClick={onClick}
    >
      {/* The ring: the highlight's own mark, sprung in rather than toggled. */}
      {lit === true && (
        <motion.circle
          cx={x}
          cy={y}
          fill="none"
          stroke="var(--color-pulsar)"
          strokeWidth={1.3}
          initial={{ r: R, opacity: 0 }}
          animate={{ r: R + 5, opacity: 1 }}
          transition={springSnappy}
        />
      )}

      {/* The live token: `SessionJourney`'s StepStar grammar at this drawing's
          scale — a pulsing flat ring around the occupied state, no blur, no
          glow (`ARCHITECTURE.md#theme`). The steady inner ring keeps the state
          marked between pulses and under reduced motion. */}
      {live && !reduceMotion && (
        <motion.circle
          cx={x}
          cy={y}
          fill="none"
          stroke="var(--color-starlight)"
          strokeWidth={1}
          initial={false}
          animate={{ r: [R + 2, R + 13], opacity: [0.5, 0] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }}
          pointerEvents="none"
        />
      )}
      {live && (
        <circle
          cx={x}
          cy={y}
          r={R + 4.5}
          fill="none"
          stroke="var(--color-starlight)"
          strokeWidth={0.8}
          opacity={0.55}
          pointerEvents="none"
        />
      )}

      {node.kind === "outcome" ? (
        // A live outcome brightens in its own colour — "rewarded" flashing
        // green says more than a generic token colour would.
        <motion.rect
          x={x - R}
          y={y - R}
          width={R * 2}
          height={R * 2}
          rx={3}
          fill={fill}
          animate={{ fillOpacity: live ? 0.75 : 0.22 }}
          transition={springSnappy}
          stroke={fill}
          strokeWidth={1}
        />
      ) : (
        <motion.circle
          cx={x}
          cy={y}
          r={R}
          animate={{ fill: live ? "var(--color-starlight)" : "var(--color-nebula)" }}
          transition={springSnappy}
          stroke={node.kind === "abort" ? "var(--color-static)" : "var(--color-starlight)"}
          strokeOpacity={node.kind === "abort" ? 0.55 : 0.8}
          strokeWidth={1}
          strokeDasharray={node.kind === "abort" ? "5 5" : undefined}
        />
      )}

      {ticks && (
        <ConditionTicks
          conditions={ticks}
          x={x}
          y={y + R + 4}
          activeId={activeCondition}
          observed={observedConditions}
          litAll={lit === true}
        />
      )}

      <text
        x={labelX}
        y={labelY}
        textAnchor={textAnchor}
        fontSize={11}
        className={lit || live ? "fill-starlight" : "fill-static"}
        style={{ transition: "fill 160ms" }}
      >
        {/* ONLY a collapsed node takes the active label. Every other node on
            the row would otherwise rename itself to the odor in play, which is
            how the first version of this made the whole live machine read
            "Odor 3". A node that stands for nothing but itself is always
            called what it is. */}
        {(ticks && activeLabel) || node.label}
      </text>

      {/* The parameter chips: the subtle labels the mapping asks for. During a
          group hover only that group's chips stay up, so the highlight names
          itself instead of leaving the reader to compare colours. */}
      {chips.map((chip, index) => {
        const covered =
          hoverGroup !== null && chip.covers.some((g) => tabOf(g) === hoverGroup);
        const chipOpacity =
          hoverGroup === null ? (lit === false ? 0.15 : 0.55) : covered ? 1 : 0.12;
        return (
          <text
            key={chip.short}
            x={chipX}
            y={chipY0 + index * 12}
            textAnchor={textAnchor}
            fontSize={9}
            className={covered ? "fill-pulsar" : "fill-static"}
            style={{ opacity: chipOpacity, transition: "opacity 160ms, fill 160ms", cursor: "pointer" }}
            // The hover handlers must NOT stopPropagation: React synthesizes
            // enter/leave from pointerout/over, so stopping the chip's leave
            // also swallowed the node <g>'s — leaving the graph *from a chip*
            // left the node ringed and its pills lit forever. Only the click
            // stays fenced, so a chip click doesn't double as a node click.
            onPointerEnter={() => onChipEnter(chip.group)}
            onPointerLeave={() => onChipLeave()}
            onClick={(event) => {
              event.stopPropagation();
              onChipClick(chip.group);
            }}
          >
            {chip.short}
          </text>
        );
      })}
    </g>
  );
}

/**
 * A rewarded trial in transit: one small flat dot riding the happy path from
 * start to the ITI, resting, and riding again — the machine shown working
 * rather than only drawn.
 *
 * NOT THE LIVE TOKEN. That one is a ringed, pulsing mark on Mission Control's
 * drawing and means "the box is here now"; this is a 2.5px dot with no ring,
 * at 0.6 opacity, so the two can never be confused. Flat — no blur, no glow
 * (`ARCHITECTURE.md#theme`). The page hides it under reduced motion and while
 * anything is lit, so it never moves under a reading.
 *
 * Driven through a hidden path's `getPointAtLength` rather than CSS
 * `offset-path`, which SVG in WKWebView does not reliably honour.
 */
function TransitToken({ d }: { d: string }) {
  const track = useRef<SVGPathElement>(null);
  const progress = useMotionValue(0);
  const cx = useMotionValue(-10);
  const cy = useMotionValue(-10);

  useEffect(() => {
    const path = track.current;
    if (!path) return;
    const length = path.getTotalLength();
    const place = (p: number) => {
      const point = path.getPointAtLength(p * length);
      cx.set(point.x);
      cy.set(point.y);
    };
    place(0);
    const unsubscribe = progress.on("change", place);
    progress.set(0);
    const controls = animate(progress, 1, {
      duration: 3.2,
      ease: "linear",
      repeat: Infinity,
      repeatDelay: 1.4,
      delay: 1,
    });
    return () => {
      controls.stop();
      unsubscribe();
    };
  }, [d, progress, cx, cy]);

  return (
    <g pointerEvents="none">
      <path ref={track} d={d} fill="none" stroke="none" />
      <motion.circle cx={cx} cy={cy} r={2.5} fill="var(--color-starlight)" opacity={0.6} />
    </g>
  );
}
