"""P3 lab UI and diagnostic isolation acceptance. No Tripoli screenshot oracle exists."""
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import test_p2_reports_ui as p2
from PySide6 import QtCore, QtWidgets
from test_p3_composition import two_members

from rawtims.contract import csv_text
from rawtims.exports import clipboard_text, cycles_csv_text
from rawtims.session import load_session, save_session
from rawtims_gui.composition import CompositionDialog


@pytest.fixture
def window(monkeypatch, tmp_path):
    yield from p2.window.__wrapped__(monkeypatch, tmp_path)


def fill(dialog, expression, name='Synthetic diagnostic', key='derived:user1'):
    dialog.output_key.setText(key)
    dialog.output_name.setText(name)
    dialog.formula.setText(expression)


def test_editor_library_undo_redo_delete_and_session(window,tmp_path):
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1911,2406.
    Separate composition history is the P3 reversible implementation of editor/library/undo.
    """
    a, fraction = window.analysis, window.current[0]
    stamp = datetime(2026,11,25,tzinfo=UTC)
    def outputs():
        return csv_text([window.workspace.fraction_row(fraction,stamp)]),clipboard_text(fraction),cycles_csv_text(a),a.history
    before = outputs()
    dialog = CompositionDialog(window)
    fill(dialog,f'[{a.keys[0]}] * 2')
    dialog.save_expression()
    assert len(dialog.book.objects[0].expressions) == 1
    assert dialog.library.currentData() == 'derived:user1'
    assert dialog.table.derived[0].spec.key not in a.keys
    assert window.is_modified()
    np.testing.assert_allclose(dialog.table.derived[0].values,a.column(a.keys[0])*2)
    dialog.function.setCurrentIndex(dialog.function.findData('derived:user1'))
    model = dialog.cycles.model()
    assert model.rowCount() == a.n_cycles
    assert model.data(model.index(0,5)) == 'Included'
    dialog.undo()
    assert not dialog.book.objects
    dialog.redo()
    assert len(dialog.book.objects[0].expressions) == 1
    fill(dialog,'[missing]')
    previous = dialog.book.to_dict()
    dialog.save_expression()
    assert 'missing' in dialog.notice.text() and dialog.book.to_dict() == previous
    dialog.refresh()
    dialog.remove_expression()
    assert not dialog.book.objects[0].expressions
    dialog.undo()
    path = save_session(window.workspace.session_state(),tmp_path/'synthetic.rawtims')
    state, problems = load_session(path)
    assert not problems
    assert state.composition == window.workspace.composition
    assert outputs() == before
    assert 'derived:user1' not in json.dumps(json.loads(path.read_text())['runs'])
    assert 'SE²' in dialog.estimators.text() and 'SD²' in dialog.estimators.text()
    assert any('Expressions / concatenation' in action.text() for action in window.diagnostics_menu.actions())
    dialog.close()


def test_ratio_fill_and_dependency_delete_refusal(window):
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1204.
    Synthetic existing columns only; no new species or uncertainty inference.
    """
    dialog = CompositionDialog(window)
    dialog.new_expression()
    dialog.output_name.setText('Synthetic ratio')
    dialog.numerator.setCurrentIndex(0)
    dialog.denominator.setCurrentIndex(1)
    dialog.fill_ratio()
    assert dialog.kind.currentText() == 'ratio'
    dialog.save_expression()
    assert len(dialog.table.derived) == 1
    fill(dialog,'[derived:user1]*2','Synthetic dependent','derived:dependent')
    dialog.save_expression()
    dialog.library.setCurrentIndex(dialog.library.findData('derived:user1'))
    previous = dialog.book.to_dict()
    dialog.remove_expression()
    assert 'missing reference' in dialog.notice.text() and dialog.book.to_dict() == previous
    dialog.close()


