import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check, Radio } from "lucide-react";
import { useMemo, useState } from "react";

import { ConstellationBoard } from "./ConstellationBoard";
import { ConstellationPicker } from "./ConstellationPicker";
import { HandshakeList } from "./HandshakeList";
import { useBoxHealth } from "@/components/chrome/ConstellationStatus";
import { Button, Select, TextInput } from "@/components/common/controls";
import { BoxBindingsTable } from "@/components/settings/BoxBindingsTable";
import { reconcileSlots } from "@/lib/constellations/slots";
import { zodiacById } from "@/lib/constellations/zodiac";
import { useBoardPresence } from "@/lib/hardware/context";
import { useHandshakeTest } from "@/lib/hardware/useHandshakeTest";
import { springPanel, springSnappy } from "@/lib/motion";
import { useSettings } from "@/lib/settings/context";
import { BAUD_RATES } from "@/lib/settings/schema";
import { useSidecar } from "@/lib/ws/context";

/**
 * First-time box setup (settings.md §5).
 *
 * In-route rather than a modal: this is a multi-minute guided flow, not a
 * transient confirmation, and vibrancy is reserved for the sidebar and true
 * modals (§2.4). Linear steps, Back always allowed, and Skip always visible —
 * everything the wizard does is equally doable from the normal Config view,
 * so it must never trap anyone.
 *
 * Steps 1–2 write straight through to settings (the wizard is resumable and
 * the bindings are real config either way). The constellation choice is local
 * until Finish, so an abandoned run leaves no half-chosen layout behind.
 */

/*
 * "BIND BOXES", not "Map hardware", which this step used to be called.
 *
 * Task → Rig wiring maps a CHANNEL to a PIN: compiler input, baked into every
 * table, and wrong silently — the wrong valve fires and the listing looks
 * correct. This step binds a BOX to a BOARD: a runtime indirection, per rig,
 * changing on every board swap, and wrong loudly, because the port will not
 * open. Two screens called "map hardware" is a support call.
 */
const STEPS = ["Bind boxes", "Nicknames", "Handshake", "Constellation", "Done"] as const;

