import { AnimatePresence, motion } from "framer-motion";
import { AudioWaveform, ChartLine, Orbit, Radio, Settings, Users, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import type { LucideIcon } from "lucide-react";

import { LiveConstellation } from "./ConstellationStatus";
import { Button } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { springSnappy } from "@/lib/motion";
import { runDeparture } from "@/lib/nav/departure";
import { useUnsaved } from "@/lib/nav/unsavedGuard";
import { useActiveSessions, useRunningSession } from "@/lib/sessions/context";
import {
  noteLocation,
  SETUP_STEP_LABEL,
  useSetupResume,
  type SetupResume,
} from "@/lib/sessions/setupResume";
import type { ActiveSessions } from "@/lib/sessions/types";

/**
 * Persistent sidebar.
 *
 * Translucent `Nebula` (vibrancy — one of only two places it's allowed;
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
 * retired: its content docks beside the Dashboard's hero CTA, so the
 * Dashboard row's active state deliberately covers the whole /session/*
 * flow, and a matte status-ok dot marks it while a session is running. **A
 * set-up left for another tab is kept** (`lib/sessions/setupResume.ts`): the
 * Dashboard row then opens the step it was left on rather than `/`, and says
 * so on a second line — from inside the flow it goes to `/` as ever, which is
 * the way to the Dashboard itself while a set-up is pending. The
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
  // **Recording**: the link to Intan RHX, which digital input each box pulses,
  // and what a recording saves. Between Task and Analytics — a recording sits
  // between what the animal does and what is made of it. Prefix-matched, so
  // `/recording` lights it; `/session/:id/recording` starts with `/session`
  // and stays with Dashboard.
  { to: "/recording", label: "Recording", icon: AudioWaveform },
  { to: "/analytics", label: "Analytics", icon: ChartLine },
];

// Settings alone. The sketch library used to sit here as its own tab; the Task
// tab now opens straight into it, so the library needs no entry of its own.
const NAV_BOTTOM: readonly NavItem[] = [
  { to: "/settings", label: "Settings", icon: Settings },
];

function NavList({
  items,
  pathname,
  sessionRunning = false,
  resume = null,
  onNavigate,
}: {
  items: readonly NavItem[];
  pathname: string;
  sessionRunning?: boolean;
  /** An unfinished set-up the Dashboard row returns to, with its caption. */
  resume?: ResumeOffer | null;
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
        const resumeHere = item.to === "/" ? resume : null;
        const to = resumeHere?.url ?? item.to;
        return (
          <li key={item.to} className="relative">
            {/* Pulsar-tinted rounded-rect selection, macOS sidebar convention.
                Spring-animated between items via layoutId —
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
              to={to}
              // `end`: the resume URL carries a search string, and NavLink's
              // own active matching is unused here anyway (see `active`).
              end
              title={
                resumeHere
                  ? `Resume ${resumeHere.recording ? "recording" : "session"} setup — ${resumeHere.step}`
                  : undefined
              }
              onClick={(event) => {
                if (!onNavigate(to)) event.preventDefault();
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
              <span className="flex min-w-0 flex-col">
                <span className="font-medium">{item.label}</span>
                <AnimatePresence initial={false}>
                  {resumeHere && (
                    <motion.span
                      key="resume"
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={springSnappy}
                      className="flex items-center gap-1 overflow-hidden whitespace-nowrap text-[11px] leading-[15px] text-pulsar"
                    >
                      {/* The Recording tab's own mark, rather than a longer
                          caption — the sidebar has room for about 20 characters. */}
                      {resumeHere.recording && (
                        <AudioWaveform size={11} strokeWidth={2} className="shrink-0" />
                      )}
                      Resume · {resumeHere.step}
                    </motion.span>
                  )}
                </AnimatePresence>
              </span>
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

interface ResumeOffer {
  url: string;
  /** The step's rail label (`SessionJourney`). */
  step: string;
  recording: boolean;
}

/** Whether a session the sidecar still reports is the one a set-up was on. */
function findUnfinished(active: ActiveSessions, sessionId: string) {
  if (active.running?.session.id === sessionId) return active.running.session;
  return (
    active.configuring.find((s) => s.id === sessionId) ??
    active.stale.find((s) => s.id === sessionId) ??
    null
  );
}

/**
 * The Dashboard row's way back into an unfinished set-up, or null.
 *
 * Offered only from outside the flow — inside it the operator is already
 * there — and, past Step 1, only while `sessions.active` still reports the
 * session: one discarded from the dock or ended from Mission Control must not
 * be resumed into a dead record.
 */
function resumeOffer(
  resume: SetupResume | null,
  active: ActiveSessions | null,
  pathname: string,
): ResumeOffer | null {
  if (!resume || pathname.startsWith("/session")) return null;
  let recording: boolean;
  if (resume.sessionId === null) {
    recording = new URLSearchParams(resume.url.split("?")[1] ?? "").get("mode") === "recording";
  } else {
    const session = active ? findUnfinished(active, resume.sessionId) : null;
    if (!session) return null;
    recording = session.recording != null;
  }
  return { url: resume.url, step: SETUP_STEP_LABEL[resume.step], recording };
}

export function Sidebar() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const sessionRunning = useRunningSession() !== null;
  const active = useActiveSessions();
  const resume = resumeOffer(useSetupResume(), active, pathname);

  // Every navigation passes through here, and the sidebar is always mounted —
  // so this, rather than each step, is what remembers where a set-up was left.
  useEffect(() => {
    noteLocation(pathname, search);
  }, [pathname, search]);
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
          resume={resume}
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
