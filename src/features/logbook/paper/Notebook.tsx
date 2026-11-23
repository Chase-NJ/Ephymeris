import { animate, motion, useMotionValue, useTransform, type MotionValue } from "framer-motion";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import { direction } from "../pages";
import { useReduceMotion } from "@/lib/useReduceMotion";

export type Side = "verso" | "recto";

/** A month's tab on the fore-edge. */
export interface EdgeTab {
  key: string;
  label: string;
  /** Where a click opens the book. */
  target: string;
  current: boolean;
  /** 0-based calendar month, which picks the tab's ink. */
  month: number;
  title: string;
}

interface Flip {
  from: string;
  to: string;
  dir: "forward" | "back";
  key: number;
}

/** How long a leaf takes to turn. A tween, not a spring: paper has no bounce. */
const TURN_S = 0.58;
const TURN_EASE = [0.4, 0.02, 0.2, 1] as const;

/** A page's side margins: a share of its width, so a narrow page keeps its measure. */
const GUTTER = "px-[clamp(20px,6%,40px)]";

const TAB_INKS = [
  "var(--color-ink-blue)",
  "var(--color-ink-teal)",
  "var(--color-ink-ochre)",
  "var(--color-ink-red)",
  "var(--color-ink-plum)",
] as const;

/**
 * The open notebook (`ARCHITECTURE.md#the-paper-exception`): two pages on a
 * block of leaves, and the leaf that turns between spreads.
 *
 * **It owns the turn and nothing else.** A spread is named by an id in
 * `order`; `renderSide` draws either page of any spread, so mid-turn this can
 * show four pages of two spreads at once: the two that stay flat and the two
 * faces of the leaf in the air. Going forward the right page lifts and lands
 * as the next spread's left; going back, the mirror.
 *
 * The leaf is a second mount of a page already on screen a frame ago, so each
 * page's scroll offset is remembered here by spread and side and put back on
 * mount. Without it a page scrolled to its last note would snap to its top as
 * it lifted.
 *
 * A turn asked for mid-turn completes the one in the air at once and starts
 * from where it landed: holding an arrow key riffles, and never queues.
 * Reduced motion swaps the spread with no leaf at all.
 */
