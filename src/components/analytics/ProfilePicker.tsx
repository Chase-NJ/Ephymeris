import { Dropdown, type DropdownOption } from "@/components/common/Dropdown";
import type { StrategyProfile } from "@/lib/analytics/view";

/**
 * Which task profile the strategy plane is showing.
 *
 * **The list is what the cohort's data actually contains**, not a list of tasks
 * the app knows about: sessions recorded on this rig, sessions copied from
 * another and decoded from their own embedded snapshot (`DATA.md#the-embedded-task-profile`), and
 * runs whose conditions were inferred from the strobes because no profile
 * resolved. All three are real profiles with real runs, so all three are here.
 *
 * **Profiles that cannot make a plane are shown and disabled, never hidden.**
 * A picker that silently omitted them would answer "why isn't my four-odor task
 * here" with an absence, which reads as a bug in the archive rather than as a
 * property of the task. Each carries its reason instead.
 *
 * A `Dropdown` rather than the `Segmented` this replaced: segments were fine
 * while the only eligible profiles were the one or two that declared exactly
 * two conditions, and they overflow the moment a cohort holds half a dozen —
 * which is now the normal case, since every distinct tuning of a task is its
 * own comparability set.
 */
export function ProfilePicker({
  profiles,
  value,
  onChange,
  labels,
}: {
  profiles: StrategyProfile[];
  value: string;
  onChange: (hash: string) => void;
  /** Profile hash → program name (`taskLabels`), which now prefers the name a
   *  run RECORDED over the path this machine resolved (`DATA.md#which-profile-decodes-a-run`). */
  labels: Map<string, string>;
}) {
  if (profiles.length <= 1) return null;

  const options: DropdownOption[] = profiles.map(({ group, axes, reason }) => {
    const runs = `${group.runCount} run${group.runCount === 1 ? "" : "s"}`;
    return {
      value: group.hash,
      label: labels.get(group.hash) ?? group.taskName ?? "unknown program",
      // The second name a binding has, the same slot the trial table's pickers
      // use: how much data is behind it, and what it can and cannot draw.
      detail: axes ? `${runs} · ${planeShape(axes)}` : `${runs} · ${reason}`,
      disabled: axes === null,
    };
  });

  return (
    <Dropdown
      value={value}
      options={options}
      placeholder="choose a task…"
      label="Task profile on the strategy plane"
      className="min-w-[13rem]"
      onChange={onChange}
    />
  );
}

function planeShape(axes: NonNullable<StrategyProfile["axes"]>): string {
  const total = axes.x.ids.length + axes.y.ids.length;
  return `${total} condition${total === 1 ? "" : "s"} on 2 axes`;
}
