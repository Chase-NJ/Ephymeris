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


#: Student's t at 0.975, df 1 to 30: the two-sided 95% quantile, as published.
_T_975 = (
    12.706205, 4.302653, 3.182446, 2.776445, 2.570582, 2.446912, 2.364624, 2.306004, 2.262157, 2.228139,
    2.200985, 2.178813, 2.160369, 2.144787, 2.131450, 2.119905, 2.109816, 2.100922, 2.093024, 2.085963,
    2.079614, 2.073873, 2.068658, 2.063899, 2.059539, 2.055529, 2.051831, 2.048407, 2.045230, 2.042272,
)


def t_quantile_975(df: int) -> float:
    """Student's t quantile at 0.975 for `df` degrees of freedom (df >= 1).

    The published value up to 30; past it the Cornish-Fisher expansion about
    z, good to 1e-5 there and better beyond. A few lines rather than
    `scipy.stats.t` (`ARCHITECTURE.md#dependency-policy`)."""
    if df < 1:
        raise ValueError("a t quantile needs at least one degree of freedom")
    if df <= len(_T_975):
        return _T_975[df - 1]
    z = Z_95
    g1 = (z**3 + z) / 4
    g2 = (5 * z**5 + 16 * z**3 + 3 * z) / 96
    g3 = (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384
    g4 = (79 * z**9 + 776 * z**7 + 1482 * z**5 - 1920 * z**3 - 945 * z) / 92160
    return z + g1 / df + g2 / df**2 + g3 / df**3 + g4 / df**4


def mean_interval(values: list[float]) -> tuple[float, float | None, float | None] | None:
    """The mean of `values` and its 95% Student-t interval, (mean, low, high),
    or None for no values (`ANALYTICS.md#uncertainty`). One value has a mean
    and no spread to bound it, so its low and high are None."""
    n = len(values)
    if n == 0:
        return None
    mean = sum(values) / n
    if n == 1:
        return mean, None, None
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    half = t_quantile_975(n - 1) * sd / math.sqrt(n)
    return mean, mean - half, mean + half


def _round(value: float | None) -> float | None:
    """Six decimals on the wire — smaller frames, and no `0.8500000000000001`."""
    return None if value is None else round(value, 6)
