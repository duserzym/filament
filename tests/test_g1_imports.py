"""Private acquisition inputs are read only and never copied into the repository."""
import numpy as np
import pytest

from rawtims.parity import drive_path
from rawtims.projects import MissingProjectSource, open_project
from rawtims.readers import open_run
from rawtims_gui.workspace import Workspace

pytestmark = pytest.mark.slow


def examples():
    folder = drive_path()
    if not folder.is_dir():
        pytest.skip('Boise examples unavailable')
    return folder


def test_raw_folder_attaches_workbook():
    folder = next(examples().glob('*KD33 z1 Pb.raw'))
    run = open_run(folder)
    assert run.n_cycles == 228
    assert run.raw.path.startswith(str(folder))
    assert run.reduction_parameters.daly_dead_time_ns == 36.3


def test_project_masks_history_undo_and_exact_source():
    folder = examples()
    a = open_project(folder / 'KD33_z1_Pb.trip')
    assert a.legacy_pending and not a.group_consistent()
    assert all(op['label'].startswith('Imported from Tripoli project KD33_z1_Pb.trip') for op in a.history)
    before = a.included.copy()
    op = a.undo()
    assert np.count_nonzero(a.included) > np.count_nonzero(before)
    a.redo()
    np.testing.assert_array_equal(a.included, before)
    assert op['keys']
    with pytest.raises(MissingProjectSource, match='B1609_F12_GA9683326 z3 Pb-56377.xls'):
        open_project(folder / 'KG5_z7_Pb.trip')
    with pytest.raises(ValueError, match='Expected source workbook'):
        open_project(folder / 'KG5_z7_Pb.trip', next(folder.glob('*KD33 z1 Pb-*.xls')))


def test_u_project_retains_workbook_rows_and_warnings_in_export():
    from datetime import datetime
    workspace = Workspace()
    workspace.open([examples() / 'KD33_z1_U_partial.trip'])
    a = workspace.analyses()[0]
    assert a.n_cycles == 300 and a.run.warnings
    a.use_union_of_rejections()
    row = workspace.fraction_row(workspace.fractions[0], datetime.now().astimezone())
    assert '270/267' in row.to_csv()['Notes']


def test_all_distinct_projects_and_top_level_acquisition_folder():
    from rawtims.parity import distinct_projects
    projects = distinct_projects(examples())
    assert len(projects) == 31
    opened = missing = 0
    for path, _digest in projects:
        try:
            analysis = open_project(path)
        except MissingProjectSource as error:
            assert 'B1609_F12_GA9683326 z3 Pb-56377.xls' in str(error)
            missing += 1
        else:
            assert analysis.legacy_pending
            opened += 1
    assert (opened, missing) == (30, 1)
    workspace = Workspace()
    workspace.open([examples()])
    assert len(workspace.analyses()) == 33


def test_two_sequence_raw_is_explicitly_unavailable():
    from dataclasses import replace

    from rawtims.readers import UnsupportedFile
    from rawtims.reprocess import reprocess
    for pattern, cycles in (('*KG5 z1 Pb-*.xls', 250), ('*KG5 z7 Pb_2-*.xls', 150)):
        run = open_run(next(examples().glob(pattern)))
        assert run.n_cycles == cycles
        assert '2 sequence' in run.metadata.method
        with pytest.raises(UnsupportedFile, match='two-sequence Pb.*3 ppm.*workbook route'):
            reprocess(run, replace(run.reduction_parameters, route='raw'))
