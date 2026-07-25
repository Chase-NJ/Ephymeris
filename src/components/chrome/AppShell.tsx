import { MotionConfig } from "framer-motion";
import { Outlet } from "react-router";

import { Sidebar } from "./Sidebar";
import { Starfield } from "./Starfield";
import { SvgDefs } from "./SvgDefs";
import { Titlebar } from "./Titlebar";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * Two-region layout per ephymeris_v1.0.md §3.1: custom titlebar across the top,
 * persistent sidebar on the left, content on the right. The starfield sits
 * behind the content region only — not behind the sidebar, whose frosted
 * surface would blur it into noise.
 */
export function AppShell() {
  const reduceMotion = useReduceMotion();

  return (
    <MotionConfig reducedMotion={reduceMotion ? "always" : "never"}>
      <div className="flex h-full flex-col bg-void">
        <SvgDefs />
        <Titlebar />
        <div className="flex min-h-0 flex-1">
          <Sidebar />
          <div className="relative min-w-0 flex-1">
            <Starfield />
            <main className="relative h-full overflow-y-auto">
              <Outlet />
            </main>
          </div>
        </div>
      </div>
    </MotionConfig>
  );
}