export function Notebook({
  order,
  currentId,
  renderSide,
  runningHead,
  folio,
  tabs,
  onTurn,
  onOpen,
  label,
}: {
  order: readonly string[];
  currentId: string;
  renderSide: (id: string, side: Side) => ReactNode;
  runningHead: (id: string, side: Side) => ReactNode;
  folio: (id: string, side: Side) => string;
  tabs: readonly EdgeTab[];
  onTurn: (delta: -1 | 1) => void;
  onOpen: (id: string) => void;
  label: string;
}) {
  const reduce = useReduceMotion();
  const [state, setState] = useState<{ shown: string; flip: Flip | null }>({
    shown: currentId,
    flip: null,
  });
  const counter = useRef(0);
  const scrolls = useRef(new Map<string, number>());

  // Derived from the prop during render (React's own pattern for it): the
  // spread shown trails `currentId` by exactly one turn.
  const resting = state.flip ? state.flip.to : state.shown;
  if (resting !== currentId) {
    if (reduce || !order.includes(resting) || !order.includes(currentId)) {
      setState({ shown: currentId, flip: null });
    } else {
      counter.current += 1;
      setState({
        shown: resting,
        flip: {
          from: resting,
          to: currentId,
          dir: direction(order, resting, currentId),
          key: counter.current,
        },
      });
    }
  }

  const flip = state.flip;
  const landed = useCallback((key: number) => {
    setState((held) => (held.flip?.key === key ? { shown: held.flip.to, flip: null } : held));
  }, []);

  // While a leaf is in the air the flat pages are the two it does not cover.
  const leftId = flip ? (flip.dir === "forward" ? flip.from : flip.to) : state.shown;
  const rightId = flip ? (flip.dir === "forward" ? flip.to : flip.from) : state.shown;

  const index = Math.max(0, order.indexOf(currentId));
  const progress = order.length > 1 ? index / (order.length - 1) : 0;
  const atStart = index === 0;
  const atEnd = index === order.length - 1;

  const page = (id: string, side: Side) => (
    <PageFrame
      key={`${id}:${side}`}
      side={side}
      head={runningHead(id, side)}
      folio={folio(id, side)}
      scrolls={scrolls}
      scrollKey={`${id}:${side}`}
    >
      {renderSide(id, side)}
    </PageFrame>
  );

  return (
    <div className="flex h-full min-h-0 items-stretch gap-3">
      <TurnButton side="back" disabled={atStart} onClick={() => onTurn(-1)} />

      <div className="relative min-w-0 flex-1">
        <section
          aria-label={label}
          aria-roledescription="notebook"
          className="paper book-block absolute inset-0"
          style={{
            // The leaves already turned stack up on the left, those to come
            // on the right: the block's two edges say how far through it is.
            paddingLeft: 3 + 8 * progress,
            paddingRight: 3 + 8 * (1 - progress),
            paddingTop: 3,
            paddingBottom: 6,
          }}
        >
          <div className="book relative h-full w-full">
            <div className="absolute inset-y-0 left-0 w-1/2" inert={flip !== null}>
              {page(leftId, "verso")}
              {flip && <CastShadow flipKey={flip.key} side="verso" />}
            </div>
            <div className="absolute inset-y-0 left-1/2 w-1/2" inert={flip !== null}>
              {page(rightId, "recto")}
              {flip && <CastShadow flipKey={flip.key} side="recto" />}
            </div>
            {flip && (
              <Leaf
                key={flip.key}
                dir={flip.dir}
                front={page(flip.from, flip.dir === "forward" ? "recto" : "verso")}
                back={page(flip.to, flip.dir === "forward" ? "verso" : "recto")}
                onLanded={() => landed(flip.key)}
              />
            )}
            {/* The spine: a hairline where the two pages meet. */}
            <div
              aria-hidden
              className="pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-[rgb(58_46_24/0.28)]"
            />
          </div>
        </section>

        {tabs.length > 0 && (
          <nav
            aria-label="Months"
            className="paper absolute top-10 left-full z-10 -ml-px flex max-h-[calc(100%-5rem)] flex-col gap-1 overflow-hidden"
          >
            {tabs.map((tab) => {
              const ink = TAB_INKS[tab.month % TAB_INKS.length]!;
              return (
                <button
                  key={tab.key}
                  type="button"
                  title={tab.title}
                  aria-current={tab.current ? "true" : undefined}
                  onClick={() => onOpen(tab.target)}
                  className="edge-tab smallcaps rounded-r-[4px] py-[4px] pr-2 pl-1.5 text-left text-[10px] leading-none"
                  style={
                    tab.current
                      ? { backgroundColor: "var(--color-paper)", color: ink, fontWeight: 700 }
                      : { backgroundColor: ink, color: "var(--color-paper)" }
                  }
                >
                  {tab.label}
                </button>
              );
            })}
          </nav>
        )}
      </div>

      <TurnButton side="forward" disabled={atEnd} onClick={() => onTurn(1)} tabs={tabs.length > 0} />
    </div>
  );
}

/** One page: running head, the scrolling block, the folio. Fills its parent. */
function PageFrame({
  side,
  head,
  folio,
  scrolls,
  scrollKey,
  children,
}: {
  side: Side;
  head: ReactNode;
  folio: string;
  scrolls: RefObject<Map<string, number>>;
  scrollKey: string;
  children: ReactNode;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const top = scrolls.current.get(scrollKey);
    if (scroller.current && top) scroller.current.scrollTop = top;
  }, [scrolls, scrollKey]);

  return (
    <div className={`page page-${side} absolute inset-0`}>
      <header
        className={`smallcaps flex shrink-0 items-baseline justify-between gap-4 ${GUTTER} pt-6 pb-3 text-[10.5px] text-ink-faint ${
          side === "verso" ? "" : "flex-row-reverse"
        }`}
      >
        {head}
      </header>
      <div
        ref={scroller}
        onScroll={(event) => scrolls.current.set(scrollKey, event.currentTarget.scrollTop)}
        className={`page-scroll min-h-0 flex-1 ${GUTTER} pb-3`}
      >
        {children}
      </div>
      <footer
        className={`shrink-0 ${GUTTER} pt-2 pb-5 text-[13px] text-ink-soft ${
          side === "verso" ? "text-left" : "text-right"
        }`}
      >
        {folio}
      </footer>
    </div>
  );
}

