"""Per-function cache invalidation and legacy-rule export provenance."""
from dataclasses import replace

import numpy as np
import pytest
from reader_fixtures import B998

from rawtims.analysis import Analysis
from rawtims.fractions import filter_rule_text
from rawtims.readers import open_run


def test_only_changed_function_statistics_are_recomputed():
    a = Analysis(open_run(B998))
    first, other = a.ratio_keys[:2]
    before = {k: (a.stats(k), a.block_stats(k), a.block_weighted_mean(k)) for k in (first, other)}
    a.toggle_cycles([4], keys=[first])
    for index, method in enumerate((a.stats, a.block_stats, a.block_weighted_mean)):
        assert method(other) is before[other][index]
        assert method(first) is not before[first][index]
    # Notebook clients can still edit arrays directly; signatures catch that.
    stat = a.stats(other)
    a.values[3, a.index(other)] *= 2
    assert a.stats(other) is not stat
    for key in a.keys:
        np.testing.assert_array_equal(a.included_for(key), a.effective[:, a.index(key)])


@pytest.mark.parametrize('rule', ['legacy_two_sigma', 'legacy_chauvenet'])
def test_legacy_rule_provenance_and_replay(rule):
    from rawtims.analysis import replay
    a = Analysis(open_run(B998))
    key = a.ratio_keys[0]
    a.values[:, a.index(key)] = 1
    a.values[-1, a.index(key)] = 10
    method = getattr(a, 'propose_' + rule)
    proposal = method([key], synced=False)
    assert proposal.cycles
    a.apply_rule(proposal)
    assert 'Legacy' in filter_rule_text(a)
    # Replay identity is checked separately by existing strict rule tests;
    # these synthetic values must be the replay source as well.
    run = replace(a.run, values=a.values.copy())
    restored = replay(run, a.history)
    np.testing.assert_array_equal(restored.included, a.included)


def test_cached_reduction_undo_checks_workbook_hash(tmp_path):
    source = tmp_path / B998.name
    source.write_bytes(B998.read_bytes())
    a = Analysis(open_run(source))
    params = replace(a.run.reduction_parameters, daly_dead_time_ns=40)
    prepared = replace(a.run, reduction_parameters=params)
    a.set_reduction_parameters(params, prepared_run=prepared)
    source.write_bytes(b'changed source')
    with pytest.raises(ValueError, match='workbook source changed'):
        a.undo()
    assert a.run.reduction_parameters == params


@pytest.mark.parametrize('rule', ['legacy_two_sigma', 'legacy_chauvenet'])
def test_explicit_legacy_per_ratio_masks_still_block_ordinary_export(rule):
    from rawtims.analysis import replay
    from rawtims.fractions import FractionError, require_shared_selection
    from rawtims.mapping import propose_mapping
    a = Analysis(open_run(B998))
    a.mapping = propose_mapping(a)
    key, other = a.group_keys[:2]
    a.values[:, a.index(key)] = 1
    a.values[-1, a.index(key)] = 10
    proposal = getattr(a, 'propose_' + rule)([key], per_ratio=True)
    assert proposal.targets == {key: (a.n_cycles - 1,)}
    assert proposal.evaluation == 'legacy_per_ratio' and not proposal.synced
    a.apply_rule(proposal)
    assert a.included[-1, a.index(other)] and not a.included[-1, a.index(key)]
    with pytest.raises(FractionError, match='per-ratio selection'):
        require_shared_selection(a)
    restored = replay(replace(a.run, values=a.values.copy()), a.history)
    np.testing.assert_array_equal(restored.included, a.included)
    a.undo()
    require_shared_selection(a)
    a.redo()
    a.use_union_of_rejections()
    require_shared_selection(a)
