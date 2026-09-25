import { motion } from "framer-motion";
import { Check } from "lucide-react";

import type { Cohort } from "@/lib/cohorts/types";
import { springSnappy } from "@/lib/motion";
import {
  animalsInGroup,
  groupRunsFor,
  populatedGroups,
  type Session,
} from "@/lib/sessions/types";

/**
 * Which group goes on the rig next (`dashboard.md` §5.2, §7.6).
 *
 * There is no run order: the operator picks, at setup and at every switch, from
 * every group that has a box-assigned animal. A group that already ran in this
 * session stays pickable — running it again appends new timestamped files and
 * overwrites nothing — and says when it ran, so a repeat is a choice rather
 * than an accident.
 */
export function GroupPicker({
  cohort,
  session,
  value,
  onChange,
}: {
  cohort: Cohort;
  /** The session being continued, for the "ran 10:42" badges; null at setup. */
  session: Session | null;
  value: string | null;
  onChange: (groupId: string) => void;
}) {
  const groups = populatedGroups(cohort);
  if (groups.length === 0) {
    return (
      <p className="text-[12px] leading-relaxed text-static">
        No group in this cohort has an animal with a box assigned.
      </p>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3" role="radiogroup">
      {groups.map((group) => {
        const selected = group.id === value;
        const animals = animalsInGroup(cohort, group.id);
        const runs = groupRunsFor(session, group.id);
        return (
          <motion.button
            key={group.id}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(group.id)}
            whileHover={{ y: -2 }}
            whileTap={{ scale: 0.99 }}
            transition={springSnappy}
            className={`flex flex-col items-start gap-1.5 rounded-md border p-3 text-left transition-colors ${
              selected ? "border-pulsar bg-pulsar/12" : "border-halo bg-nebula"
            }`}
          >
            <span className="flex w-full items-center justify-between gap-2">
              <span className="truncate text-[12px] font-medium text-starlight">
                {group.name}
              </span>
              {runs.length > 0 && (
                <span
                  className="flex shrink-0 items-center gap-1 font-mono text-[10px]"
                  style={{ color: "var(--color-status-ok)" }}
                  title={
                    runs.length > 1
                      ? `This group has run ${runs.length} times in this session`
                      : "This group has already run in this session"
                  }
                >
                  <Check size={11} strokeWidth={2} />
                  ran {runs.map((run) => clockOf(run.startedAt)).join(", ")}
                </span>
              )}
            </span>
            <span className="font-mono text-[10px] leading-relaxed text-static">
              {animals.map((a) => `${a.name || "unnamed"} → box ${a.boxNumber}`).join(" · ")}
            </span>
          </motion.button>
        );
      })}
    </div>
  );
}

/** A stored ISO timestamp as local `HH:MM`, or the raw text if it won't parse. */
function clockOf(iso: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}
