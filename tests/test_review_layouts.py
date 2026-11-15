"""Opt-in Review layouts use the same run, group mask and undo history."""
import numpy as np
import pytest
from PySide6 import QtCore, QtTest, QtWidgets
from reader_fixtures import B998

from rawtims_gui import main as gui
from rawtims_gui.studio.theme import build_application


@pytest.fixture(params=['strips', 'wall'])
def variant(request, qt_settings_folder, monkeypatch, tmp_path):
    app = build_application(['layout-test'], theme_mode='light')
    settings = QtCore.QSettings(str(tmp_path / 'layout.ini'), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(gui, 'app_settings', lambda: settings)
    window = gui.MainWindow(restore_geometry=False, layout=request.param)
    window.resize(1280, 800)
    window.show()
    window.open_paths([str(B998)], synchronous=True)
    app.processEvents()
    yield window
    window.unsaved_prompt = lambda _name: 'discard'
    window.close()
    window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_b998_block_cells_are_shared_and_undoable(variant):
    window = variant
    analysis = window.analysis
    assert analysis.run.raw.name == B998.name
    assert len(window.plot_wall.plots) == 6
    assert window.cycles_used() == (96, 96)
    assert '96/96' in window.review_shell.state.text()
    before = analysis.effective.copy()
    # A manual rejection survives block exclusion, reinclusion and undo.
    window.request_toggle('206/204 D', [22])
    manual = analysis.effective.copy()
    cell = window.block_header.cells[2]
    QtTest.QTest.mouseClick(cell, QtCore.Qt.MouseButton.LeftButton)
    rows = analysis.run.block == 2
    assert not analysis.effective[rows].any()
    assert analysis.group_consistent()
    assert '0/16' in cell.text()
    assert not cell.isChecked()
    window.undo()
    np.testing.assert_array_equal(analysis.effective, manual)
    window.redo()
    assert not analysis.effective[rows].any()
    QtTest.QTest.mouseClick(cell, QtCore.Qt.MouseButton.LeftButton)
    np.testing.assert_array_equal(analysis.effective, manual)
    window.undo()
    window.undo()
    window.undo()
    np.testing.assert_array_equal(analysis.effective, before)


def test_resize_collapse_maximise_and_reset(variant):
    window = variant
    shell = window.review_shell
    for width, height, columns in ((1024, 640, 1), (1280, 800, 2), (1440, 900, 3)):
        window.resize(width, height)
        QtWidgets.QApplication.processEvents()
        assert window.size() == QtCore.QSize(width, height)
        assert window.plot_wall.column_count() == (1 if window.layout_name == 'strips' else columns)
        assert not window.plot_wall.horizontalScrollBar().isVisible()
        assert shell.inspector.content.width() <= shell.inspector.width()
    shell.inspector.set_collapsed(True, animate=False)
    QtWidgets.QApplication.processEvents()
    assert shell.inspector.width() == 30
    shell.inspector.set_collapsed(False, animate=False)
    QtWidgets.QApplication.processEvents()
    assert shell.inspector.width() >= shell.inspector.default
    card = window.plot_wall.cards[0]
    card.max_button.click()
    assert window.plot_wall.maximised is card
    window.clear_selection_action.trigger()
    assert window.plot_wall.maximised is None
    shell.toggle_outer()
    assert not shell.inspector.isVisible()
    window.clear_selection_action.trigger()
    assert shell.inspector.isVisible()
    shell.splitter.setSizes([100, 700, 400] if window.layout_name == 'strips' else [700, 400])
    shell.splitter.save()
    assert window.settings.contains(f'review/{window.layout_name}/splitter_v1')
    QtTest.QTest.mouseDClick(shell.splitter.handle(1), QtCore.Qt.MouseButton.LeftButton)
    reset = shell.splitter.sizes()
    shell.splitter.setSizes(shell.splitter.defaults)
    assert shell.splitter.sizes() == reset


def test_cli_default_stays_classic():
    assert gui.parse_arguments([]).layout == 'classic'
    assert gui.parse_arguments(['--layout', 'strips']).layout == 'strips'
    assert gui.parse_arguments(['--layout', 'wall']).layout == 'wall'


def test_splitter_settings_are_restored_per_layout(variant):
    window = variant
    shell = window.review_shell
    shell.splitter.setSizes([56, 750, 400] if window.layout_name == 'strips' else [750, 400])
    shell.splitter.save()
    expected = shell.splitter.sizes()
    second = gui.MainWindow(restore_geometry=False, layout=window.layout_name)
    second.resize(window.size())
    second.show()
    QtWidgets.QApplication.processEvents()
    try:
        assert second.review_shell.splitter.sizes() == expected
        other = 'wall' if window.layout_name == 'strips' else 'strips'
        assert not window.settings.contains(f'review/{other}/splitter_v1')
    finally:
        second.close()
        second.deleteLater()


def test_many_long_fraction_ids_fit_and_remain_selectable(variant):
    from copy import copy

    window = variant
    fractions = []
    for index in range(40):
        fraction = copy(window.current[0])
        fraction.fraction_id = f'Long laboratory sample identifier with aliquot and fraction {index:02d}'
        fractions.append(fraction)
    window.workspace.fractions = fractions
    window.fraction_list.set_fractions(fractions, None)
    window.select_run(fractions[0], 'Pb')
    window.resize(1024, 640)
    QtWidgets.QApplication.processEvents()
    assert window.review_shell.picker.count() == 40
    window.review_shell.picker.setCurrentIndex(39)
    window.review_shell.select_run(39)
    assert window.current == (fractions[39], 'Pb')
    if window.layout_name == 'strips':
        window.review_shell.toggle_rail()
        QtWidgets.QApplication.processEvents()
        assert window.fraction_list.verticalScrollBar().maximum() > 0
        assert not window.fraction_list.horizontalScrollBar().isVisible()
        assert window.plot_control_bar.width() >= window.plot_control_bar.minimumSizeHint().width()
    assert window.size() == QtCore.QSize(1024, 640)
