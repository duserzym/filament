"""The cycle plot wall: one plot per selected function against cycle number (SPEC F6, F8).

Each :class:`CyclePlot` shows one function of the current analysis:

* blocks shaded alternately, excluded blocks tinted red;
* the mean line and the 2SE, 1σ and 2σ bands of the included cycles; for a
  ratio in geometric mode the bands are exp(mean ln r ± k·s), as the
  statistics are taken on ln r;
* used cycles filled, excluded cycles hollow red, invalid cycles grey crosses;
* selected cycles ringed;
* cycles a previewed rule would reject marked with an amber square (the
  preview never changes the analysis; see :mod:`rawtims_gui.rules_panel`).

Mouse (sculpting, as Tripoli's): a click toggles the nearest cycle, a left drag
draws a box that toggles the cycles inside, ⌘/Ctrl-click adds or removes a
cycle from the selection and ⇧-drag selects a box. The right button opens a
menu with the block toggle. In the scrolling wall the wheel scrolls; ⌘/Ctrl +
wheel zooms the plot (UX rule 2, plots inside a scrolling page).

The plots never change the analysis themselves: they emit requests that the
window turns into :class:`rawtims.analysis.Analysis` operations, so every
edit is in the history.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
import math

import numpy as np

from PySide6 import QtCore, QtGui, QtWidgets

import pyqtgraph as pg

from rawtims import stats as _stats
from rawtims.analysis import Analysis
from rawtims.mapping import ElementMapping, MappedRatio, ratio_stats
from rawtims_gui.studio.theme import ThemeSpec, active_theme, theme_color
from rawtims_gui.studio.widgets import RoundedPlotWidget

PLOT_MIN_HEIGHT = 168
PLOT_MAX_HEIGHT = 340
COLUMN_MIN_WIDTH = 290
CLICK_RADIUS_PX = 10
SELECT_MODIFIERS = QtCore.Qt.KeyboardModifier.ControlModifier | QtCore.Qt.KeyboardModifier.MetaModifier
PREVIEW_COLORS = {"light": "#d97706", "dark": "#f0b429"}


def preview_color(theme: ThemeSpec | None = None) -> str:
    theme = theme or active_theme()
    return PREVIEW_COLORS.get(theme.name, PREVIEW_COLORS["light"])


def direct_mapping(mapping: ElementMapping | None, key: str) -> MappedRatio | None:
    """The contract ratio a function supplies directly (not inverted), if any."""
    if mapping is None:
        return None
    for mapped in mapping.ratios.values():
        if mapped.key == key and not mapped.inverted:
            return mapped
    return None


def plot_stats(analysis: Analysis, mapping: ElementMapping | None, key: str) -> _stats.Stats:
    """Statistics shown for a plotted function: ratio statistics for a mapped one, else the function's own."""
    mapped = direct_mapping(mapping, key)
    if mapped is not None:
        return ratio_stats(analysis, mapped)
    return analysis.stats(key)


def is_ratio_scale(analysis: Analysis, mapping: ElementMapping | None, key: str) -> bool:
    return analysis.function(key).is_ratio or direct_mapping(mapping, key) is not None


def format_number(value: float, digits: int = 7) -> str:
    if value is None or not math.isfinite(value):
        return "–"
    return f"{value:.{digits}g}"


