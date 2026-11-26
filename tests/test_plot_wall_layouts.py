"""Synthetic-only regression coverage for in-place review plot layouts."""
import numpy as np
import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from reader_fixtures import SYNTHETIC_PB
from synthetic_review import install_synthetic_review
from rawtims_gui import main as gui
from rawtims_gui.review_layouts import SharedBlocks
from rawtims_gui.studio.theme import build_application


def settle():
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


@pytest.fixture
def viewer(qt_settings_folder, monkeypatch, tmp_path):
    build_application(['plot-layout-test'], theme_mode='light')
    settings = QtCore.QSettings(str(tmp_path / 'view.ini'), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(gui, 'app_settings', lambda: settings)
    window = gui.MainWindow(restore_geometry=False)
    window.resize(1440, 900)
    window.show()
    window.open_paths([str(SYNTHETIC_PB)], synchronous=True)
    settle()
    yield window
    window.unsaved_prompt = lambda _: 'discard'
    window.close()
    window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_switch_preserves_live_plots_masks_selection_history_and_views(viewer, monkeypatch):
    w = viewer
    wall = w.plot_wall
    key = wall.plots[0].key
    w.request_toggle(key, [10])
    w.request_toggle(key, [11])
    w.undo()  # Preserve an available redo as well as undo.
    w.request_select(key, [15, 17], False)
    w.review_shell.set_focus(True)
    wall.plots[0].getPlotItem().setXRange(10, 50, padding=0)
    for i, plot in enumerate(wall.plots):
        plot.getPlotItem().setYRange(i + 1, i + 2, padding=0)
    wall.cards[0].header.setFocus()
    settle()
    plots, cards, state = list(wall.plots), list(wall.cards), wall.state
    masks = w.analysis.effective.copy()
    history = (w.analysis.history_count, w.analysis.can_undo, w.analysis.can_redo)
    yranges = [p.view_box.viewRange()[1] for p in plots]
    focus = QtWidgets.QApplication.focusWidget()
    def forbidden(*_args, **_kwargs):
        pytest.fail('Layout switching must not rebuild or refresh data')
    monkeypatch.setattr(w, '_rebuild_view', forbidden)
    for plot in plots:
        monkeypatch.setattr(plot, 'update_state', forbidden)
    for mode in ('auto-fit', 'stacked', 'auto-fit', 'stacked'):
        wall.set_plot_layout(mode)
        settle()
        assert wall.plots == plots and wall.cards == cards and wall.state is state
        assert w.selection == {15, 17}
        assert all(p.selected_rows == {15, 17} for p in plots)
        np.testing.assert_array_equal(w.analysis.effective, masks)
        assert (w.analysis.history_count, w.analysis.can_undo, w.analysis.can_redo) == history
        np.testing.assert_allclose([p.view_box.viewRange()[1] for p in plots], yranges)
        np.testing.assert_allclose([p.view_box.viewRange()[0] for p in plots], np.tile([10, 50], (len(plots), 1)))
        assert w.review_shell.focused and QtWidgets.QApplication.focusWidget() is focus


def test_stacked_axis_shared_strip_and_linked_pan_from_every_plot(viewer):
    wall = viewer.plot_wall
    assert wall.plot_layout == 'stacked' and wall.column_count() == 1
    assert wall.shared_blocks is viewer.block_header
    assert [s for s in wall.findChildren(SharedBlocks) if s.isVisibleTo(wall)] == [wall.shared_blocks]
    assert wall.shared_blocks.isVisibleTo(viewer)
    for index, plot in enumerate(wall.plots):
        axis = plot.getPlotItem().getAxis('bottom')
        assert axis.isVisible() == (index == len(wall.plots) - 1)
        assert plot.height() >= 150
        plot.getPlotItem().setXRange(10 + index, 50 + index, padding=0)
        settle()
        assert all(np.allclose(p.view_box.viewRange()[0], [10 + index, 50 + index]) for p in wall.plots)
    assert wall.verticalScrollBar().maximum() > 0
    # The single strip remains available while scrolling and uses the bottom plot's transform.
    wall.verticalScrollBar().setValue(wall.verticalScrollBar().maximum())
    settle()
    strip = wall.shared_blocks
    plot = strip.plot
    block = next(b for b, cell in strip.cells.items() if cell.isVisible())
    cycles = viewer.analysis.run.cycle[viewer.analysis.run.block == block]
    offset = strip.mapFromGlobal(plot.viewport().mapToGlobal(QtCore.QPoint())).x()
    vb = plot.view_box
    x = vb.mapViewToScene(QtCore.QPointF(float(cycles.min()) - .5, 0)).x()
    assert abs(strip.cells[block].x() - offset - max(x, vb.sceneBoundingRect().left())) <= 1
    before = viewer.analysis.effective.copy()
    QtTest.QTest.mouseClick(strip.cells[block], QtCore.Qt.MouseButton.LeftButton)
    assert not viewer.analysis.effective[viewer.analysis.run.block == block].any()
    viewer.undo()
    np.testing.assert_array_equal(viewer.analysis.effective, before)


@pytest.mark.parametrize('width,height,columns', [(1440, 900, 2), (2560, 1440, 4)])
def test_auto_fit_width_and_stress_resize(viewer, width, height, columns):
    install_synthetic_review(viewer)
    wall = viewer.plot_wall
    viewer.resize(width, height)
    viewer.review_shell.layout_buttons['auto-fit'].click()
    settle()
    assert wall.column_count() == columns
    assert not viewer.review_shell.inspector.collapsed
    assert wall.shared_blocks.isHidden()
    assert len(wall.cards) == 12
    assert all(card.width() >= 420 and card.height() >= 260 for card in wall.cards)
    assert all(card.blocks.isVisibleTo(wall) for card in wall.cards)
    assert all(p.getPlotItem().getAxis('bottom').isVisible() for p in wall.plots)
    assert not wall.horizontalScrollBar().isVisible()
    if width == 1440:
        assert wall.verticalScrollBar().maximum() > 0
    viewer.resize(1280, 800)
    settle()
    assert wall.column_count() == 2
    viewer.resize(1440, 900)
    viewer.review_shell.layout_buttons['stacked'].click()
    settle()
    assert wall.column_count() == 1 and wall.shared_blocks.isVisibleTo(viewer)


def test_layout_preferences_accessibility_and_exclusive_view_actions(viewer):
    shell, wall = viewer.review_shell, viewer.plot_wall
    assert wall.plot_layout == 'stacked'
    assert shell.layout_bar.accessibleName() == 'Plot layout'
    for mode, button in shell.layout_buttons.items():
        assert button.accessibleName() == f'{button.text()} plot layout'
        assert button.toolTip()
        assert shell.layout_actions[mode].isCheckable()
    shell.layout_actions['auto-fit'].trigger()
    assert shell.layout_buttons['auto-fit'].isChecked()
    assert not shell.layout_actions['stacked'].isChecked()
    second = gui.MainWindow(restore_geometry=False)
    try:
        assert second.plot_wall.plot_layout == 'auto-fit'
        assert second.review_shell.layout_actions['auto-fit'].isChecked()
        second.review_shell.layout_buttons['stacked'].click()
        assert second.settings.value(wall.layout_key) == 'stacked'
    finally:
        second.close()
        second.deleteLater()


@pytest.mark.parametrize('mode', ['stacked', 'auto-fit'])
def test_intensities_theme_hover_and_card_maximise(viewer, mode):
    wall = viewer.plot_wall
    wall.set_plot_layout(mode)
    viewer.set_plot_mode('intensities')
    settle()
    assert wall.plot_layout == mode
    before = viewer.analysis.effective.copy()
    for theme in ('dark', 'light'):
        viewer.set_theme(theme)
        settle()
        wall.plots[0].cycleHovered.emit(20)
        assert all(p.hover_guide.isVisible() and p.hover_guide.value() == 20 for p in wall.plots)
        card = wall.cards[0]
        card.max_button.click()
        settle()
        assert wall.maximised is card
        assert card.plot.getPlotItem().getAxis('bottom').isVisible()
        card.max_button.click()
        settle()
        assert wall.maximised is None
    np.testing.assert_array_equal(viewer.analysis.effective, before)


@pytest.mark.parametrize('mode', ['stacked', 'auto-fit'])
def test_synthetic_cycle_mouse_and_block_keyboard_drag_shift(viewer, mode):
    wall = viewer.plot_wall
    wall.set_plot_layout(mode)
    settle()
    plot = wall.plots[0]
    before = viewer.analysis.effective.copy()
    point = plot.mapFromScene(plot.view_box.mapViewToScene(plot.point_of(50)))
    QtTest.QTest.mouseClick(plot.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           QtCore.Qt.KeyboardModifier.ControlModifier, pos=point)
    assert 50 in viewer.selection
    np.testing.assert_array_equal(viewer.analysis.effective, before)
    settle()
    point = plot.mapFromScene(plot.view_box.mapViewToScene(plot.point_of(70)))
    QtTest.QTest.mouseClick(plot.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=point)
    assert not viewer.analysis.included_for(plot.key)[70]
    viewer.undo()
    np.testing.assert_array_equal(viewer.analysis.effective, before)
    strip = viewer.block_header
    first, last = strip.cells[2], strip.cells[4]
    end = first.mapFrom(strip, last.geometry().center())
    QtTest.QTest.mousePress(first, QtCore.Qt.MouseButton.LeftButton)
    QtTest.QTest.mouseMove(first, end)
    np.testing.assert_array_equal(viewer.analysis.effective, before)
    QtTest.QTest.mouseRelease(first, QtCore.Qt.MouseButton.LeftButton, pos=end)
    assert not viewer.analysis.effective[np.isin(viewer.analysis.run.block, [2, 3, 4])].any()
    QtTest.QTest.mouseClick(strip.cells[5], QtCore.Qt.MouseButton.LeftButton,
                           QtCore.Qt.KeyboardModifier.ShiftModifier)
    assert viewer.analysis.effective[np.isin(viewer.analysis.run.block, [2, 3, 4, 5])].all()
    strip.cells[2].setFocus()
    QtTest.QTest.keyClick(strip.cells[2], QtCore.Qt.Key.Key_Right)
    assert strip.cells[3].hasFocus()
    QtTest.QTest.keyClick(strip.cells[3], QtCore.Qt.Key.Key_Space)
    assert not viewer.analysis.effective[viewer.analysis.run.block == 3].any()
    assert viewer.analysis.group_consistent()
