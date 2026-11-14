"""Rejection rules: hand-made arrays with known answers and one real fixture (SPEC F9)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from rawtims.rules import RuleProposal, chauvenet_rejections, k_sigma_rejections, propose
from reader_fixtures import TIMSDP_FILES, read


def _chauvenet_data(a: float = 4.0, n_pairs: int = 9) -> np.ndarray:
    # 2·n_pairs values of ±1, then +a and −a: mean 0, SD² = (2·n_pairs + 2a²) / (n − 1).
    return np.array([1.0, -1.0] * n_pairs + [a, -a])


def test_chauvenet_known_answer():
    data = _chauvenet_data()  # n = 20, SD = √(50/19) = 1.6222
    # For ±4: z = 2.4658, C = 20 · erfc(z/√2) = 0.273 < 0.5, rejected. For ±1: C = 10.8, kept.
    sd = math.sqrt(50 / 19)
    assert 20 * math.erfc(4 / sd / math.sqrt(2)) == pytest.approx(0.2734, abs=1e-4)
    assert chauvenet_rejections(data).tolist() == [18, 19]
    assert chauvenet_rejections(data, probability=0.2).tolist() == []  # 0.273 is not below 0.2
    assert chauvenet_rejections(data[1:]).tolist() == []  # 19 values: below the minimum count of 20
    assert chauvenet_rejections(data[1:], min_n=19).tolist() != []


def test_chauvenet_counts_only_included_values_and_is_one_pass():
    data = np.concatenate([_chauvenet_data(), [100.0]])
    include = np.ones(data.size, dtype=bool)
    include[-1] = False  # an excluded wild value takes no part and is not proposed again
    assert chauvenet_rejections(data, include).tolist() == [18, 19]
    # One pass: with the 100 included, the SD is so inflated that only the 100 goes.
    assert chauvenet_rejections(data).tolist() == [20]
    assert chauvenet_rejections(np.full(25, 3.0)).tolist() == []  # zero SD: nothing


def test_k_sigma_iterates():
    data = np.array([1.0, -1.0] * 10 + [4.0, 40.0])
    # Pass 1: mean 2, SD 8.586: only 40 is beyond 2 SD. Pass 2: mean 0.190, SD 1.327: 4 is beyond 2.655.
    assert k_sigma_rejections(data, max_iterations=1).tolist() == [21]
    assert k_sigma_rejections(data).tolist() == [20, 21]
    assert k_sigma_rejections(data, k=50).tolist() == []
    include = np.ones(data.size, dtype=bool)
    include[21] = False
    assert k_sigma_rejections(data, include).tolist() == [20]
    with pytest.raises(ValueError):
        k_sigma_rejections(data, k=0)


def test_propose_synced_per_function_and_block_scope():
    values = np.column_stack([_chauvenet_data(), _chauvenet_data()[::-1]])
    include = np.ones(values.shape, dtype=bool)
    block = np.repeat([1, 2], 10)
    synced = propose("chauvenet", values, include, ["a", "b"], [False, False], block)
    assert synced.synced and synced.rejected == {"a": (18, 19), "b": (0, 1)} and synced.cycles == (0, 1, 18, 19)
    assert synced.params == {"probability": 0.5, "min_n": 20, "log_ratios": False}
    per_function = propose("chauvenet", values, include, ["a", "b"], [False, False], block, synced=False)
    assert not per_function.synced and per_function.rejected == synced.rejected
    by_block = propose("chauvenet", values, include, ["a", "b"], [False, False], block, scope="block")
    assert by_block.cycles == ()  # 10 cycles per block is below the minimum count
    by_block = propose("k_sigma", values[:, :1], include[:, :1], ["a"], [False], block, scope="block", k=1.5)
    assert by_block.scope == "block" and by_block.params["k"] == 1.5
    assert RuleProposal.from_dict(by_block.to_dict()) == by_block
    with pytest.raises(TypeError):
        propose("chauvenet", values, include, ["a", "b"], [False, False], block, k=2)


def test_real_fixture_against_an_independent_computation():
    run = read(TIMSDP_FILES["GHR1 230921F03 U-239"])
    keys = ["265/267", "270/267", "272/270"]
    values = np.column_stack([run.column(key) for key in keys])
    include = ~np.column_stack([run.invalid[:, run.function(key).index] for key in keys])
    proposal = propose("chauvenet", values, include, keys, [True] * 3, run.block, synced=False)
    for j, key in enumerate(keys):
        x = values[:, j]
        n = len(x)
        mean = sum(x) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in x) / (n - 1))
        expected = tuple(i for i, v in enumerate(x) if n * math.erfc(abs(v - mean) / sd / math.sqrt(2)) < 0.5)
        assert proposal.rejected[key] == expected, key
    assert proposal.rejected["270/267"]  # the run does have Chauvenet outliers

    k_proposal = propose("k_sigma", values, include, keys, [True] * 3, run.block, synced=True)
    logs = np.log(values[:, 1])
    keep = np.ones(len(logs), dtype=bool)
    for _ in range(10):
        m, s = logs[keep].mean(), logs[keep].std(ddof=1)
        out = keep & (np.abs(logs - m) > 2 * s)
        if not out.any():
            break
        keep &= ~out
    assert k_proposal.rejected["270/267"] == tuple(np.flatnonzero(~keep))
