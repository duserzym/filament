"""P1 presentation oracles and synthetic edge cases; no lab data or network.

Oracle paths are relative to the supplied pinned source clones (OGTripoli
d906f70, Tripoli 00dc941). These are scalar/source-semantics comparisons,
not claims of matching upstream screenshots.
"""
from dataclasses import replace
from datetime import UTC, datetime
import os
from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.analysis import Analysis
from rawtims.contract import csv_text
from rawtims.diagnostics import oxygen_monitor
from rawtims.exports import clipboard_text, cycles_csv_text
from rawtims.fractions import Fraction
from rawtims.model import Function, RawFile, Run, RunMetadata
from rawtims.session import load_session, save_session, session_document, session_fingerprint
from rawtims_gui import main as gui
from rawtims_gui.diagnostic_data import DisplayOptions, dot_sizes, histogram, reciprocal
from rawtims_gui.diagnostics import DiagnosticDialog, display_options, edit_notes, graph_sheets, plot_pages, print_pages, save_pages, set_display
from rawtims_gui.plots import CyclePlot, PlotState
from rawtims_gui.studio.theme import build_application
from rawtims_gui.workspace import Workspace
from reader_fixtures import SYNTHETIC_U, TIMSDP_FILES, read


@pytest.fixture
def synthetic():
    functions = (Function(0, '272/270', '272/270', 'ratio', numerator_mass=272, denominator_mass=270),
                 Function(1, 'Synthetic intensity', 'intensity', 'intensity'),
                 Function(2, 'Synthetic gain', 'gain', 'other'))
    values = np.array([[.004, 10, 1], [.008, 20, 2], [.012, 30, 3], [.016, 40, 4], [.020, 50, 5], [.024, 60, 6]])
    run = Run('synthetic-p1', RawFile('synthetic-memory', 'synthetic-memory', 0, '0'*64, 'synthetic'),
              'U', RunMetadata(sample_id='Synthetic P1', cycles_per_block=3), functions,
              np.arange(11, 17), np.array([1, 1, 1, 2, 2, 2]), np.arange(6.)*2.5,
              values, np.zeros_like(values, dtype=bool))
    analysis = Analysis(run)
    analysis.toggle_cycles([1, 4], ['272/270'], False)
    return analysis


