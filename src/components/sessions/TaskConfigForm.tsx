import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { Select } from "@/components/common/controls";
import { ConfigFields } from "@/components/sessions/ConfigFields";
import { springSnappy } from "@/lib/motion";
import type { TaskProfile } from "@/lib/sessions/types";
import { QUICK_TUNE_GROUPS } from "@/lib/tasks/topology";

/**
 * Per-box pre-flight config form (`dashboard.md` §7.3).
 *
 * Fields, labels and defaults come straight from the sketch's Task Profile
 * `config` array (`tasks.md` §3.2) — the app knows nothing task-specific.
 * A sketch with no profile renders nothing at all, and gets a bare `START`.
 *
 * Collapsed by default, and that is the point: this is the *override* layer
 * (§6.9). A behaviour sketch now declares forty-odd fields, and six of those
 * expanded inline would bury the mapping step's actual job — choosing a sketch
 * per animal — under two hundred inputs. The summary line says how many values
 * differ from the rig's defaults for this animal, which is the only thing an
 * operator needs to see at a glance.
 *
 * Opened, the pane leads with **Quick tune** — the `QUICK_TUNE_GROUPS`
 * registry's groups (correction budgets, the lazy-penalty escalation),
 * ordered by how often the lab actually turns them at setup rather than by
 * when they act in a trial. Everything else sits behind them under "all
 * parameters", in the sketch's own order, each group appearing exactly once:
 * the quick strip *removes* its groups from the long list rather than
 * repeating them, because a field shown twice in one form reads as two
 * settings even while shared state keeps them honest.
 */
export function TaskConfigForm({
  profile,
  config,
  baseline,
  onChange,
  disabled = false,
}: {
  profile: TaskProfile | null;
  config: Record<string, unknown>;
  /** This rig's saved defaults for the sketch — what "overridden" is measured against. */
  baseline: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (!profile || profile.config.length === 0) return null;

  const overridden = profile.config.filter(
    (f) => f.metadataKey in config && !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
  ).length;

  // Which quick-tune groups this profile actually declares — a profile with
  // neither renders exactly the old single list.
  const promoted = QUICK_TUNE_GROUPS.filter((group) =>
    profile.config.some((field) => field.group === group),
  );
  // The header's second glance: how many of the overrides are quick-tune ones,
  // so "2 overridden" on a collapsed card already says whether it is the usual
  // pair of knobs or something deeper.
  const quickOverridden = profile.config.filter(
    (f) =>
      f.group !== undefined &&
      promoted.includes(f.group) &&
      f.metadataKey in config &&
      !Object.is(config[f.metadataKey], baseline[f.metadataKey]),
  ).length;

  return (
    <div className="mt-2 flex flex-col gap-1.5 border-t border-halo pt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 text-left"
      >
        <motion.span animate={{ rotate: open ? 90 : 0 }} transition={springSnappy} className="flex">
          <ChevronRight size={11} strokeWidth={1.75} className="text-static" />
        </motion.span>
        <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-static">
          {profile.taskName}
        </span>
        <span className={`text-[10px] ${overridden > 0 ? "text-pulsar" : "text-static/70"}`}>
          {overridden > 0
            ? `${overridden} overridden${
                quickOverridden > 0 && quickOverridden < overridden
                  ? ` · ${quickOverridden} quick`
                  : quickOverridden === overridden && overridden > 0
                    ? " · quick tune"
                    : ""
              }`
            : `${profile.config.length} parameters`}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={springSnappy}
            className="overflow-hidden"
          >
            {/* Capped and scrolled, not grown. Forty fields open inline made the
                tile as tall as its contents, so one animal's overrides pushed
                the rest of the group's cards off the screen — on the step whose
                whole job is comparing them. The height animation is unchanged:
                Framer measures this pane, and the pane is never taller than the
                cap. The hairline edges are what make a list cut mid-field read
                as a scroll region rather than a clipping bug. */}
            <div className="my-1 max-h-[min(46vh,380px)] overflow-y-auto border-y border-halo py-2 pr-1">
              {promoted.length > 0 && (
                <div className="mb-3">
                  {/* A matte left rule, not a glow: promoted is an ordering
                      claim, and the accent stays desaturated per the theme. */}
                  <div className="border-l-2 border-pulsar/50 pl-2.5">
                    <div className="mb-1.5 font-mono text-[9px] tracking-wider text-static/70 uppercase">
                      Quick tune
                      <span className="ml-2 normal-case tracking-normal text-static/50">
                        the values turned per animal, per day
                      </span>
                    </div>
                    <div className="flex flex-col gap-3">
                      {promoted.map((group) => (
                        <section key={group}>
                          <div className="mb-1 border-b border-halo pb-1 font-mono text-[10px] tracking-wider text-static uppercase">
                            {group}
                          </div>
                          <ConfigFields
                            profile={profile}
                            config={config}
                            baseline={baseline}
                            onChange={onChange}
                            disabled={disabled}
                            only={group}
                          />
                        </section>
                      ))}
                    </div>
                  </div>
                  <div className="mt-3 mb-1 font-mono text-[9px] tracking-wider text-static/50 uppercase">
                    All parameters
                    <span className="ml-2 normal-case tracking-normal">
                      as the sketch declares them
                    </span>
                  </div>
                </div>
              )}
              <ConfigFields
                profile={profile}
                config={config}
                baseline={baseline}
                onChange={onChange}
                disabled={disabled}
                exclude={promoted}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Sketch picker scoped to one box, grouped by category (§3). */
export function SketchPicker({
  sketches,
  value,
  onChange,
  label,
  disabled = false,
  className = "",
}: {
  sketches: Array<{ category: string; name: string; path: string }>;
  value: string | null;
  onChange: (path: string | null) => void;
  label: string;
  disabled?: boolean;
  /** Layout-only — forwarded to the underlying Select. */
  className?: string;
}) {
  const options = [
    { value: "", label: "— select a sketch —" },
    ...sketches.map((s) => ({ value: s.path, label: `${s.category} / ${s.name}` })),
  ];
  return (
    <Select
      label={label}
      value={value ?? ""}
      options={options}
      onChange={(v) => onChange(v === "" ? null : String(v))}
      disabled={disabled}
      // The flow is waiting on exactly this control until a sketch is picked —
      // but not while it's locked, when waiting on it would be a lie.
      attention={value === null && !disabled}
      className={className}
    />
  );
}
