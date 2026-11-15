"""GUI step A: import, fraction list, plot wall, cycle table, hand rejection with SYNCH, undo (SPEC section 5, F3-F10).

Mouse gestures are exercised through the slots the mouse handlers call
(``CyclePlot._on_click`` and ``_on_box`` with view coordinates), not through
pixel-exact synthetic events.
"""

from __future__ import annotations

import pytest
import numpy as np

QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6 import QtGui, QtTest, QtWidgets  # noqa: E402

from reader_fixtures import B998, FIXTURES, GHR1_PB_XLS, GHR1_U_XLS, TIMSDP_FILES  # noqa: E402
from rawtims_gui import main as gui_main  # noqa: E402
from rawtims_gui.studio.theme import active_theme, build_application  # noqa: E402

B998_MAPPED = ["206/204 D", "206/207 D", "206/205 D", "207/205 D", "204/205 D", "208/205 D"]
NO_MODIFIER = QtCore.Qt.KeyboardModifier.NoModifier


@pytest.fixture
def app():
    return build_application(["test"], theme_mode="light")


@pytest.fixture(params=["classic", "wall"])
def window(app, qt_settings_folder, request):
    gui_main.app_settings().clear()
    window = gui_main.MainWindow(restore_geometry=False, layout=request.param)
    window.resize(gui_main.DEFAULT_SIZE)
    window.show()
    yield window
    window.unsaved_prompt = lambda _name: "discard"  # never block on the unsaved-session question
    window.close()
    window.deleteLater()
    # Delete it now: a window left alive would be restyled by every later theme switch.
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


@pytest.fixture
def b998(window):
    window.open_paths([str(B998)], synchronous=True)
    QtWidgets.QApplication.processEvents()
    return window


def _wait_for_import(window, start) -> None:
    """Run ``start`` (which begins an import on the thread pool) and wait until the window has the result."""
    finished = []
    window.importFinished.connect(finished.append)
    start()
    assert QtCore.QThreadPool.globalInstance().waitForDone(20_000)
    for _ in range(50):
        QtWidgets.QApplication.processEvents()
        if finished:
            break
    window.importFinished.disconnect(finished.append)
    assert finished, "the import did not finish"


def _open_async(window, *paths) -> None:
    """The interactive path: read on the thread pool, then deliver the result to the window."""
    _wait_for_import(window, lambda: window.open_paths([str(p) for p in paths]))


def test_import_pairs_runs_into_fractions(window):
    _open_async(window, B998)
    assert window.fraction_list.contents() == [("13223M02 iz1", B998.name, None)]
    assert window.analysis is window.workspace.fractions[0].pb
    assert window.workflow_step_list.currentRow() == gui_main.WORKFLOW_STEPS.index("Review")

    _open_async(window, GHR1_PB_XLS, GHR1_U_XLS)
    pb_timsdp, u_timsdp = TIMSDP_FILES["GHR1 230921 F08b-216"], TIMSDP_FILES["GHR1 230921F03 U-239"]
    _open_async(window, pb_timsdp, u_timsdp, FIXTURES / "MANIFEST.toml", B998)
    assert window.fraction_list.contents() == [
        ("13223M02 iz1", B998.name, None),
        ("GHR1 20200827-11", GHR1_PB_XLS.name, GHR1_U_XLS.name),
        # The two KU IsoLinx files carry different sample IDs (F08 and F01), so they open as two fractions.
        ("GHR1 230921 F08", pb_timsdp.name, None),
        ("GHR1 230921F01", None, u_timsdp.name),
    ]
    # Skipped files: a status-bar button with the list, never a dialog.
    assert window.skipped_button.isVisibleTo(window) and window.skipped_button.text() == "2 skipped"
    reasons = [window.skipped_list.item(i).text() for i in range(window.skipped_list.count())]
    assert any(text.startswith("MANIFEST.toml: ") for text in reasons)
    assert any(text.startswith(B998.name) and "already open" in text for text in reasons)
    assert not QtWidgets.QApplication.activeModalWidget()

    # The fraction ID is editable; an ID already used merges the runs when they fit.
    u_fraction = window.workspace.find("GHR1 230921F01")
    assert window.rename_fraction(u_fraction, "GHR1 230921 F08")
    assert window.fraction_list.contents()[2:] == [("GHR1 230921 F08", pb_timsdp.name, u_timsdp.name)]
    assert not window.rename_fraction(window.workspace.find("GHR1 230921 F08"), "GHR1 20200827-11")
    assert window.rename_fraction(window.workspace.find("13223M02 iz1"), "z1")
    assert window.fraction_list.contents()[0][0] == "z1"


