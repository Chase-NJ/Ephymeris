import { motion } from "framer-motion";
import { ChartLine, Orbit, Settings, Terminal, Users } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import type { LucideIcon } from "lucide-react";

import { LiveConstellation } from "./ConstellationStatus";
import { springSnappy } from "@/lib/motion";

/**
 * Persistent sidebar (ephymeris_v1.0.md §3.2).
 *
 * Frosted `Nebula` (§2.4 vibrancy — one of only two places it's allowed). Five
 * equally-weighted destinations; "Start a Session" is deliberately absent, as
 * it's the app's single primary action and gets the hero CTA instead. The
 * constellation widget is pinned to the bottom so box connectivity is never
 * something the user has to navigate to check.
 */

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

const NAV: readonly NavItem[] = [
  { to: "/", label: "Dashboard", icon: Orbit },
  { to: "/cohorts", label: "Cohorts", icon: Users },
  { to: "/debug", label: "Debug Mode", icon: Terminal },
  { to: "/analytics", label: "Analytics", icon: ChartLine },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const { pathname } = useLocation();

  return (
    <nav className="vibrancy flex w-[200px] shrink-0 flex-col border-r border-halo">
      <ul className="flex flex-col gap-0.5 p-2 pt-3">
        {NAV.map((item) => {
          const active = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
          return (
            <li key={item.to} className="relative">
              {/* Pulsar-tinted rounded-rect selection, macOS sidebar convention
                  (§3.2). Spring-animated between items via layoutId (§2.5). */}
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
              </NavLink>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto">
        <div className="mx-3 border-t border-halo" />
        <div className="pt-2.5">
          <LiveConstellation />
        </div>
      </div>
    </nav>
  );
}
