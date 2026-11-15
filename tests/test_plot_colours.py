"""Tripoli palette, shared decorations, marker fill and colour-vision audit."""
from pathlib import Path
import re
import runpy
import subprocess

import numpy as np
import pyqtgraph as pg
import pytest
from PySide6 import QtCore, QtWidgets
from reader_fixtures import B998
from test_review_window import app, window  # noqa: F401, fixtures for both layouts

from rawtims_gui.main import LEGEND, LEGEND_TIP
from rawtims_gui.plot_palette import PALETTES, plot_palette
from rawtims_gui.plots import plot_stats
from rawtims_gui.studio.theme import theme_color


audit = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/check_plot_colours.py'))['audit']

@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_tokens_complete_and_valid(theme):
    required = ('band2sigma', 'band1sigma', 'bandSE', 'mean', 'meanFrozen', 'included',
                'excluded', 'selection', 'blockSeparator', 'blockOff', 'blockSelecting', 'hoverGuide')
    assert all(theme_color(getattr(PALETTES[theme], key)).isValid() for key in required)


def test_plot_sources_have_no_colour_literals():
    root = Path(__file__).resolve().parents[1]
    paths = [str(root / 'src/rawtims_gui' / name) for name in ('plots.py', 'review_layouts.py')]
    # A grep guard covers hex, CSS rgb(a), QColor channel triples and named colours.
    result = subprocess.run(['rg', '-n', r'#[0-9a-fA-F]{3,8}\b|rgba?\(|QColor\(\s*\d|["\x27](red|blue|black|white|pink|yellow|green|grey|gray)["\x27]', *paths],
                            capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    for path in paths:
        assert 'plot_palette(' in Path(path).read_text()


def test_colour_blind_contrast_and_fill_cue():
    result = audit()
    for theme in result.values():
        for vision in theme.values():
            assert vision['included_vs_excluded'] >= 1.8
            assert vision['included_vs_background'] >= 14
            assert vision['excluded_vs_background'] >= 3
    # The modest dark-mode state contrast is why hollow/filled is mandatory.
    assert result['dark']['deuteranopia']['included_vs_excluded'] < 3


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_plot_semantics_on_both_layouts(window, theme):
    window.set_theme(theme)
    window.open_paths([str(B998)], synchronous=True)
    a = window.analysis
    rejected = np.flatnonzero(np.isin(a.run.cycle, [22, 23, 24])).tolist()
    window.request_toggle('206/204 D', rejected)
    off_rows = np.flatnonzero(a.run.block == 4)
    window.request_block_toggle('206/204 D', int(off_rows[0]))
    palette = plot_palette()
    for p in window.plot_wall.plots:
        for row in rejected + off_rows.tolist():
            assert p.points.data['symbol'][row] == 's'
            assert p.points.data['brush'][row].style() == QtCore.Qt.BrushStyle.NoBrush
            assert p.points.data['pen'][row].color() == theme_color(palette.excluded)
        assert p.points.data['symbol'][0] == 's'
        assert p.points.data['brush'][0].color() == theme_color(palette.included)
        assert p.points.data['brush'][0].style() == QtCore.Qt.BrushStyle.SolidPattern
        assert p.pinned_points.opts['pen'].color() == theme_color(palette.excluded)
        regions = [d for d in p._decorations if isinstance(d, pg.LinearRegionItem)]
        off = [d for d in regions if d.orientation == 'vertical']
        assert len(off) == 1
        assert off[0].getRegion() == (float(a.run.cycle[off_rows].min()) - .5,
                                      float(a.run.cycle[off_rows].max()) + .5)
        assert off[0].brush.color() == theme_color(palette.blockOff)
        bands = [d for d in regions if d.orientation == 'horizontal']
        assert [d.brush.color() for d in bands] == [theme_color(c) for c in
            (palette.band2sigma, palette.band1sigma, palette.bandSE)]
        mean = next(d for d in p._decorations if isinstance(d, pg.InfiniteLine) and d.angle == 0)
        assert mean.pen.color() == theme_color(palette.mean) and mean.pen.widthF() == 1
        assert max(d.zValue() for d in bands) < off[0].zValue() < mean.zValue()
        stats = plot_stats(a, window.plot_wall.state.mapping, p.key)
        # Plot may be geometric (exp bounds) or arithmetic.
        expected = np.array([stats.center - stats.se, stats.center + stats.se])
        if stats.mode == 'geometric' and not p._log:
            expected = np.exp(expected)
        np.testing.assert_allclose(bands[-1].getRegion(), expected)
        separators = [d for d in p._decorations if isinstance(d, pg.InfiniteLine) and d.angle == 90]
        assert len(separators) == len(a.blocks) - 1
        assert all(d.pen.style() == QtCore.Qt.PenStyle.DashDotLine and
                   d.pen.color() == theme_color(palette.blockSeparator) for d in separators)
    if window.layout_name == 'wall':
        assert palette.blockOff in window.block_header.cells[4].styleSheet()
    assert '2SE' not in LEGEND + LEGEND_TIP
    assert re.search(r'\bSE\b', LEGEND)


def test_hover_guide_propagates_and_clears_on_both_layouts(window):
    window.open_paths([str(B998)], synchronous=True)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    p = window.plot_wall.plots[0]
    scene = p.view_box.mapViewToScene(p.point_of(30))
    p.scene().sigMouseMoved.emit(scene)
    for card in window.plot_wall.plots:
        assert card.hover_guide.isVisible()
        assert card.hover_guide.value() == a_cycle(window, 30)
        assert card.hover_guide.pen.color() == theme_color(plot_palette().hoverGuide)
    p.scene().sigMouseMoved.emit(QtCore.QPointF(-100, -100))
    assert all(not card.hover_guide.isVisible() for card in window.plot_wall.plots)


def a_cycle(window, row):
    return float(window.analysis.run.cycle[row])


def test_cycle_range_includes_missing_endpoints(window):
    from dataclasses import replace
    from rawtims.analysis import Analysis
    from rawtims_gui.plots import PlotState
    window.open_paths([str(B998)], synchronous=True)
    original = window.analysis.run
    values = original.values.copy()
    column = original.keys.index(window.plotted_keys()[0])
    values[[0, -1], column] = np.nan
    analysis = Analysis(replace(original, values=values))
    state = PlotState(analysis, window.plot_wall.state.mapping, False, frozenset())
    window.plot_wall.refresh(state, rebuild=True)
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    expected = [float(original.cycle.min()) - .5, float(original.cycle.max()) + .5]
    assert window.plot_wall.plots[0].rows_shown.size == original.n_cycles - 2
    assert all(np.allclose(p.view_box.viewRange()[0], expected) for p in window.plot_wall.plots)
