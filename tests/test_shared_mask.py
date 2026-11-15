"""Shared contract-cycle selection and exact history, without Qt."""
import json
from dataclasses import replace

import numpy as np
import pytest
from reader_fixtures import B998, SYNTHETIC_U, TIMSDP_FILES, read

from rawtims.analysis import Analysis, AnalysisSettings, replay
from rawtims_gui.workspace import Workspace


@pytest.mark.parametrize('path', [B998, SYNTHETIC_U, TIMSDP_FILES['GHR1 230921F03 U-239'],
                                  TIMSDP_FILES['WH205 z41 U-655']])
def test_group_edits_history_replay_and_independence(path):
    a = Analysis(read(path), AnalysisSettings(synced=False))
    group = a.group_keys
    assert group and a.group_consistent()
    op = a.toggle_cycles([2, 4], [group[-1]], False)
    assert op['keys'] == group and len(a.history) == 1
    assert all(not a.included_for(k)[[2, 4]].any() for k in group)
    free = [k for k in a.keys if k not in group]
    assert all(a.included[:, a.index(k)].all() for k in free)
    a.toggle_block(int(a.blocks[0]), False)
    assert all(not a.included_for(k)[a.run.block == a.blocks[0]].any() for k in group)
    rebuilt = replay(a.run, json.loads(json.dumps(a.history)), AnalysisSettings(synced=False))
    np.testing.assert_array_equal(rebuilt.included, a.included)
    np.testing.assert_array_equal(rebuilt.effective, a.effective)
    assert rebuilt.group_consistent()
    a.undo()
    a.undo()
    assert a.included.all() and a.block_included.all()
    a.redo()
    assert a.group_consistent()
    if free:
        before = a.included[:, [a.index(k) for k in group]].copy()
        a.toggle_cycles([8], [free[0]], False)
        np.testing.assert_array_equal(before, a.included[:, [a.index(k) for k in group]])


def test_mapping_adoption_is_one_reversible_entry_and_workspace_follows_undo():
    w = Workspace()
    w.open([B998])
    a = w.analyses()[0]
    a.toggle_cycles([3], ['206/204 D'], False)
    a.toggle_cycles([9], ['206/207 F'], False)
    before = a.included.copy()
    choices = {r: m.to_dict() for r, m in w.mapping(a).ratios.items()}
    choices['206Pb/207Pb'] = {'function': '206/207 F'}
    n = len(a.history)
    w.set_mapping(a, choices)
    assert len(a.history) == n + 1 and a.history[-1]['op'] == 'set_mapping'
    assert a.group_consistent() and not a.included_for('206/207 F')[3] and a.included_for('206/207 F')[9]
    after = a.included.copy()
    a.undo()
    assert w.mapping(a).ratios['206Pb/207Pb'].key == '206/207 D'
    np.testing.assert_array_equal(a.included, before)
    a.redo()
    assert w.mapping(a).ratios['206Pb/207Pb'].key == '206/207 F'
    np.testing.assert_array_equal(a.included, after)
    rebuilt = replay(a.run, a.history)
    assert rebuilt.group_keys == a.group_keys and rebuilt.group_consistent()
    np.testing.assert_array_equal(rebuilt.included, after)


def test_u_includes_inputs_even_with_instrument_correction_and_pb_is_independent():
    u = Analysis(read(SYNTHETIC_U))
    assert {'270/267', '265/267'} <= set(u.group_keys)
    from rawtims.readers.functions import build_functions
    run = read(TIMSDP_FILES['WH205 z41 U-655'])
    names = [f.name.replace('270/267', '270/265') for f in run.functions]
    values = run.values.copy()
    values[:, run.keys.index('270/267')] *= run.column('267/265')
    derived = Analysis(replace(run, functions=tuple(build_functions(names)), values=values))
    assert {'267/265', '270/265', '238/235oc', '233/235oc', '238/233oc'} <= set(derived.group_keys)
    pb = Analysis(read(B998))
    u.toggle_cycles([1], ['270/267'], False)
    assert pb.included.all() and u.group_consistent()


def test_invalid_group_values_have_one_effective_mask_without_recorded_rejection():
    run = read(B998)
    invalid = run.invalid.copy()
    invalid[7, run.keys.index('206/204 D')] = True
    a = Analysis(replace(run, invalid=invalid))
    assert all(not a.included_for(k)[7] for k in a.group_keys)
    assert a.included.all() and not a.history and a.group_consistent()