class SculptViewBox(pg.ViewBox):
    """A view box whose left button sculpts (click, box) instead of panning."""

    sigPointClicked = QtCore.Signal(object, object)  # view QPointF, modifiers
    sigBoxDrawn = QtCore.Signal(object, object)  # view QRectF, modifiers
    sigContextRequested = QtCore.Signal(object, object)  # view QPointF, screen QPoint

    def mouseClickEvent(self, ev):  # noqa: N802 - pyqtgraph API
        if ev.button() == QtCore.Qt.MouseButton.LeftButton:
            ev.accept()
            self.sigPointClicked.emit(self.mapSceneToView(ev.scenePos()), ev.modifiers())
        elif ev.button() == QtCore.Qt.MouseButton.RightButton:
            ev.accept()
            self.sigContextRequested.emit(self.mapSceneToView(ev.scenePos()), ev.screenPos().toPoint())
        else:
            super().mouseClickEvent(ev)

    def mouseDragEvent(self, ev, axis=None):  # noqa: N802 - pyqtgraph API
        if ev.button() != QtCore.Qt.MouseButton.LeftButton or axis is not None:
            super().mouseDragEvent(ev, axis)
            return
        ev.accept()
        start = ev.buttonDownPos(ev.button())
        if ev.isFinish():
            self.rbScaleBox.hide()
            rect = self.childGroup.mapRectFromParent(QtCore.QRectF(pg.Point(start), pg.Point(ev.pos())))
            self.sigBoxDrawn.emit(rect.normalized(), ev.modifiers())
        else:
            self.updateScaleBox(start, ev.pos())


def _quiet(item: QtWidgets.QGraphicsItem) -> None:
    """Make a decoration ignore the mouse so clicks reach the view box."""
    item.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
    item.setAcceptHoverEvents(False)
    for line in getattr(item, "lines", ()):
        line.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)
        line.setAcceptHoverEvents(False)


def _alpha(color: str, alpha: int) -> QtGui.QColor:
    value = QtGui.QColor(theme_color(color))
    value.setAlpha(alpha)
    return value


@dataclass
class PlotState:
    """What a plot draws; the window builds it and the plot only reads it."""

    analysis: Analysis
    mapping: ElementMapping | None
    log_ratio: bool
    selection: frozenset[int]
    preview: Mapping[str, frozenset[int]] = field(default_factory=dict)  # function key -> rows a rule would reject
    fit_all: bool = False


