"""Private-data regression checks; all acquisition data is read only at runtime."""
import numpy as np
import pytest

from rawtims.analysis import replay
from rawtims.parity import drive_path, run_parity, sheets_path

pytestmark = pytest.mark.slow


@pytest.fixture(scope='module')
def audit():
    path = drive_path()
    if not path.is_dir():
        pytest.skip('BSU acquisition folder is not available')
    return run_parity(path, sheets_path())


def test_every_distinct_project_has_parity_or_a_documented_exception(audit):
    assert len(audit.projects) == 31
    assert audit.workbook_count == 33
    for project in audit.projects:
        assert project.accounted, (project.label, project.issues, project.failures)
        assert project.project.version == '4.10.0.3'
        assert sum('2σ SD (plot band)' in c.quantity for c in project.checks) == len(project.project.ratios)
        # No tolerance exemption is allowed for source cycles, masks or project
        # statistics, including the internal checks of the unavailable source.
        assert all(c.passed for c in project.checks if not c.quantity.startswith('sheet '))
    assert sum(bool(p.issues) for p in audit.projects) == 1
    if audit.sheet_count:
        assert sum(any(c.exception for c in p.checks) and not p.issues for p in audit.projects) == 2


def test_all_pasted_ratios_match_the_correct_acquisition(audit):
    if not audit.sheet_count:
        pytest.skip('BSU reduction spreadsheets are not available')
    assert audit.sheet_count == 126  # 14 fractions × (6 Pb + 3 U)
    assert sum(p.sheet_matches for p in audit.projects) == 126
    # Exceptions must be justified by a different acquisition which actually
    # matches those sheet rows, not merely by a filename or broad tolerance.
    for fraction in ('z4', 'z7'):
        matched = [p for p in audit.projects if p.project.settings['sampleName'] == 'KG5'
                   and p.project.settings['fractionName'] == fraction and p.project.settings['ratioType'] == 'Pb'
                   and p.sheet_matches == 6]
        assert len(matched) == 1 and '.raw/' in matched[0].label


def test_project_masks_are_public_history_and_replay_exactly(audit):
    for project in audit.projects:
        a = project.analysis
        if a is None:
            continue
        restored = replay(a.run, a.history, strict=True)
        np.testing.assert_array_equal(restored.included, a.included)
        np.testing.assert_array_equal(restored.effective, a.effective)
        assert restored.settings == a.settings
        for i, r in enumerate(project.project.ratios):
            np.testing.assert_array_equal(a.included_for(a.keys[i]), r.accepted)
        assert all(op['op'] in ('set_setting', 'toggle_cycles', 'toggle_block') for op in a.history)


def test_real_oxide_and_processing_metadata(audit):
    uranium = [p for p in audit.projects if p.project.settings['ratioType'] == 'U']
    assert len(uranium) == 14
    for project in uranium:
        s = project.project.settings
        assert float(s['r18O_16O']) == 0.0020
        assert s['AmOxideCorrected'] and not s['AmFractionationCorrected']
        assert project.sheet_matches == 3 or not audit.sheet_count
        assert any('270/267 exactly equals' in note for note in project.notes)
    assert any('[36.3] ns' in fact for fact in audit.facts)
