"""The per-run trial seed — `data-saving.md` §6.4.

The property under test is a negative one: **no two runs draw the same trial
sequence**. That can't be proven by a test, but the three ways it has actually
been broken can each be pinned:

* seeding from the board, whose only clock restarts with the run;
* seeding once and reusing the value across boxes or across restarts;
* handing the firmware a value it treats as "no seed at all".
"""

from __future__ import annotations

from ephymeris_sidecar.tasks.profile import parse_profile
from ephymeris_sidecar.tasks.seed import SEED_MAX, SEED_MIN, new_trial_seed
from ephymeris_sidecar.tasks.start_command import build_start_command, with_trial_seed


def test_a_seed_never_lands_on_a_value_the_firmware_would_discard() -> None:
    """Arduino's `randomSeed(0)` is a documented no-op, and avr-libc's
    Park-Miller state space stops at `2**31 - 2`. A draw outside that range is
    either the most reproducible value available or one the board silently
    folds into a different number from the one we logged."""
    for _ in range(2000):
        seed = new_trial_seed()
        assert SEED_MIN <= seed <= SEED_MAX
        assert seed != 0


def test_seeds_do_not_repeat_across_a_run_of_draws() -> None:
    """Not a randomness test — a collision detector.

    ``micros()``-at-START, the scheme this replaced, fails exactly here: its
    reachable range is a few hundred values clustered around one boot latency,
    so a few thousand draws from it would collide constantly. A CSPRNG over 2^31
    should produce none at this scale.
    """
    draws = [new_trial_seed() for _ in range(5000)]
    assert len(set(draws)) == len(draws)


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


def test_the_seed_rides_on_the_start_line_beside_the_config() -> None:
    profile = parse_profile(
        {
            "taskName": "GRGL",
            "config": [
                {"metadataKey": "correction_left", "wireKey": "CL",
                 "label": "L", "type": "int", "default": 0},
            ],
        }
    )
    command = with_trial_seed(build_start_command(profile, {}), 123456789)
    assert command == "START CL=0 SEED=123456789"


def test_a_profile_less_sketch_still_gets_a_seed() -> None:
    """A bare `START` is the profile-less case (§6.1), not a case where trial
    order stops mattering — the shaping sketches declare no config at all and
    are the ones that were running a fixed sequence."""
    assert with_trial_seed(build_start_command(None, {}), 7) == "START SEED=7"
