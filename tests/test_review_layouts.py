"""The default wall obeys the shared panel contract and uses group-wide undo."""
import numpy as np
import pytest
from PySide6 import QtCore, QtTest, QtWidgets
from reader_fixtures import B998, SYNTHETIC_PB
from synthetic_review import install_synthetic_review

from rawtims_gui import main as gui
from rawtims_gui.review_layouts import reduced_motion
from rawtims_gui.studio.theme import build_application


@pytest.fixture
def wall(qt_settings_folder, monkeypatch, tmp_path):
    build_application(['layout-test'], theme_mode='light')
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


@pytest.mark.parametrize('plot_layout', ['stacked', 'auto-fit'])
def test_block_cells_toggle_group_with_undo_and_keyboard(wall, plot_layout):
    wall.plot_wall.set_plot_layout(plot_layout)
    settle()
    analysis = wall.analysis
    before = analysis.effective.copy()
    wall.request_toggle('206/204 D', [22])
    manual = analysis.effective.copy()
    cell = wall.block_header.cells[2]
    QtTest.QTest.mouseClick(cell, QtCore.Qt.MouseButton.LeftButton)
    rows = analysis.run.block == 2
    assert not analysis.effective[rows].any()
    assert analysis.group_consistent()
    assert '0/16' in cell.toolTip() and not cell.isChecked()
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
        assert second.review_shell.inspector.animation.state() != QtCore.QAbstractAnimation.State.Running
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
    assert card.plot.height() >= card.height() - 64
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


@pytest.mark.parametrize('width,height,columns', [(1024, 640, 1), (1280, 800, 2), (1440, 900, 2), (1512, 982, 2), (2560, 1440, 4)])
def test_columns_sizes_and_readable_card_area(wall, width, height, columns):
    wall.plot_wall.set_plot_layout('auto-fit')
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
        assert wall.plot_wall.verticalScrollBar().maximum() > 0
        assert all(card.isVisible() for card in wall.plot_wall.cards)
    assert not wall.stats_panel.table.isVisible()
    assert wall.stats_panel.block_table.isVisible() is False  # collapsed inspector


@pytest.mark.parametrize('width,height', [(1024, 640), (1280, 800), (1440, 900), (1512, 982)])
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
        assert wall.block_header.height() == 18
        assert all(c.width() > 0 and c.geometry().right() < wall.block_header.width()
                   for c in wall.block_header.cells.values())
        assert all('cycles used' in c.accessibleName() for c in wall.block_header.cells.values())
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


@pytest.mark.parametrize('count', [6, 7])
@pytest.mark.parametrize('width,height', [(1280, 800), (1024, 640)])
@pytest.mark.parametrize('plot_layout', ['stacked', 'auto-fit'])
def test_collapsed_ratios_scroll_and_cycle_axes_align(wall, count, width, height, plot_layout):
    wall.plot_wall.set_plot_layout(plot_layout)
    if count == 7:
        wall.open_paths([str(SYNTHETIC_PB)], synchronous=True)
        wall.select_run(wall.workspace.fractions[-1], 'Pb')
        wall.plot_contract_ratios()
        assert '202/205 D' in wall.plotted_keys()
    assert len(wall.plotted_keys()) == count
    wall.resize(width, height)
    wall.review_shell.inspector.set_collapsed(True, animate=False)
    settle()
    view = wall.plot_wall
    viewport = QtCore.QRect(QtCore.QPoint(0, 0), view.viewport().size())
    complete = [c for c in view.cards if viewport.contains(
        QtCore.QRect(c.mapTo(view.viewport(), QtCore.QPoint()), c.size()))]
    assert len(complete) >= (2 if plot_layout == 'stacked' else 1)
    assert view.verticalScrollBar().maximum() > 0
    assert view.column_count() == (1 if plot_layout == 'stacked' else 2)
    ranges = [p.view_box.viewRange()[0] for p in view.plots]
    np.testing.assert_allclose(ranges, np.tile(ranges[0], (count, 1)))
    for col in range(view.column_count()):
        plots = view.plots[col::view.column_count()]
        lefts = [p.view_box.mapViewToScene(QtCore.QPointF(23, 0)).x() for p in plots]
        assert max(lefts) - min(lefts) < .01
    # X zooms remain shared as well, including across different ratio scales.
    view.plots[0].getPlotItem().setXRange(10, 50, padding=0)
    settle()
    assert all(np.allclose(p.view_box.viewRange()[0], [10, 50]) for p in view.plots)