@pytest.mark.parametrize('rule', ['chauvenet', 'k_sigma'])
@pytest.mark.parametrize('one', [False, True])
def test_rule_preview_counts_and_statistics_are_a_dry_run(rule, one):
    from rawtims import rules, stats
    a = Analysis(read(B998), AnalysisSettings(synced=False))
    before = a.included.copy()
    history = a.history
    key = '206/204 D'
    proposal = getattr(a, 'propose_' + rule)([key] if one else None)
    independently_flagged = {}
    for k in a.group_keys:
        data = np.log(a.column(k)) if rule == 'k_sigma' else a.column(k)
        function = rules.k_sigma_rejections if rule == 'k_sigma' else rules.chauvenet_rejections
        independently_flagged[k] = tuple(function(data, a.included_for(k)))
    assert proposal.flagged == independently_flagged
    expected = set(independently_flagged[key]) if one else {r for rows in independently_flagged.values() for r in rows}
    assert set(proposal.cycles) == expected and proposal.evaluation == ('one' if one else 'union')
    assert a.history == history
    np.testing.assert_array_equal(a.included, before)
    for k in a.group_keys:
        after = a.included_for(k).copy()
        after[list(expected)] = False
        computed = stats.describe(a.column(k), after)
        result = proposal.before_after[k]
        assert result['before']['n'] == a.stats(k).n_used
        assert result['before']['se_pct'] == a.stats(k).se_pct
        assert result['after']['n'] == computed.n_used
        assert result['after']['se_pct'] == pytest.approx(computed.se_pct)
    a.apply_rule(proposal)
    assert a.group_consistent()
    for k in a.group_keys:
        assert a.stats(k).n_used == proposal.before_after[k]['after']['n']
        assert a.stats(k).se_pct == pytest.approx(proposal.before_after[k]['after']['se_pct'])
    assert all(a.included[:, a.index(k)].all() for k in a.keys if k not in a.group_keys)
    rebuilt = replay(a.run, a.history, AnalysisSettings(synced=False))
    np.testing.assert_array_equal(rebuilt.included, a.included)
    a.undo()
    np.testing.assert_array_equal(a.included, before)


def test_synch_on_free_rule_does_not_touch_the_group():
    a = Analysis(read(B998))
    p = a.propose_chauvenet(['206/208 D'])
    a.apply_rule(p)
    assert all(a.included[:, a.index(k)].all() for k in a.group_keys)


def old_session(tmp_path):
    """A genuine pre-change rule record: no expanded targets or migration fields."""
    from rawtims.fractions import Fraction
    from rawtims.rules import propose
    from rawtims.session import SessionState, save_session
    a = Analysis(read(B998))
    keys = a.mapping.function_keys
    columns = [a.index(k) for k in keys]
    p = propose('chauvenet', a.values[:, columns], a.effective[:, columns], keys,
                [True] * len(keys), a.run.block, synced=False)
    op = {'op': 'apply_rule', 'description': p.describe(), **p.to_dict(),
          'changed': [[r, k] for k, rows in p.rejected.items() for r in rows]}
    old = replay(a.run, [op])
    f = Fraction('legacy')
    f.pb = old
    path = save_session(SessionState([f]), tmp_path / 'old.rawtims')
    document = json.loads(path.read_text())
    for record in document['runs']:
        record.pop('legacy_masks')
        record.pop('legacy_pending')
    path.write_text(json.dumps(document))
    return path, old.included.copy(), p


