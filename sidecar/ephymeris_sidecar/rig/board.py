"""What the board can drive: the Mega's timers and serial pins, RIG109 and RIG102.

Driven outputs are TASKS.md#driven-outputs; the serial pins, TASKS.md#wiring-rules.

A `pwm_out` channel is `analogWrite`, which needs a pin a hardware timer
drives; a `tone_out` channel is `tone()`, which the Mega's AVR core plays on
ONE pin at a time, on Timer2, taking that timer's two PWM pins with it. These
are facts about the board, not the rig, so they live here rather than in the
wiring document an operator edits. The table is the Mega 2560's, the only board
the app compiles for (`arduino:avr:mega`), transcribed from the AVR core's
`variants/mega/pins_arduino.h` (`digital_pin_to_timer_PGM`) and `Tone.cpp`.
"""

from __future__ import annotations

from typing import Iterable

#: Pin -> the timer whose compare output drives it. Timer0 also runs millis();
#: `analogWrite` leaves its prescaler alone, so its pins are safe to use, at
#: 980 Hz where the others run at 490 Hz.
PWM_TIMER: dict[int, int] = {
    2: 3, 3: 3, 5: 3,
    4: 0, 13: 0,
    6: 4, 7: 4, 8: 4,
    9: 2, 10: 2,
    11: 1, 12: 1,
    44: 5, 45: 5, 46: 5,
}

#: The timer `tone()` takes on a Mega (`Tone.cpp`: one tone pin, `USE_TIMER2`).
TONE_TIMER = 2

#: How many tone pins the Mega's core can play at once.
TONE_CHANNELS = 1

#: Pin -> its name on the board, for the pins no channel may take: USART0,
#: which the Mega wires to its USB-serial chip. It is the link every box
#: streams strobes over and takes `BEGIN`, `SET` and `START` on, so a channel
#: driving or reading either pin would break the box's serial. The board HAS
#: these pins, so they stay inside `pin_range`; every pin offer and RIG102
#: leave them out instead.
SERIAL_PINS: dict[int, str] = {0: "RX0", 1: "TX0"}


def offered_pins(pin_min: int, pin_max: int) -> list[int]:
    """The pins of `pin_min`..`pin_max` a channel may be put on: all but the serial pins."""
    return [p for p in range(pin_min, pin_max + 1) if p not in SERIAL_PINS]


def serial_pin_problem(name: str, pin: int) -> str | None:
    """RIG102's message for a channel on a serial pin; None when `pin` is not one."""
    if pin not in SERIAL_PINS:
        return None
    return (f"{name!r} is on pin {pin}, the Mega's {SERIAL_PINS[pin]}: the USB serial the box streams "
            "strobes over. A channel there would break that link; move it to another pin.")


def reserved_pins_json() -> list[dict[str, object]]:
    """`RigDocument.reservedPins`: the serial pins, so the editor can leave them out."""
    return [{"pin": pin, "name": name} for pin, name in sorted(SERIAL_PINS.items())]


def drive_problems(channels: Iterable) -> list[tuple[str, str]]:  # noqa: ANN001 - registry.Channel
    """RIG109: driven outputs this board cannot run. (channel, message) pairs.

    Two PWM channels on one timer are NOT a problem: `analogWrite` keeps the
    timer's frequency and each compare output holds its own duty.
    """
    channels = list(channels)
    tones = [c for c in channels if c.drive == "tone"]
    out: list[tuple[str, str]] = []
    for c in channels:
        if c.drive != "pwm":
            continue
        timer = PWM_TIMER.get(c.index) if isinstance(c.index, int) else None
        if timer is None:
            pins = ", ".join(str(p) for p in sorted(PWM_TIMER))
            out.append((c.name, f"{c.name!r} is a pwm_out on pin {c.index}, which no timer drives, so it "
                        f"could only be fully on or off. A Mega's PWM pins are {pins}."))
        elif timer == TONE_TIMER and tones:
            out.append((c.name, f"{c.name!r} is a pwm_out on pin {c.index}, on Timer{TONE_TIMER}, which "
                        f"tone() takes for {tones[0].name!r}: its duty would stop while a tone plays. "
                        "Move it to another PWM pin."))
    for c in tones[TONE_CHANNELS:]:
        out.append((c.name, f"{c.name!r} is a second tone_out channel after {tones[0].name!r}. A Mega "
                    "plays one tone pin at a time, so one of them would stay silent."))
    return out