/**
 * The leaf in the air: two faces back to back, hinged on the spine. `front`
 * is the page being left, `back` the one arriving on the other side of it.
 */
function Leaf({
  dir,
  front,
  back,
  onLanded,
}: {
  dir: "forward" | "back";
  front: ReactNode;
  back: ReactNode;
  onLanded: () => void;
}) {
  const turned = useMotionValue(0);
  const rotateY = useTransform(turned, [0, 1], [0, dir === "forward" ? -180 : 180]);
  // Each face darkens as it tips away from the reader and clears as it lands.
  const frontShade = useTransform(turned, [0, 0.5], [0, 0.34]);
  const backShade = useTransform(turned, [0.5, 1], [0.34, 0]);
  const done = useRef(onLanded);
  done.current = onLanded;

  useEffect(() => {
    const controls = animate(turned, 1, {
      duration: TURN_S,
      ease: [...TURN_EASE],
      onComplete: () => done.current(),
    });
    // Animation frames stop while the window is hidden or covered, and a leaf
    // left in the air keeps both pages inert. A timer still fires there, so
    // the turn lands on time whether or not anyone saw it.
    const landed = window.setTimeout(() => done.current(), TURN_S * 1000 + 200);
    return () => {
      controls.stop();
      window.clearTimeout(landed);
    };
  }, [turned]);

  return (
    <motion.div
      aria-hidden
      inert
      className="absolute inset-y-0 z-10 w-1/2"
      style={{
        left: dir === "forward" ? "50%" : 0,
        transformOrigin: dir === "forward" ? "left center" : "right center",
        transformStyle: "preserve-3d",
        rotateY,
      }}
    >
      <div className="absolute inset-0" style={{ backfaceVisibility: "hidden" }}>
        {front}
        <Shade opacity={frontShade} toward={dir === "forward" ? "left" : "right"} />
      </div>
      <div
        className="absolute inset-0"
        style={{ backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}
      >
        {back}
        <Shade opacity={backShade} toward={dir === "forward" ? "right" : "left"} />
      </div>
    </motion.div>
  );
}

/** A turning face's own shading, deepest at the spine. */
function Shade({ opacity, toward }: { opacity: MotionValue<number>; toward: "left" | "right" }) {
  return (
    <motion.div
      className="pointer-events-none absolute inset-0"
      style={{
        opacity,
        background: `linear-gradient(to ${toward}, rgb(58 46 24 / 0.1), rgb(58 46 24 / 0.75))`,
      }}
    />
  );
}

/** The shadow a leaf in the air throws on the page under it: none at rest. */
function CastShadow({ flipKey, side }: { flipKey: number; side: Side }) {
  return (
    <motion.div
      key={flipKey}
      className="pointer-events-none absolute inset-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: [0, 0.22, 0] }}
      transition={{ duration: TURN_S, ease: "easeInOut" }}
      style={{
        background: `linear-gradient(to ${side === "verso" ? "left" : "right"}, rgb(20 16 8 / 0.9), transparent 70%)`,
      }}
    />
  );
}

/** Turn one spread. On the desk, so it wears the desk's colours. */
function TurnButton({
  side,
  disabled,
  onClick,
  tabs = false,
}: {
  side: "back" | "forward";
  disabled: boolean;
  onClick: () => void;
  /** Clear of the month tabs hanging off the fore-edge. */
  tabs?: boolean;
}) {
  const Icon = side === "back" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={side === "back" ? "Previous page" : "Next page"}
      title={side === "back" ? "Previous page  ←" : "Next page  →"}
      className={`flex w-9 shrink-0 items-center justify-center self-center rounded-full py-6 text-static transition-colors hover:bg-nebula hover:text-starlight disabled:opacity-25 disabled:hover:bg-transparent ${
        tabs ? "ml-9" : ""
      }`}
    >
      <Icon size={22} strokeWidth={1.5} aria-hidden />
    </button>
  );
}