def test_concatenation_dialog_explicit_selection_and_provenance(window,monkeypatch):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:177-228.
    Synthetic dated members; require explicit selection and retain original boundaries.
    """
    a,b,sources = two_members()
    monkeypatch.setattr(window.workspace,'analyses',lambda: list(sources.values()))
    dialog = CompositionDialog(window)
    def choose(d):
        table = d.findChild(QtWidgets.QTableWidget)
        for row in range(2): table.item(row,0).setCheckState(QtCore.Qt.CheckState.Checked)
        buttons = d.findChild(QtWidgets.QDialogButtonBox)
        buttons.accepted.emit()
        return QtWidgets.QDialog.DialogCode.Accepted
    monkeypatch.setattr(QtWidgets.QDialog,'exec',choose)
    dialog.members_dialog()
    assert len(dialog.book.objects) == 1
    assert dialog.table.boundaries == (4,)
    assert dialog.table.run_ids[0] == a.run.run_id
    assert a.run.raw.sha256 in dialog.provenance.toPlainText()
    assert b.run.raw.sha256 in dialog.provenance.toPlainText()
    assert dialog.blocks.rowCount() == 4
    dialog.remove_object()
    assert not dialog.book.objects
    dialog.undo()
    assert len(dialog.book.objects) == 1
    assert dialog.table.boundaries == (4,)
    dialog.close()


@pytest.mark.parametrize('theme',['light','dark'])
@pytest.mark.parametrize('width,height',[(1280,800),(1440,900)])
def test_p3_layout_fits_all_tabs(window,theme,width,height,tmp_path,monkeypatch):
    """No Tripoli screenshot oracle: explicit P3 lab layout acceptance, both themes/sizes."""
    window.set_theme(theme)
    window.resize(width,height)
    dialog = CompositionDialog(window)
    fill(dialog,f'sqrt([{window.analysis.keys[0]}])')
    dialog.save_expression()
    dialog.show()
    folder = Path(os.environ.get('RAWTIMS_P3_SHOTS',tmp_path))
    folder.mkdir(parents=True,exist_ok=True)
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        for _ in range(3): QtWidgets.QApplication.processEvents()
        assert window.width() == width and window.height() == height
        assert window.plot_wall.horizontalScrollBar().maximum() == 0
        assert dialog.minimumSizeHint().width() < width
        assert dialog.width() < width and dialog.height() < height
        if index == 1:
            assert dialog.cycles.horizontalScrollBar().maximum() == 0
        if index == 2:
            assert dialog.blocks.horizontalScrollBar().maximum() == 0
        assert dialog.grab().save(str(folder/f'synthetic-p3-{theme}-{width}-tab{index}.png'))
    assert window.grab().save(str(folder/f'synthetic-p3-window-{theme}-{width}.png'))
    def inspect_members(members):
        members.show()
        for _ in range(3): QtWidgets.QApplication.processEvents()
        assert members.minimumSizeHint().width() < width
        assert members.width() < width and members.height() < height
        assert members.grab().save(str(folder/f'synthetic-p3-members-{theme}-{width}.png'))
        members.reject()
        return QtWidgets.QDialog.DialogCode.Rejected
    monkeypatch.setattr(QtWidgets.QDialog,'exec',inspect_members)
    dialog.members_dialog()
    dialog.close()


def test_unit_mismatch_ratio_and_empty_workspace(window):
    dialog = CompositionDialog(window)
    functions = list(dialog.table.functions)
    functions[0] = replace(functions[0],unit='SYNTHETIC incompatible')
    dialog.table = replace(dialog.table,functions=tuple(functions))
    dialog.numerator.setCurrentIndex(0)
    dialog.denominator.setCurrentIndex(1)
    dialog.fill_ratio()
    assert 'matching kinds and units' in dialog.notice.text()
    dialog.close()
    from rawtims_gui.workspace import Workspace
    window.workspace = Workspace()
    window.current = None
    other = CompositionDialog(window)
    assert other.table is None
    other.save_expression()
    assert not window.workspace.composition
    other.close()
