import type { SketchDiscovery } from "@/lib/settings/schema";

import { LibraryStatusNote } from "./LibraryStatusNote";

/**
 * The bundled sketch library as a browsable list — categories, sketches, and
 * which ones this rig has tuned.
 *
 * A list rather than the old dropdown, because the library ships with the app
 * and is a dozen entries the operator returns to: a `<Select>` answers "pick
 * one from many", this answers "what is here, what have I changed, where was
 * I". The `N tuned` chip is the part the dropdown could never say — it is
 * read from `settings.taskDefaults`, so the operator can see at a glance
 * which sketches carry rig overrides without opening each one.
 *
 * One `<button>` per sketch (real focus, real Enter), selected row lit the
 * way the sidebar lights its active tab — same `bg-pulsar/18` material, since
 * this list *is* navigation within the page.
 */
export function SketchLibrary({
  discovery,
  selected,
  tuned,
  onSelect,
  onRefresh,
  canRefresh,
}: {
  discovery: SketchDiscovery;
  selected: string | null;
  /** Sketch folder name → count of saved overrides (`settings.taskDefaults`). */
  tuned: Map<string, number>;
  onSelect: (path: string) => void;
  onRefresh: () => void;
  canRefresh: boolean;
}) {
  // Categories in discovery order — the sidecar walks the library in its
  // on-disk order, which is the numbered-folder order the lab authored.
  const categories: Array<{ name: string; sketches: typeof discovery.sketches }> = [];
  for (const sketch of discovery.sketches) {
    const bucket = categories.find((c) => c.name === sketch.category);
    if (bucket) bucket.sketches.push(sketch);
    else categories.push({ name: sketch.category, sketches: [sketch] });
  }

  return (
    <div className="hud rounded-md p-3">
      <div className="flex items-baseline justify-between gap-2 px-1">
        <span className="text-[11px] text-static">Library</span>
        <span className="font-mono text-[9px] tabular-nums text-static/70">
          {discovery.sketches.length} sketch{discovery.sketches.length === 1 ? "" : "es"}
        </span>
      </div>

      {/* Capped and scrollable so the sticky column (tile above, this card,
          the status note) always fits a viewport — a sticky column taller
          than the screen stops sticking exactly when the operator is deepest
          in the parameters, which is when the tile matters most. */}
      <div className="scrollbar-none mt-1.5 flex max-h-[38vh] flex-col gap-2 overflow-y-auto">
        {categories.map((category) => (
          <div key={category.name}>
            <div className="px-1 font-mono text-[9px] tracking-wider text-static/60 uppercase">
              {category.name}
            </div>
            <div className="mt-0.5 flex flex-col">
              {category.sketches.map((sketch) => {
                const active = sketch.path === selected;
                const overrides = tuned.get(sketch.name) ?? 0;
                return (
                  <button
                    key={sketch.path}
                    type="button"
                    onClick={() => onSelect(sketch.path)}
                    aria-pressed={active}
                    className={`flex items-center gap-2 rounded-sm px-2 py-1 text-left transition-colors ${
                      active
                        ? "bg-pulsar/18 text-starlight"
                        : "text-static hover:bg-halo/50 hover:text-starlight"
                    }`}
                  >
                    <span className="min-w-0 flex-1 truncate text-[12px]">
                      {sketch.name}
                    </span>
                    {overrides > 0 && (
                      <span
                        className="shrink-0 font-mono text-[9px] tabular-nums text-pulsar"
                        title={`${overrides} parameter${overrides === 1 ? "" : "s"} saved off the sketch's own values on this rig`}
                      >
                        {overrides} tuned
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
        {discovery.sketches.length === 0 && (
          <p className="px-1 text-[11px] leading-relaxed text-static">
            No sketches found in the bundled library.
          </p>
        )}
      </div>

      <LibraryStatusNote
        discovery={discovery}
        onRefresh={onRefresh}
        canRefresh={canRefresh}
      />
    </div>
  );
}
