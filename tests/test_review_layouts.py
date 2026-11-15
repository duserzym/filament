"""The default wall obeys the shared panel contract and uses group-wide undo."""
import numpy as np
import pytest
from PySide6 import QtCore, QtTest, QtWidgets
from reader_fixtures import B998
from synthetic_review import install_synthetic_review

from rawtims_gui import main as gui
from rawtims_gui.review_layouts import reduced_motion
from rawtims_gui.studio.theme import build_application


@pytest.fixture
def wall(qt_settings_folder, monkeypatch, tmp_path):
    app = build_application(['layout-test'], theme_mode='light')
    settings = QtCore.QSettings(str(tmp_path / 'layout.ini'), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(gui, 'app_settings', lambda: settings)
    window = gui.MainWindow(restore_geometry=False)
    window.resize(1280, 800)
    window.show()
    window.open_paths([str(B998)], synchronous=True)
    settle()
    # Offscreen Qt does not activate the viewer after constructing plot widgets.
    QtWidgets.QApplication.setActiveWindow(window)
    yield window
    window.unsaved_prompt = lambda _name: 'discard'
    window.close()
    window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def settle():
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


def test_default_is_wall_classic_is_explicit():
    assert gui.parse_arguments([]).layout == 'wall'
    assert gui.parse_arguments(['--layout', 'classic']).layout == 'classic'
    assert gui.parse_arguments(['--layout', 'wall']).layout == 'wall'
    with pytest.raises(SystemExit):
        gui.parse_arguments(['--layout', 'removed-layout'])


def test_block_cells_toggle_group_with_undo_and_keyboard(wall):
    analysis = wall.analysis
    before = analysis.effective.copy()
    wall.request_toggle('206/204 D', [22])
    manual = analysis.effective.copy()
    cell = wall.block_header.cells[2]
    QtTest.QTest.mouseClick(cell, QtCore.Qt.MouseButton.LeftButton)
    rows = analysis.run.block == 2
    assert not analysis.effective[rows].any()
    assert analysis.group_consistent()
    assert '0/16' in cell.text() and not cell.isChecked()
    assert '17, 18' in cell.toolTip()
    wall.undo()
    np.testing.assert_array_equal(analysis.effective, manual)
    wall.redo()
    QtTest.QTest.keyClick(cell, QtCore.Qt.Key.Key_Space)
    np.testing.assert_array_equal(analysis.effective, manual)
    cell.setFocus()
    QtTest.QTest.keyClick(cell, QtCore.Qt.Key.Key_Right)
    assert wall.block_header.cells[3].hasFocus()
    QtTest.QTest.keyClick(wall.block_header.cells[3], QtCore.Qt.Key.Key_Return)
    assert not analysis.effective[analysis.run.block == 3].any()
    while analysis.can_undo:
        wall.undo()
    np.testing.assert_array_equal(analysis.effective, before)


def test_inspector_preserves_width_and_persists_per_viewer(wall):
    shell = wall.review_shell
    shell.splitter.setSizes([900, 350])
    settle()
    expanded = shell.splitter.sizes()
    shell.inspector.set_collapsed(True, animate=False)
    settle()
    assert shell.inspector.width() == 30
    shell.inspector.set_collapsed(False, animate=False)
    settle()
    assert shell.splitter.sizes() == expanded
    shell.inspector.set_collapsed(True, animate=False)
    shell.splitter.save()
    assert wall.settings.contains('review/wall/splitter_v2')
    second = gui.MainWindow(restore_geometry=False)
    second.resize(1280, 800)
    second.show()
    settle()
    try:
        assert second.review_shell.inspector.collapsed
        assert second.review_shell.inspector.width() == 30
        second.review_shell.inspector_action.trigger()
        settle()
        assert abs(second.review_shell.inspector.width() - expanded[1]) <= 1
        assert not second.review_shell.inspector.animation.state() == QtCore.QAbstractAnimation.State.Running
    finally:
        second.close()
        second.deleteLater()


def test_splitter_restore_reset_and_tab_stability(wall):
    shell = wall.review_shell
    shell.splitter.setSizes([900, 350])
    shell.splitter.save()
    expected = shell.splitter.sizes()
    second = gui.MainWindow(restore_geometry=False)
    second.resize(1280, 800)
    second.show()
    settle()
    try:
        assert second.review_shell.splitter.sizes() == expected
    finally:
        second.close()
        second.deleteLater()
    for index in range(4):
        wall.inspector_tabs.setCurrentIndex(index)
        settle()
        assert shell.splitter.sizes() == expected
        assert shell.inspector.animation.state() == QtCore.QAbstractAnimation.State.Stopped
    QtTest.QTest.mouseDClick(shell.splitter.handle(1), QtCore.Qt.MouseButton.LeftButton)
    settle()
    assert abs(shell.inspector.width() - 300) <= 1
    shell.inspector.set_collapsed(True, animate=False)
    wall.reset_layout_action.trigger()
    settle()
    assert not shell.inspector.collapsed
    assert abs(shell.inspector.width() - 300) <= 1


def test_maximise_header_shortcut_and_esc_restore_one_level(wall):
    shell, plot_wall = wall.review_shell, wall.plot_wall
    card = plot_wall.cards[0]
    original = shell.splitter.sizes()
    # Outer header -> inner card -> Esc -> outer -> Esc -> original.
    wall.wall_header.setFocus()
    QtTest.QTest.keyClick(wall, QtCore.Qt.Key.Key_Return, QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.ShiftModifier)
    assert shell.outer_maximised and not shell.inspector.isVisible()
    card.header.setFocus()
    shell.max_action.trigger()
    settle()
    assert plot_wall.maximised is card
    assert sum(c.isVisible() for c in plot_wall.cards) == 1
    assert card.width() > wall.width() - 100
    assert card.plot.height() >= card.height() - 30
    QtTest.QTest.keyClick(wall, QtCore.Qt.Key.Key_Escape)
    assert plot_wall.maximised is None and shell.outer_maximised
    QtTest.QTest.keyClick(wall, QtCore.Qt.Key.Key_Escape)
    settle()
    assert not shell.outer_maximised and shell.inspector.isVisible()
    assert shell.splitter.sizes() == original
    card.max_button.click()
    assert shell.outer_maximised and plot_wall.maximised is card
    QtTest.QTest.keyClick(wall, QtCore.Qt.Key.Key_Escape)
    assert not shell.outer_maximised
    QtTest.QTest.mouseDClick(card.header, QtCore.Qt.MouseButton.LeftButton)
    assert plot_wall.maximised is card
    QtTest.QTest.mouseDClick(card.header, QtCore.Qt.MouseButton.LeftButton)
    assert plot_wall.maximised is None
    wall.request_select('206/204 D', [1, 2], False)
    QtTest.QTest.keyClick(wall, QtCore.Qt.Key.Key_Escape)
    assert not wall.selection  # Esc retains its normal role outside maximise.


@pytest.mark.parametrize('width,height,columns', [(1024, 640, 1), (1280, 800, 2), (1440, 900, 3)])
def test_columns_sizes_and_readable_card_area(wall, width, height, columns):
    wall.resize(width, height)
    settle()
    assert wall.size() == QtCore.QSize(width, height)
    assert wall.plot_wall.column_count() == columns
    assert wall.review_shell.inspector.width() <= width * .30
    for card in wall.plot_wall.cards:
        assert card.plot.view_box.height() >= 128
        assert card.panel_size.minimum.height() <= card.height() <= card.panel_size.maximum.height()
    wall.review_shell.inspector.set_collapsed(True, animate=False)
    settle()
    if width == 1280:
        assert wall.plot_wall.verticalScrollBar().maximum() == 0
        assert all(card.isVisible() for card in wall.plot_wall.cards)
    assert not wall.stats_panel.table.isVisible()
    assert wall.stats_panel.block_table.isVisible() is False  # collapsed inspector


@pytest.mark.parametrize('width,height', [(1024, 640), (1280, 800), (1440, 900)])
def test_synthetic_worstcase_no_horizontal_overflow(wall, width, height):
    run = install_synthetic_review(wall)
    assert (run.n_functions, run.n_cycles, run.blocks_measured) == (12, 400, 20)
    assert all(len(f.fraction_id) == 60 for f in wall.workspace.fractions)
    wall.resize(width, height)
    import os
    from pathlib import Path
    shots = os.environ.get('RAWTIMS_UI_ROUND_SHOTS')
    if shots and width == 1280:
        settle()
        assert wall.grab().save(str(Path(shots) / 'after_worstcase_1280_light.png'), 'PNG')
    for collapsed in (False, True):
        wall.review_shell.inspector.set_collapsed(collapsed, animate=False)
        for tab in range(4):
            wall.inspector_tabs.setCurrentIndex(tab)
            settle()
            assert wall.size() == QtCore.QSize(width, height)
            for area in wall.findChildren(QtWidgets.QAbstractScrollArea):
                if not area.isVisibleTo(wall):
                    continue
                assert not area.horizontalScrollBar().isVisible(), area.objectName()
                if isinstance(area, QtWidgets.QScrollArea):
                    assert area.widget().width() <= area.viewport().width(), area.objectName()
        assert min(c.width() for c in wall.block_header.cells.values()) >= 28
    wall.review_shell.picker.setCurrentIndex(39)
    wall.review_shell.select_run(39)
    assert wall.current[0] is wall.workspace.fractions[39]


@pytest.mark.parametrize('variable', ['UPBRPY_REDUCE_MOTION', 'UPBLAB_REDUCE_MOTION', 'qt'])
def test_reduced_motion_and_instant_keyboard_paths(wall, monkeypatch, variable):
    if variable == 'qt':
        hints = QtWidgets.QApplication.styleHints()
        class Preference:
            name = 'ReducedMotion'
        class Accessibility:
            def motionPreference(self):
                return Preference()
        monkeypatch.setattr(hints, 'accessibility', lambda: Accessibility())
    else:
        monkeypatch.setenv(variable, '1')
    inspector = wall.review_shell.inspector
    assert reduced_motion(inspector)
    inspector.set_collapsed(True, animate=True)
    settle()
    assert inspector.width() == 30
    assert inspector.animation.state() == QtCore.QAbstractAnimation.State.Stopped
    wall.review_shell.inspector_action.trigger()
    assert not inspector.collapsed
    wall.mode_buttons['intensities'].click()
    assert wall.mode_bar._motion.state() == QtCore.QAbstractAnimation.State.Stopped


def test_mouse_panel_motion_is_short_ease_out_keyboard_is_instant(wall, monkeypatch):
    from rawtims_gui import review_layouts
    monkeypatch.setattr(review_layouts, 'reduced_motion', lambda _widget: False)
    panel = wall.review_shell.inspector
    QtTest.QTest.mouseClick(panel.button, QtCore.Qt.MouseButton.LeftButton)
    assert panel.animation.state() == QtCore.QAbstractAnimation.State.Running
    assert 0 < panel.animation.duration() < 300
    assert panel.animation.easingCurve().type() == QtCore.QEasingCurve.Type.OutCubic
    QtTest.QTest.qWait(210)
    assert panel.width() == 30
    wall.review_shell.inspector_action.trigger()
    settle()
    assert not panel.collapsed and panel.animation.state() == QtCore.QAbstractAnimation.State.Stopped


def test_maximise_uses_hover_when_focus_is_in_inspector(wall, monkeypatch):
    card = wall.plot_wall.cards[1]
    wall.stats_panel.block_function.setFocus()
    monkeypatch.setattr(QtWidgets.QApplication, 'widgetAt', lambda _point: card.header)
    wall.review_shell.max_action.trigger()
    assert wall.plot_wall.maximised is card
    assert not wall.review_shell.inspector.isVisible()
    wall.review_shell.restore()
    assert wall.review_shell.inspector.isVisible()