def test_dropping_files_on_the_window_opens_them(window):
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(GHR1_PB_XLS)), QtCore.QUrl.fromLocalFile(str(GHR1_U_XLS))])
    point = QtCore.QPointF(400, 300)
    enter = QtGui.QDragEnterEvent(point, QtCore.Qt.DropAction.CopyAction, mime, QtCore.Qt.MouseButton.LeftButton, NO_MODIFIER)
    window.dragEnterEvent(enter)
    assert enter.isAccepted()
    drop = QtGui.QDropEvent(point, QtCore.Qt.DropAction.CopyAction, mime, QtCore.Qt.MouseButton.LeftButton, NO_MODIFIER)
    _wait_for_import(window, lambda: window.dropEvent(drop))
    assert window.fraction_list.contents() == [("GHR1 20200827-11", GHR1_PB_XLS.name, GHR1_U_XLS.name)]


def test_inline_fraction_id_edit_and_chips(b998):
    window = b998
    row = window.fraction_list.rows[0]
    row.id_editor.start_editing()
    row.id_editor.edit.setText("13223M02 z1")
    row.id_editor.edit.editingFinished.emit()
    QtWidgets.QApplication.processEvents()
    assert window.workspace.fractions[0].fraction_id == "13223M02 z1"
    row = window.fraction_list.rows[0]
    assert row.chips["Pb"].tile_active and row.chips["Pb"].tile_selected
    assert not row.chips["U"].tile_active  # missing U run: dashed chip, clicking it does nothing
    row.chips["U"].click()
    assert window.current[1] == "Pb"


def test_plot_wall_shows_the_mapped_functions(b998):
    window = b998
    assert [plot.key for plot in window.plot_wall.plots] == B998_MAPPED
    assert window.plot_wall.column_count() == 2
    plot = window.plot_wall.plot("206/204 D")
    assert plot.rows_shown.size == 96
    assert "206/204 D" in plot.title_text and "%" in plot.title_text
    window.set_plot_mode("intensities")
    assert [plot.key for plot in window.plot_wall.plots] == ["204 D", "205 D", "206 D", "207 D", "208 D"]
    window.set_plotted(["204 D", "Pb208 S5 int"])
    assert [plot.key for plot in window.plot_wall.plots] == ["204 D", "Pb208 S5 int"]
    window.set_plot_mode("ratios")
    window.set_plotted([*B998_MAPPED, "206/208 D"])
    assert window.plot_wall.plots[-1].key == "206/208 D"
    assert [window.stats_panel.table.item(i, 0).text() for i in range(window.stats_panel.table.rowCount())] == [*B998_MAPPED, "206/208 D"]
    window.plot_contract_ratios()
    assert [plot.key for plot in window.plot_wall.plots] == B998_MAPPED


def test_click_rejects_through_the_history_with_undo_and_redo(b998):
    window = b998
    analysis = window.analysis
    plot = window.plot_wall.plot("206/204 D")
    stats_before = analysis.stats("206/204 D")
    assert stats_before.n_used == 96 and analysis.history == []

    plot._on_click(plot.point_of(20), NO_MODIFIER)
    op = analysis.history[-1]
    assert op["op"] == "toggle_cycles" and op["cycles"] == [20] and op["include"] is False
    assert op["keys"] == B998_MAPPED  # SYNCH on: every mapped function
    assert all(not analysis.included[20, analysis.index(key)] for key in B998_MAPPED)
    assert analysis.included[20, analysis.index("206/208 D")]
    assert analysis.stats("206/204 D").n_used == 95
    assert window.stats_panel.table.item(0, 3).text() == "95/96"
    assert window.cycles_label.text() == "Cycles 95/96"
    assert window.history_label.text() == "History 1"
    assert plot.points.data["symbol"][20] == "o" and plot.points.data["brush"][20].style() == QtCore.Qt.BrushStyle.NoBrush

    window.undo_action.trigger()
    assert analysis.history == [] and analysis.stats("206/204 D").n_used == 96
    assert window.history_label.text() == "History 0 · redo available"
    window.redo_action.trigger()
    assert len(analysis.history) == 1 and analysis.stats("206/204 D").n_used == 95
    # Clicking the excluded point again includes it.
    plot._on_click(plot.point_of(20), NO_MODIFIER)
    assert analysis.history[-1]["include"] is True and analysis.stats("206/204 D").n_used == 96
    assert window.undo_action.shortcut().matches(QtGui.QKeySequence(QtGui.QKeySequence.StandardKey.Undo)) != QtGui.QKeySequence.SequenceMatch.NoMatch