def test_focus_folds_inside_window_and_restores_each_panel_and_width(wall):
    shell = wall.review_shell
    shell.toggle_rail()
    shell.splitter.setSizes([850, 330])
    settle()
    before = shell.splitter.sizes()
    QtTest.QTest.keyClick(wall, QtCore.Qt.Key.Key_F,
                         QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.ShiftModifier)
    settle()
    assert shell.focused and shell.focus_action.isChecked()
    assert shell.rail.isHidden() and shell.rail_strip.isVisibleTo(wall)
    assert shell.inspector.collapsed and shell.inspector.width() == 30
    assert shell.splitter.transient
    assert shell.focus_action.shortcut() == QtCore.QKeyCombination(
        QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.ShiftModifier,
        QtCore.Qt.Key.Key_F)
    shell.rail_strip.click()
    settle()
    assert shell.rail.isVisibleTo(wall) and shell.inspector.collapsed
    shell.inspector.button.click()
    QtTest.QTest.qWait(200)
    settle()
    assert not shell.inspector.collapsed and shell.rail.isVisibleTo(wall)
    shell.set_focus(False)
    settle()
    assert shell.splitter.sizes() == before
    assert not shell.inspector.collapsed and shell.rail.isVisibleTo(wall)
    assert not shell.splitter.transient
    assert not wall.settings.value('review/wall/focus_v1', True, type=bool)


def test_focus_preserves_collapsed_preference_and_survives_new_viewer(wall):
    shell = wall.review_shell
    shell.inspector.set_collapsed(True, animate=False)
    before = shell.splitter.sizes()
    shell.set_focus(True)
    shell.show_inspector_tab(1)
    settle()
    assert not shell.inspector.collapsed
    assert wall.settings.value(shell.inspector.key, False, type=bool)
    shell.splitter.save()
    second = gui.MainWindow(restore_geometry=False)
    second.resize(1280, 800)
    second.show()
    settle()
    try:
        assert second.review_shell.focused
        second.review_shell.set_focus(False)
        settle()
        assert second.review_shell.inspector.collapsed
    finally:
        second.close()
        second.deleteLater()
    shell.set_focus(False)
    settle()
    assert shell.inspector.collapsed and shell.splitter.sizes() == before


@pytest.mark.parametrize('plot_layout', ['stacked', 'auto-fit'])
def test_block_strip_range_drag_shift_and_axis_zoom(wall, monkeypatch, plot_layout):
    wall.plot_wall.set_plot_layout(plot_layout)
    settle()
    strip = wall.block_header
    a = wall.analysis
    last = strip.cells[4]
    history = a.history_count
    # Mouse moves only preview; the shared masks and plots are untouched.
    updates = []
    original = wall.plot_wall.refresh
    monkeypatch.setattr(wall.plot_wall, 'refresh', lambda *a, **k: (updates.append(1), original(*a, **k))[-1])
    first = strip.cells[2]
    end = first.mapFrom(strip, last.geometry().center())
    QtTest.QTest.mousePress(first, QtCore.Qt.MouseButton.LeftButton)
    QtTest.QTest.mouseMove(first, end)
    assert a.history_count == history and not updates
    QtTest.QTest.mouseRelease(first, QtCore.Qt.MouseButton.LeftButton, pos=end)
    assert a.history_count == history + 3 and len(updates) == 1
    assert not a.effective[np.isin(a.run.block, [2, 3, 4])].any()
    for card in wall.plot_wall.cards:
        assert all(not card.blocks.cells[b].isChecked() for b in (2, 3, 4))
    # Shift-click extends the strip's last anchor, and includes that range.
    QtTest.QTest.mouseClick(strip.cells[5], QtCore.Qt.MouseButton.LeftButton,
                           QtCore.Qt.KeyboardModifier.ShiftModifier)
    assert a.effective[np.isin(a.run.block, [2, 3, 4, 5])].all()
    plot = wall.plot_wall.plots[0]
    plot.getPlotItem().setXRange(17, 64, padding=0)
    settle()
    vb = plot.view_box
    for b in (2, 3):
        cycles = a.run.cycle[a.run.block == b]
        scene_x = vb.mapViewToScene(QtCore.QPointF(float(cycles.min())-.5, 0)).x()
        offset = strip.mapFromGlobal(plot.viewport().mapToGlobal(QtCore.QPoint())).x()
        assert abs(strip.cells[b].x() - (offset + max(vb.sceneBoundingRect().left(), scene_x))) <= 1
    assert strip.cells[1].isHidden()