@pytest.fixture
def window(monkeypatch, tmp_path, synthetic):
    build_application(['p1-test'], theme_mode='light')
    settings = QtCore.QSettings(str(tmp_path/'p1.ini'), QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(gui, 'app_settings', lambda: settings)
    window = gui.MainWindow(restore_geometry=False)
    fraction = Fraction(fraction_id='Synthetic P1', u=synthetic)
    window.workspace.fractions = [fraction]
    window.resize(1280, 800)
    window.show()
    window.select_run(fraction, 'U')
    window.set_plotted(['272/270', 'gain'])
    for _ in range(3):
        QtWidgets.QApplication.processEvents()
    yield window
    window.unsaved_prompt = lambda _: 'discard'
    window.close()
    window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_histogram_tripoli_boundary_oracle():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/plots/histograms/HistogramBuilder.java:55-80.

    Positive internal boundary uses Tripoli's 1.000000001 epsilon and the
    last bin includes the rightmost datum. Rejected counts extend the primitive.
    """
    edges, accepted, rejected = histogram(np.array([1., 2., 3., 4.]), np.array([1, 0, 1, 1], dtype=bool), 3)
    np.testing.assert_equal(edges, [1, 2, 3, 4])
    np.testing.assert_equal(accepted, [1, 1, 1])
    np.testing.assert_equal(rejected, [1, 0, 0])


@pytest.mark.parametrize('values', [[], [3, 3, 3], [0, -1, 1, float('nan'), float('inf')]])
def test_histogram_counts_every_finite_cycle(values):
    values = np.array(values, dtype=float)
    mask = np.arange(len(values)) % 2 == 0
    _, a, r = histogram(values, mask, 4)
    assert a.sum() + r.sum() == np.isfinite(values).sum()
    assert a.sum() == (np.isfinite(values) & mask).sum()


def test_java_dot_radius_oracle():
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/AnalysisTwoUserFunctionsPlot.java:219-235,621-647."""
    np.testing.assert_equal(dot_sizes([0, 10, 20, 30, np.nan], 2, 6), [4, 4, 8, 12, 4])
    np.testing.assert_equal(dot_sizes([5, 5], 2, 6), [12, 12])
    with pytest.raises(ValueError):
        dot_sizes([1], 6, 2)


def test_oxygen_monitor_opt_in_and_invalids(synthetic):
    """F13 extension: no dedicated Tripoli /2 monitor oracle exists in either clone."""
    before = synthetic.values.copy()
    with pytest.raises(ValueError, match='Verified'):
        oxygen_monitor([.004])
    np.testing.assert_allclose(oxygen_monitor([.004, .006, 0, -1, np.nan, np.inf], verified_uo2=True),
                               [.002, .003, np.nan, np.nan, np.nan, np.nan], equal_nan=True)
    np.testing.assert_equal(synthetic.values, before)


@pytest.mark.parametrize('mode,expected', [('Pinned', [11,12,13,14,15,16]), ('INCLUDE', [11,12,13,14,15,16]),
                                           ('IGNORE', [11,12,13,14,15,16]), ('HIDE', [1,2,3,4])])
def test_rejection_display_oracle(window, mode, expected):
    """OGTripoli/source/RawRatio.cs:804-839; source/forms/frmRatioGraph.cs:753-825.

    Hide compresses accepted positions and suppresses separators; Include and
    Ignore retain positions. Existing filament Pinned is an additional default.
    """
    a = window.analysis
    effective, history = a.effective.copy(), a.history_count
    stats = a.stats('272/270')
    set_display(window, 'rejected', mode)
    plot = window.plot_wall.plots[0]
    np.testing.assert_equal(plot.x_shown, expected)
    if mode == 'HIDE':
        np.testing.assert_equal(plot.rows_shown, [0,2,3,5])
        assert plot.rows_in(QtCore.QRectF(.5, 0, 1, 1)) == [0]
        assert not plot._block_decorations
    assert plot._fit_all == (mode == 'INCLUDE')
    np.testing.assert_equal(a.effective, effective)
    assert a.history_count == history and a.stats('272/270') == stats


def test_hidden_invalid_cycle_keeps_position(window):
    """OGTripoli/source/RawRatio.cs:828-831 retains zero/missing rows in Hide."""
    a = window.analysis
    invalid = a.run.invalid.copy()
    invalid[1, 0] = True
    values = a.run.values.copy()
    values[1, 0] = 0
    a = Analysis(replace(a.run, values=values, invalid=invalid))
    plot = CyclePlot('272/270')
    plot.update_state(PlotState(a, None, False, frozenset(), display=DisplayOptions(rejected='HIDE')))
    assert 1 in plot.rows_shown  # zero is missing rather than an outlier
    plot.close()


@pytest.mark.parametrize('bands,visible', [('2σ, σ, SE', [True,True,True]), ('σ, SE', [False,True,True]), ('SE', [False,False,True])])
def test_stats_band_sets_oracle(window, bands, visible):
    """OGTripoli/source/forms/frmRatioGraph.cs:533-563,2286-2310: nested 2s/s/SE sets."""
    set_display(window, 'bands', bands)
    plot = window.plot_wall.plots[0]
    assert [b.isVisible() for b in plot._bands] == visible
    for band, k in zip(plot._bands, [2,1,1]):
        spread = window.analysis.stats(plot.key).se if band is plot._bands[-1] else window.analysis.stats(plot.key).sd
        np.testing.assert_allclose(band.getRegion(), [window.analysis.stats(plot.key).mean-k*spread, window.analysis.stats(plot.key).mean+k*spread])
    set_display(window, 'stats', False)
    assert not any(b.isVisible() for b in plot._bands)
    assert not window.plot_wall.cards[0].summary.isVisible()
    restored = display_options(window.settings)
    assert restored.bands == bands and not restored.stats


def test_block_means_and_block_zoom_oracle(window):
    """OGTripoli/source/forms/frmRatioGraph.cs:827-840 draws stored block means.

    Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/AnalysisBlockCyclesPlotOG.java:1143-1163
    fits one block with ±1 x margin and 5% y margin; filament exposes this as
    a view-only menu button, without entering upstream's sculpting mode.
    """
    before = window.analysis.effective.copy()
    set_display(window, 'block_means', True)
    plot = window.plot_wall.plots[0]
    expected = [s.mean for s in window.analysis.block_stats(plot.key).values()]
    np.testing.assert_allclose([line.yData[0] for line in plot._block_mean_lines], expected)
    plot.zoom_block(2)
    np.testing.assert_allclose(plot.view_box.viewRange()[0], [13,17])
    np.testing.assert_allclose(plot.view_box.viewRange()[1], [.0156,.0244])
    np.testing.assert_equal(window.analysis.effective, before)


def test_inverse_readouts_bands_and_freeze_oracle(window):
    """OGTripoli/source/RawRatio.cs:849 freezes display stats; frmRatioGraph.cs:713-727 marks frozen mean.

    Inverse display is separate from Mapping; the frozen display keeps its
    snapshot while actual arithmetic statistics continue to refresh.
    Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/AnalysisTwoUserFunctionsPlot.java:186-196
    uses per-cycle reciprocal values for an inverted function.
    """
    plot = window.plot_wall.plots[0]
    original = window.analysis.column(plot.key).copy()
    set_display(window, 'inverted', True)
    np.testing.assert_allclose(plot.y_shown, 1/original)
    assert 'display inverse' in window.plot_wall.cards[0].name.text()
    assert 'source MSWD' in window.plot_wall.cards[0].summary.text()
    assert plot._mean_line.value() == pytest.approx(np.mean(1/original[window.analysis.included_for(plot.key)]))
    assert all(a <= b for a,b in (band.getRegion() for band in plot._bands))
    set_display(window, 'frozen', True)
    frozen = plot.display_stats()
    window.request_toggle(plot.key, [5])
    assert plot.display_stats() == frozen
    assert window.analysis.stats(plot.key).mean != frozen.mean
    assert 'Frozen statistics' in window.plot_wall.cards[0].name.text()
    set_display(window, 'frozen', False)
    assert plot.display_stats().mean == pytest.approx(np.mean(1/original[window.analysis.included_for(plot.key)]))
    np.testing.assert_equal(window.analysis.column(plot.key), original)


def test_xy_time_histogram_and_oxygen_dialog(window):
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1499-1530.

    Any two columns pair by original row, including rejected cycles. Existing
    Run.time is seconds; no model residuals are manufactured.
    """
    dialog = DiagnosticDialog(window)
    dialog.mode.setCurrentText('x–y')
    dialog.y.setCurrentIndex(dialog.y.findData('gain'))
    dialog.intensity.setCurrentIndex(dialog.intensity.findData('intensity'))
    np.testing.assert_equal(dialog.coordinates[0], window.analysis.column('272/270'))
    np.testing.assert_equal(dialog.coordinates[1], window.analysis.column('gain'))
    np.testing.assert_equal(dialog.rows, np.arange(6))
    dialog.mode.setCurrentText('Time')
    np.testing.assert_equal(dialog.coordinates[0], [0,2.5,5,7.5,10,12.5])
    dialog.mode.setCurrentText('Oxygen monitor')
    assert 'verify' in dialog.status.text()
    dialog.verify.setChecked(True)
    np.testing.assert_equal(dialog.coordinates[1], window.analysis.column('272/270')/2)
    dialog.x.setCurrentIndex(dialog.x.findData('gain'))
    assert not dialog.verify.isChecked()
    assert not dialog.plot.listDataItems()
    dialog.close()


def test_recipe_save_load_delete(window, monkeypatch):
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1536-1635: named recipes/delete."""
    dialog = DiagnosticDialog(window)
    monkeypatch.setattr(QtWidgets.QInputDialog, 'getText', lambda *a, **k: ('Synthetic recipe', True))
    dialog.mode.setCurrentText('x–y')
    dialog.y.setCurrentIndex(dialog.y.findData('gain'))
    dialog.save_recipe()
    assert window.workspace.presentation['recipes']['Synthetic recipe']['y'] == 'gain'
    dialog.y.setCurrentIndex(0)
    dialog.load_recipe()
    assert dialog.y.currentData() == 'gain'
    assert not dialog.verify.isChecked()
    dialog.delete_recipe()
    assert window.workspace.presentation['recipes'] == {}
    dialog.close()


def test_missing_time_and_recipe_function(window):
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1504-1507 requires valid axes."""
    dialog = DiagnosticDialog(window)
    window.workspace.presentation['recipes'] = {'Missing': {'x':'missing', 'y':'gain'}}
    dialog.refresh_recipes()
    dialog.load_recipe()
    assert 'unavailable' in dialog.status.text()
    dialog.analysis = Analysis(replace(window.analysis.run, time=np.full(6, np.nan)))
    dialog.mode.setCurrentText('Time')
    assert 'no recorded cycle times' in dialog.status.text()
    dialog.close()


def test_point_style_persists_without_history(window, monkeypatch):
    """OGTripoli/source/forms/frmRatioGraph.cs:2054-2074: graph size/style presentation controls."""
    plot = window.plot_wall.plots[0]
    history = window.analysis.history_count
    monkeypatch.setattr(QtWidgets.QColorDialog, 'getColor', lambda *a: QtGui.QColor('#4477aa'))
    monkeypatch.setattr(QtWidgets.QInputDialog, 'getDouble', lambda *a: (7., True))
    plot.choose_point_color()
    plot.choose_point_size()
    window._rebuild_view()
    plot = window.plot_wall.plots[0]
    assert plot.point_color == '#4477aa' and plot.point_size == 7
    assert window.analysis.history_count == history


def test_printer_page_order(window, monkeypatch):
    """OGTripoli/source/forms/frmGraphPageDisplay.cs:195-205: each graph printed in page order."""
    from rawtims_gui import diagnostics
    events = []
    class Printer:
        def __init__(self, *a): pass
        def newPage(self): events.append('new-page')
        def resolution(self): return 300
        def pageRect(self, *a): return QtCore.QRectF(0,0,600,800)
    class Dialog:
        def __init__(self, *a): pass
        def exec(self): return QtWidgets.QDialog.DialogCode.Accepted
    class Painter:
        def __init__(self, *a): pass
        def isActive(self): return True
        def drawText(self, area, flags, title): events.append(title)
        def drawImage(self, *a): events.append('image')
        def end(self): events.append('end')
    pages = plot_pages(window)
    monkeypatch.setattr(diagnostics.QtPrintSupport, 'QPrinter', Printer)
    Printer.PrinterMode = type('Mode', (), {'HighResolution': 1})
    Printer.Unit = type('Unit', (), {'DevicePixel': 1})
    monkeypatch.setattr(diagnostics.QtPrintSupport, 'QPrintDialog', Dialog)
    monkeypatch.setattr(diagnostics.QtGui, 'QPainter', Painter)
    print_pages(window, pages)
    assert events == [pages[0][0], 'image', 'new-page', pages[1][0], 'image', 'end']


def test_notes_session_roundtrip_and_no_replay_change(tmp_path):
    """OGTripoli/source/TripoliWorkProduct.cs:42; Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/SessionManager.fxml:74.

    Plain text is stored as inert optional presentation metadata, not exported.
    """
    workspace = Workspace()
    workspace.open([SYNTHETIC_U])
    before = workspace.session_state()
    assert 'presentation' not in session_document(before, None)
    a = before.analyses()[0]
    history, values = a.history_count, a.values.copy()
    workspace.presentation = {'notes': {'session': 'Synthetic <plain> & λ\nsecond line', 'run:'+a.run.run_id: 'Run note'},
                              'recipes': {'Synthetic': {'mode':'x–y', 'x':a.functions[0].key, 'y':a.functions[1].key}},
                              'future_extension': {'preserve':[1,2,3]}}
    path = save_session(workspace.session_state(), tmp_path/'synthetic-p1.rawtims')
    state, problems = load_session(path)
    assert not problems and state.presentation == workspace.presentation
    restored = Workspace()
    restored.restore(state)
    assert restored.presentation == workspace.presentation
    np.testing.assert_equal(state.analyses()[0].values, values)
    assert state.analyses()[0].history_count == history
    assert session_fingerprint(state, path) == session_fingerprint(workspace.session_state(), path)
    state.presentation['notes']['session'] += ' edited'
    assert session_fingerprint(state, path) != session_fingerprint(workspace.session_state(), path)


def test_notes_editor_scopes_and_cancel(window, monkeypatch):
    """OGTripoli/source/forms/fmrMainTripoli.cs:4047 edits work-product notations."""
    def save(dialog):
        editor = dialog.findChild(QtWidgets.QPlainTextEdit)
        editor.setPlainText('Synthetic session note')
        dialog.findChild(QtWidgets.QComboBox).setCurrentIndex(1)
        editor.setPlainText('Synthetic work-product note')
        return QtWidgets.QDialog.DialogCode.Accepted
    monkeypatch.setattr(QtWidgets.QDialog, 'exec', save)
    edit_notes(window)
    notes = window.workspace.presentation['notes'].copy()
    assert notes['session'] == 'Synthetic session note'
    assert notes['run:synthetic-p1'] == 'Synthetic work-product note'
    monkeypatch.setattr(QtWidgets.QDialog, 'exec', lambda dialog: QtWidgets.QDialog.DialogCode.Rejected)
    edit_notes(window)
    assert window.workspace.presentation['notes'] == notes


def test_notes_only_session_is_dirty_and_rename_retains_notes(window):
    """OGTripoli/source/TripoliWorkProduct.cs:42 stores notations with the work product."""
    window.workspace.presentation['notes'] = {'fraction:Synthetic P1': 'Synthetic fraction note'}
    fraction = window.current[0]
    assert window.workspace.rename(fraction, 'Synthetic renamed')[0]
    assert window.workspace.presentation['notes']['fraction:Synthetic renamed'] == 'Synthetic fraction note'
    window.workspace = Workspace()
    assert not window.is_modified()
    window.workspace.presentation['notes'] = {'session':'Synthetic notes only'}
    assert window.is_modified()


def test_presentation_keeps_fraction_clipboard_and_cycle_exports(window):
    """OGTripoli/source/RawRatio.cs:804-849 separates active display rows; P1 additionally preserves all export bytes.

    Synthetic committed U fixture exercises a real mapped fraction and oxide
    functions, so the test covers export behavior beyond in-memory point masks.
    """
    workspace = Workspace()
    workspace.open([SYNTHETIC_U])
    window.workspace = workspace
    fraction = workspace.fractions[0]
    window.select_run(fraction, 'U')
    stamp = datetime(2026,11,25,tzinfo=UTC)
    def outputs():
        return (csv_text([workspace.fraction_row(fraction, stamp)]), clipboard_text(fraction), cycles_csv_text(window.analysis))
    before = outputs()
    for key, value in (('block_means',True), ('inverted',True), ('frozen',True), ('rejected','HIDE'), ('bands','SE'), ('stats',False)):
        set_display(window, key, value)
    workspace.presentation['notes'] = {'session':'Synthetic review note'}
    plot_pages(window)
    assert outputs() == before


def test_graph_page_order_png_and_plot_visibility(window, monkeypatch, tmp_path):
    """OGTripoli/source/forms/frmGraphPageDisplay.cs:185-205 provides screen/each-graph printing.

    OGTripoli/source/forms/fmrMainTripoli.cs:3440-3467 provides all/selected
    row visibility; P1 deliberately limits this to plot membership.
    """
    pages = plot_pages(window)
    assert len(pages) == 2
    sheets = graph_sheets(pages * 3)
    assert [title for title,_ in sheets] == ['Graphs 1–4', 'Graphs 5–6']
    assert sheets[0][1].width() == max(p.width() for _,p in pages)*2
    assert pages[0][0].startswith('272/270') and pages[1][0].startswith('Synthetic gain')
    assert all(not image.isNull() and image.height() > 150 for _,image in pages)
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(tmp_path/'synthetic-page.png'), 'PNG'))
    save_pages(window, pages)
    assert [p.name for p in sorted(tmp_path.glob('synthetic-page-*.png'))] == ['synthetic-page-001.png', 'synthetic-page-002.png']
    assert not QtGui.QImage(str(tmp_path/'synthetic-page-002.png')).isNull()
    before = window.analysis.effective.copy()
    next(a for a in window.diagnostics_menu.actions() if a.text() == 'Plot all functions in this view').trigger()
    assert set(window.plotted_keys()) == {'272/270','gain'}
    window.function_list.item(0).setSelected(True)
    next(a for a in window.diagnostics_menu.actions() if a.text() == 'Show selected function rows').trigger()
    assert window.plotted_keys() == ['272/270']
    next(a for a in window.diagnostics_menu.actions() if a.text() == 'Select all function rows').trigger()
    next(a for a in window.diagnostics_menu.actions() if a.text() == 'Show selected function rows').trigger()
    assert set(window.plotted_keys()) == {'272/270','gain'}
    np.testing.assert_equal(window.analysis.effective, before)


@pytest.mark.parametrize('fixture', ['GHR1 230921 F08b-216', 'WH205 z4 Pb-654'])
def test_committed_tripoli_columns_display_unchanged(window, fixture):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/AnalysisStatsRecord.java:68; named A/B committed fixtures.

    Existing fields remain unchanged under all transforms; upstream numeric
    report agreement is separately covered by test_stats_oracle.py.
    """
    analysis = Analysis(read(TIMSDP_FILES[fixture]))
    plot = CyclePlot(analysis.functions[0].key)
    stats, mask = analysis.stats(plot.key), analysis.effective.copy()
    plot.update_state(PlotState(analysis, None, False, frozenset(), display=DisplayOptions(block_means=True)))
    assert plot.display_stats() == stats
    np.testing.assert_equal(plot.y_shown, analysis.column(plot.key)[np.isfinite(analysis.column(plot.key))])
    np.testing.assert_equal(analysis.effective, mask)
    plot.close()


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('width,height', [(1280,800),(1440,900)])
def test_p1_layout_fits_both_themes(window, theme, width, height, tmp_path):
    """No Tripoli screenshot oracle; explicit P1 lab UI acceptance sizes."""
    window.set_theme(theme)
    window.resize(width, height)
    set_display(window, 'inverted', True)
    set_display(window, 'frozen', True)
    for _ in range(3):
        QtWidgets.QApplication.processEvents()
    assert window.width() == width and window.height() == height
    assert window.plot_wall.horizontalScrollBar().maximum() == 0
    assert window.review_shell.toolbar.width() <= window.width()
    dialog = DiagnosticDialog(window)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    assert dialog.minimumSizeHint().width() <= 860
    assert dialog.width() < width and dialog.height() < height
    assert window.grab().save(str(tmp_path/f'synthetic-p1-{theme}-{width}.png'))
    shots = os.environ.get('RAWTIMS_P1_SHOTS')
    if shots:
        folder = Path(shots)
        folder.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(folder/f'synthetic-p1-{theme}-{width}.png'))
        assert dialog.grab().save(str(folder/f'synthetic-diagnostic-{theme}-{width}.png'))
    dialog.close()