def test_synch_off_cannot_disable_the_group_mask(b998):
    window = b998
    analysis = window.analysis
    assert window.synch_action.isChecked() and analysis.settings.synced
    window.synch_action.trigger()
    assert analysis.settings.synced and not window.synch_action.isEnabled() and analysis.history == []
    plot = window.plot_wall.plot("206/207 D")
    plot._on_click(plot.point_of(30), NO_MODIFIER)
    assert analysis.history[-1]["keys"] == B998_MAPPED
    assert not analysis.included[30, analysis.index("206/207 D")]
    assert not analysis.included[30, analysis.index("206/204 D")]
    window.undo_action.trigger()
    assert analysis.settings.synced and window.synch_action.isChecked()


def test_box_block_and_selection_tools(b998):
    window = b998
    analysis = window.analysis
    plot = window.plot_wall.plot("206/205 D")
    first, fourth = plot.point_of(0), plot.point_of(3)
    rect = QtCore.QRectF(QtCore.QPointF(first.x() - 0.4, -1e9), QtCore.QPointF(fourth.x() + 0.4, 1e9))
    plot._on_box(rect, NO_MODIFIER)
    assert analysis.history[-1]["cycles"] == [0, 1, 2, 3] and analysis.stats("206/205 D").n_used == 92

    window.request_block_toggle("206/205 D", 40)
    block = int(analysis.run.block[40])
    assert not analysis.block_included[list(analysis.blocks).index(block)]
    window.block_action.trigger()  # B: the block of the last clicked cycle, back on
    assert analysis.block_included.all()

    # ⌘-click selects without rejecting; Delete rejects the selection; B toggles its block.
    plot._on_click(plot.point_of(70), QtCore.Qt.KeyboardModifier.ControlModifier)
    plot._on_box(QtCore.QRectF(QtCore.QPointF(plot.point_of(72).x() - 0.4, -1e9), QtCore.QPointF(plot.point_of(73).x() + 0.4, 1e9)),
                 QtCore.Qt.KeyboardModifier.ShiftModifier | QtCore.Qt.KeyboardModifier.ControlModifier)
    assert window.selection == {70, 72, 73} and analysis.stats("206/205 D").n_used == 92
    assert plot.selected_rows == {70, 72, 73}
    window.reject_action.trigger()
    assert analysis.history[-1]["cycles"] == [70, 72, 73] and analysis.history[-1]["include"] is False
    window.block_action.trigger()
    assert not analysis.block_included[list(analysis.blocks).index(int(analysis.run.block[70]))]
    window.clear_selection_action.trigger()
    assert not window.selection and not plot.selected_rows

    assert window.reset_analysis(confirm=False)
    assert analysis.effective.sum() == (~analysis.invalid).sum()
    window.undo_action.trigger()
    assert not analysis.block_included.all()


