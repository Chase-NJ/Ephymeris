import { motion } from "framer-motion";
import { ArrowRight, Dices, RotateCcw, X } from "lucide-react";
import { useMemo, type ReactNode } from "react";

import { HudPanel, HudSection } from "@/components/common/HudPanel";
import { Button, Toggle } from "@/components/common/controls";
import {
  PLANET_TYPES,
  PLANET_TYPE_LABEL,
  derivedAppearance,
  planetPalette,
  rerollSeed,
  type PlanetType,
  type ResolvedAppearance,
} from "@/lib/cohorts/appearance";
import type { Animal, CohortSummary } from "@/lib/cohorts/types";

/**
 * The focused cohort's panel: who is in it, and what its world looks like.
 *
 * Docked beside the planet rather than living in the cohort editor, because you
 * are tuning the thing you are looking at, at the size you will see it — a hue
 * chosen against a 64px preview is a hue chosen for a different object. It
 * follows the scene's existing grammar, where focusing a star docks a panel and
 * the camera composes the frame around it (`docksPanel`).
 *
 * **It stops short of the bottom of the window.** A panel that runs edge to
 * edge reads as a sidebar — a permanent fixture — and this is a card about one
 * thing you clicked. The scene's pan legend also lives down there.
 *
 * **Edits are live and unsaved until Save.** The uniforms update every frame
 * (`PlanetarySurface` mutates rather than rebuilds), so dragging the hue turns
 * the real world in real time — but a drag is not a decision, and writing on
 * every step would put a `cohorts.update` and a `cohorts.updated` broadcast
 * behind each pixel of slider travel.
 */
export function AppearancePanel({
  cohort,
  animals,
  appearance,
  dirty,
  saving,
  error,
  onChange,
  onReset,
  onSave,
  onDiscard,
  onOpen,
  onClose,
}: {
  cohort: CohortSummary;
  /** The roster, once `cohorts.get` has answered; null while it is on its way. */
  animals: Animal[] | null;
  appearance: ResolvedAppearance;
  dirty: boolean;
  saving: boolean;
  error: string | null;
  onChange: (next: ResolvedAppearance) => void;
  /** Back to the world this cohort's id derives — stores `null`. */
  onReset: () => void;
  onSave: () => void;
  onDiscard: () => void;
  /** Into the cohort proper: the roster, groups, data folder. */
  onOpen: () => void;
  onClose: () => void;
}) {
  const palette = useMemo(() => planetPalette(appearance), [appearance]);
  const isDerived = useMemo(
    () => sameWorld(appearance, derivedAppearance(cohort.id)),
    [appearance, cohort.id],
  );

  return (
    <HudPanel className="pointer-events-auto absolute right-4 top-4 flex w-[400px] max-h-[calc(100%-6rem)] flex-col gap-3">
      <header className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-display text-[17px] text-starlight">
            {cohort.name}
          </h2>
          <p className="mt-0.5 font-mono text-[10px] text-static">
            {plural(cohort.animalCount, "animal")} · {plural(cohort.cageCount, "cage")} ·{" "}
            {plural(cohort.groupCount, "group")}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          title="Back to the sky (Esc)"
          aria-label="Back to the sky"
          className="shrink-0 rounded-sm p-1 text-static transition-colors hover:text-starlight"
        >
          <X size={14} strokeWidth={1.75} />
        </button>
      </header>

      <Button variant="primary" onClick={onOpen} className="w-full justify-center">
        Open cohort
        <ArrowRight size={13} strokeWidth={1.75} />
      </Button>

      {/* The roster. Scrolls inside its own box, so a 24-animal cohort does
          not push the world controls off the bottom of the card — the thing
          you came to this panel for stays reachable whatever the roster. */}
      <HudSection
        title="Animals"
        headerRight={
          animals ? (
            <span className="font-mono text-[10px] text-static/70">
              {animals.filter((a) => a.boxNumber !== null).length} boxed
            </span>
          ) : null
        }
        className="flex min-h-0 shrink flex-col"
      >
        <Roster animals={animals} />
      </HudSection>

      <HudSection
        title="World"
        headerRight={
          <span className="font-mono text-[10px] text-static/70">
            {isDerived ? "derived from id" : "custom"}
          </span>
        }
        className="shrink-0"
      >
        <div className="flex flex-col gap-3.5 p-3">
          <Field label="Type">
            <div className="flex flex-wrap gap-1">
              {PLANET_TYPES.map((type) => (
                <TypeChip
                  key={type}
                  type={type}
                  hue={appearance.hue}
                  active={type === appearance.type}
                  onSelect={() => onChange({ ...appearance, type })}
                />
              ))}
            </div>
          </Field>

          <Field
            label="Hue"
            right={
              <span className="font-mono text-[10px] text-static/70">
                {Math.round(appearance.hue)}°
              </span>
            }
          >
            {/* A native range: the one control in the app whose value is a
                continuous quantity the user is HUNTING for rather than
                entering, and a number field would make finding a colour a
                typing exercise. The track is the thing it selects from. */}
            <input
              type="range"
              min={0}
              max={359}
              step={1}
              value={Math.round(appearance.hue)}
              aria-label="Hue"
              onChange={(e) => onChange({ ...appearance, hue: Number(e.target.value) })}
              className="hue-range h-2 w-full cursor-pointer appearance-none rounded-full"
              style={{ background: HUE_TRACK }}
            />
            <div className="mt-2 flex items-center gap-1">
              {[palette.deep, palette.edge, palette.core, palette.peak, palette.accent].map(
                (colour, i) => (
                  <span
                    key={i}
                    title={SWATCH_LABEL[i]}
                    className="h-3.5 flex-1 rounded-sm border border-halo"
                    style={{ background: colour.getStyle() }}
                  />
                ),
              )}
            </div>
          </Field>

          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[12px] text-starlight">Ring</div>
              <div className="text-[10px] text-static/70">A dust plane and its debris.</div>
            </div>
            <Toggle
              checked={appearance.ring}
              onChange={(ring) => onChange({ ...appearance, ring })}
              label="Ring"
            />
          </div>

          <div className="flex items-center gap-2 border-t border-halo pt-3">
            <Button variant="secondary" onClick={() => onChange(rerollSeed(appearance))}>
              <Dices size={13} strokeWidth={1.75} />
              Re-roll weather
            </Button>
            {!isDerived && (
              <Button
                variant="ghost"
                onClick={onReset}
                title="Back to the world this cohort's id draws"
              >
                <RotateCcw size={12} strokeWidth={1.75} />
                Reset
              </Button>
            )}
          </div>
          <p className="text-[10px] leading-relaxed text-static/70">
            A re-roll moves the weather and nothing else — type, hue and size
            stay, so a cohort you already recognise stays recognisable.
          </p>
        </div>
      </HudSection>

      {/* The save bar exists only while there is something to save, and it is
          the one loud thing on the card when it does: an unsaved hue is easy
          to walk away from, and walking away drops it. */}
      {(dirty || error) && (
        <div className="flex shrink-0 items-center justify-between gap-2 rounded-md border border-halo bg-void/40 px-3 py-2">
          {error ? (
            <span className="min-w-0 flex-1 truncate text-[11px] text-status-error">
              {error}
            </span>
          ) : (
            <span className="min-w-0 flex-1 truncate text-[11px] text-static">
              Unsaved changes to this world
            </span>
          )}
          {dirty && (
            <>
              <Button variant="ghost" onClick={onDiscard} disabled={saving}>
                Discard
              </Button>
              <Button variant="primary" onClick={onSave} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </>
          )}
        </div>
      )}
    </HudPanel>
  );
}

