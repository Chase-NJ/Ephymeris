"""The per-run trial seed — `TASKS.md#seed`.

The property under test is a negative one: **no two runs draw the same trial
sequence**. That can't be proven by a test, but the three ways it has actually
been broken can each be pinned:

* seeding from the board, whose only clock restarts with the run;
* seeding once and reusing the value across boxes or across restarts;
* handing the firmware a value it treats as "no seed at all".
"""

from __future__ import annotations

from ephymeris_sidecar.tasks.profile import parse_profile
from ephymeris_sidecar.tasks.seed import new_trial_seed
from ephymeris_sidecar.tasks.start_command import build_start_command


def test_a_seed_never_lands_on_a_value_the_firmware_would_discard() -> None:
    """Arduino's `randomSeed(0)` is a documented no-op, and avr-libc's
    Park-Miller state space stops at `2**31 - 2`. A draw outside that range is
    either the most reproducible value available or one the board silently
    folds into a different number from the one we logged."""
    for _ in range(2000):
        seed = new_trial_seed()
        assert 1 <= seed <= 2**31 - 2


def test_seeds_do_not_repeat_across_a_run_of_draws() -> None:
    """Not a randomness test — a collision detector.

    ``micros()``-at-START, the scheme this replaced, fails exactly here: its
    reachable range is a few hundred values clustered around one boot latency,
    so a thousand draws from it would collide by the hundreds. A CSPRNG over
    2^31 collides about once in 4000 such runs by the birthday bound
    (n^2 / 2N with n = 1000), and the budget of ONE repeat pushes a false
    failure out past one in ten million — the 5000-draw, zero-collision
    version of this assertion failed on a green suite about once in 170 runs.
    """
    draws = [new_trial_seed() for _ in range(1000)]
    assert len(draws) - len(set(draws)) <= 1


def test_consecutive_draws_are_not_adjacent() -> None:
    """The specific tell of a clock-derived seed.

    Two seeds drawn microseconds apart from a timer differ by microseconds.
    Nothing about the distance between draws here should encode the distance in
    time between them, so back-to-back values must not be neighbours.
    """
    previous = new_trial_seed()
    for _ in range(200):
        seed = new_trial_seed()
        assert abs(seed - previous) > 1000
        previous = seed


def test_the_seed_rides_on_the_start_line_and_the_config_on_the_set_lines() -> None:
    profile = parse_profile(
        {
            "taskName": "GRGL",
            "config": [
                {"metadataKey": "correction_left", "wireKey": "CL",
                 "label": "L", "type": "int", "default": 0},
            ],
        }
    )
    command = build_start_command(profile, {})
    assert command.set_lines == ("SET CL=0",)
    assert command.start_line(123456789) == "START SEED=123456789"


def test_a_profile_less_sketch_still_gets_a_seed() -> None:
    """A bare `START` is the profile-less case (`TASKS.md#task-profile`), not a case where trial
    order stops mattering — the shaping sketches declare no config at all and
    are the ones that were running a fixed sequence."""
    assert build_start_command(None, {}).start_line(7) == "START SEED=7"
