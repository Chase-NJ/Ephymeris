import { motion } from "framer-motion";
import { ChartLine, Orbit, Radio, Settings, Users, Workflow } from "lucide-react";
import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import type { LucideIcon } from "lucide-react";

import { LiveConstellation } from "./ConstellationStatus";
import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { springSnappy } from "@/lib/motion";
import { runDeparture } from "@/lib/nav/departure";
import { useUnsaved } from "@/lib/nav/unsavedGuard";
import { useRunningSession } from "@/lib/sessions/context";

/**
 * Persistent sidebar (dashboard.md §2.2).
 *
 * Translucent `Nebula` (§1.4 vibrancy — one of only two places it's allowed;
 * `.vibrancy-sky`, the tint-only variant, since its backdrop is the sky rather
 * than content and a blur only erases a starfield). Positioned as an overlay
 * rather than a flex sibling, because the sky runs full-bleed underneath it
 * (see `AppShell`); the glass has to have something to be glass over.
 * Two groups: the working destinations at the top, and Settings pinned to the
 * bottom just above the constellation widget — the macOS convention of app
 * preferences living at the edge of the list. **Rig sits in the top group,
 * directly under Dashboard**: it is how *this rig* is wired, so it belongs
 * beside the sky it describes rather than filed away with preferences — the
 * Dashboard's Rig tile links straight to it. The
 * Dashboard owns the primary
 * action *and* the way back to a running session — the Launch nav item is
 * retired (§3.2): its content docks beside the Dashboard's hero CTA, so the
 * Dashboard row's active state deliberately covers the whole /session/*
 * flow, and a matte status-ok dot marks it while a session is running. The
 * constellation widget stays at the very bottom so box connectivity is never
 * something the user has to navigate to check.
 */

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Overrides the default prefix rule when a tab owns more than its route. */
  match?: (pathname: string) => boolean;
}

const NAV_MAIN: readonly NavItem[] = [
  {
    to: "/",
    label: "Dashboard",
    icon: Orbit,
    // `/debug` counts as Dashboard, not as a destination of its own. Debug has
    // no nav entry: it is reached only by selecting a box on the Dashboard's
    // sky, and it *is* that sky with the camera flown in — so the tab the user
    // came from should stay lit rather than nothing being selected at all. The
    // same reasoning `/session/*` already gets.
    match: (p) => p === "/" || p.startsWith("/session") || p.startsWith("/debug"),
  },
  // **Rig**, at the route still spelled `/config` (see `App.tsx`). The tab is
  // named for its subject — this rig's wiring, all of it: box→board bindings,
  // the utility baseline, and the channel→pin editor that used to live on Task.
  { to: "/config", label: "Rig", icon: Radio },
  { to: "/cohorts", label: "Cohorts", icon: Users },
  { to: "/task", label: "Task", icon: Workflow },
  { to: "/analytics", label: "Analytics", icon: ChartLine },
];

// Settings alone. The sketch library used to sit here as its own tab; it is now
// `/task/sketches`, reached from the Task landing and from the Dashboard's Task
// tile — a sketch is one of the things a task can be made of, so a tab of its
// own was filing it by where it came from rather than by what it is for.
const NAV_BOTTOM: readonly NavItem[] = [
  { to: "/settings", label: "Settings", icon: Settings },
];

function NavList({
  items,
  pathname,
  sessionRunning = false,
  onNavigate,
}: {
  items: readonly NavItem[];
  pathname: string;
  sessionRunning?: boolean;
  /** Returns false to swallow the click — the shell is asking first. */
  onNavigate: (to: string) => boolean;
}) {
  return (
    <ul className="flex flex-col gap-0.5 p-2">
      {items.map((item) => {
        const active = item.match
          ? item.match(pathname)
          : item.to === "/"
            ? pathname === "/"
            : pathname.startsWith(item.to);
        return (
          <li key={item.to} className="relative">
            {/* Pulsar-tinted rounded-rect selection, macOS sidebar convention
                (§3.2). Spring-animated between items via layoutId (§2.5) —
                one shared id, so the highlight glides between the two groups
                as readily as within one. */}
            {active && (
              <motion.span
                layoutId="nav-selection"
                transition={springSnappy}
                className="absolute inset-0 rounded-md bg-pulsar/18"
              />
            )}
            <NavLink
              to={item.to}
              onClick={(event) => {
                if (!onNavigate(item.to)) event.preventDefault();
              }}
              className={`relative flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] transition-colors ${
                active ? "text-starlight" : "text-static hover:text-starlight"
              }`}
            >
              <item.icon
                size={16}
                strokeWidth={1.75}
                className={active ? "text-pulsar" : ""}
              />
              <span className="font-medium">{item.label}</span>
              {item.to === "/" && sessionRunning && (
                <span
                  title="Session running"
                  className="ml-auto inline-block size-1.5 rounded-full"
                  style={{ background: "var(--color-status-ok)" }}
                />
              )}
            </NavLink>
          </li>
        );
      })}
    </ul>
  );
}

export function Sidebar() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const sessionRunning = useRunningSession() !== null;
  /*
   * A screen holding unsaved work asks before it is left
   * (`lib/nav/unsavedGuard.ts`). The sidebar is the right place for this even
   * though it knows nothing about cohorts: it is the one control present on
   * every screen, and it is the door the loss actually happens through — every
   * tab here unmounts the current route unconditionally and immediately.
   */
  const unsaved = useUnsaved();
  const [pending, setPending] = useState<string | null>(null);

  /*
   * Two things happen on the way out, in this order, and only on the path that
   * actually navigates.
   *
   * `runDeparture` lets the screen being left start leaving — for the
   * constellation views that is clearing the focused star, which has to land in
   * the *same commit* as the navigation for the camera to fly out rather than
   * cut (`lib/nav/departure.ts`). React batches both, since they share one click
   * handler. It is deliberately after the two early returns: a swallowed click
   * navigates nowhere, and a screen that ends up staying must not have started
   * leaving.
   */
  const onNavigate = (to: string): boolean => {
    if (to === pathname) return true;
    if (unsaved) {
      setPending(to);
      return false;
    }
    runDeparture();
    return true;
  };

  return (
    <nav className="vibrancy-sky absolute inset-y-0 left-0 z-20 flex w-sidebar flex-col border-r border-halo">
      <div className="pt-1">
        <NavList
          items={NAV_MAIN}
          pathname={pathname}
          sessionRunning={sessionRunning}
          onNavigate={onNavigate}
        />
      </div>

      <div className="mt-auto">
        <NavList items={NAV_BOTTOM} pathname={pathname} onNavigate={onNavigate} />
        <div className="mx-3 border-t border-halo" />
        <div className="pt-2.5">
          <LiveConstellation />
        </div>
      </div>

      <Modal
        open={pending !== null}
        onClose={() => setPending(null)}
        title="Discard unsaved changes?"
      >
        <div className="px-5 py-4">
          <p className="text-[13px] leading-relaxed text-static">
            This screen has changes that haven&apos;t been saved. Leaving now
            discards them — there is nothing to recover them from.
          </p>
          <div className="mt-4 flex gap-2">
            <Button
              variant="primary"
              onClick={() => {
                const to = pending;
                setPending(null);
                if (to) {
                  // The click this confirms is the one `onNavigate` swallowed,
                  // so the departure it skipped happens here instead.
                  runDeparture();
                  navigate(to);
                }
              }}
            >
              Discard and leave
            </Button>
            <Button variant="ghost" onClick={() => setPending(null)}>
              Keep editing
            </Button>
          </div>
        </div>
      </Modal>
    </nav>
  );
}