def test_table_selection_and_points_follow_each_other(b998):
    window = b998
    window.set_plot_mode("table")
    table = window.cycle_table
    model = table.cycle_model
    assert model.columnCount() == 4 + len(B998_MAPPED) and model.rowCount() == 96
    assert [model.headerData(c, QtCore.Qt.Orientation.Horizontal) for c in range(4)] == ["Include", "Block", "Cycle", "Time (s)"]
    assert table.frozen.frozen_columns() == [0, 1, 2]
    selection = QtCore.QItemSelection(model.index(5, 0), model.index(6, model.columnCount() - 1))
    table.selectionModel().select(selection, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
    assert window.selection == {5, 6}
    window.set_plot_mode("ratios")
    plot = window.plot_wall.plot("206/204 D")
    assert plot.selected_rows == {5, 6} and len(plot.ring.data) == 2
    plot._on_click(plot.point_of(9), QtCore.Qt.KeyboardModifier.ControlModifier)
    assert table.selected_rows() == [5, 6, 9]
    # Unticking Include in the table is the same synced toggle as a click.
    model.setData(model.index(12, 0), QtCore.Qt.CheckState.Unchecked, QtCore.Qt.ItemDataRole.CheckStateRole)
    assert window.analysis.history[-1]["cycles"] == [12] and window.analysis.history[-1]["keys"] == B998_MAPPED
    assert model.data(model.index(12, 0), QtCore.Qt.ItemDataRole.CheckStateRole) == QtCore.Qt.CheckState.Unchecked


def test_log_ratio_and_theme_switch(b998):
    window = b998
    plot = window.plot_wall.plot("206/204 D")
    linear = plot.y_shown.copy()
    window.log_action.trigger()
    assert plot.y_shown == pytest.approx(__import__("numpy").log(linear))
    assert plot.title_text.startswith("ln(206/204 D)")
    window.set_theme("dark")
    try:
        assert active_theme().name == "dark" and window.theme_actions["dark"].isChecked()
        assert window.settings.value(gui_main.THEME_KEY) == "dark"
    finally:
        window.set_theme("light")


def _reject_b998_outliers(window):
    values = window.analysis.column("206/204 D")
    rows = np.argsort(np.abs(values - np.median(values)))[-2:].tolist()
    window.request_toggle("206/204 D", rows)
    return rows


def test_accepted_range_pins_outliers_and_click_restores_through_history(b998):
    plot = b998.plot_wall.plot("206/204 D")
    all_range = plot.view_box.viewRange()[1]
    rows = _reject_b998_outliers(b998)
    QtWidgets.QApplication.processEvents()
    accepted_range = plot.view_box.viewRange()[1]
    values = b998.analysis.column(plot.key)
    accepted = values[b998.analysis.included_for(plot.key)]
    padding = np.ptp(accepted) * 0.08
    assert accepted_range == pytest.approx([accepted.min() - padding, accepted.max() + padding])
    assert accepted_range[1] < values[rows].min()
    assert len(plot.pinned_points.data) == 2
    assert set(plot.pinned_points.data["symbol"]) == {"t1"}
    for row, point in zip(sorted(rows), plot.pinned_points.points()):
        # Tooltips retain the true value even though the marker is at an edge.
        assert f"{b998.analysis.column(plot.key)[row]:.12g}" in point.data()
        assert point.brush().style() == QtCore.Qt.BrushStyle.NoBrush
    b998.undo()
    assert plot.view_box.viewRange()[1] == pytest.approx(all_range)
    b998.redo()
    assert plot.view_box.viewRange()[1] == pytest.approx(accepted_range)
    # Exercise a real mouse event on the edge marker, including scatter hit handling.
    point = plot.point_of(rows[0])
    pos = plot.mapFromScene(plot.view_box.mapViewToScene(point))
    QtTest.QTest.mouseClick(plot.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=pos)
    QtWidgets.QApplication.processEvents()
    assert b998.analysis.included_for(plot.key)[rows[0]]
    assert b998.analysis.history[-1]["include"] is True
    b998.undo()
    assert not b998.analysis.included_for(plot.key)[rows[0]]


def test_fit_all_points_is_a_view_preference_and_preserves_zoom_until_data_changes(b998, tmp_path):
    plot = b998.plot_wall.plot("206/204 D")
    _reject_b998_outliers(b998)
    path = b998.save_session_as(tmp_path / "range.rawtims")
    accepted_range = plot.view_box.viewRange()[1]
    assert not b998.fit_all_action.isChecked()
    b998.fit_all_button.click()
    all_range = plot.view_box.viewRange()[1]
    assert all_range[0] < plot.y_shown.min() and all_range[1] > plot.y_shown.max()
    assert not len(plot.pinned_points.data)
    assert not b998.is_modified()
    assert b998.settings.value(gui_main.FIT_ALL_KEY, type=bool)
    other = gui_main.MainWindow(restore_geometry=False)
    try:
        assert other.fit_all_action.isChecked()
    finally:
        other.deleteLater()
    b998.fit_all_button.click()
    assert plot.view_box.viewRange()[1] == pytest.approx(accepted_range)
    # ViewBox wheel zoom is the path used by the plot's ⌘/Ctrl-wheel handler.
    QtWidgets.QApplication.processEvents()
    pos = plot.viewport().rect().center()
    wheel = QtGui.QWheelEvent(QtCore.QPointF(pos), QtCore.QPointF(plot.viewport().mapToGlobal(pos)),
                             QtCore.QPoint(), QtCore.QPoint(0, 120), QtCore.Qt.MouseButton.NoButton,
                             QtCore.Qt.KeyboardModifier.ControlModifier, QtCore.Qt.ScrollPhase.NoScrollPhase, False)
    QtWidgets.QApplication.sendEvent(plot.viewport(), wheel)
    zoomed = plot.view_box.viewRange()[1]
    assert zoomed != pytest.approx(accepted_range)
    b998.request_select(plot.key, [50], False)
    b998.preview_rule()
    b998.discard_preview()
    b998.set_theme("dark")
    assert plot.view_box.viewRange()[1] == pytest.approx(zoomed)
    b998.request_toggle(plot.key, [50])
    assert plot.view_box.viewRange()[1] != pytest.approx(zoomed)
    b998.set_fit_all_points(True)
    b998.unsaved_prompt = lambda _name: "discard"
    assert b998.open_session(path, synchronous=True)
    assert b998.fit_all_action.isChecked()  # session loading leaves the viewer preference alone


def test_invalid_points_do_not_stretch_the_default_range(b998):
    from dataclasses import replace
    from rawtims.analysis import Analysis
    from rawtims_gui.plots import PlotState

    plot = b998.plot_wall.plot("206/204 D")
    run = b998.analysis.run
    values, invalid = run.values.copy(), run.invalid.copy()
    column = b998.analysis.index(plot.key)
    rows = np.argsort(np.abs(values[:, column] - np.median(values[:, column])))[-2:]
    values[rows, column] = [-1e6, 1e6]
    invalid[rows, column] = True
    analysis = Analysis(replace(run, values=values, invalid=invalid))
    plot.update_state(PlotState(analysis, None, False, frozenset()), rebuild=True)
    lo, hi = plot.view_box.viewRange()[1]
    assert 1700 < lo < 1900 and 2200 < hi < 2400
    assert not len(plot.pinned_points.data)  # invalid points remain grey crosses
    assert all(plot.points.data["symbol"][row] == "x" for row in rows)
    # The same finite extremes, when excluded rather than invalid, pin in both directions.
    excluded = Analysis(replace(run, values=values))
    excluded.toggle_cycles(rows.tolist(), [plot.key], False)
    plot.update_state(PlotState(excluded, None, False, frozenset()))
    assert set(plot.pinned_points.data["symbol"]) == {"t", "t1"}
    # A flat accepted series still gets a nonzero, proportionate range.
    values[:, column] = 2000
    analysis = Analysis(replace(run, values=values, invalid=invalid))
    plot.update_state(PlotState(analysis, None, False, frozenset()))
    lo, hi = plot.view_box.viewRange()[1]
    assert 0 < lo < 2000 < hi < 3000


@pytest.mark.parametrize("size", [(1280, 800), (1440, 900), (1024, 640)])
def test_review_fits_without_horizontal_scrolling(b998, size):
    window = b998
    window.resize(*size)
    for _ in range(3):
        QtWidgets.QApplication.processEvents()
    assert window.size() == QtCore.QSize(*size)
    assert window.minimumSize() == QtCore.QSize(1024, 640)
    wall = window.plot_wall
    assert not wall.horizontalScrollBar().isVisible()
    assert wall.container.width() <= wall.viewport().width()
    if window.layout_name == "wall":
        assert wall.column_count() == (3 if size[0] >= 1440 else 2 if size[0] >= 1100 else 1)
    else:
        assert 1 <= wall.column_count() <= 2
    for plot in wall.plots:
        assert plot.width() >= 250 and plot.geometry().right() <= wall.container.width()
    for panel in (window.rail_panel, window.centre_stack, window.inspector_panel):
        if not panel.isVisible():
            continue
        top_left = panel.mapTo(window, QtCore.QPoint(0, 0))
        assert top_left.x() >= 0 and top_left.x() + panel.width() <= size[0]


def test_reset_layout(b998):
    window = b998
    window.resize(1100, 700)
    window.reset_layout_action.trigger()
    assert window.size() == window.default_window_size()
    assert window.settings.value(gui_main.GEOMETRY_KEY) is None


def test_open_and_export_png_renders_a_loaded_run(tmp_path):
    from test_main_window import _run_cli

    output = tmp_path / "b998.png"
    result = _run_cli("--theme", "light", "--open", str(B998), "--export", "png", str(output), tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert output.stat().st_size > 10_000
    assert QtGui.QImage(str(output)).size() == QtCore.QSize(1280, 800)
