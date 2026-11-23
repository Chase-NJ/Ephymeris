import { Dices } from "lucide-react";

import { Button, NumberInput, Segmented } from "@/components/common/controls";
import { Panel } from "@/features/tasks/editor/Panel";
import {
  ANIMAL_FIELDS,
  FALLBACKS,
  PRESETS,
  presetOf,
  withSetting,
  type Animal,
  type AnimalField,
} from "./animals";

const GROUPS = ["Strategy", "Engagement", "Impulsivity and speed"] as const;

/**
 * Who is in the box: a preset to start from, then every setting of the animal,
 * and the session it is run for (`TASKS.md#the-simulated-animal`). Changing
 * anything reruns the session on the same seed, so two animals meet the same
 * draws; the dice deal a new one.
 */
export function AnimalPanel({
  animal,
  onAnimal,
  seed,
  onNewSeed,
  limitMinutes,
  onLimitMinutes,
  running,
}: {
  animal: Animal;
  onAnimal: (next: Animal) => void;
  seed: number | null;
  onNewSeed: () => void;
  limitMinutes: number;
  onLimitMinutes: (minutes: number) => void;
  running: boolean;
}) {
  const preset = presetOf(animal);
  const guesses = animal.followsOdorEnd < 1 || animal.learningTrials > 0;

  return (
    <Panel
      id="sim-animal"
      name="Simulated animal"
      note={running ? "running…" : (preset?.label ?? "custom")}
      className="min-h-0 flex-1"
      bodyClassName="scrollbar-slim min-h-0 flex-1 overflow-y-auto"
    >
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Animal presets">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onAnimal(p.animal)}
            aria-pressed={preset?.id === p.id}
            title={p.blurb}
            className={`rounded-sm border px-2 py-1 text-[11px] transition-colors ${
              preset?.id === p.id
                ? "border-pulsar bg-pulsar/15 text-starlight"
                : "border-halo text-static hover:border-static/70 hover:text-starlight"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>
      <p className="mt-2 min-h-[2.4em] text-[11px] leading-snug text-static">
        {preset?.blurb ?? "An animal of your own. It senses the light, the odor and water, never a task setting."}
      </p>

      {GROUPS.map((group) => (
        <section key={group} className="mt-3 border-t border-halo/60 pt-2.5">
          <h3 className="m-0 font-mono text-[9px] tracking-[0.16em] text-static/80 uppercase">{group}</h3>
          {ANIMAL_FIELDS.filter((field) => field.group === group).map((field) => (
            <SettingRow
              key={field.key}
              field={field}
              value={animal[field.key]}
              onChange={(value) => onAnimal(withSetting(animal, field.key, value))}
            />
          ))}
          {group === "Strategy" && guesses && (
            <div className="mt-2 flex items-center justify-between gap-2">
              <span className="text-[11px] text-static" title="What it does when it is not answering by the odor.">
                Otherwise
              </span>
              <Segmented
                label="What it does when it is not answering by the odor"
                value={animal.fallback}
                options={FALLBACKS}
                onChange={(fallback) => onAnimal({ ...animal, fallback })}
              />
            </div>
          )}
        </section>
      ))}

      <section className="mt-3 border-t border-halo/60 pt-2.5">
        <h3 className="m-0 font-mono text-[9px] tracking-[0.16em] text-static/80 uppercase">Session</h3>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-[11px] text-static" title="The session's time limit: STOP is sent then, and the box ends at its next trial boundary.">
            Time limit
          </span>
          <span className="flex items-center gap-1.5">
            <NumberInput
              value={limitMinutes}
              fallback={60}
              integer
              min={1}
              max={240}
              onChange={(minutes) => onLimitMinutes(minutes)}
              label="Session time limit in minutes"
              className="w-20"
            />
            <span className="font-mono text-[10px] text-static">min</span>
          </span>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-[11px] text-static" title="The trial seed: the same seed deals the same draws, to the board and to the animal.">
            Seed
          </span>
          <span className="flex items-center gap-1.5">
            <span className="font-mono text-[11px] tabular-nums text-starlight">{seed ?? "—"}</span>
            <Button variant="outline" shape="icon" onClick={onNewSeed} title="Run again on a new seed" label="New seed">
              <Dices size={13} strokeWidth={1.75} />
            </Button>
          </span>
        </div>
      </section>
    </Panel>
  );
}

function SettingRow({
  field,
  value,
  onChange,
}: {
  field: AnimalField;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="mt-2 grid grid-cols-[104px_minmax(0,1fr)_64px] items-center gap-2" title={field.help}>
      <span className="text-[11px] text-static">{field.label}</span>
      <input
        type="range"
        min={field.min}
        max={field.max}
        step={field.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="hue-range h-1 w-full cursor-pointer appearance-none rounded-full bg-halo"
      />
      <span className="text-right font-mono text-[11px] tabular-nums text-starlight">{field.show(value)}</span>
    </label>
  );
}