class CyclePlot(RoundedPlotWidget):
    """One function against cycle number."""

    toggleRequested = QtCore.Signal(str, list)  # key, rows
    selectRequested = QtCore.Signal(str, list, bool)  # key, rows, additive
    blockToggleRequested = QtCore.Signal(str, int)  # key, row in the block
    focused = QtCore.Signal(str)

    def __init__(self, key: str, parent: QtWidgets.QWidget | None = None) -> None:
        self.view_box = SculptViewBox()
        super().__init__(parent, viewBox=self.view_box)
        self.key = key
        self.rows_shown = np.zeros(0, dtype=int)
        self.x_shown = np.zeros(0)
        self.y_shown = np.zeros(0)
        self.y_display = np.zeros(0)
        self._effective = np.zeros(0, dtype=bool)
        self._invalid = np.zeros(0, dtype=bool)
        self._values = np.zeros(0)
        self._fit_all = False
        self.selected_rows: frozenset[int] = frozenset()
        self.preview_rows: frozenset[int] = frozenset()
        self.title_text = ""
        self._log = False
        self._ratio_scale = False
        self._decorations: list[QtWidgets.QGraphicsItem] = []
        self._block = np.zeros(0, dtype=int)
        self.setMinimumHeight(PLOT_MIN_HEIGHT)
        self.setMinimumWidth(160)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        item = self.getPlotItem()
        item.titleLabel.setAttr("justify", "left")
        item.hideButtons()
        item.setMenuEnabled(False)
        item.getAxis("left").setWidth(62)
        self.points = pg.ScatterPlotItem(pxMode=True)
        self.points.setZValue(10)
        self.pinned_points = pg.ScatterPlotItem(pxMode=True, size=10, hoverable=True,
                                               tip=lambda x, y, data: data)
        self.pinned_points.setZValue(13)
        self.ring = pg.ScatterPlotItem(pxMode=True, symbol="o", size=13)
        self.ring.setZValue(11)
        self.preview_points = pg.ScatterPlotItem(pxMode=True, symbol="s", size=12)
        self.preview_points.setZValue(12)
        item.addItem(self.points)
        item.addItem(self.pinned_points, ignoreBounds=True)
        item.addItem(self.ring)
        item.addItem(self.preview_points)
        for scatter in (self.points, self.pinned_points):
            scatter.sigClicked.connect(lambda _item, _points, ev: self._on_click(
                self.view_box.mapSceneToView(ev.scenePos()), ev.modifiers()))
        _quiet(self.ring)
        _quiet(self.preview_points)
        self.view_box.sigPointClicked.connect(self._on_click)
        self.view_box.sigBoxDrawn.connect(self._on_box)
        self.view_box.sigContextRequested.connect(self._on_context)
        self.view_box.sigRangeChanged.connect(self._update_pins)
        self.apply_theme()

    # -------------------------------------------------------------- style
    def apply_theme(self, theme: ThemeSpec | None = None) -> None:
        theme = theme or active_theme()
        self.setBackground(theme.plot_background)
        item = self.getPlotItem()
        font = QtGui.QFont(self.font())
        font.setPointSizeF(8.5)
        for name in ("left", "bottom"):
            axis = item.getAxis(name)
            axis.setPen(pg.mkPen(theme.axis_line))
            axis.setTextPen(pg.mkPen(theme.axis_text))
            axis.setTickFont(font)
        item.showGrid(x=False, y=True, alpha=0.25)
        self.ring.setPen(pg.mkPen(theme.accent_strong, width=2))
        self.ring.setBrush(pg.mkBrush(None))
        self.preview_points.setPen(pg.mkPen(preview_color(theme), width=2))
        self.preview_points.setBrush(pg.mkBrush(None))
        self.pinned_points.setPen(pg.mkPen(theme.danger, width=1.6))
        self.pinned_points.setBrush(pg.mkBrush(None))

    # --------------------------------------------------------------- data
    def update_state(self, state: PlotState, *, rebuild: bool = False) -> None:
        """Redraw points, bands and title from the analysis (``rebuild`` also resets the axes)."""
        theme = active_theme()
        analysis = state.analysis
        column = analysis.index(self.key)
        run = analysis.run
        values = analysis.values[:, column]
        self._block = run.block
        self._ratio_scale = is_ratio_scale(analysis, state.mapping, self.key)
        log = state.log_ratio and self._ratio_scale
        rebuild = rebuild or log != self._log
        self._log = log
        if log:
            with np.errstate(divide="ignore", invalid="ignore"):
                y = np.where(values > 0, np.log(np.where(values > 0, values, 1.0)), np.nan)
        else:
            y = values.astype(float)
        shown = np.isfinite(y)
        effective = analysis.effective[:, column][shown]
        invalid = analysis.invalid[:, column][shown]
        # Preview, selection and theme redraws must preserve a user's wheel zoom.
        refit = (rebuild or state.fit_all != self._fit_all
                 or not np.array_equal(y[shown], self.y_shown)
                 or not np.array_equal(run.cycle[shown], self.x_shown)
                 or not np.array_equal(effective, self._effective)
                 or not np.array_equal(invalid, self._invalid))
        self.rows_shown = np.flatnonzero(shown)
        self.x_shown = run.cycle[shown].astype(float)
        self.y_shown = y[shown]
        self.y_display = self.y_shown.copy()
        self._values = values[shown].copy()
        self._effective = effective.copy()
        self._invalid = invalid.copy()
        self._fit_all = state.fit_all
        used_brush = pg.mkBrush(theme.accent)
        bad_pen = pg.mkPen(theme.danger, width=1.6)
        grey = pg.mkPen(theme.faint, width=1.4)
        no_pen = pg.mkPen(None)
        brushes, pens, symbols, sizes = [], [], [], []
        for used, bad in zip(effective, invalid):
            if bad:
                brushes.append(pg.mkBrush(None))
                pens.append(grey)
                symbols.append("x")
                sizes.append(7)
            elif used:
                brushes.append(used_brush)
                pens.append(no_pen)
                symbols.append("o")
                sizes.append(6)
            else:
                brushes.append(pg.mkBrush(None))
                pens.append(bad_pen)
                symbols.append("o")
                sizes.append(7)
        self.points.setData(x=self.x_shown, y=self.y_shown, brush=brushes, pen=pens, symbol=symbols, size=sizes)
        self._draw_decorations(state, theme, log)
        self.set_selection(state.selection)
        self.set_preview(state.preview.get(self.key, frozenset()))
        stats = plot_stats(analysis, state.mapping, self.key)
        name = analysis.function(self.key).name
        label = f"ln({name})" if log else name
        if math.isfinite(stats.mean):
            detail = f"{format_number(stats.mean)} ± {format_number(stats.se_pct, 3)} %"
        else:
            detail = "no usable cycles"
        self.title_text = f"{label}   {detail}"
        self.setToolTip(f"{label}: mean {detail} (1σ SE of the mean), {stats.n_used} of {stats.n_total} cycles used")
        self.getPlotItem().setTitle(
            f"<span style='color:{theme.text}; font-weight:600'>{_html(label)}</span>"
            f"<span style='color:{theme.muted}'>&nbsp;&nbsp;&nbsp;{_html(detail)}</span>",
            size="9pt",
        )
        # A long title must not widen the plot past its widget: let it clip at the right.
        title = self.getPlotItem().titleLabel
        title.setMinimumWidth(0)
        title.setMaximumWidth(max(10, self.width() - 20))
        if refit:
            self.reset_view()
        self._update_pins()

    def reset_view(self) -> None:
        item = self.getPlotItem()
        item.disableAutoRange()
        if self.x_shown.size:
            item.setXRange(float(self.x_shown.min()) - 0.5, float(self.x_shown.max()) + 0.5, padding=0.01)
        values = self.y_shown if self._fit_all else self.y_shown[self._effective]
        if values.size:
            lo, hi = float(values.min()), float(values.max())
            padding = (hi - lo) * 0.08 if hi > lo else max(abs(lo) * 0.08, 0.01)
            item.setYRange(lo - padding, hi + padding, padding=0)
        else:
            item.setYRange(0, 1, padding=0)

    def _update_pins(self, *_args) -> None:
        """Pin excluded outliers just inside the current edges, including while zooming."""
        self.y_display = self.y_shown.copy()
        lo, hi = self.view_box.viewRange()[1]
        outside = (~self._effective & ~self._invalid
                   & ((self.y_shown < lo) | (self.y_shown > hi)))
        if self._fit_all:
            outside[:] = False
        # Leave room for the entire triangle and its click target inside the view.
        inset = min((hi - lo) / 4, abs(self.view_box.viewPixelSize()[1]) * 7)
        self.y_display[outside] = np.clip(self.y_shown[outside], lo + inset, hi - inset)
        self.pinned_points.setData(
            x=self.x_shown[outside], y=self.y_display[outside],
            symbol=["t1" if value > hi else "t" for value in self.y_shown[outside]],
            data=[f"Cycle {cycle:g}: {value:.12g} (excluded)"
                  for cycle, value in zip(self.x_shown[outside], self._values[outside])],
        )
        self.set_selection(self.selected_rows)
        self.set_preview(self.preview_rows)

    def _draw_decorations(self, state: PlotState, theme: ThemeSpec, log: bool) -> None:
        item = self.getPlotItem()
        for old in self._decorations:
            item.removeItem(old)
        self._decorations = []
        analysis = state.analysis
        run = analysis.run
        transparent = pg.mkPen(None)
        for position, block in enumerate(analysis.blocks):
            rows = run.block == block
            lo, hi = float(run.cycle[rows].min()) - 0.5, float(run.cycle[rows].max()) + 0.5
            if not analysis.block_included[position]:
                brush = pg.mkBrush(_alpha(theme.danger, 30))
            elif position % 2:
                brush = pg.mkBrush(_alpha(theme.accent, 16))
            else:
                continue
            region = pg.LinearRegionItem((lo, hi), orientation="vertical", movable=False, brush=brush, pen=transparent)
            region.setZValue(-20)
            _quiet(region)
            item.addItem(region, ignoreBounds=True)
            self._decorations.append(region)
        stats = plot_stats(analysis, state.mapping, self.key)
        if not math.isfinite(stats.center):
            return
        center = stats.center
        if stats.mode == "geometric":
            def bound(k: float, s: float) -> tuple[float, float]:
                lo, hi = center - k * s, center + k * s
                return (lo, hi) if log else (math.exp(lo), math.exp(hi))
            mean = center if log else math.exp(center)
        else:
            def bound(k: float, s: float) -> tuple[float, float]:
                return center - k * s, center + k * s
            mean = center
        bands = [(2.0, stats.sd, 22), (1.0, stats.sd, 30), (2.0, stats.se, 60)]
        for z, (k, spread, alpha) in enumerate(bands):
            if not math.isfinite(spread):
                continue
            lo, hi = bound(k, spread)
            band = pg.LinearRegionItem((lo, hi), orientation="horizontal", movable=False,
                                       brush=pg.mkBrush(_alpha(theme.accent, alpha)), pen=transparent)
            band.setZValue(-10 + z)
            _quiet(band)
            item.addItem(band, ignoreBounds=True)
            self._decorations.append(band)
        line = pg.InfiniteLine(pos=mean, angle=0, movable=False, pen=pg.mkPen(theme.accent_strong, width=1.3))
        line.setZValue(-5)
        _quiet(line)
        item.addItem(line, ignoreBounds=True)
        self._decorations.append(line)

    def set_selection(self, rows: frozenset[int] | set[int]) -> None:
        self.selected_rows = frozenset(rows)
        if not self.selected_rows or not self.rows_shown.size:
            self.ring.setData(x=[], y=[])
            return
        mask = np.isin(self.rows_shown, list(self.selected_rows))
        self.ring.setData(x=self.x_shown[mask], y=self.y_display[mask])

    def set_preview(self, rows: frozenset[int] | set[int]) -> None:
        self.preview_rows = frozenset(rows)
        if not self.preview_rows or not self.rows_shown.size:
            self.preview_points.setData(x=[], y=[])
            return
        mask = np.isin(self.rows_shown, list(self.preview_rows))
        self.preview_points.setData(x=self.x_shown[mask], y=self.y_display[mask])

    # ------------------------------------------------------- interaction
    def row_near(self, view_point: QtCore.QPointF) -> int | None:
        """The cycle row whose point is nearest to a view position, within the click radius."""
        if not self.rows_shown.size:
            return None
        px, py = self.view_box.viewPixelSize()
        if not px or not py:
            return None
        dx = (self.x_shown - view_point.x()) / px
        dy = (self.y_display - view_point.y()) / py
        distance = np.hypot(dx, dy)
        best = int(np.argmin(distance))
        return int(self.rows_shown[best]) if distance[best] <= CLICK_RADIUS_PX else None

    def rows_in(self, rect: QtCore.QRectF) -> list[int]:
        inside = ((self.x_shown >= rect.left()) & (self.x_shown <= rect.right())
                  & (self.y_display >= rect.top()) & (self.y_display <= rect.bottom()))
        return [int(row) for row in self.rows_shown[inside]]

    def point_of(self, row: int) -> QtCore.QPointF:
        """The view position of a cycle's point (for tests and keyboard tools)."""
        index = int(np.flatnonzero(self.rows_shown == row)[0])
        return QtCore.QPointF(float(self.x_shown[index]), float(self.y_display[index]))

    def _on_click(self, view_point, modifiers) -> None:
        self.focused.emit(self.key)
        row = self.row_near(view_point)
        if modifiers & SELECT_MODIFIERS:
            if row is not None:
                self.selectRequested.emit(self.key, [row], True)
            return
        if row is not None:
            self.toggleRequested.emit(self.key, [row])

    def _on_box(self, rect, modifiers) -> None:
        self.focused.emit(self.key)
        rows = self.rows_in(rect)
        if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
            self.selectRequested.emit(self.key, rows, bool(modifiers & SELECT_MODIFIERS))
        elif rows:
            self.toggleRequested.emit(self.key, rows)

    def _on_context(self, view_point, screen_point) -> None:
        self.focused.emit(self.key)
        menu = QtWidgets.QMenu(self)
        row = self.row_near(view_point)
        if row is None and self.rows_shown.size:
            # Anywhere over a block: the nearest cycle by x names the block.
            row = int(self.rows_shown[int(np.argmin(np.abs(self.x_shown - view_point.x())))])
        if row is not None:
            block = int(self._block[row])
            action = menu.addAction(f"Toggle block {block}")
            action.triggered.connect(lambda: self.blockToggleRequested.emit(self.key, row))
        menu.addAction("Reset zoom").triggered.connect(self.reset_view)
        menu.popup(screen_point)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: N802 - Qt API
        if event.modifiers() & SELECT_MODIFIERS:
            super().wheelEvent(event)
        else:
            event.ignore()  # the wall scrolls


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class PlotWall(QtWidgets.QScrollArea):
    """Plots tiled in one or two columns (three on wide screens), scrolling vertically only."""

    toggleRequested = QtCore.Signal(str, list)
    selectRequested = QtCore.Signal(str, list, bool)
    blockToggleRequested = QtCore.Signal(str, int)
    focused = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlotWall")
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.container = QtWidgets.QWidget()
        self.container.setObjectName("PlotWallContainer")
        self.container.setAutoFillBackground(False)
        self.grid = QtWidgets.QGridLayout(self.container)
        self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setSpacing(8)
        self.setWidget(self.container)
        self.viewport().setAutoFillBackground(False)
        self.container.setStyleSheet("#PlotWallContainer { background: transparent; }")
        self.plots: list[CyclePlot] = []
        self.state: PlotState | None = None
        self._columns = 0

    def set_plots(self, keys: Sequence[str], state: PlotState | None) -> None:
        for plot in self.plots:
            self.grid.removeWidget(plot)
            plot.deleteLater()
        self.plots = []
        self.state = state
        if state is not None:
            for key in keys:
                plot = CyclePlot(key, self.container)
                plot.toggleRequested.connect(self.toggleRequested)
                plot.selectRequested.connect(self.selectRequested)
                plot.blockToggleRequested.connect(self.blockToggleRequested)
                plot.focused.connect(self.focused)
                plot.update_state(state, rebuild=True)
                self.plots.append(plot)
        self._columns = 0
        self._relayout()

    def refresh(self, state: PlotState, *, rebuild: bool = False) -> None:
        self.state = state
        for plot in self.plots:
            plot.update_state(state, rebuild=rebuild)

    def set_selection(self, rows: set[int] | frozenset[int]) -> None:
        if self.state is not None:
            self.state = replace(self.state, selection=frozenset(rows))
        for plot in self.plots:
            plot.set_selection(rows)

    def plot(self, key: str) -> CyclePlot:
        for plot in self.plots:
            if plot.key == key:
                return plot
        raise KeyError(key)

    def apply_theme(self) -> None:
        theme = active_theme()
        for plot in self.plots:
            plot.apply_theme(theme)
            if self.state is not None:
                plot.update_state(self.state)

    def column_count(self) -> int:
        width = self.viewport().width()
        if width >= 3 * COLUMN_MIN_WIDTH + 400:
            return 3
        return 2 if width >= 2 * COLUMN_MIN_WIDTH else 1

    def _relayout(self) -> None:
        columns = max(1, min(self.column_count(), len(self.plots) or 1))
        rows = max(1, math.ceil(len(self.plots) / columns))
        spacing = self.grid.spacing()
        height = int((self.viewport().height() - spacing * (rows - 1)) / rows)
        height = max(PLOT_MIN_HEIGHT, min(PLOT_MAX_HEIGHT, height))
        for plot in self.plots:
            plot.setFixedHeight(height)
        if columns != self._columns:
            self._columns = columns
            for plot in self.plots:
                self.grid.removeWidget(plot)
            for index, plot in enumerate(self.plots):
                self.grid.addWidget(plot, index // columns, index % columns)
            for column in range(3):
                self.grid.setColumnStretch(column, 1 if column < columns else 0)
            for row in range(self.grid.rowCount() + 1):
                self.grid.setRowStretch(row, 0)
            self.grid.setRowStretch(rows, 1)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._relayout()


__all__ = ["CyclePlot", "PlotState", "PlotWall", "SculptViewBox", "direct_mapping", "format_number", "is_ratio_scale", "plot_stats", "preview_color"]
