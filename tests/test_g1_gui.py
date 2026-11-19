"""Offscreen desktop flows, staged workers and launch seams."""
from __future__ import annotations

from dataclasses import replace
from threading import Event
from time import monotonic

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from reader_fixtures import B998

from rawtims.parity import drive_path
from rawtims_gui import main as gui
from rawtims_gui.studio.theme import build_application


def settle():
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


def until(predicate, seconds=10):
    end = monotonic() + seconds
    while not predicate() and monotonic() < end:
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(2)
    assert predicate(), 'worker did not finish'


@pytest.fixture
def window(monkeypatch, tmp_path, qt_settings_folder):
    build_application(['g1-test'], theme_mode='light')
    settings = QtCore.QSettings(str(tmp_path / 'g1.ini'), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(gui, 'app_settings', lambda: settings)
    w = gui.MainWindow(restore_geometry=False)
    w.resize(1280,800)
    w.show()
    w.open_paths([str(B998)], synchronous=True)
    settle()
    yield w
    w.reduction_controller.cancel()
    until(lambda: not w._workers)
    w.unsaved_prompt = lambda _name: 'discard'
    w.close()
    w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('size', [(1512,982), (1440,900), (1280,800), (1024,640)])
def test_new_panels_fit_and_buttons_are_reachable(window, size):
    w = window
    w.resize(*size)
    for page_name in ('Reduction','Run info'):
        w.show_correction_page(page_name)
        settle()
        assert w.size() == QtCore.QSize(*size)
        for area in w.findChildren(QtWidgets.QScrollArea):
            if area.isVisibleTo(w) and area.widget():
                assert area.widget().width() <= area.viewport().width(), (page_name, area.objectName())
                assert not area.horizontalScrollBar().isVisible()
        for button in w.reduction_panel.findChildren(QtWidgets.QPushButton) if page_name == 'Reduction' else []:
            scroll = w.correction_pages.currentWidget()
            scroll.ensureWidgetVisible(button)
            settle()
            pos = button.mapTo(w, QtCore.QPoint())
            assert w.rect().contains(QtCore.QRect(pos, button.size()))
            assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 12
    w.set_workflow_step('Export')
    settle()
    for button in (w.export_panel.xlsx_button,w.export_panel.tables_button,w.export_panel.send_button):
        pos = button.mapTo(w, QtCore.QPoint())
        assert w.rect().contains(QtCore.QRect(pos, button.size()))
        assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 12


def test_wheel_never_edits_fields(window):
    w=window
    w.show_correction_page('Reduction')
    combo=w.reduction_panel.route
    before=combo.currentIndex()
    pos=combo.rect().center()
    event=QtGui.QWheelEvent(QtCore.QPointF(pos),QtCore.QPointF(combo.mapToGlobal(pos)),QtCore.QPoint(),QtCore.QPoint(0,-120),
                           QtCore.Qt.MouseButton.NoButton,QtCore.Qt.KeyboardModifier.NoModifier,QtCore.Qt.ScrollPhase.ScrollUpdate,False)
    QtWidgets.QApplication.sendEvent(combo,event)
    assert combo.currentIndex()==before
    assert not combo.model().item(1).isEnabled()
    assert 'no acquisition folder' in w.reduction_panel.raw_notice.text()


def test_worker_apply_cancel_stale_and_failure(window,monkeypatch):
    import rawtims_gui.reduction_panel as module
    w=window
    a=w.analysis
    initial=a.run
    entered,release=Event(),Event()
    def calculate(source,params):
        entered.set()
        assert release.wait(10)
        return replace(source,values=source.values.copy()*1.001,reduction_parameters=params)
    monkeypatch.setattr(module,'reprocess',calculate)
    w.reduction_panel.dead_time.setText('40')
    w.reduction_controller.apply()
    until(entered.is_set)
    assert w.reduction_panel.progress.isVisibleTo(w.reduction_panel)
    assert a.run is initial
    w.reduction_controller.cancel()
    release.set()
    until(lambda:not w._workers)
    assert a.run is initial
    entered.clear();release.clear()
    w.reduction_panel.dead_time.setText('40')
    w.reduction_controller.apply()
    until(entered.is_set)
    a.toggle_cycles([0])
    release.set()
    until(lambda:not w._workers)
    assert a.run is initial and 'discarded' in w.reduction_panel.status.text()

    def fails(*args):
        raise ValueError('synthetic reduction failure')
    monkeypatch.setattr(module,'reprocess',fails)
    w.reduction_controller.apply()
    until(lambda:not w._workers)
    assert a.run is initial and 'synthetic reduction failure' in w.reduction_panel.status.text()
    monkeypatch.setattr(module,'reprocess',lambda source,params:replace(source,values=source.values.copy()*1.001,reduction_parameters=params))
    w.reduction_controller.apply()
    until(lambda:not w._workers)
    assert a.run.reduction_parameters.daly_dead_time_ns==40
    assert 'ppm' in w.reduction_panel.diff.text()
    after=a.run
    # Cached undo/redo may not call the expensive reprocessor again.
    monkeypatch.setattr('rawtims.reprocess.reprocess',fails)
    w.undo()
    assert a.run is initial
    w.redo()
    assert a.run is after


def test_toolbar_drag_splitter_preview_and_navigation(window):
    w = window
    tools = w.plot_wall.tools
    tools.place()
    origin = tools.pos()
    grip = tools.grip
    local = grip.rect().center()
    start = grip.mapToGlobal(local)
    def mouse(kind, delta, buttons):
        event = QtGui.QMouseEvent(kind, QtCore.QPointF(local + delta), QtCore.QPointF(start + delta),
                                 QtCore.Qt.MouseButton.LeftButton if kind != QtCore.QEvent.Type.MouseMove else QtCore.Qt.MouseButton.NoButton,
                                 buttons, QtCore.Qt.KeyboardModifier.NoModifier)
        QtWidgets.QApplication.sendEvent(grip, event)
    mouse(QtCore.QEvent.Type.MouseButtonPress, QtCore.QPoint(), QtCore.Qt.MouseButton.LeftButton)
    mouse(QtCore.QEvent.Type.MouseMove, QtCore.QPoint(-50, 35), QtCore.Qt.MouseButton.LeftButton)
    assert tools.pos() == origin and tools.ghost.isVisible()
    target = tools.drag[2]
    mouse(QtCore.QEvent.Type.MouseButtonRelease, QtCore.QPoint(-50, 35), QtCore.Qt.MouseButton.NoButton)
    assert tools.pos() == target and not tools.ghost.isVisible()
    assert w.settings.value('plots/tools_position') == target
    assert QtWidgets.QApplication.overrideCursor() is None
    assert tools.parentWidget().rect().contains(tools.geometry())
    w.review_shell.splitter.dragStarted.emit()
    for plot in w.plot_wall.plots:
        if plot.isVisible():
            assert plot.resize_preview.overlay is not None
            assert not plot.updatesEnabled()
    w.review_shell.splitter.dragFinished.emit()
    assert all(p.resize_preview.overlay is None and p.updatesEnabled() for p in w.plot_wall.plots)
    plot = w.plot_wall.plots[0]
    history = w.analysis.history_count
    for mode in ('pan', 'zoom'):
        w.plot_wall.set_navigation_mode(mode)
        plot._on_click(QtCore.QPointF(float(plot.x_shown[0]), float(plot.y_shown[0])), QtCore.Qt.KeyboardModifier.NoModifier)
        assert w.analysis.history_count == history
    w.plot_wall.set_navigation_mode('review')


def test_box_motion_is_coalesced(window, monkeypatch):
    box = window.plot_wall.plots[0].view_box
    moves = []
    monkeypatch.setattr(box, 'updateScaleBox', lambda *points: moves.append(points))
    class Drag:
        def button(self): return QtCore.Qt.MouseButton.LeftButton
        def accept(self): pass
        def buttonDownPos(self, button): return QtCore.QPointF(1, 1)
        def pos(self): return QtCore.QPointF(50, 50)
        def isFinish(self): return False
    for _ in range(100):
        box.mouseDragEvent(Drag())
    assert not moves and box._drag_timer.isActive()
    box._drag_timer.stop()
    box._flush_drag_box()
    assert len(moves) == 1


def test_legacy_per_ratio_rule_preview_apply_and_union(window):
    from rawtims.fractions import FractionError, require_shared_selection
    w = window
    a = w.analysis
    key = a.group_keys[0]
    a.values[:, a.index(key)] = 1
    a.values[-1, a.index(key)] = 10
    w.rules_panel.set_rule('legacy_two_sigma')
    w.rules_panel.per_ratio_box.setChecked(True)
    w.rules_panel.function_combo.setCurrentIndex(w.rules_panel.function_combo.findData('one'))
    w.rules_panel.ratio_combo.setCurrentIndex(w.rules_panel.ratio_combo.findData(key))
    before = a.included.copy()
    proposal = w.preview_rule()
    np.testing.assert_array_equal(a.included, before)
    assert proposal.evaluation == 'legacy_per_ratio'
    w.apply_preview()
    assert not a.group_consistent()
    with pytest.raises(FractionError):
        require_shared_selection(a)
    w.undo()
    np.testing.assert_array_equal(a.included, before)
    w.redo()
    w.use_union_of_rejections()
    require_shared_selection(a)


def test_natural_order_for_fraction_picker(window):
    from rawtims.fractions import Fraction
    from rawtims_gui.studio.naming import natural_sort_key
    a = window.analysis
    fractions = [Fraction(name, pb=a) for name in ('sample z10', 'sample z2', 'sample z1')]
    window.workspace.fractions = fractions
    window.current = (fractions[0], 'Pb')
    window.fraction_list.set_fractions(fractions, window.current)
    window.review_shell.refresh()
    picker = window.review_shell.picker
    assert [picker.itemText(i) for i in range(3)] == [f'sample z{i} · Pb' for i in (1, 2, 10)]
    layout = window.fraction_list.rows_layout
    assert [layout.itemAt(i).widget().fraction.fraction_id for i in range(3)] == [f'sample z{i}' for i in (1, 2, 10)]
    assert sorted(['10', '2', '1'], key=natural_sort_key) == ['1', '2', '10']


def test_xlsx_csv_send_no_real_launch(window,tmp_path,monkeypatch):
    from openpyxl import load_workbook

    from rawtims_gui import age_app
    w=window
    xlsx=w.save_review_xlsx(str(tmp_path/'review.xlsx'))
    assert xlsx
    book=load_workbook(xlsx)
    assert book.sheetnames==['Fractions','Cycles','Provenance']
    assert book['Cycles'].max_row==w.analysis.n_cycles+1
    assert any(c.value=='206/204 D included' for c in book['Cycles'][1])
    book.close()
    outputs=w.save_review_tables(str(tmp_path))
    assert {p.name for p in outputs}=={'fractions.csv','cycles.csv','provenance.csv'}
    sent=[]
    monkeypatch.setattr(age_app,'send',lambda path,command,**kwargs:sent.append((path,command)) or 'mocked send')
    assert w.send_to_age_app(str(tmp_path))
    assert len(sent)==1 and sent[0][0].is_file()
    assert w.settings.value('export/send_folder')==str(tmp_path)


@pytest.mark.slow
def test_project_warning_and_real_apply_roundtrip(window,tmp_path):
    p=drive_path()
    if not p.is_dir():pytest.skip('Boise examples unavailable')
    w=window
    w.unsaved_prompt=lambda _name:'discard'
    assert w.walkthrough.start(folder=p,step=1,synchronous=True)
    until(lambda: not w._workers)
    a=w.analysis
    mask=a.included.copy()
    w.show_correction_page('Reduction')
    w.reduction_panel.dead_time.setText('40')
    w.reduction_controller.apply()
    until(lambda: not w._workers)
    assert a.run.reduction_parameters.daly_dead_time_ns==40,w.reduction_panel.status.text()
    np.testing.assert_array_equal(a.included,mask)
    assert '36.3 → 40' in w.reduction_panel.diff.text()
    path=w.save_session_as(tmp_path/'g1.session')
    assert path
    w.undo();assert a.run.reduction_parameters.daly_dead_time_ns==36.3
    w.redo();assert a.run.reduction_parameters.daly_dead_time_ns==40
    w.unsaved_prompt=lambda _name:'discard'
    assert w.open_session(path,synchronous=True)
    assert w.analysis.run.reduction_parameters.daly_dead_time_ns==40
    assert '36.3 → 40' in w.reduction_panel.diff.text()
    f=w.workspace.fractions[0]
    w.select_run(f,'U')
    w.warning_chip.click()
    assert '270/267' in w.run_info_panel.text.text()
    assert 'terminal' in w.run_info_panel.text.text()
    assert w.warning_chip.isVisibleTo(w)
    w.open_paths([str(p/'KG5_z7_Pb.trip')],synchronous=True)
    assert w.source_bar.isVisibleTo(w)
    assert 'B1609_F12_GA9683326 z3 Pb-56377.xls' in w.source_notice.text()
    assert w.locate_button.isVisibleTo(w)


@pytest.mark.slow
def test_scripted_walkthrough_reaches_send_without_launching(window, tmp_path, monkeypatch):
    from rawtims_gui import age_app
    from rawtims_gui.walkthrough import availability
    if not drive_path().is_dir():
        pytest.skip('Boise examples unavailable')
    assert 'Examples unavailable' in availability(tmp_path)
    w = window
    w.unsaved_prompt = lambda _name: 'discard'
    monkeypatch.setattr(age_app, 'send', lambda *args, **kwargs: pytest.fail('walkthrough must not launch'))
    assert w.walkthrough.start(folder=drive_path(), step=5, synchronous=True)
    until(lambda: not w._workers)
    fraction = w.workspace.fractions[0]
    assert fraction.pb.run.reduction_parameters.daly_dead_time_ns == 40
    assert fraction.pb.run.reduction_parameters.route == 'raw'
    assert not fraction.pb.legacy_pending and not fraction.u.legacy_pending
    assert fraction.pb.group_consistent() and fraction.u.group_consistent()
    assert '36.3 → 40' in w.reduction_panel.diff.text()
    assert w.inspector_tabs.tabText(w.inspector_tabs.currentIndex()) == 'Export'
    assert w.walkthrough.step == 5
