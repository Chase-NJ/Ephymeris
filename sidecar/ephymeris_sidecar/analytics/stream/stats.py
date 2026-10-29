"""The uncertainty every probability carries — `ANALYTICS.md#uncertainty`.
"""

from __future__ import annotations

import math


#: z for a 95% interval. Wilson rather than the normal approximation because
#: this data lives at small n *and* at p near 1 — a trained animal sits around
#: 0.95 — which is exactly where the normal approximation runs past 1.0
#: (`ANALYTICS.md#uncertainty`).
Z_95 = 1.959964


def wilson_interval(hits: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """95% Wilson score interval for `hits` of `n`, or `None` when n is 0."""
    if n <= 0:
        return None
    p = hits / n
    z2 = z * z
    denominator = 1 + z2 / n
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (
        max(0.0, (centre - margin) / denominator),
        min(1.0, (centre + margin) / denominator),
    )


def _round(value: float | None) -> float | None:
    """Six decimals on the wire — smaller frames, and no `0.8500000000000001`."""
    return None if value is None else round(value, 6)