def test_old_session_is_exact_until_explicit_union_and_preserves_comparison_masks(tmp_path):
    from datetime import UTC, datetime

    from rawtims.exports import clipboard_text, cycles_csv_text
    from rawtims.fractions import FractionError, fraction_row
    from rawtims.session import load_session, save_session
    path, original, _proposal = old_session(tmp_path)
    state, problems = load_session(path)
    assert not problems
    a = state.analyses()[0]
    assert not a.group_consistent() and a.legacy_pending
    np.testing.assert_array_equal(a.included, original)
    assert set(a.group_differences()) == set(a.group_keys)
    for export in (lambda: fraction_row(state.fractions[0], datetime.now(UTC)),
                   lambda: clipboard_text(state.fractions[0]), lambda: cycles_csv_text(a)):
        with pytest.raises(FractionError, match=r'per-ratio selection \(legacy\)'):
            export()
    masks = {k: v.copy() for k, v in a.legacy_masks.items()}
    history = len(a.history)
    a.use_union_of_rejections()
    assert a.group_consistent() and not a.legacy_pending and len(a.history) == history + 1
    assert all(a.stats(k).n_used == 93 for k in a.group_keys)
    assert fraction_row(state.fractions[0], datetime.now(UTC))
    a.undo()
    np.testing.assert_array_equal(a.included, original)
    assert a.legacy_pending
    a.redo()
    again, errors = load_session(save_session(state, tmp_path / 'again.rawtims'))
    assert not errors and not again.analyses()[0].legacy_pending
    np.testing.assert_array_equal(again.analyses()[0].included, a.included)
    for key, mask in masks.items():
        np.testing.assert_array_equal(again.analyses()[0].legacy_masks[key], mask)
    again.analyses()[0].undo()
    assert again.analyses()[0].legacy_pending
    np.testing.assert_array_equal(again.analyses()[0].included, original)


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('rule', [None, 'chauvenet', 'k_sigma'])
def test_comparison_is_independent_arithmetic_and_read_only(tmp_path, legacy, rule):
    from rawtims.legacy import legacy_comparison
    from rawtims.rules import chauvenet_rejections, k_sigma_rejections
    from rawtims.session import load_session
    a = load_session(old_session(tmp_path)[0])[0].analyses()[0] if legacy else Analysis(read(B998))
    a.toggle_cycles([5], [a.group_keys[0]], False)
    a.set_setting('stat_mode', 'geometric')
    before, history = a.included.copy(), a.history
    result = legacy_comparison(a, a.mapping, rule)
    for row in result.rows:
        values = a.column(row.key)
        if rule:
            mask = ~a.invalid[:, a.index(row.key)]
            flags = chauvenet_rejections(values, mask) if rule == 'chauvenet' else k_sigma_rejections(np.log(values), mask)
            mask[flags] = False
        else:
            mask = a.legacy_masks.get(row.key, a.included_for(row.key))
        selected = values[mask]
        assert row.stats.mean == pytest.approx(selected.mean())
        assert row.stats.se_pct == pytest.approx(100 * selected.std(ddof=1) / np.sqrt(len(selected)) / selected.mean())
        assert row.stats.n_used == len(selected) and row.stats.mode == 'arithmetic'
        with pytest.raises(ValueError):
            result.masks[row.key][0] = False
    np.testing.assert_array_equal(a.included, before)
    assert a.history == history and result.clipboard_text.count('(Mean, %StdErr)') == 6


def test_both_runs_record_the_shared_cycle_selection():
    from datetime import UTC, datetime

    from rawtims import fractions
    f = fractions.Fraction('paired', pb=Analysis(read(B998)), u=Analysis(read(SYNTHETIC_U)))
    row = fractions.fraction_row(f, datetime.now(UTC))
    assert row.values['Pb Cycle Selection'] == row.values['U Cycle Selection'] == 'shared'


def test_contract_has_shared_cycle_selection_provenance():
    from rawtims.contract import COLUMNS
    assert {'Pb Cycle Selection', 'U Cycle Selection'} <= {c.name for c in COLUMNS}


def test_invariant_is_checked_at_every_export_boundary(monkeypatch):
    from datetime import UTC, datetime

    from rawtims.exports import clipboard_text, cycles_csv_text
    from rawtims.fractions import Fraction, FractionError, fraction_row
    a = Analysis(read(B998))
    f = Fraction('B998', pb=a)
    checked = []
    def inconsistent():
        checked.append(True)
        return False
    monkeypatch.setattr(a, 'group_consistent', inconsistent)
    for export in (lambda: fraction_row(f, datetime.now(UTC)), lambda: clipboard_text(f), lambda: cycles_csv_text(a)):
        n = len(checked)
        with pytest.raises(FractionError, match='per-ratio selection'):
            export()
        assert len(checked) > n


def test_mixed_rule_keeps_free_synch_setting_independent_of_group_union():
    a = Analysis(read(B998), AnalysisSettings(synced=False))
    free = ['206/208 D', '206/207 F']
    p = a.propose_chauvenet(['206/204 D', *free], synced=False)
    a.apply_rule(p)
    for key in free:
        assert set(np.flatnonzero(~a.included[:, a.index(key)])) == set(p.rejected[key])
    assert a.group_consistent()
    assert all(a.included[:, a.index(k)].all() for k in a.keys if k not in a.group_keys and k not in free)


def test_cycle_selection_values_are_validated_and_written_by_default():
    from datetime import UTC, datetime

    from rawtims.contract import CONTRACT_ID, FractionRow
    from rawtims.fractions import Fraction, fraction_row
    row = fraction_row(Fraction('B998', pb=Analysis(read(B998))), datetime.now(UTC))
    assert row.values['Pb Cycle Selection'] == 'shared' and 'U Cycle Selection' not in row.values
    bad = FractionRow.from_csv({'Contract': CONTRACT_ID, 'Fraction ID': 'z1', 'Pb Cycle Selection': 'sometimes'})
    assert any('is not one of' in p for p in bad.problems())
