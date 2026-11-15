"""Statistics of one function over the included cycles (SPEC F11 and section 3).

Pure functions on 1-D NumPy arrays plus a boolean include mask; nothing here
knows about runs, files or the GUI.

Conventions (legacy C# Tripoli by default, Java Tripoli for comparison):

* **Ratios, geometric mode** (an option): statistics are taken on ln r.
  ``center`` = mean of ln r, ``sd`` = sample SD of ln r (n − 1), ``se`` =
  sd / √n, reported ``mean`` = exp(center) (the geometric mean). The reported
  1σ percent standard error is the *smaller* of the two asymmetric sides,
  (exp(c + se) − exp(c)) / exp(c) and (exp(c) − exp(c − se)) / exp(c), which
  is always the lower side: ``se_pct`` = (1 − e^(−se)) · 100. ``sd_pct`` uses
  the same smaller-side rule on sd. The upper sides (e^x − 1) · 100, which
  Tripoli writes into its full CSV report, are ``se_pct_upper`` and
  ``sd_pct_upper``.
* **Arithmetic mode** (the default for ratios, as legacy Tripoli; always used for intensities and
  other functions): ``mean`` = ``center`` = arithmetic mean, ``sd`` (n − 1),
  ``se`` = sd / √n, ``se_pct`` = se / mean · 100, ``sd_pct`` = sd / mean · 100
  (signed, as Tripoli reports them for a negative mean).

In geometric mode ``sd`` and ``se`` are on the ln scale (dimensionless); in
arithmetic mode they are in the function's units.

Values that cannot enter (non-finite anywhere; ≤ 0 in geometric mode) are
dropped even when the mask includes them, so ``n_used`` counts the values
actually averaged. ``n_total`` is the length of the array.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Literal

import numpy as np

StatMode = Literal["geometric", "arithmetic"]
STAT_MODES: tuple[str, ...] = ("geometric", "arithmetic")


@dataclass(frozen=True)
class Stats:
    """Summary of one function over its included cycles (see the module docstring for the conventions)."""

    mean: float
    sd: float
    se: float
    se_pct: float
    sd_pct: float
    n_used: int
    n_total: int
    mode: StatMode
    center: float

    @property
    def se_pct_upper(self) -> float:
        """Upper-side percent SE: (e^se − 1)·100 in geometric mode, se_pct otherwise."""
        return math.expm1(self.se) * 100.0 if self.mode == "geometric" else self.se_pct

    @property
    def sd_pct_upper(self) -> float:
        """Upper-side percent SD: (e^sd − 1)·100 in geometric mode, sd_pct otherwise."""
        return math.expm1(self.sd) * 100.0 if self.mode == "geometric" else self.sd_pct

    def to_dict(self) -> dict:
        return asdict(self)


def _check_mode(mode: str) -> None:
    if mode not in STAT_MODES:
        raise ValueError(f"unknown statistics mode {mode!r}; expected one of {STAT_MODES}")


def _as_arrays(values, include) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError("values must be one-dimensional")
    if include is None:
        include = np.ones(values.shape, dtype=bool)
    else:
        include = np.asarray(include, dtype=bool)
        if include.shape != values.shape:
            raise ValueError(f"include mask shape {include.shape} does not match values {values.shape}")
    return values, include


def usable(values, include=None, *, mode: StatMode = "arithmetic") -> np.ndarray:
    """The include mask restricted to values that can enter: finite, and > 0 in geometric mode."""
    _check_mode(mode)
    values, include = _as_arrays(values, include)
    ok = include & np.isfinite(values)
    if mode == "geometric":
        with np.errstate(invalid="ignore"):
            ok &= values > 0
    return ok


def transform(values, mode: StatMode) -> np.ndarray:
    """The values the statistics work on: ln r in geometric mode (NaN where r ≤ 0), the values otherwise."""
    _check_mode(mode)
    values = np.asarray(values, dtype=np.float64)
    if mode == "arithmetic":
        return values
    out = np.full(values.shape, np.nan)
    positive = np.isfinite(values) & (values > 0)
    out[positive] = np.log(values[positive])
    return out


def describe(values, include=None, *, mode: StatMode = "arithmetic") -> Stats:
    """Statistics of ``values[include]`` in the given mode. NaN fields when too few values are usable."""
    values, include = _as_arrays(values, include)
    ok = usable(values, include, mode=mode)
    data = transform(values, mode)[ok]
    n = int(data.size)
    center = float(data.mean()) if n else math.nan
    sd = float(data.std(ddof=1)) if n > 1 else math.nan
    se = sd / math.sqrt(n) if n > 1 else math.nan
    if mode == "geometric":
        mean = math.exp(center) if n else math.nan
        se_pct = -math.expm1(-se) * 100.0
        sd_pct = -math.expm1(-sd) * 100.0
    else:
        mean = center
        se_pct = se / mean * 100.0 if n and mean != 0 else math.nan
        sd_pct = sd / mean * 100.0 if n and mean != 0 else math.nan
    return Stats(mean=mean, sd=sd, se=se, se_pct=se_pct, sd_pct=sd_pct, n_used=n, n_total=int(values.size), mode=mode, center=center)


def mode_for(is_ratio: bool, ratio_mode: StatMode = "arithmetic") -> StatMode:
    """Ratios use ``ratio_mode``; every other function is arithmetic."""
    _check_mode(ratio_mode)
    return ratio_mode if is_ratio else "arithmetic"


def function_stats(values, include=None, *, is_ratio: bool, ratio_mode: StatMode = "arithmetic") -> Stats:
    """:func:`describe` with the mode chosen by the function kind."""
    return describe(values, include, mode=mode_for(is_ratio, ratio_mode))


def block_stats(values, include, block, *, is_ratio: bool, ratio_mode: StatMode = "arithmetic") -> dict[int, Stats]:
    """The same statistics for each block separately, keyed by block number (ascending)."""
    values, include = _as_arrays(values, include)
    block = np.asarray(block)
    if block.shape != values.shape:
        raise ValueError("block array shape does not match values")
    mode = mode_for(is_ratio, ratio_mode)
    return {int(b): describe(values[block == b], include[block == b], mode=mode) for b in np.unique(block)}


@dataclass(frozen=True)
class WeightedMean:
    """Block-mode result: a weighted mean of block means (``center`` on the statistics scale).

    ``mean`` is exp(center) for ratios in geometric mode, ``sigma`` the 1σ of
    ``center`` and ``sigma_pct`` the percent 1σ of ``mean`` (upper side for
    geometric, as Tripoli reports block mode). ``mswd`` follows ``convention``.
    """

    mean: float
    center: float
    sigma: float
    sigma_pct: float
    mswd: float
    n_blocks: int
    mode: StatMode
    convention: str

    def to_dict(self) -> dict:
        return asdict(self)


def block_weighted_mean(
    values,
    include,
    block,
    *,
    is_ratio: bool,
    ratio_mode: StatMode = "arithmetic",
    block_included: dict[int, bool] | None = None,
    convention: Literal["tripoli", "standard"] = "tripoli",
) -> WeightedMean:
    """Weighted mean of the block means, with an MSWD-like dispersion statistic. Not the default statistic.

    ``convention="tripoli"`` reproduces current Tripoli's abandoned block mode
    (``AnalysisStatsRecord.generateAnalysisStatsRecord``): weights are
    1 / SD_b² (the block's standard *deviation*, not its standard error), the
    1σ of the mean is √(1/Σw), and the dispersion is
    Σ (m_b − m̄)² / σ_m̄² / (n_blocks − 1), dividing by the variance of the
    weighted mean rather than by each block's variance. It is kept for
    comparison only.

    ``convention="standard"`` is the textbook form: weights 1 / SE_b²,
    σ = √(1/Σw), MSWD = Σ (m_b − m̄)² / SE_b² / (n_blocks − 1).

    Blocks with fewer than two usable values, or flagged off in
    ``block_included``, are left out.
    """
    if convention not in ("tripoli", "standard"):
        raise ValueError(f"unknown convention {convention!r}")
    per_block = block_stats(values, include, block, is_ratio=is_ratio, ratio_mode=ratio_mode)
    mode = mode_for(is_ratio, ratio_mode)
    means, spreads = [], []
    for number, stats in per_block.items():
        if block_included is not None and not block_included.get(number, True):
            continue
        spread = stats.sd if convention == "tripoli" else stats.se
        if stats.n_used < 2 or not math.isfinite(spread) or spread <= 0:
            continue
        means.append(stats.center)
        spreads.append(spread)
    n = len(means)
    if n == 0:
        return WeightedMean(math.nan, math.nan, math.nan, math.nan, math.nan, 0, mode, convention)
    m = np.array(means)
    w = 1.0 / np.square(spreads)
    center = float(np.sum(w * m) / np.sum(w))
    variance = float(1.0 / np.sum(w))
    sigma = math.sqrt(variance)
    if n < 2:
        mswd = math.nan
    elif convention == "tripoli":
        mswd = float(np.sum(np.square(m - center)) / variance / (n - 1))
    else:
        mswd = float(np.sum(w * np.square(m - center)) / (n - 1))
    if mode == "geometric":
        mean = math.exp(center)
        sigma_pct = math.expm1(sigma) * 100.0
    else:
        mean = center
        sigma_pct = sigma / center * 100.0 if center != 0 else math.nan
    return WeightedMean(mean, center, sigma, sigma_pct, mswd, n, mode, convention)


@dataclass(frozen=True)
class Correlation:
    """Pearson r between two functions over the cycles usable for both, and that number of cycles."""

    r: float
    n: int

    def to_dict(self) -> dict:
        return asdict(self)


def correlation(values_a, values_b, include_a=None, include_b=None, *, mode_a: StatMode = "arithmetic", mode_b: StatMode = "arithmetic") -> Correlation:
    """Pearson correlation of two functions over the cycles included and usable for both.

    It is computed on the values the statistics use: ln r for a ratio in
    geometric mode, the values otherwise.

    Why this is the correlation of the two *means*: over the same n cycles,
    cov(x̄, ȳ) = cov(x, y) / n, var(x̄) = var(x) / n and var(ȳ) = var(y) / n,
    so cov(x̄, ȳ) / √(var x̄ · var ȳ) = cov(x, y) / √(var x · var y), the
    cycle-level Pearson r (the n − 1 factors cancel as well). In geometric
    mode the means are of ln r; the reported geometric means exp(x̄), exp(ȳ)
    are smooth monotone transforms, whose first-order (delta-method) errors
    are those of x̄ and ȳ scaled by exp(x̄) and exp(ȳ), and scaling does not
    change a correlation. The identity holds exactly only when both means use
    the same cycles; if the include sets differ, the r over the shared cycles
    is an approximation for the means over the separate sets.
    """
    a, include_a = _as_arrays(values_a, include_a)
    b, include_b = _as_arrays(values_b, include_b)
    if a.shape != b.shape:
        raise ValueError("the two functions have different lengths")
    shared = usable(a, include_a, mode=mode_a) & usable(b, include_b, mode=mode_b)
    x = transform(a, mode_a)[shared]
    y = transform(b, mode_b)[shared]
    n = int(x.size)
    if n < 3:
        return Correlation(math.nan, n)
    dx = x - x.mean()
    dy = y - y.mean()
    denominator = math.sqrt(float(np.dot(dx, dx)) * float(np.dot(dy, dy)))
    if denominator == 0:
        return Correlation(math.nan, n)
    r = float(np.dot(dx, dy)) / denominator
    return Correlation(max(-1.0, min(1.0, r)), n)


__all__ = [
    "STAT_MODES",
    "Correlation",
    "StatMode",
    "Stats",
    "WeightedMean",
    "block_stats",
    "block_weighted_mean",
    "correlation",
    "describe",
    "function_stats",
    "mode_for",
    "transform",
    "usable",
]
