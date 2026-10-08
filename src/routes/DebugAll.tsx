import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { useBoxHealth } from "@/components/chrome/ConstellationStatus";
import { SidecarStatusPill } from "@/components/common/SidecarStatusPill";
import { DebugConstellation } from "@/components/debug/DebugConstellation";
import { AllBoxesPanel } from "@/components/debug/all/AllBoxesPanel";
import { setRigSelection } from "@/lib/constellations/viewMemory";
import { springPanel } from "@/lib/motion";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/** The sidebar's width — the one chrome the framing clears sideways. */
const SIDEBAR_PX = 200;

/**
 * Debug Mode for every box at once (`/debug/all`,
 * `USER-GUIDE.md#commanding-every-box`).
 *
 * The same sky as the Dashboard and per-box Debug, pulled back rather than
 * flown in: the camera settles on its all-boxes pose and the whole asterism
 * rises into the sky above the panel docked along the bottom
 * (`SceneIntent.frameAll`), every targeted star ringed. A star click here does not fly to the star — it takes that box in or
 * out of the targets, so the constellation itself is the selector.
 */
export function DebugAll() {
  const navigate = useNavigate();
  const { status } = useSidecar();
  const { settings } = useSettings();
  const bound = useBoundBoxes();
  const health = useBoxHealth();
  const [hovered, setHovered] = useState<number | null>(null);

  // Detected boxes to start with: a box not on the bus can do nothing here.
  const [targets, setTargets] = useState<Set<number>>(() => {
    const detected = bound.filter((b) => (health[b] ?? "absent") !== "absent");
    return new Set(detected.length > 0 ? detected : bound);
  });

  // A box unbound while this view is open leaves the targets with it.
  const boundKey = bound.join(",");
  useEffect(() => {
    setTargets((prev) => new Set([...prev].filter((b) => bound.includes(b))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [boundKey]);

  // Nothing bound means nothing to command; the Dashboard says how to bind.
  useEffect(() => {
    if (settings.boxes.length > 0 && bound.length === 0) navigate("/", { replace: true });
  }, [bound.length, settings.boxes.length, navigate]);

  // This view never has a single box selected.
  useEffect(() => setRigSelection(null), []);

  const back = useCallback(() => navigate("/"), [navigate]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector("[role=dialog]")) back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [back]);

  const toggle = (box: number) =>
    setTargets((prev) => {
      const next = new Set(prev);
      if (next.has(box)) next.delete(box);
      else next.add(box);
      return next;
    });

  const ringed = useMemo(() => new Set(targets), [targets]);

  return (
    // The Dashboard's scaffold, pixel for pixel, so the shared canvas is handed
    // over without a resize.
    <div className="relative h-full">
      <div className="absolute inset-0">
        <DebugConstellation
          selected={null}
          frameAll
          // The panel docks along the bottom, so sideways there is only the
          // sidebar to clear: centre the asterism in the content area, half
          // the sidebar's width right of the window's centre.
          frameShift={-SIDEBAR_PX / 2}
          ringed={ringed}
          highlight={hovered}
          onHover={setHovered}
          onSelect={(box) => {
            if (box !== null) toggle(box);
          }}
        />
      </div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="pointer-events-none absolute top-7 left-8 flex items-start gap-4"
      >
        <div>
          <div className="font-mono text-[9px] tracking-[0.18em] text-static/70 uppercase">
            Telemetry · Debug
          </div>
          <h1 className="font-display text-[22px] text-starlight">All boxes</h1>
          <p className="mt-0.5 font-mono text-[10px] text-static/70">
            {targets.size} of {bound.length} targeted — click a star to take it in or out
          </p>
        </div>
        <span className="pointer-events-auto mt-4 shrink-0">
          <SidecarStatusPill status={status} />
        </span>
      </motion.div>

      <AnimatePresence>
        <AllBoxesPanel
          key="all"
          bound={bound}
          health={health}
          targets={targets}
          hovered={hovered}
          onToggle={toggle}
          onTargets={(boxes) => setTargets(new Set(boxes))}
          onHover={setHovered}
          onBack={back}
        />
      </AnimatePresence>
    </div>
  );
}
