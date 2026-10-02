import { motion } from "framer-motion";
import { Plus, Rocket, X } from "lucide-react";
import { useMemo, useState, type DragEvent } from "react";

import type { Animal } from "@/lib/cohorts/types";
import { springSnappy } from "@/lib/motion";

/**
 * Cage assignment as a boarding scene — the `cage` field of
 * `DATA.md#data-model`.
 *
 * Every animal is a crew chip; every cage is a spaceship. Drag a chip aboard
 * the ship its animal is housed in (or click the chip, then the ship — a
 * trackpad-friendly fallback for the same move), and add ships as the rack
 * grows. The metaphor is the 3D constellation's, on purpose: cagemates
 * boarded together here ride one craft in orbit there, so this panel is
 * literally crewing the fleet the sky will draw.
 *
 * Assignment is optional and never gates anything. An animal left on the dock
 * simply flies solo, exactly as every animal did before cages existed.
 *
 * > [!IMPORTANT]
 * > **The drag half of this only works because `dragDropEnabled` is `false`**
 * > in `src-tauri/tauri.conf.json`. Tauri defaults it to `true`, which hands
 * > the webview's drag-and-drop to the OS-level file-drop handler and swallows
 * > HTML5 DnD entirely — Tauri's own schema says disabling it "is required to
 * > use HTML5 drag and drop on the frontend on Windows", which is what the lab
 * > runs. The failure is quiet and *partial*: `dragstart` and `dragover` still
 * > fire, so the chip looks draggable and the ship even highlights, but `drop`
 * > never arrives and the animal springs back. It reads as a CSS or React bug
 * > and is neither. The click-to-board path below is unaffected, which is
 * > exactly why it kept working while this didn't.
 * >
 * > A JSON config file can't carry a comment, hence this one. If drag ever
 * > silently stops working again, check that key first.
 *
 * Ships are identified by their cage *number*, which is the stored fact; an
 * empty ship (just added, or just emptied) exists only in this component's
 * state, because a cage with no animals in it isn't a fact the roster can
 * carry — `cage` lives on the animal.
 */
