import { motion } from "framer-motion";
import { ChartLine, Orbit, Radio, Settings, Users, Workflow } from "lucide-react";
import { NavLink, useLocation } from "react-router";
import type { LucideIcon } from "lucide-react";

import { LiveConstellation } from "./ConstellationStatus";
import { springSnappy } from "@/lib/motion";
import { useRunningSession } from "@/lib/sessions/context";

/**
 * Persistent sidebar (dashboard.md §2.2).
 *
 * Frosted `Nebula` (§2.4 vibrancy — one of only two places it's allowed).
 * Two groups: the working destinations at the top, and the configuration
 * pair (Config, Settings) pinned to the bottom just above the constellation
 * widget — the macOS convention of setup living at the edge of the list
 * rather than among the daily destinations. The Dashboard owns the primary
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
  { to: "/cohorts", label: "Cohorts", icon: Users },
  { to: "/task", label: "Task", icon: Workflow },
  { to: "/analytics", label: "Analytics", icon: ChartLine },
];

const NAV_BOTTOM: readonly NavItem[] = [
  { to: "/config", label: "Config", icon: Radio },
  { to: "/settings", label: "Settings", icon: Settings },
];

function NavList({
  items,
  pathname,
  sessionRunning = false,
}: {
  items: readonly NavItem[];
  pathname: string;
  sessionRunning?: boolean;
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
  const sessionRunning = useRunningSession() !== null;

  return (
    <nav className="vibrancy flex w-[200px] shrink-0 flex-col border-r border-halo">
      <div className="pt-1">
        <NavList items={NAV_MAIN} pathname={pathname} sessionRunning={sessionRunning} />
      </div>

      <div className="mt-auto">
        <NavList items={NAV_BOTTOM} pathname={pathname} />
        <div className="mx-3 border-t border-halo" />
        <div className="pt-2.5">
          <LiveConstellation />
        </div>
      </div>
    </nav>
  );
}
