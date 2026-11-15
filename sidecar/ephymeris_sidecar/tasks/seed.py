"""The per-run trial seed — `TASKS.md#seed`.

A behaviour session's trial sequence must not be reproducible between runs. Two
animals drawing the same odor order, or one animal drawing the same order on
Monday and Tuesday, is a confound that looks like data: the sequence itself
becomes a cue the animal can learn, and any effect it produces is
indistinguishable from the effect the experiment is testing for.

**Why the board can't do this itself.** The obvious firmware answer is
``micros()`` at ``START``, and it is wrong in a way that reads as right. Opening
the serial port is what starts the run *and* what pulls DTR, which resets the
Mega — so ``micros()`` is not measuring the operator's click, it is measuring
the fixed interval from the board's own reset to the host's ``START``, and the
click cancels out of it exactly. What is left is boot time plus one serial
round-trip: a few milliseconds, quantised to the 4 µs ``micros()`` actually
resolves, clustered tightly around the same value every single time. That is a
few hundred reachable seeds in practice, so two sessions colliding outright is a
birthday problem over a very small space — likely within a few dozen runs, not
unlikely-in-principle. An AVR also has no entropy source to fall back on: no RNG
peripheral, and a floating-ADC read is a folk remedy, not a guarantee.

So the seed is drawn **here** and handed to the board on the ``START`` line. The
host has a real CSPRNG, and the draw happens at the instant the operator starts
the box, which is what makes it a fresh draw per run rather than per flash.

The range is `[1, 2**31 - 2]` for two firmware-side reasons, both load-bearing:

* Arduino's ``randomSeed(0)`` is a **no-op** — it explicitly skips ``srandom``
  for a zero seed, leaving the generator at its default state. A seed of 0
  would therefore be the single most reproducible value we could send.
* avr-libc's ``random()`` is the Park–Miller minimal-standard generator, whose
  state space is `[1, 2**31 - 2]`. Anything at or above the modulus is folded,
  so staying inside the range keeps the value we log identical to the state the
  board is actually running on.
"""

from __future__ import annotations

import hashlib
import secrets
import time

#: Inclusive bounds of a usable seed — see the module docstring.
SEED_MIN = 1
SEED_MAX = 2**31 - 2


def new_trial_seed() -> int:
    """A fresh, unpredictable seed for one box's run.

    ``secrets`` is the load-bearing entropy: it is OS-backed and is on its own
    sufficient for the guarantee this function exists to make. The two clocks
    are mixed in rather than relied upon — the operator's start click is the
    entropy the experiment *conceptually* wants, and folding it in through a
    hash can only ever add to the CSPRNG draw, never dilute it. Reading it here
    (rather than on the board) is what makes it the click at all.

    The digest is far wider than the output range, so reducing it to the
    Park–Miller state space leaves a modulo bias below any scale that could
    matter.
    """
    material = b"".join(
        (
            secrets.token_bytes(32),
            # Wall clock: when the operator clicked, to the nanosecond.
            time.time_ns().to_bytes(8, "big"),
            # Monotonic clock: unaffected by an NTP step or a manual clock
            # change, so two runs across one of those still differ here.
            time.perf_counter_ns().to_bytes(8, "big"),
        )
    )
    digest = hashlib.blake2b(material, digest_size=16).digest()
    return int.from_bytes(digest, "big") % (SEED_MAX - SEED_MIN + 1) + SEED_MIN
