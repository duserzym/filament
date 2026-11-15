"""Statistics functions on hand-made arrays (SPEC F11)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from rawtims.stats import block_stats, block_weighted_mean, correlation, describe, function_stats, transform


def test_geometric_mode_on_known_logs():
    logs = np.array([0.1, 0.2, 0.3, 0.4])
    stats = describe(np.exp(logs), mode="geometric")
    sd = math.sqrt(sum((x - 0.25) ** 2 for x in logs) / 3)
    se = sd / 2
    assert stats.center == pytest.approx(0.25, abs=1e-15)
    assert stats.mean == pytest.approx(math.exp(0.25), rel=1e-15)
    assert stats.sd == pytest.approx(sd, rel=1e-14) and stats.se == pytest.approx(se, rel=1e-14)
    assert stats.se_pct == pytest.approx((1 - math.exp(-se)) * 100, rel=1e-14)
    assert stats.sd_pct == pytest.approx((1 - math.exp(-sd)) * 100, rel=1e-14)
    assert stats.se_pct_upper == pytest.approx((math.exp(se) - 1) * 100, rel=1e-14)
    assert (stats.n_used, stats.n_total, stats.mode) == (4, 4, "geometric")
    json.dumps(stats.to_dict())


def test_arithmetic_mode_and_negative_mean():
    values = np.array([-2.0, -4.0, -6.0])
    stats = describe(values, mode="arithmetic")
    assert stats.mean == stats.center == -4.0
    assert stats.sd == pytest.approx(2.0) and stats.se == pytest.approx(2 / math.sqrt(3))
    assert stats.se_pct == pytest.approx(-(2 / math.sqrt(3)) / 4 * 100)  # signed, as Tripoli reports it
    assert stats.sd_pct == pytest.approx(-50.0)
    assert stats.se_pct_upper == stats.se_pct


def test_mask_nan_and_nonpositive_values():
    values = np.array([1.0, 2.0, np.nan, -1.0, 0.0, 4.0, 100.0])
    include = np.array([True, True, True, True, True, True, False])
    geometric = describe(values, include, mode="geometric")
    assert geometric.n_used == 3 and geometric.n_total == 7
    assert geometric.mean == pytest.approx(2.0, rel=1e-15)  # (1 * 2 * 4) ** (1/3)
    arithmetic = describe(values, include, mode="arithmetic")
    assert arithmetic.n_used == 5 and arithmetic.mean == pytest.approx(6.0 / 5)
    assert np.isnan(transform(values, "geometric")[[2, 3, 4]]).all()


def test_too_few_values_give_nan_not_errors():
    empty = describe(np.array([1.0, 2.0]), np.array([False, False]))
    assert empty.n_used == 0 and math.isnan(empty.mean) and math.isnan(empty.se_pct)
    single = describe(np.array([2.0]))
    assert single.n_used == 1 and single.mean == pytest.approx(2.0) and math.isnan(single.sd) and math.isnan(single.se_pct)
    with pytest.raises(ValueError):
        describe(np.ones(3), np.ones(2, dtype=bool))
    with pytest.raises(ValueError):
        describe(np.ones(3), mode="harmonic")


def test_function_stats_picks_the_mode_by_kind():
    values = np.array([1.0, 2.0, 4.0])
    assert function_stats(values, is_ratio=True).mode == "arithmetic"
    assert function_stats(values, is_ratio=True, ratio_mode="geometric").mode == "geometric"
    assert function_stats(values, is_ratio=False).mode == "arithmetic"
    assert function_stats(values, is_ratio=False, ratio_mode="geometric").mean == pytest.approx(7 / 3)


def test_block_stats_split_by_block():
    values = np.array([1.0, 2.0, 3.0, 10.0, 20.0, 30.0])
    block = np.array([1, 1, 1, 2, 2, 2])
    include = np.array([True, True, True, True, False, True])
    per_block = block_stats(values, include, block, is_ratio=False)
    assert list(per_block) == [1, 2]
    assert per_block[1].mean == 2.0 and per_block[1].n_used == 3
    assert per_block[2].mean == 20.0 and per_block[2].n_used == 2 and per_block[2].n_total == 3


def test_block_weighted_mean_standard_and_tripoli_conventions():
    # Block 1: 1, 3 (mean 2, sd √2, se 1); block 2: 4, 6, 8 (mean 6, sd 2, se 2/√3).
    values = np.array([1.0, 3.0, 4.0, 6.0, 8.0])
    block = np.array([1, 1, 2, 2, 2])
    standard = block_weighted_mean(values, None, block, is_ratio=False, convention="standard")
    w = np.array([1.0, 3.0 / 4.0])
    center = (2 * w[0] + 6 * w[1]) / w.sum()
    assert standard.center == pytest.approx(center) and standard.sigma == pytest.approx(math.sqrt(1 / w.sum()))
    assert standard.mswd == pytest.approx(w[0] * (2 - center) ** 2 + w[1] * (6 - center) ** 2)
    assert standard.n_blocks == 2 and standard.sigma_pct == pytest.approx(standard.sigma / center * 100)

    tripoli = block_weighted_mean(values, None, block, is_ratio=False)
    w = np.array([1 / 2.0, 1 / 4.0])  # 1 / SD²
    center = (2 * w[0] + 6 * w[1]) / w.sum()
    variance = 1 / w.sum()
    assert tripoli.convention == "tripoli" and tripoli.center == pytest.approx(center)
    assert tripoli.mswd == pytest.approx(((2 - center) ** 2 + (6 - center) ** 2) / variance / 1)

    ratio = block_weighted_mean(np.exp(values / 10), None, block, is_ratio=True, ratio_mode="geometric", convention="standard")
    assert ratio.mode == "geometric" and ratio.mean == pytest.approx(math.exp(ratio.center))
    assert ratio.sigma_pct == pytest.approx(math.expm1(ratio.sigma) * 100)
    skipped = block_weighted_mean(values, None, block, is_ratio=False, block_included={1: False})
    assert skipped.n_blocks == 1 and math.isnan(skipped.mswd)


def test_correlation_perfect_and_anti():
    x = np.linspace(1.0, 2.0, 25)
    perfect = correlation(x, 3 * x + 1, mode_a="arithmetic", mode_b="arithmetic")
    assert perfect.r == pytest.approx(1.0, abs=1e-15) and perfect.n == 25
    # In geometric mode, r = x² and r = x³ have perfectly correlated logs.
    assert correlation(x**2, x**3, mode_a="geometric", mode_b="geometric").r == pytest.approx(1.0, abs=1e-15)
    assert correlation(x, 1 / x, mode_a="geometric", mode_b="geometric").r == pytest.approx(-1.0, abs=1e-15)


def test_correlation_uses_cycles_included_in_both():
    rng = np.random.default_rng(1)
    a = rng.normal(10, 1, 40)
    b = a + rng.normal(0, 0.5, 40)
    include_a = np.ones(40, dtype=bool)
    include_b = np.ones(40, dtype=bool)
    include_a[[1, 2]] = False
    include_b[[2, 3, 4]] = False
    result = correlation(a, b, include_a, include_b, mode_a="arithmetic", mode_b="arithmetic")
    shared = include_a & include_b
    assert result.n == 36 == shared.sum()
    assert result.r == pytest.approx(np.corrcoef(a[shared], b[shared])[0, 1], rel=1e-13)
    assert math.isnan(correlation(a[:2], b[:2]).r)
