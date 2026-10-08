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
      <div className="px-4 py-3.5">
        <p className="pb-2 text-[12px] leading-relaxed text-static">
          How the status display draws your boxes — the widget at the foot of the
          sidebar and the Dashboard&rsquo;s sky. Pure presentation: nothing here
          changes how the rig is wired.
        </p>
        {chosen ? (
          // The board sits on its own inset so the drag surface reads as a
          // surface — a chart in a tile, not stars loose on the glass.
          <div className="surface-inset rounded-md px-4 pb-2 pt-3">
            <div className="mx-auto max-w-[460px]">
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
              {chosen.name} — drag a box to a different star to rearrange
            </p>
          </div>
        ) : (
          <p className="pb-2 text-[12px] leading-relaxed text-static">
            No constellation chosen yet — the status display uses the plain
            layout. Pick one below.
          </p>
        )}
        <div className="mt-3">
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
