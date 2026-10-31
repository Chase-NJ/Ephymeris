import { Orbit } from "lucide-react";
import { useMemo } from "react";

import { NODE_FILL, type BoxHealth } from "@/components/chrome/ConstellationStatus";
import { HudTile } from "@/components/common/HudTile";
import { ConstellationBoard } from "@/components/config/ConstellationBoard";
import { ConstellationPicker } from "@/components/config/ConstellationPicker";
import { reconcileSlots } from "@/lib/constellations/slots";
import { zodiacById } from "@/lib/constellations/zodiac";
import type { BoxBinding, EphymerisSettings } from "@/lib/settings/schema";

/**
 * Which zodiac the status display draws, and which star each box sits on
 * (`ARCHITECTURE.md#status-constellation`).
 *
 * On the Rig tab, beside the boxes it draws: the board below is those boxes,
 * lit with the same health the Boxes tile reports, so choosing a sky and
 * binding a board are one sitting. Pure presentation still — nothing here
 * changes how the rig is wired — and the slot map follows box add/remove on
 * its own (`Config.onBoxesChange` reconciles it), so the tile can be ignored
 * forever and stay honest.
 */
export function ConstellationTile({
  boxes,
  constellation,
  constellationSlots,
  health,
  onChange,
}: {
  boxes: BoxBinding[];
  constellation: string | null;
  constellationSlots: EphymerisSettings["constellationSlots"];
  health: Partial<Record<number, BoxHealth>>;
  onChange: (
    patch: Partial<Pick<EphymerisSettings, "constellation" | "constellationSlots">>,
  ) => void;
}) {
  const bound = useMemo(
    () => boxes.filter((b) => b.hardwareId !== null).map((b) => b.box),
    [boxes],
  );
  const labels = useMemo(
    () => Object.fromEntries(boxes.map((b) => [b.box, b.label])),
    [boxes],
  );
  const chosen = zodiacById(constellation);

  function onPick(id: string) {
    const next = zodiacById(id);
    if (!next) return;
    onChange({
      constellation: id,
      constellationSlots: reconcileSlots(next, constellationSlots, bound),
    });
  }

  return (
    <HudTile
      icon={Orbit}
      label="Constellation"
      status={<ConstellationFact name={chosen?.name ?? null} bound={bound} health={health} />}
    >
      {/* Board beside picker, not above it: stacked, the two filled a screen
          and pushed the rest of the Rig tab below the fold for a choice made
          once. The board keeps a fixed height so any sky fits the same box. */}
      <div className="grid grid-cols-[220px_minmax(0,1fr)] gap-4 px-4 py-3">
        {/* The board sits on its own inset so the drag surface reads as a
            surface — a chart in a tile, not stars loose on the glass. */}
        <div className="surface-inset flex flex-col rounded-md px-2 pb-1.5 pt-2">
          {chosen ? (
            <>
              <div className="h-[132px]">
                <ConstellationBoard
                  constellation={chosen}
                  slots={constellationSlots}
                  boxes={bound}
                  labels={labels}
                  health={health}
                  onSlotsChange={(next) => onChange({ constellationSlots: next })}
                />
              </div>
              <p className="mt-1 text-center font-mono text-[10px] text-static/70">
                drag a box to another star
              </p>
            </>
          ) : (
            <p className="m-auto px-2 text-center text-[11px] leading-relaxed text-static">
              No constellation yet — the status display uses the plain layout.
            </p>
          )}
        </div>
        <div className="min-w-0">
          <p className="pb-2 text-[12px] leading-snug text-static">
            How the sidebar widget and the Dashboard&rsquo;s sky draw your
            boxes. Presentation only — nothing here changes the wiring.
          </p>
          <ConstellationPicker
            selected={constellation}
            boxCount={bound.length}
            onSelect={onPick}
          />
        </div>
      </div>
    </HudTile>
  );
}

/**
 * The tile's fact: the chosen sky, and the bound boxes as the same health dots
 * the sidebar widget and the Boxes tile draw (`NODE_FILL`, four states). The
 * board lights its nodes from the same map, so the corner is a preview of the
 * drawing, not a second opinion.
 */
function ConstellationFact({
  name,
  bound,
  health,
}: {
  name: string | null;
  bound: readonly number[];
  health: Partial<Record<number, BoxHealth>>;
}) {
  return (
    <>
      {bound.length > 0 && (
        <span className="flex items-center gap-1" aria-hidden>
          {bound.map((box) => (
            <span
              key={box}
              className="size-1.5 rounded-full"
              style={{ background: NODE_FILL[health[box] ?? "absent"] }}
            />
          ))}
        </span>
      )}
      <span className={name ? "text-starlight" : undefined}>
        {name ?? "plain layout"}
        {bound.length > 0 && (
          <span className="text-static">
            {" · "}
            {bound.length} {bound.length === 1 ? "box" : "boxes"}
          </span>
        )}
      </span>
    </>
  );
}
