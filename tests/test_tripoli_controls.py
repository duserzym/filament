"""Visible Tripoli controls reuse the established review actions; synthetic data only."""
import numpy as np
import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from reader_fixtures import SYNTHETIC_PB
from rawtims_gui import main as gui
from rawtims_gui.studio.theme import build_application


def settle():
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


@pytest.fixture
def viewer(qt_settings_folder, monkeypatch, tmp_path):
    build_application(['tripoli-controls-test'], theme_mode='light')
    settings = QtCore.QSettings(str(tmp_path / 'controls.ini'), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(gui, 'app_settings', lambda: settings)
    window = gui.MainWindow(restore_geometry=False)
    window.unsaved_prompt = lambda _: 'discard'
    window.resize(1280, 800)
    window.show()
    window.open_paths([str(SYNTHETIC_PB)], synchronous=True)
    settle()
    yield window
    window.close()
    window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('layout', ['stacked', 'auto-fit'])
@pytest.mark.parametrize('size', [(1280, 800), (1440, 900)])
def test_controls_visible_accessible_and_fit(viewer, theme, layout, size):
    w = viewer
    w.set_theme(theme)
    w.plot_wall.set_plot_layout(layout)
    w.resize(*size)
    settle()
    shell = w.review_shell
    assert w.size() == QtCore.QSize(*size)
    bar = shell.wall_actions
    assert w.rect().contains(QtCore.QRect(bar.mapTo(w, QtCore.QPoint()), bar.size()))
    rectangles = []
    for button in (shell.layout_bar, *shell.control_buttons.values()):
        assert button.isVisibleTo(w)
        assert button.accessibleName()
        if isinstance(button, QtWidgets.QToolButton):
            assert button.toolTip()
            assert button.focusPolicy() == QtCore.Qt.FocusPolicy.StrongFocus
        rect = QtCore.QRect(button.mapTo(bar, QtCore.QPoint()), button.size())
        assert bar.rect().contains(rect), (button.accessibleName(), rect, bar.rect())
        assert all(not rect.intersects(other) for other in rectangles)
        rectangles.append(rect)
    for card in w.plot_wall.cards:
        rectangles = []
        for button in card.header_buttons:
            assert button.accessibleName() and button.toolTip()
            if button.isHidden():
                continue
            rect = QtCore.QRect(button.mapTo(card.header, QtCore.QPoint()), button.size())
            assert card.header.rect().contains(rect)
            assert all(not rect.intersects(other) for other in rectangles)
            rectangles.append(rect)


def test_wall_buttons_share_actions_and_synch_lock(viewer, monkeypatch):
    w = viewer
    buttons = w.review_shell.control_buttons
    assert buttons['synch'].defaultAction() is w.synch_action
    assert not buttons['synch'].isEnabled() and buttons['synch'].isChecked()
    assert buttons['synch'].text() == 'SYNCH'
    assert 'Correlated ratios' in buttons['synch'].toolTip()
    assert buttons['plots'].menu() is w.function_menu
    w.review_shell.show_inspector_tab(1)
    buttons['stats'].click()
    assert w.inspector_tabs.currentIndex() == 0
    before = w.analysis.effective.copy()
    monkeypatch.setattr(QtWidgets.QMessageBox, 'question', lambda *_a, **_k: QtWidgets.QMessageBox.StandardButton.Cancel)
    for key, action in [('log', w.log_action), ('fit', w.fit_all_action),
                        ('reset', w.reset_analysis_action), *w.review_shell.navigation_actions.items()]:
        assert buttons[key].defaultAction() is action
        spy = QtTest.QSignalSpy(action.triggered)
        buttons[key].click()
        assert spy.count() == 1
    assert w.log_ratio and w.fit_all_points
    assert all(p.view_box.navigation_mode == 'zoom' for p in w.plot_wall.plots)
    # The floating path and Options path keep the visible buttons in sync.
    w.plot_wall.tools.buttons['pan'].click()
    assert buttons['pan'].isChecked()
    w.review_shell.navigation_actions['review'].trigger()
    assert buttons['review'].isChecked()
    assert all(c.sculpt_button.isChecked() for c in w.plot_wall.cards)
    # Free-function SYNCH uses the existing setting action and its undo history.
    free = next(k for k in w.analysis.keys if k not in w.analysis.group_keys)
    w._set_focus_key(free)
    assert buttons['synch'].isEnabled()
    original = w.analysis.settings.synced
    buttons['synch'].click()
    assert w.analysis.settings.synced != original
    w.undo_action.trigger()
    assert w.analysis.settings.synced == original
    np.testing.assert_array_equal(w.analysis.effective, before)


def test_chauvenet_preview_apply_and_reset_use_existing_paths(viewer, monkeypatch):
    w = viewer
    panel = w.rules_panel
    buttons = w.review_shell.control_buttons
    panel.set_rule('legacy_chauvenet')
    w.review_shell.inspector.set_collapsed(True, animate=False)
    before = w.analysis.effective.copy()
    buttons['chauvenet'].click()
    assert w.inspector_tabs.currentIndex() == 1 and not w.review_shell.inspector.collapsed
    assert panel.rule_combo.currentData() == 'chauvenet'
    card = w.plot_wall.cards[1]
    card.chauvenet_button.click()
    assert panel.function_combo.currentData() == 'one'
    assert panel.ratio_combo.currentData() == card.plot.key
    np.testing.assert_array_equal(w.analysis.effective, before)
    # The card opens precisely the existing one-ratio path; rejections stay shared.
    assert panel.scope_combo.currentData() == 'run'
    panel.function_combo.setCurrentIndex(panel.function_combo.findData('mapped'))
    assert not buttons['apply'].isEnabled()
    preview_spy = QtTest.QSignalSpy(panel.previewRequested)
    buttons['preview'].click()
    assert preview_spy.count() == 1
    proposal = w.current_proposal()
    assert proposal is not None and buttons['apply'].isEnabled()
    np.testing.assert_array_equal(w.analysis.effective, before)
    # Compare both entry points against precisely the same existing proposal.
    buttons['apply'].click()
    applied = w.analysis.effective.copy()
    w.undo()
    panel.preview_button.click()
    panel.apply_button.click()
    np.testing.assert_array_equal(w.analysis.effective, applied)
    assert not buttons['apply'].isEnabled()
    w.request_toggle(w.plot_wall.plots[0].key, [0])
    w.toggle_block(int(w.analysis.blocks[-1]))
    rejected = w.analysis.effective.copy()
    monkeypatch.setattr(QtWidgets.QMessageBox, 'question', lambda *_a, **_k: QtWidgets.QMessageBox.StandardButton.Reset)
    buttons['reset'].click()
    reset = w.analysis.effective.copy()
    w.undo()
    np.testing.assert_array_equal(w.analysis.effective, rejected)
    w.reset_analysis(confirm=False)
    np.testing.assert_array_equal(w.analysis.effective, reset)


@pytest.mark.parametrize('layout', ['stacked', 'auto-fit'])
def test_card_restore_sculpt_and_wall_restore_preserve_numbers(viewer, layout):
    w = viewer
    w.plot_wall.set_plot_layout(layout)
    card = w.plot_wall.cards[0]
    before = w.analysis.effective.copy()
    history = w.analysis.history_count
    card.sculpt_button.click()
    assert card.plot.view_box.navigation_mode == 'pan'
    card.tools.buttons['zoom'].click()
    assert not card.sculpt_button.isChecked()
    card.sculpt_button.click()
    assert card.plot.view_box.navigation_mode == 'review'
    card.plot.getPlotItem().setXRange(10, 20, padding=0)
    card.plot.getPlotItem().setYRange(1, 2, padding=0)
    card.restore_button.click()
    restored = np.array(card.plot.view_box.viewRange())
    assert restored[0, 1] > 20
    card.plot.getPlotItem().setXRange(10, 20, padding=0)
    card.plot.getPlotItem().setYRange(1, 2, padding=0)
    card.tools.resetRequested.emit()
    np.testing.assert_allclose(card.plot.view_box.viewRange(), restored)
    for plot in w.plot_wall.plots:
        plot.getPlotItem().setYRange(1, 2, padding=0)
    w.review_shell.control_buttons['restore'].click()
    wall_restored = [p.view_box.viewRange() for p in w.plot_wall.plots]
    for plot in w.plot_wall.plots:
        plot.getPlotItem().setYRange(1, 2, padding=0)
    w.plot_wall.tools.resetRequested.emit()
    np.testing.assert_allclose([p.view_box.viewRange() for p in w.plot_wall.plots], wall_restored)
    np.testing.assert_array_equal(w.analysis.effective, before)
    assert w.analysis.history_count == history