def test_content_popovers_and_overflow_keep_controls_and_actions(wall):
    shell = wall.review_shell
    install_synthetic_review(wall)
    wall.resize(1024, 640)
    settle()
    shell.toolbar.reflow()
    folded = [(w, menu) for w, menu, _, _ in shell.toolbar.entries if menu.menuAction().isVisible()]
    assert folded
    assert shell.toolbar.overflow.isVisibleTo(wall)
    assert all(not w.isVisibleTo(wall) for w, _ in folded)
    assert wall.reset_analysis_action in shell.more_menu.actions()
    # Open nonblocking, inspect real menu content, retain picker checks.
    wall.function_menu.popup(wall.function_button.mapToGlobal(QtCore.QPoint(0, 26)))
    settle()
    assert wall.function_list.isVisible()
    assert wall.function_list.height() <= wall.height() * .5
    assert wall.function_menu.height() < wall.height()
    checked = wall.function_list.item(0).checkState()
    wall.function_list.item(0).setCheckState(QtCore.Qt.CheckState.Unchecked if checked == QtCore.Qt.CheckState.Checked
                                           else QtCore.Qt.CheckState.Checked)
    assert wall.function_menu.isVisible()  # Multiple checks need no repeated opening.
    wall.function_menu.hide()
    shell.options_menu.popup(shell.options_button.mapToGlobal(QtCore.QPoint(0, 26)))
    settle()
    assert shell.options_menu.isVisible()
    assert wall.log_action in shell.options_menu.actions()
    assert wall.fit_all_action in shell.options_menu.actions()
    shell.options_menu.hide()
    wall.resize(1512, 982)
    settle()
    shell.toolbar.reflow()
    assert not any(menu.menuAction().isVisible() for _, menu, _, _ in shell.toolbar.entries)
    assert shell.picker.isVisibleTo(wall) and wall.function_button.isVisibleTo(wall)


@pytest.mark.parametrize('plot_layout', ['stacked', 'auto-fit'])
def test_local_log_yfit_mswd_and_reset_preserve_shared_cycles(wall, plot_layout):
    wall.plot_wall.set_plot_layout(plot_layout)
    settle()
    card, other = wall.plot_wall.cards[:2]
    plot = card.plot
    before = wall.analysis.effective.copy()
    plot.getPlotItem().setXRange(10, 50, padding=0)
    plot.getPlotItem().setYRange(1, 2, padding=0)
    card.fit_button.click()
    assert np.allclose(plot.view_box.viewRange()[0], [10, 50])
    assert plot.view_box.viewRange()[1][1] > 100
    card.log_button.click()
    assert plot._log and not other.plot._log
    assert 'ln(' in card.name.text()
    assert 'MSWD' in card.summary.text()
    assert 'MSWD of block means' in card.summary.toolTip()
    point = plot.view_box.mapViewToScene(QtCore.QPointF(30, plot.view_box.viewRange()[1][0]))
    QtTest.QTest.mouseDClick(plot.viewport(), QtCore.Qt.MouseButton.LeftButton,
                           pos=plot.mapFromScene(point))
    settle()
    assert plot.view_box.viewRange()[0][1] > 50
    np.testing.assert_array_equal(wall.analysis.effective, before)


@pytest.mark.parametrize('width,height', [(1512, 982), (1440, 900), (1280, 800), (1024, 640)])
def test_toolbar_and_panels_fit_all_sizes_and_focus(wall, width, height):
    wall.resize(width, height)
    settle()
    shell = wall.review_shell
    for focus in (False, True):
        shell.set_focus(focus)
        settle()
        assert wall.size() == QtCore.QSize(width, height)
        bounds = wall.rect()
        for widget in (shell.toolbar, shell.centre, shell.inspector):
            assert bounds.contains(QtCore.QRect(widget.mapTo(wall, QtCore.QPoint()), widget.size()))
        for widget, menu, _, _ in shell.toolbar.entries:
            if menu.menuAction().isVisible():
                continue
            assert shell.toolbar.rect().contains(QtCore.QRect(widget.mapTo(shell.toolbar, QtCore.QPoint()), widget.size()))
        assert wall.plot_wall.verticalScrollBar().maximum() > 0
        for card in wall.plot_wall.cards:
            assert card.plot.view_box.height() >= 128
            assert card.blocks.height() == 18
        if focus:
            assert wall.plot_wall.viewport().width() > width * .88


def test_maximise_restores_open_rail_and_focus_strips(wall):
    shell = wall.review_shell
    shell.toggle_rail()
    settle()
    original = shell.splitter.sizes()
    shell.toggle_outer()
    settle()
    assert shell.rail.isHidden() and shell.inspector.isHidden()
    assert wall.plot_wall.viewport().width() > wall.width() - 60
    shell.restore()
    settle()
    assert shell.rail.isVisibleTo(wall) and shell.splitter.sizes() == original
    shell.set_focus(True)
    shell.toggle_outer()
    settle()
    assert shell.rail_strip.isHidden() and shell.inspector.isHidden()
    shell.restore()
    settle()
    assert shell.rail_strip.isVisibleTo(wall) and shell.inspector.collapsed
    assert shell.splitter.transient
    shell.set_focus(False)
    settle()
    assert shell.rail.isVisibleTo(wall) and shell.splitter.sizes() == original
