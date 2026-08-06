import { motion } from "framer-motion";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { CircleAlert, Radio } from "lucide-react";
import { useMemo, useState } from "react";

import { useBoxHealth } from "@/components/chrome/ConstellationStatus";
import { Select, TextInput } from "@/components/common/controls";
import { HandshakeList } from "@/components/config/HandshakeList";
import { UtilitySketchPanel } from "@/components/config/UtilitySketchPanel";
import { RigWiringEditor } from "@/components/hardware/RigWiringEditor";
import { BoxBindingsTable } from "@/components/settings/BoxBindingsTable";
import { SettingGroup, SettingRow } from "@/components/settings/SettingRow";
import { reconcileSlots } from "@/lib/constellations/slots";
import { zodiacById } from "@/lib/constellations/zodiac";
import { useUtilityStatus } from "@/lib/hardware/context";
import { useHandshakeTest } from "@/lib/hardware/useHandshakeTest";
import { springPanel } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { BAUD_RATES, type BoxBinding } from "@/lib/settings/schema";
import { CMD } from "@/lib/ws/protocol";
import { useSidecar } from "@/lib/ws/context";

/**
 * Rig — everything about this rig's hardware, on one screen (settings.md §5).
 *
 * **The screen is called Rig; the route and this file are still `config`.** The
 * name is the operator's word for the subject; the path is an internal address
 * the docs and this app's history already spell one way. See `App.tsx`.
 *
 * Top to bottom it follows the order a rig comes up in: **Boxes** (bind a box
 * number to a board, name it, watch it come alive — with the handshake test to
 * prove a binding took), **Utility baseline** (the resting firmware and what
 * it is doing right now), **Wiring** (the channel→pin map the task compiler
 * consumes), then the two knobs that rarely move (baud, `arduino-cli`).
 *
 * Two things used to live here and moved out, in opposite directions:
 *
 * - **The constellation board and picker are on Settings now.** They style the
 *   status display — which star a box sits on — and never touch the hardware,
 *   so they were interface filed under wiring. `onBoxesChange` still
 *   reconciles the slot map, because *this* screen is where boxes appear and
 *   disappear, and the slot map has to follow whether or not anyone visits
 *   Settings.
 * - **The setup wizard is gone entirely.** It was five linear steps over the
 *   same four surfaces this page now shows at once; with the page itself
 *   reading in setup order, a second, modal way through it was a maintenance
 *   cost with no second story to tell. First run simply lands here with an
 *   empty Boxes table and its own "add one for each box" prompt.
 *
 * **Wiring joined it from the other side** (`RigWiringEditor`, formerly
 * `/task/hardware`): binding a box to a board and binding a channel to a pin
 * are different wirings — runtime vs compile-time — but they are one subject,
 * and the Task landing keeps a door here for the flow that consumes the
 * channel map.
 */
export function Config() {
  const { settings, update, discovery, loaded, saveError } = useSettings();
  const { client, status } = useSidecar();
  const health = useBoxHealth();
  const handshake = useHandshakeTest();
  const utility = useUtilityStatus();
  const [reflashing, setReflashing] = useState(false);
  const connected = status === "connected";

  const bound = useMemo(
    () => settings.boxes.filter((b) => b.hardwareId !== null),
    [settings.boxes],
  );

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
        {/* Wider than the settings screens (max-w-3xl): the wiring editor's
            board map wants the room, and the page is a workbench now, not a
            form. */}
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
            <SettingGroup title="Boxes">
              <BoxBindingsTable
                boxes={settings.boxes}
                health={health}
                onChange={onBoxesChange}
              />
              <div className="border-t border-halo px-4 py-3.5">
                <div className="pb-0.5 text-[13px] font-medium text-starlight">
                  Handshake test
                </div>
                <p className="pb-2 text-[12px] leading-relaxed text-static">
                  Proof a binding took: opens the box&rsquo;s console and waits
                  for its firmware to announce itself.
                </p>
                <HandshakeList
                  bound={bound}
                  handshake={handshake}
                  connected={connected}
                />
              </div>
            </SettingGroup>

            <SettingGroup title="Utility baseline">
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
            </SettingGroup>

            {/* The channel→pin map. Its own save discipline, deliberately not
                the page's write-per-change: a wiring edit can break saved
                tasks, so it previews, lists what would break, and asks. */}
            <SettingGroup title="Wiring — every pin, and what it means">
              <RigWiringEditor />
            </SettingGroup>

            <SettingGroup title="Hardware">
              <SettingRow
                label="Default baud rate"
                description="Starting value for each console. Debug Mode allows a per-box override."
              >
                <Select
                  label="Default baud rate"
                  value={settings.defaultBaud}
                  options={BAUD_RATES.map((b) => ({
                    value: b,
                    label: String(b),
                  }))}
                  onChange={(defaultBaud) => void update({ defaultBaud })}
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
            </SettingGroup>
          </fieldset>

          <p className="mt-6 px-1 text-[11px] leading-relaxed text-static/70">
            Hardware settings are stored by the app shell and pushed to the
            backend whenever they change, so this screen keeps working even when
            the backend doesn&rsquo;t. The handshake test, the baseline readout
            and the wiring editor are the parts that need it.
          </p>
        </section>
      </motion.div>
    </div>
  );
}