export function CageAssignment({
  animals,
  onChange,
}: {
  animals: Animal[];
  onChange: (next: Animal[]) => void;
}) {
  // Empty ships the user has added (or emptied) this visit — merged with the
  // cages the roster actually holds, so a saved cohort reopens with its fleet.
  const [emptyShips, setEmptyShips] = useState<number[]>([]);
  // Click-to-board fallback: the chip picked up, awaiting a ship click.
  const [carried, setCarried] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<number | "dock" | null>(null);

  const ships = useMemo(() => {
    const cages = new Set<number>(emptyShips);
    for (const a of animals) if (a.cage !== null) cages.add(a.cage);
    return [...cages].sort((a, b) => a - b);
  }, [animals, emptyShips]);

  const dock = animals.filter((a) => a.cage === null);
  const nextCage = ships.length > 0 ? Math.max(...ships) + 1 : 1;

  function board(animalId: string, cage: number | null) {
    onChange(animals.map((a) => (a.id === animalId ? { ...a, cage } : a)));
    setCarried(null);
    setDragOver(null);
  }

  function dropHandlers(target: number | "dock") {
    return {
      onDragOver: (event: DragEvent) => {
        event.preventDefault();
        setDragOver(target);
      },
      onDragLeave: () => setDragOver((over) => (over === target ? null : over)),
      onDrop: (event: DragEvent) => {
        event.preventDefault();
        const id = event.dataTransfer.getData("text/plain");
        if (id) board(id, target === "dock" ? null : target);
      },
    };
  }

  /** Click-to-board: with a chip in hand, clicking a zone places it. */
  function clickTarget(target: number | "dock") {
    if (carried === null) return;
    board(carried, target === "dock" ? null : target);
  }

  if (animals.length === 0) {
    return (
      <p className="px-4 py-3.5 text-[12px] leading-relaxed text-static">
        Add animals above, then drag cagemates aboard a shared spaceship here.
      </p>
    );
  }

  return (
    <div className="px-4 py-3.5">
      <p className="text-[12px] leading-relaxed text-static">
        Drag each animal aboard the spaceship it shares with its cagemates —
        or click an animal, then its ship. Cagemates fly together in the
        constellation; anyone left on the dock flies solo.
      </p>

      {/* The dock: unassigned animals, and the drop target that sends a crew
          member back ashore. */}
      <div
        {...dropHandlers("dock")}
        onClick={() => clickTarget("dock")}
        className="mt-3 rounded-sm border border-dashed px-3 py-2.5 transition-colors"
        style={{
          borderColor:
            dragOver === "dock" ? "var(--color-pulsar)" : "var(--color-halo)",
        }}
      >
        <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-static/70">
          Dock · flying solo
        </div>
        <div className="flex min-h-[26px] flex-wrap gap-1.5">
          {dock.length === 0 && (
            <span className="py-0.5 text-[11px] text-static/60">
              Everyone is aboard a ship.
            </span>
          )}
          {dock.map((animal) => (
            <CrewChip
              key={animal.id}
              animal={animal}
              carried={carried === animal.id}
              onCarry={() => setCarried(carried === animal.id ? null : animal.id)}
            />
          ))}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {ships.map((cage) => {
          const crew = animals.filter((a) => a.cage === cage);
          return (
            <div
              key={cage}
              {...dropHandlers(cage)}
              onClick={() => clickTarget(cage)}
              className="rounded-sm border bg-nebula px-3 py-2.5 transition-colors"
              style={{
                borderColor:
                  dragOver === cage ? "var(--color-pulsar)" : "var(--color-halo)",
              }}
            >
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-[12px] font-medium text-starlight">
                  <Rocket size={13} strokeWidth={1.75} className="text-pulsar" />
                  Ship {cage}
                </span>
                <span className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-static/70">
                    {crew.length === 0
                      ? "no crew"
                      : `${crew.length} ${crew.length === 1 ? "animal" : "animals"}`}
                  </span>
                  {crew.length === 0 && (
                    <button
                      type="button"
                      title={`Scrap ship ${cage}`}
                      aria-label={`Scrap ship ${cage}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        setEmptyShips((s) => s.filter((n) => n !== cage));
                      }}
                      className="text-static transition-colors hover:text-starlight"
                    >
                      <X size={12} strokeWidth={1.75} />
                    </button>
                  )}
                </span>
              </div>
              <div className="mt-2 flex min-h-[26px] flex-wrap gap-1.5">
                {crew.length === 0 && (
                  <span className="py-0.5 text-[11px] text-static/60">
                    Drag animals aboard…
                  </span>
                )}
                {crew.map((animal) => (
                  <CrewChip
                    key={animal.id}
                    animal={animal}
                    carried={carried === animal.id}
                    onCarry={() => setCarried(carried === animal.id ? null : animal.id)}
                  />
                ))}
              </div>
            </div>
          );
        })}

        <button
          type="button"
          onClick={() => setEmptyShips((s) => [...s, nextCage])}
          className="flex min-h-[76px] items-center justify-center gap-1.5 rounded-sm border border-dashed border-halo text-[12px] text-static transition-colors hover:border-pulsar hover:text-starlight"
        >
          <Plus size={13} strokeWidth={1.75} />
          <Rocket size={13} strokeWidth={1.75} />
          Add a spaceship
        </button>
      </div>

      {carried !== null && (
        <p className="mt-2 text-[11px] text-static">
          Now click the ship —{" "}
          <button
            type="button"
            onClick={() => setCarried(null)}
            className="underline decoration-dotted underline-offset-2 hover:text-starlight"
          >
            or put {animals.find((a) => a.id === carried)?.name ?? "them"} down
          </button>
          .
        </p>
      )}
    </div>
  );
}

/**
 * One animal, as a draggable crew chip. `layout` animates the hop between
 * dock and ship on the app's spring rather than teleporting.
 */
function CrewChip({
  animal,
  carried,
  onCarry,
}: {
  animal: Animal;
  carried: boolean;
  onCarry: () => void;
}) {
  return (
    // A plain <button> carries the HTML5 drag: on a motion component,
    // `onDragStart` is framer's pan-gesture prop and the native event would
    // never be heard. The motion wrapper owns only the layout hop.
    <motion.span layout layoutId={`crew-${animal.id}`} transition={springSnappy}>
      <button
        type="button"
        draggable
        onDragStart={(event) => event.dataTransfer.setData("text/plain", animal.id)}
        onClick={(event) => {
          event.stopPropagation();
          onCarry();
        }}
        title={carried ? "Click a ship to board" : "Drag aboard a ship, or click to pick up"}
        className="cursor-grab rounded-full border px-2 py-0.5 font-mono text-[11px] leading-tight transition-colors active:cursor-grabbing"
        style={{
          borderColor: carried ? "var(--color-pulsar)" : "var(--color-halo)",
          color: carried ? "var(--color-starlight)" : "var(--color-static)",
          background: carried
            ? "color-mix(in srgb, var(--color-pulsar) 18%, transparent)"
            : "var(--color-void)",
        }}
      >
        {animal.name || "unnamed"}
      </button>
    </motion.span>
  );
}
