"""Analysis: include mask, operations, undo/redo/reset, history and replay (SPEC F8-F10, section 0 decision 3)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from rawtims.analysis import Analysis, AnalysisSettings, ReplayMismatch, replay
from reader_fixtures import B998, GHR1_PB_XLS, GHR1_U_XLS, NBS981_XLS, SYNTHETIC_PB, SYNTHETIC_U, TIMSDP_FILES, read

U239 = TIMSDP_FILES["GHR1 230921F03 U-239"]
ALL_FILES = [B998, GHR1_PB_XLS, GHR1_U_XLS, NBS981_XLS, *TIMSDP_FILES.values(), SYNTHETIC_U, SYNTHETIC_PB]


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.stem)
def test_opening_rejects_nothing(path):
    analysis = Analysis(read(path))
    assert analysis.included.all() and analysis.block_included.all()
    assert np.array_equal(analysis.effective, ~analysis.invalid)
    assert analysis.history == [] and not analysis.can_undo and not analysis.can_redo
    for key in analysis.keys:
        assert analysis.stats(key).n_used == int((~analysis.invalid[:, analysis.index(key)]).sum())


def _snapshot(analysis: Analysis):
    return analysis.included.copy(), analysis.block_included.copy(), analysis.settings, analysis.values.copy()


def _same(a, b):
    return np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]) and a[2] == b[2] and np.array_equal(a[3], b[3], equal_nan=True)


def test_preview_does_not_change_the_mask_apply_and_undo_restore_it():
    analysis = Analysis(read(U239))
    before = _snapshot(analysis)
    proposal = analysis.propose_chauvenet()
    k_proposal = analysis.propose_k_sigma(scope="block")
    assert proposal.cycles and k_proposal.cycles
    assert _same(before, _snapshot(analysis)) and analysis.history == []

    op = analysis.apply_rule(proposal)
    assert op["rule"] == "chauvenet" and op["synced"] and op["scope"] == "run"
    assert op["description"].startswith("Chauvenet P=0.5 n>=20 (run, synced)")
    excluded_rows = np.flatnonzero(~analysis.included.all(axis=1)).tolist()
    assert excluded_rows == list(proposal.cycles)
    assert (~analysis.included[proposal.cycles, :]).all()  # synced: every function, oxide columns included
    analysis.undo()
    assert _same(before, _snapshot(analysis))
    analysis.redo()
    assert np.flatnonzero(~analysis.included.all(axis=1)).tolist() == list(proposal.cycles)


def test_per_function_rule_touches_only_its_keys():
    analysis = Analysis(read(U239))
    proposal = analysis.propose_chauvenet(["270/267", "272/270"], synced=False)
    analysis.apply_rule(proposal)
    for key in analysis.keys:
        rejected = set(proposal.rejected.get(key, ()))
        assert set(np.flatnonzero(~analysis.included[:, analysis.index(key)]).tolist()) == rejected, key


def test_toggles_settings_reset_history_and_replay():
    run = read(U239)
    analysis = Analysis(run)
    analysis.toggle_cycles([5, 6], ["270/267"])
    assert not analysis.included[[5, 6], analysis.index("270/267")].any() and analysis.included[[5, 6], 0].all()
    analysis.toggle_cycles([5, 7])  # synced; not every addressed flag is on, so all of them go on
    assert analysis.included[[5, 7], :].all()
    analysis.toggle_cycles([5, 7])  # now all on, so all go off
    assert not analysis.included[[5, 7], :].any()
    analysis.toggle_block(2)
    assert not analysis.effective[run.block == 2].any()
    stats_before = analysis.stats("238/235oc")
    analysis.set_setting("r18", 0.00206)
    assert analysis.stats("238/235oc").mean != stats_before.mean
    assert analysis.function("238/235oc").metadata["r18"] == 0.00206
    analysis.apply_rule(analysis.propose_k_sigma(["270/267"], synced=False))
    analysis.set_setting("stat_mode", "arithmetic")
    assert analysis.stats("270/267").mode == "arithmetic"

    history = analysis.history
    assert [op["op"] for op in history] == ["toggle_cycles", "toggle_cycles", "toggle_cycles", "toggle_block", "set_setting", "apply_rule", "set_setting"]
    restored = json.loads(json.dumps(history))
    rebuilt = replay(run, restored)
    assert _same(_snapshot(rebuilt), _snapshot(analysis)) and rebuilt.history == history

    snapshot = _snapshot(analysis)
    analysis.reset()
    assert analysis.included.all() and analysis.block_included.all()
    analysis.undo()
    assert _same(_snapshot(analysis), snapshot)

    while analysis.can_undo:
        analysis.undo()
    fresh = Analysis(run)
    assert _same(_snapshot(analysis), _snapshot(fresh)) and analysis.history == []
    analysis.redo()
    analysis.toggle_block(1)  # a new operation drops the redo stack
    assert not analysis.can_redo and len(analysis.history) == 2


def test_replay_detects_a_history_that_no_longer_fits():
    run = read(U239)
    analysis = Analysis(run)
    analysis.toggle_cycles([3], ["265/267"], include=False)
    history = analysis.history
    history[0]["changed"] = [[4, "265/267"]]
    with pytest.raises(ReplayMismatch):
        replay(run, history)
    assert not replay(run, history, strict=False).included[3, analysis.index("265/267")]
    with pytest.raises(ValueError):
        replay(run, [{"op": "explode"}])


def test_settings_validation_and_correlation():
    run = read(U239)
    analysis = Analysis(run, AnalysisSettings(synced=False))
    with pytest.raises(ValueError):
        analysis.set_setting("r18", -1.0)
    with pytest.raises(KeyError):
        analysis.set_setting("colour", "red")
    with pytest.raises(ValueError):
        AnalysisSettings(stat_mode="median")
    assert analysis.propose_chauvenet().synced is False
    assert analysis.history == []
    # 238/235oc is built from 270/267 and 265/267: strongly correlated with 270/267, over identical cycle sets.
    analysis.toggle_cycles([0, 1, 2], ["270/267"], include=False)
    corr = analysis.correlation("270/267", "238/235oc")
    assert corr.n == run.n_cycles - 3 and corr.r > 0.99
    assert analysis.correlation("270/267", "270/267").r == pytest.approx(1.0, abs=1e-12)
    blocks = analysis.block_stats("270/267")
    assert sum(s.n_used for s in blocks.values()) == analysis.stats("270/267").n_used
    assert analysis.block_weighted_mean("270/267", convention="standard").n_blocks == run.blocks_measured
