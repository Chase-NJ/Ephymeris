import { motion } from "framer-motion";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import {
  Anchor,
  ArrowRight,
  CircleAlert,
  CircuitBoard,
  Radio,
  SlidersHorizontal,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import {
  NODE_FILL,
  useBoxHealth,
  type BoxHealth,
} from "@/components/chrome/ConstellationStatus";
import { KindStrip } from "@/components/hardware/KindStrip";
import { TextInput } from "@/components/common/controls";
import { Dropdown } from "@/components/common/Dropdown";
import { HudTile } from "@/components/common/HudTile";
import { UtilitySketchPanel } from "@/components/config/UtilitySketchPanel";
import { SettingRow } from "@/components/settings/SettingRow";
import { BoxBindingsTable } from "@/components/settings/BoxBindingsTable";
import { reconcileSlots } from "@/lib/constellations/slots";
import { zodiacById } from "@/lib/constellations/zodiac";
import { getRig } from "@/lib/hardware/commands";
import type { RigDocument } from "@/lib/hardware/types";
import { useUtilityStatus } from "@/lib/hardware/context";
import { useHandshakeTest } from "@/lib/hardware/useHandshakeTest";
import { CASCADE, RISE, springPanel, springSnappy } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { BAUD_RATES, type BoxBinding } from "@/lib/settings/schema";
import { CMD, EVT } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";

/**
 * Rig — everything about this rig's hardware, on one screen (`ARCHITECTURE.md#where-each-setting-is-edited`).
 *
 * **The screen is called Rig; the route and this file are still `config`.** The
 * name is the operator's word for the subject; the path is an internal address
 * the docs and this app's history already spell one way. See `App.tsx`.
 *
 * **A column of HUD tiles now, in the Dashboard's idiom** — frosted glass over
 * the rig's sky, each tile a subject with an icon header and one live fact
 * (`SummaryCard`'s header grammar, `EntranceTile`'s hover vocabulary). Still a
 * scrolling column rather than the Dashboard's fixed columns, because these
 * tiles are *forms*: the bindings table grows a row per box and the baseline
 * panel a chip per box, and a layout that cannot scroll caps the rig.
 *
 * Top to bottom it follows the order a rig comes up in: **Boxes** (bind a box
 * number to a board, name it, watch it come alive — with the handshake test to
 * prove a binding took), **Utility baseline** (the resting firmware and what
 * it is doing right now), **Wiring** (a door now, not a section — the
 * channel→pin editor lives at `/config/wiring` behind it, `RigWiring.tsx`),
 * then the two knobs that rarely move (baud, `arduino-cli`).
 *
 * What is NOT here, and why:
 *
 * - **The constellation board and picker are on Settings.** They style the
 *   status display — which star a box sits on — and never touch the hardware.
 *   `onBoxesChange` still reconciles the slot map, because *this* screen is
 *   where boxes appear and disappear, and the slot map has to follow whether
 *   or not anyone visits Settings.
 * - **There is no setup wizard.** The page itself reads in setup order; first
 *   run lands here with an empty Boxes table and its own "add one for each
 *   box" prompt.
 * - **The wiring editor has its own route.** Binding a box to a board and a
 *   channel to a pin are different wirings — runtime vs compile-time — but one
 *   subject, so the door is here; the editor is a workbench that needs the
 *   width, so the room is `/config/wiring`.
 */
export function Config() {
  const navigate = useNavigate();
  const { settings, update, discovery, loaded, saveError } = useSettings();
  const { client, status } = useSidecar();
  const health = useBoxHealth();
  const handshake = useHandshakeTest();
  const utility = useUtilityStatus();
  const wiring = useWiringSummary();
  const [reflashing, setReflashing] = useState(false);
  const connected = status === "connected";

  const bound = useMemo(
    () => settings.boxes.filter((b) => b.hardwareId !== null),
    [settings.boxes],
  );
  const connectedCount = bound.filter(
    (b) => (health[b.box] ?? "absent") !== "absent",
  ).length;

  /** Box edits keep the constellation slot map honest in the same settings
   * write — the board lives on Settings now, but boxes are added and removed
   * *here*, and a slot map pointing at a box that no longer exists would
   * scramble the status display for everyone who never opens Settings. */
  function onBoxesChange(boxes: BoxBinding[]) {
    const nextBound = boxes
      .filter((b) => b.hardwareId !== null)
      .map((b) => b.box);
    const constellation = zodiacById(settings.constellation);
    void update(
      constellation
        ? {
            boxes,
            constellationSlots: reconcileSlots(
              constellation,
              settings.constellationSlots,
              nextBound,
            ),
          }
        : { boxes },
    );
  }

  /**
   * The one manual restore. `force` is what makes it useful: the automatic
   * paths skip a box already believed to be at baseline, and the reason to
   * press this is usually that the belief is wrong.
   */
  async function reflashBaseline() {
    setReflashing(true);
    try {
      await client.call(CMD.UTILITY_ENSURE, { force: true });
    } catch (err) {
      console.error("utility baseline reflash failed", err);
    } finally {
      setReflashing(false);
    }
  }

  return (
    // Every route sits on the rig's sky. Not decoration: a route that mounts no
    // constellation is the only thing that releases the shared canvas, and that
    // teardown is what made a sidebar round trip snap (`SkyBackdrop`).
    <div className="relative h-full">
      <SkyBackdrop />

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit: the shell holds every page opaque on the way out
        // now, so anything that should fade has to say so (`AppShell`).
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        {/* Wider than the settings screens (max-w-3xl): the bindings table
            wants the room, and the page is a workbench now, not a form. */}
        <section className="pointer-events-auto mx-auto max-w-5xl px-10 py-9">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <Radio size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <div className="min-w-0">
              <h1 className="font-display text-[22px] text-starlight">Rig</h1>
              <p className="font-mono text-[10px] text-static/70">
                which board is box 3, what it rests on, and what every pin does
              </p>
            </div>
          </div>

          {saveError && (
            <div
              className="mt-4 flex items-center gap-2 rounded-sm border border-halo px-3 py-2 text-[12px]"
              style={{ color: "var(--color-status-error)" }}
            >
              <CircleAlert size={14} strokeWidth={1.75} />
              {saveError}
            </div>
          )}

          <fieldset disabled={!loaded} className="contents">
            {/* The tiles arrive as a cascade, top-down in setup order — the
                Task tab's entrance, for the same reason: a page assembling
                beats a page slamming in as one frame. */}
            <motion.div
              variants={CASCADE}
              initial="hidden"
              animate="shown"
              className="mt-7 flex flex-col gap-5"
            >
              <motion.div variants={RISE}>
                <HudTile
                  icon={Radio}
                  label="Boxes"
                  status={<BoxesFact bound={bound} health={health} connected={connectedCount} />}
                >
                  {/* Bind, see it come alive, prove it took — one row per box.
                      The handshake used to be a second list of the same boxes
                      under this table; it is the row's last column now. */}
                  <BoxBindingsTable
                    boxes={settings.boxes}
                    health={health}
                    handshake={handshake}
                    connected={connected}
                    onChange={onBoxesChange}
                  />
                </HudTile>
              </motion.div>

              <motion.div variants={RISE}>
                <HudTile
                  icon={Anchor}
                  label="Utility baseline"
                  status={settings.utilitySketchName ?? "off"}
                >
                  <UtilitySketchPanel
                    sketches={discovery.sketches}
                    boxes={settings.boxes}
                    value={settings.utilitySketchName}
                    status={utility}
                    busy={reflashing}
                    connected={connected}
                    onChange={(utilitySketchName) =>
                      void update({ utilitySketchName })
                    }
                    onReflash={() => void reflashBaseline()}
                  />
                </HudTile>
              </motion.div>

              {/* The one reference door this page keeps: the channel→pin map.
                  The strobe vocabulary used to sit beside it at half width, on
                  the argument that a code and a pin are the same kind of fact.
                  It reads codes as a fact about the TASK now
                  (`TASKS.md#strobe-vocabulary`) and lives on the Task tab; what is left is a single
                  door, which is the width `WiringDoor` was drawn at. */}
              <motion.div variants={RISE}>
                {/* The editor kept its own save discipline through every move —
                    preview, list what would break, ask — and keeps its own
                    page too. */}
                <WiringDoor
                  summary={wiring}
                  onOpen={() => navigate("/config/wiring")}
                />
              </motion.div>

              <motion.div variants={RISE}>
                <HudTile
                  icon={SlidersHorizontal}
                  label="Hardware"
                  status={`${settings.defaultBaud} baud`}
                >
                  <SettingRow
                    label="Default baud rate"
                    description="Starting value for each console. Debug Mode allows a per-box override."
                  >
                    <Dropdown
                      label="Default baud rate"
                      size="regular"
                      value={String(settings.defaultBaud)}
                      options={BAUD_RATES.map((b) => ({
                        value: String(b),
                        label: String(b),
                      }))}
                      placeholder="baud"
                      className="w-[140px] font-mono"
                      onChange={(v) =>
                        void update({ defaultBaud: Number(v) as (typeof BAUD_RATES)[number] })
                      }
                    />
                  </SettingRow>

                  <SettingRow
                    label="arduino-cli path"
                    description="Leave empty to use the bundled binary. Override only if you need a specific install."
                  >
                    <TextInput
                      label="arduino-cli path override"
                      mono
                      value={settings.arduinoCliPath ?? ""}
                      placeholder="bundled"
                      onChange={(v) =>
                        void update({ arduinoCliPath: v.trim() === "" ? null : v })
                      }
                      className="w-[280px]"
                    />
                  </SettingRow>
                </HudTile>
              </motion.div>
            </motion.div>
          </fieldset>

          <p className="mt-6 px-1 text-[11px] leading-relaxed text-static/70">
            Hardware settings are stored by the app shell and pushed to the
            backend whenever they change, so this screen keeps working even when
            the backend doesn&rsquo;t. The handshake test, the baseline readout
            and the wiring page are the parts that need it.
          </p>
        </section>
      </motion.div>
    </div>
  );
}

/**
 * The Boxes tile's fact: the bound boxes as health dots, then the count.
 *
 * The dots are the sidebar constellation's stars in a row — same `NODE_FILL`,
 * same four states — so the tile header and the widget beside it agree about
 * every box before either is read. The count takes the colour of what it sums
 * to: Ion when everything bound is on the bus, the error tone the moment any
 * box is in fault (a fault is exactly the thing this page exists to surface),
 * and quiet otherwise. Status colours as state, never as decoration.
 */
function BoxesFact({
  bound,
  health,
  connected,
}: {
  bound: readonly { box: number }[];
  health: Partial<Record<number, BoxHealth>>;
  connected: number;
}) {
  if (bound.length === 0) return <span>nothing bound</span>;
  const states = bound.map((b) => health[b.box] ?? "absent");
  const anyFault = states.includes("fault");
  const allUp = connected === bound.length;
  const colour = anyFault
    ? "var(--color-status-error)"
    : allUp
      ? "var(--color-status-ok)"
      : "var(--color-static)";
  return (
    <>
      <span className="flex items-center gap-1" aria-hidden>
        {states.map((state, i) => (
          <span
            key={bound[i]!.box}
            className="size-1.5 rounded-full"
            style={{ background: NODE_FILL[state] }}
          />
        ))}
      </span>
      <span style={{ color: colour }}>
        {connected}/{bound.length} connected
      </span>
    </>
  );
}

/**
 * The Wiring door — `EntranceTile`'s vocabulary at the landing's full width.
 *
 * A door and not a summary, exactly like the Dashboard's entrance tiles: the
 * destination is a workbench, and a tile that previewed its board here would
 * be a second, read-only rendering of a document whose whole page exists one
 * click away. On hover the tile lifts, the rule brightens, and the motif runs
 * a trace — one channel being wired, the gesture the room behind the door
 * exists for. Matte throughout: movement and a single accent, no glow (`ARCHITECTURE.md#theme`).
 */
function WiringDoor({
  summary,
  onOpen,
}: {
  /** The wiring document and its provenance, once read. */
  summary: WiringSummary | null;
  onOpen: () => void;
}) {
  return (
    <motion.button
      type="button"
      onClick={onOpen}
      initial="idle"
      animate="idle"
      whileHover="hover"
      whileTap={{ scale: 0.995 }}
      variants={{ idle: { y: 0 }, hover: { y: -2 } }}
      transition={springSnappy}
      className="hud group relative flex h-full w-full items-center gap-4 overflow-hidden rounded-md py-3.5 pl-4 pr-0 text-left transition-colors hover:border-static/40"
    >
      <CircuitBoard
        size={18}
        strokeWidth={1.75}
        className="shrink-0 self-start text-pulsar"
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1 text-[13px] font-medium text-starlight">
          Wiring
          <ArrowRight
            size={11}
            strokeWidth={2}
            className="text-static transition-transform group-hover:translate-x-0.5"
          />
        </span>
        <span className="mt-0.5 block text-[11px] leading-snug text-static">
          Every pin, and what it means — the channel→pin map every task compiles
          against.
        </span>
        {/* The strip: one segment per channel kind in the colour that kind
            wears on the board map and in every task's trial table, so the door
            says what the room behind it is made of. */}
        {summary && (
          <span className="mt-2 block">
            <KindStrip doc={summary.doc} />
            <span className="mt-1 block font-mono text-[10px] text-static/70">
              {summary.custom ? "this rig's own wiring" : "as shipped"}
            </span>
          </span>
        )}
      </span>
      {/* The motif bleeds off the tile's right edge, clipped by it — texture at
          the corner of the eye, not a picture competing with the words. */}
      <span
        aria-hidden
        className="pointer-events-none -my-3.5 shrink-0 self-center opacity-70 transition-opacity group-hover:opacity-100"
      >
        <WiringMotif />
      </span>
    </motion.button>
  );
}

/**
 * The door's motif: `RigMotif`'s picture — a pin header, one trace being run
 * to a box — redrawn wider for a full-width tile. Reads the `idle`/`hover`
 * variants of the door it sits in.
 */
function WiringMotif() {
  return (
    <svg width="168" height="62" viewBox="0 0 168 62" fill="none" aria-hidden>
      {/* Two rows of pads — a pin header, seen from above. */}
      {[0, 1].map((row) =>
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((col) => (
          <rect
            key={`${row}-${col}`}
            x={8 + col * 12}
            y={10 + row * 12}
            width="5"
            height="5"
            rx="1"
            fill="var(--color-halo)"
          />
        )),
      )}
      {/* The pad the trace leaves from. */}
      <motion.rect
        x={44}
        y={22}
        width="5"
        height="5"
        rx="1"
        variants={{
          idle: { fill: "var(--color-static)", opacity: 0.5 },
          hover: { fill: "var(--color-pulsar)", opacity: 1 },
        }}
        transition={springSnappy}
      />
      {/* The trace: down, right, down — orthogonal, like a routed track. */}
      <motion.path
        d="M46.5 27 V37 H112 V42"
        stroke="var(--color-pulsar)"
        strokeWidth="1.25"
        strokeLinecap="round"
        variants={{
          idle: { pathLength: 0, opacity: 0.35 },
          hover: { pathLength: 1, opacity: 1 },
        }}
        transition={{ duration: 0.45, ease: "easeOut" }}
      />
      {/* The box the trace lands on. */}
      <rect
        x={99}
        y={42}
        width="26"
        height="13"
        rx="2"
        stroke="var(--color-static)"
        strokeOpacity="0.45"
        strokeWidth="1"
      />
    </svg>
  );
}

/**
 * The door's one live fact: how many channels the wiring document declares,
 * and whether it is this rig's own or the pinout the build shipped. The same
 * `hardware.get` the editor opens with — read-only here, refreshed when
 * another surface saves, and quietly absent until the backend answers.
 */
interface WiringSummary {
  doc: RigDocument;
  custom: boolean;
}

function useWiringSummary(): WiringSummary | null {
  const { client, status } = useSidecar();
  const [summary, setSummary] = useState<WiringSummary | null>(null);

  useEffect(() => {
    if (status !== "connected") return;
    let cancelled = false;
    const load = () =>
      void getRig(client)
        .then((reply) => {
          if (cancelled) return;
          setSummary({
            doc: reply.document as RigDocument,
            custom: Boolean(reply.status.custom),
          });
        })
        .catch(() => {
          // The door works without its fact line; the page behind it is where
          // a load failure is surfaced with room to explain itself.
        });
    load();
    const off = client.on(EVT.HARDWARE_UPDATED, load);
    return () => {
      cancelled = true;
      off();
    };
  }, [client, status]);

  return summary;
}
