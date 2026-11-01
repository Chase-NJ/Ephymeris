"""What the board can drive: the Mega's timers, and RIG109 (TASKS.md#driven-outputs).

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