export function SetupWizard({ onExit }: { onExit: () => void }) {
  const { settings, update } = useSettings();
  const { status } = useSidecar();
  const detected = useBoardPresence();
  const health = useBoxHealth();
  const handshake = useHandshakeTest();

  const [step, setStep] = useState(0);
  const [choice, setChoice] = useState<string | null>(settings.constellation);
  const [localSlots, setLocalSlots] = useState(settings.constellationSlots);

  const bound = useMemo(
    () => settings.boxes.filter((b) => b.hardwareId !== null),
    [settings.boxes],
  );
  const boundNumbers = useMemo(() => bound.map((b) => b.box), [bound]);
  const labels = useMemo(
    () => Object.fromEntries(settings.boxes.map((b) => [b.box, b.label])),
    [settings.boxes],
  );
  const chosen = zodiacById(choice);
  const connected = status === "connected";

  const canAdvance =
    step === 0 ? bound.length > 0 : step === 3 ? chosen !== null : true;

  function pick(id: string) {
    setChoice(id);
    const constellation = zodiacById(id);
    if (constellation) {
      setLocalSlots(reconcileSlots(constellation, localSlots, boundNumbers));
    }
  }

  function finish() {
    void update({
      constellation: choice,
      constellationSlots: localSlots,
      boxSetupComplete: true,
    });
    onExit();
  }

  function skip() {
    void update({ boxSetupComplete: true });
    onExit();
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-3xl px-10 py-9"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
            <Radio size={18} strokeWidth={1.75} className="text-pulsar" />
          </span>
          <div>
            <h1 className="font-display text-[22px] text-starlight">Box setup</h1>
            <p className="text-[12px] text-static">
              Step {step + 1} of {STEPS.length} — {STEPS[step]}
            </p>
          </div>
        </div>
        <Button variant="ghost" onClick={skip}>
          Skip setup
        </Button>
      </div>

      {/* Step dots */}
      <div className="mt-5 flex items-center gap-1.5">
        {STEPS.map((label, index) => (
          <motion.span
            key={label}
            animate={{
              backgroundColor:
                index <= step ? "var(--color-pulsar)" : "var(--color-halo)",
              width: index === step ? 22 : 8,
            }}
            transition={springSnappy}
            className="h-1.5 rounded-full"
          />
        ))}
      </div>

      <div className="mt-5">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={springPanel}
            className="surface rounded-md"
          >
            {step === 0 && (
              <div>
                <StepIntro
                  title="Bind your boxes to boards"
                  body={
                    <>
                      Add a row for each behavior box in the rig and bind it to a
                      connected board. Boards are identified by USB serial number,
                      so bindings survive Windows renumbering COM ports.{" "}
                      <span className="font-mono text-[11px]">
                        {detected.length} board{detected.length === 1 ? "" : "s"} detected.
                      </span>
                    </>
                  }
                />
                <BoxBindingsTable
                  boxes={settings.boxes}
                  onChange={(boxes) => void update({ boxes })}
                />
              </div>
            )}

            {step === 1 && (
              <div>
                <StepIntro
                  title="Name your boxes"
                  body="Nicknames appear on the constellation, in Debug Mode, and in Mission Control. Cage position or a memorable name both work."
                />
                <div className="flex flex-col gap-1.5 px-4 pb-4">
                  {bound.map((binding) => (
                    <div key={binding.box} className="grid grid-cols-[38px_1fr] items-center gap-x-3">
                      <span className="font-mono text-[12px] text-static">{binding.box}</span>
                      <TextInput
                        label={`Nickname for box ${binding.box}`}
                        value={binding.label}
                        placeholder={`Box ${binding.box}`}
                        onChange={(label) =>
                          void update({
                            boxes: settings.boxes.map((b) =>
                              b.box === binding.box ? { ...b, label } : b,
                            ),
                          })
                        }
                        className="w-[280px]"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {step === 2 && (
              <div>
                <StepIntro
                  title="Test the connection"
                  body={
                    connected
                      ? "Each test opens the box's serial port — which resets the board — and listens for ten seconds. A READY line means the loaded sketch speaks the Ephymeris protocol; any output at all means the wiring and port are good. A failed or silent box won't stop you continuing — hardware can be off right now."
                      : "The backend isn't connected, so ports can't be opened. You can continue and test later from Config."
                  }
                />
                {/* The baud rate lives on this step rather than a step of its
                    own because this is where a wrong one first shows itself: a
                    mismatch doesn't error, it just makes every box look silent.
                    Every sketch in the lab's directory opens at 9600. */}
                <div className="flex items-center justify-between gap-4 px-4 pb-3">
                  <p className="text-[12px] text-static">
                    Baud rate — match what your sketches open the serial port at.
                    A mismatch looks exactly like a dead board.
                  </p>
                  <Select
                    label="Default baud rate"
                    value={settings.defaultBaud}
                    options={BAUD_RATES.map((b) => ({ value: b, label: String(b) }))}
                    onChange={(defaultBaud) => void update({ defaultBaud })}
                  />
                </div>
                <div className="px-4 pb-4">
                  <HandshakeList bound={bound} handshake={handshake} connected={connected} />
                </div>
              </div>
            )}

            {step === 3 && (
              <div>
                <StepIntro
                  title="Choose your constellation"
                  body="Your boxes become stars in a zodiac constellation — the status display in the sidebar and here in Config. Pick a shape; you can drag boxes between stars afterward."
                />
                <div className="px-4 pb-4">
                  <ConstellationPicker
                    selected={choice}
                    boxCount={boundNumbers.length}
                    onSelect={pick}
                  />
                  {chosen && (
                    <div className="mx-auto mt-4 max-w-[420px]">
                      <ConstellationBoard
                        constellation={chosen}
                        slots={localSlots}
                        boxes={boundNumbers}
                        labels={labels}
                        health={health}
                        onSlotsChange={setLocalSlots}
                      />
                      <p className="mt-1 text-center text-[11px] text-static">
                        Drag a box to a different star to rearrange.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {step === 4 && (
              <div className="px-4 py-5">
                <StepIntro
                  title="All set"
                  body={
                    <>
                      {bound.length} box{bound.length === 1 ? "" : "es"} configured
                      {chosen ? (
                        <>
                          {" "}
                          on <span className="text-starlight">{chosen.name}</span>
                        </>
                      ) : null}
                      . Everything here — bindings, nicknames, tests, and the
                      constellation — stays editable in Config.
                    </>
                  }
                  bare
                />
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <Button variant="ghost" onClick={() => setStep((s) => s - 1)} disabled={step === 0}>
          <ArrowLeft size={13} strokeWidth={1.75} />
          Back
        </Button>
        {step < STEPS.length - 1 ? (
          <Button variant="primary" onClick={() => setStep((s) => s + 1)} disabled={!canAdvance}>
            Next
            <ArrowRight size={13} strokeWidth={1.75} />
          </Button>
        ) : (
          <Button variant="primary" onClick={finish}>
            <Check size={13} strokeWidth={1.75} />
            Finish
          </Button>
        )}
      </div>
    </motion.section>
  );
}

function StepIntro({
  title,
  body,
  bare = false,
}: {
  title: string;
  body: React.ReactNode;
  bare?: boolean;
}) {
  return (
    <div className={bare ? "" : "px-4 pb-2 pt-4"}>
      <h2 className="text-[15px] font-medium text-starlight">{title}</h2>
      <p className="mt-1 max-w-[520px] text-[12px] leading-relaxed text-static">{body}</p>
    </div>
  );
}