/**
 * The roster rows. Cage first, because the ships outside are cages and this
 * is where the eye goes to check "which ship is which"; box after, because a
 * boxed animal is the one that can run.
 */
function Roster({ animals }: { animals: Animal[] | null }) {
  if (animals === null) {
    return (
      <p className="px-3 py-2.5 font-mono text-[10px] text-static/60">loading the roster…</p>
    );
  }
  if (animals.length === 0) {
    return (
      <p className="px-3 py-2.5 text-[11px] leading-relaxed text-static">
        No animals yet. Open the cohort to add them.
      </p>
    );
  }
  const sorted = [...animals].sort(
    (a, b) => (a.cage ?? 99) - (b.cage ?? 99) || a.name.localeCompare(b.name),
  );
  return (
    <div className="scrollbar-slim min-h-0 max-h-[168px] overflow-y-auto">
      {sorted.map((animal) => (
        <div
          key={animal.id}
          className="flex items-center gap-2 border-b border-halo/60 px-3 py-1 text-[11px] last:border-b-0"
        >
          <span className="min-w-0 flex-1 truncate text-starlight">{animal.name}</span>
          <span className="shrink-0 font-mono text-[10px] text-static">
            {animal.sex ?? "—"}
          </span>
          <span
            className="w-[52px] shrink-0 text-right font-mono text-[10px] text-static"
            title="Home cage"
          >
            {animal.cage !== null ? `cage ${animal.cage}` : "no cage"}
          </span>
          <span
            className={`w-[44px] shrink-0 text-right font-mono text-[10px] ${
              animal.boxNumber !== null ? "text-pulsar" : "text-static/50"
            }`}
            title="Assigned box"
          >
            {animal.boxNumber !== null ? `box ${animal.boxNumber}` : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

/** A type chip carries a swatch of what it would look like AT THIS HUE, so
 *  choosing one is a comparison rather than a guess. */
function TypeChip({
  type,
  hue,
  active,
  onSelect,
}: {
  type: PlanetType;
  hue: number;
  active: boolean;
  onSelect: () => void;
}) {
  const swatch = useMemo(
    () => planetPalette({ type, hue, ring: false, seed: 0 }),
    [type, hue],
  );
  return (
    <motion.button
      type="button"
      onClick={onSelect}
      whileTap={{ scale: 0.97 }}
      aria-pressed={active}
      className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] transition-colors ${
        active
          ? "border-pulsar bg-pulsar/18 text-starlight"
          : "border-halo text-static hover:border-static/60 hover:text-starlight"
      }`}
    >
      <span
        aria-hidden
        className="size-2.5 shrink-0 rounded-full border border-halo"
        style={{
          background: `linear-gradient(135deg, ${swatch.core.getStyle()} 50%, ${swatch.edge.getStyle()} 50%)`,
        }}
      />
      {PLANET_TYPE_LABEL[type]}
    </motion.button>
  );
}

function Field({
  label,
  right,
  children,
}: {
  label: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="font-mono text-[10px] uppercase tracking-wider text-static">
          {label}
        </span>
        {right}
      </div>
      {children}
    </div>
  );
}

function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

const SWATCH_LABEL = ["deep ground", "lowland", "upland", "peaks", "accent"];

/** The full circle, so the slider's track is the thing it selects from. */
const HUE_TRACK = `linear-gradient(to right, ${Array.from(
  { length: 13 },
  (_, i) => `hsl(${i * 30} 45% 55%)`,
).join(", ")})`;

function sameWorld(a: ResolvedAppearance, b: ResolvedAppearance): boolean {
  return (
    a.type === b.type &&
    a.ring === b.ring &&
    Math.round(a.hue) === Math.round(b.hue) &&
    Math.floor(a.seed) === Math.floor(b.seed)
  );
}
