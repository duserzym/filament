"""The default Review wall; edits remain on MainWindow's shared Analysis path."""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from rawtims_gui.plot_palette import plot_palette
from rawtims_gui.plots import PlotWall, format_number, plot_stats
from rawtims_gui.studio.naming import natural_sort_key
from rawtims_gui.studio.review_toolbar import ReviewToolbar
from rawtims_gui.studio.splitters import StudioSplitter, _SplitterHandle
from rawtims_gui.studio.theme import active_theme
from rawtims_gui.studio.widgets import ElidedLabel, SegmentedBar, SegmentButton, set_style


@dataclass(frozen=True)
class PanelSize:
    """Logical pixels; splitter users may resize between these limits."""
    default: QtCore.QSize
    minimum: QtCore.QSize
    maximum: QtCore.QSize


WORK_SIZE = PanelSize(QtCore.QSize(940, 680), QtCore.QSize(420, 180), QtCore.QSize(16777215, 16777215))
CARD_SIZE = PanelSize(QtCore.QSize(440, 280), QtCore.QSize(420, 260), QtCore.QSize(16777215, 900))
INSPECTOR_SIZE = PanelSize(QtCore.QSize(300, 680), QtCore.QSize(240, 180), QtCore.QSize(430, 16777215))


class ReviewToolButton(QtWidgets.QToolButton):
    """Remember the activation source; keyboard paths never animate."""
    mouse_activated = False

    def mousePressEvent(self, event):
        self.mouse_activated = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.mouse_activated = False

    def keyPressEvent(self, event):
        self.mouse_activated = False
        super().keyPressEvent(event)


class PanelHeader(QtWidgets.QWidget):
    doubleClicked = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        event.accept()


def tool(text, tip, slot):
    button = ReviewToolButton()
    button.setText(text)
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    button.clicked.connect(slot)
    return button


class ResetHandle(_SplitterHandle):
    def mouseDoubleClickEvent(self, event):
        self.splitter().reset_sizes()
        event.accept()


class ReviewSplitter(StudioSplitter):
    def __init__(self, settings):
        super().__init__(QtCore.Qt.Orientation.Horizontal)
        self.settings = settings
        self.key = 'review/wall/splitter_v2'
        self.defaults = [940, 300]
        self.transient = False
        self.setHandleWidth(10)
        self.setChildrenCollapsible(False)
        self.splitterMoved.connect(self.save)

    def createHandle(self):
        return ResetHandle(self.orientation(), self)

    def save(self, *_args):
        if not self.transient:
            self.settings.setValue(self.key, self.saveState())

    def reset_sizes(self):
        self.reset_panels()
        self.setSizes(self.defaults)
        self.save()

    def restore(self):
        state = self.settings.value(self.key)
        if not isinstance(state, QtCore.QByteArray) or not self.restoreState(state):
            self.setSizes(self.defaults)


class BlockCell(ReviewToolButton):
    """Focusable segments; all mouse edits commit only on release."""

    def keyPressEvent(self, event):
        cells = list(self.parentWidget().cells.values())
        direction = {QtCore.Qt.Key.Key_Left: -1, QtCore.Qt.Key.Key_Right: 1,
                     QtCore.Qt.Key.Key_Home: -10000, QtCore.Qt.Key.Key_End: 10000}.get(event.key())
        if direction is not None:
            cells[max(0, min(len(cells)-1, cells.index(self)+direction))].setFocus()
            event.accept()
        elif event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.click()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.setFocus()
            self.parentWidget().begin(self.block, event.modifiers())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.parentWidget().drag_to(self.mapToParent(event.position().toPoint()))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            strip = self.parentWidget()
            strip.drag_to(self.mapToParent(event.position().toPoint()))
            strip.finish()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class SharedBlocks(QtWidgets.QWidget):
    """An 18 px cycle-axis strip, shared or per card and synced by Analysis.

    Segment edges use the linked ViewBox transform, including while zoomed.
    A drag only updates a border; it never recalculates or replots the data.
    """
    blockClicked = QtCore.Signal(int)
    rangeRequested = QtCore.Signal(list)

    def __init__(self, plot=None):
        super().__init__()
        self.plot = plot
        self.setObjectName('SharedBlocks')
        self.setFixedHeight(18)
        self.setMinimumWidth(0)
        self.cells = {}
        self.analysis = None
        self.anchor = None
        self.drag = None
        if plot is not None:
            plot.view_box.sigRangeChanged.connect(self.align_axis)
            plot.view_box.sigResized.connect(self.align_axis)

    def align_axis(self, *_args):
        if self.analysis is None or self.plot is None:
            return
        vb = self.plot.view_box
        offset = self.mapFromGlobal(self.plot.viewport().mapToGlobal(QtCore.QPoint())).x()
        left = offset + vb.mapViewToScene(QtCore.QPointF(vb.viewRange()[0][0], 0)).x()
        right = left + vb.width()
        for block, cell in self.cells.items():
            cycles = self.analysis.run.cycle[self.analysis.run.block == block]
            x0 = offset + vb.mapViewToScene(QtCore.QPointF(float(cycles.min())-.5, 0)).x()
            x1 = offset + vb.mapViewToScene(QtCore.QPointF(float(cycles.max())+.5, 0)).x()
            start, end = round(max(left, x0)), round(min(right, x1))
            cell.setGeometry(start, 0, max(0, end-start), 18)
            cell.setVisible(end > start)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.align_axis()

    def begin(self, block, modifiers):
        start = self.anchor if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier and self.anchor in self.cells else block
        self.drag = (start, block)
        self.anchor = start
        self._highlight()

    def drag_to(self, point):
        if self.drag is None:
            return
        visible = [c for c in self.cells.values() if not c.isHidden()]
        if visible:
            cell = min(visible, key=lambda c: abs(c.geometry().center().x()-point.x()))
            self.drag = (self.drag[0], cell.block)
            self._highlight()

    def _highlight(self):
        for block, cell in self.cells.items():
            active = self.drag is not None and min(self.drag) <= block <= max(self.drag)
            cell.setDown(active)

    def finish(self):
        if self.drag is None:
            return
        start, end = self.drag
        self.drag = None
        self._highlight()
        blocks = [b for b in self.cells if min(start, end) <= b <= max(start, end)]
        if len(blocks) == 1:
            self.blockClicked.emit(blocks[0])
        else:
            self.rangeRequested.emit(blocks)

    def refresh(self, analysis):
        self.analysis = analysis
        blocks = list(map(int, analysis.blocks)) if analysis is not None else []
        if list(self.cells) != blocks:
            for cell in self.cells.values():
                cell.hide()
                cell.deleteLater()
            self.cells = {}
            self.anchor = None
            for block in blocks:
                cell = BlockCell(self)
                cell.block = block
                cell.setCheckable(True)
                cell.setText(str(block))
                cell.setMinimumSize(0, 0)
                cell.clicked.connect(lambda _checked=False, b=block: self.blockClicked.emit(b))
                self.cells[block] = cell
        if analysis is None:
            return
        columns = [analysis.index(k) for k in analysis.group_keys]
        effective = analysis.effective[:, columns].all(axis=1) if columns else np.ones(analysis.n_cycles, dtype=bool)
        theme = active_theme()
        palette = plot_palette(theme)
        for block, included in zip(blocks, analysis.block_included):
            rows = analysis.run.block == block
            used, total = int(effective[rows].sum()), int(rows.sum())
            cell = self.cells[block]
            cell.setChecked(bool(included))
            cell.setAccessibleName(f'Block {block}: {used}/{total} cycles used')
            cycles = ', '.join(str(int(c)) for c in analysis.run.cycle[rows])
            cell.setToolTip(f'Block {block} · cycles {cycles}\n{used}/{total} used across shared ratios. '
                            'Click / Space: toggle · Shift-click / drag: block range · ← →: move')
            set_style(cell, f'QToolButton {{ padding: 0; min-width: 0; min-height: 0; font-size: 9px; '
                      f'color: {palette.axisText if included else palette.excluded}; '
                      f'background: {palette.background if included else palette.blockOff}; '
                      f'border: 1px solid {palette.axisLine}; border-radius: 2px; }} '
                      f'QToolButton:pressed, QToolButton:focus {{ background: {theme.accent_soft}; border-color: {theme.accent}; }}')
        self.align_axis()


class RatioCard(QtWidgets.QFrame):
    panel_size = CARD_SIZE

    def __init__(self, plot, maximise):
        super().__init__(plot.parentWidget())
        self.plot = plot
        self.setMinimumWidth(self.panel_size.minimum.width())
        self.setMaximumHeight(self.panel_size.maximum.height())
        self.setObjectName('RatioCard')
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        self.header = PanelHeader()
        self.header.setFixedHeight(38)
        plot.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Expanding)
        header = QtWidgets.QGridLayout(self.header)
        header.setContentsMargins(4, 0, 0, 0)
        header.setSpacing(4)
        self.name = ElidedLabel(plot.key)
        self.name.setMinimumWidth(0)
        self.name.setToolTip(plot.key)
        self.name.setStyleSheet('font-size: 11px; font-weight: 600;')
        header.addWidget(self.name, 0, 0)
        self.summary = ElidedLabel('')
        self.summary.setMinimumWidth(0)
        self.summary.setStyleSheet('font-size: 11px;')
        self.summary.setStyleSheet('font-size: 10px;')
        header.addWidget(self.summary, 1, 0, 1, 5)
        header.setColumnStretch(0, 1)
        self.log_button = tool('ln', f'Log scale for {plot.key}', self.toggle_log)
        self.log_button.setCheckable(True)
        self.fit_button = tool('↕', f'Fit y axis for {plot.key}', plot.fit_y)
        header.addWidget(self.log_button, 0, 1)
        header.addWidget(self.fit_button, 0, 2)
        self.max_button = tool('⤢', f'Maximise / restore {plot.key}', lambda: maximise(self))
        self.max_button.setFixedSize(22, 22)
        self.max_button.setStyleSheet('QToolButton { padding: 0; font-size: 16px; }')
        for button in (self.log_button, self.fit_button, self.max_button):
            button.setFixedSize(20, 20)
            button.setStyleSheet('QToolButton { padding: 0; min-width: 0; min-height: 0; font-size: 11px; }')
        header.addWidget(self.max_button, 0, 3)
        self.header.doubleClicked.connect(lambda: maximise(self))
        layout.addWidget(self.header)
        layout.addWidget(plot, 1)
        self.blocks = SharedBlocks(plot)
        layout.addWidget(self.blocks)
        self.blocks.blockClicked.connect(lambda block: self.window().toggle_block(block))
        self.blocks.rangeRequested.connect(lambda blocks: self.window().toggle_block_range(blocks))
        from rawtims_gui.studio.plot_tools import PlotTools
        self.tools = PlotTools(plot)
        self.tools.modeChanged.connect(self.set_navigation_mode)
        self.tools.resetRequested.connect(plot.reset_view)
        self.tools.moved.connect(lambda point: self.window().settings.setValue(f'plots/tools/{plot.key}', point))
        settings = getattr(self.window(), 'settings', None)
        if settings:
            point = settings.value(f'plots/tools/{plot.key}')
            if isinstance(point, QtCore.QPoint):
                self.tools.move(point)
                self.tools._has_place = True
        self.tools.place()
        self.tools.hide()
        plot.installEventFilter(self)

    def set_stacked(self, stacked):
        """Reposition the existing header widgets without rebuilding the plot."""
        header = self.header.layout()
        for widget in (self.name, self.summary, self.log_button, self.fit_button, self.max_button):
            header.removeWidget(widget)
        self.header.setFixedHeight(24 if stacked else 38)
        header.addWidget(self.name, 0, 0)
        header.addWidget(self.summary, 0 if stacked else 1, 1 if stacked else 0, 1, 1 if stacked else 5)
        for column, button in enumerate((self.log_button, self.fit_button, self.max_button), 2 if stacked else 1):
            header.addWidget(button, 0, column)
        header.setColumnStretch(0, 1)
        header.setColumnStretch(1, 3 if stacked else 0)
        self.blocks.setVisible(not stacked)

    def eventFilter(self, watched, event):
        if watched is self.plot:
            if event.type() == QtCore.QEvent.Type.Enter:
                self.tools.show()
                self.tools.place()
            elif event.type() == QtCore.QEvent.Type.Leave and not self.tools.underMouse():
                self.tools.hide()
        return super().eventFilter(watched, event)

    def set_navigation_mode(self, mode):
        import pyqtgraph as pg
        self.plot.view_box.navigation_mode = mode
        self.plot.view_box.setMouseMode(pg.ViewBox.RectMode if mode == 'zoom' else pg.ViewBox.PanMode)
        self.tools.buttons[mode].setChecked(True)

    def toggle_log(self, checked):
        self.plot.log_override = checked
        self.plot.update_state(self.window().plot_wall.state)
        self.refresh(self.window().plot_wall.state)

    def refresh(self, state):
        stats = plot_stats(state.analysis, state.mapping, self.plot.key)
        name = f'ln({self.plot.key})' if self.plot._log else self.plot.key
        mean, se = format_number(stats.mean), format_number(stats.se_pct, 3)
        self.name.setText(name)
        mswd = format_number(state.analysis.block_weighted_mean(self.plot.key, convention="standard").mswd, 3)
        self.summary.setText(f'{mean} ± {se}% SE · n {stats.n_used}/{stats.n_total} · MSWD {mswd}')
        self.summary.setToolTip(f'{name}: mean {mean}, {se}% SE (1σ), n {stats.n_used}/{stats.n_total}; MSWD of block means {mswd}')
        self.log_button.setVisible(self.plot._ratio_scale)
        self.log_button.setChecked(self.plot._log)
        self.blocks.refresh(state.analysis)
        if not getattr(self.plot, 'external_title', False):
            self.plot.external_title = True
            self.plot.getPlotItem().setTitle(None)
        palette = plot_palette()
        set_style(self, f'#RatioCard {{ background: {palette.background}; border: 1px solid {palette.axisLine}; border-radius: 8px; }}')


class ReviewPlotWall(PlotWall):
    panel_size = WORK_SIZE
    layoutChanged = QtCore.Signal(str)
    layout_key = 'review/wall/plot_layout_v1'

    def __init__(self, parent=None):
        self.cards = []
        self.plot_layout = 'stacked'
        self.shared_blocks = None
        self.maximised = None
        self.maximise_card = self._toggle_card
        super().__init__(parent)
        self.grid.setSpacing(6)
        self.shared_blocks = SharedBlocks()
        self.shared_blocks.setParent(self)
        self.shared_blocks.hide()
        self.shared_blocks.blockClicked.connect(lambda block: self.window().toggle_block(block))
        self.shared_blocks.rangeRequested.connect(lambda blocks: self.window().toggle_block_range(blocks))

    def set_plot_layout(self, layout):
        if layout not in ('stacked', 'auto-fit'):
            layout = 'stacked'
        self.plot_layout = layout
        self.settings.setValue(self.layout_key, layout)
        for card in self.cards:
            card.set_stacked(layout == 'stacked')
        self._relayout()
        self.layoutChanged.emit(layout)

    def _bind_shared_blocks(self, plot):
        strip = self.shared_blocks
        if strip.plot is not None:
            strip.plot.view_box.sigRangeChanged.disconnect(strip.align_axis)
            strip.plot.view_box.sigResized.disconnect(strip.align_axis)
        strip.plot = plot
        if plot is not None:
            plot.view_box.sigRangeChanged.connect(strip.align_axis)
            plot.view_box.sigResized.connect(strip.align_axis)

    def set_plots(self, keys, state):
        self._bind_shared_blocks(None)
        if self.maximised and hasattr(self.window(), 'review_shell'):
            self.window().review_shell.restore_all()
        self.maximised = None
        for card in self.cards:
            self.grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        self.cards = []
        super().set_plots(keys, state)
        for plot in self.plots:
            self.grid.removeWidget(plot)
            plot.setMinimumHeight(152)
            card = RatioCard(plot, self.toggle_card)
            self.cards.append(card)
            card.refresh(state)
            card.set_stacked(self.plot_layout == 'stacked')
        self.tools.hide()
        self.shared_blocks.refresh(state.analysis if state else None)
        self._relayout()
        for card in self.cards:
            point = self.window().settings.value(f'plots/tools/{card.plot.key}')
            if isinstance(point, QtCore.QPoint):
                card.tools._has_place = True
                card.tools.move(point)
                card.tools.place()

    def set_navigation_mode(self, mode):
        super().set_navigation_mode(mode)
        for card in self.cards:
            card.set_navigation_mode(mode)

    def begin_resize_preview(self):
        for card in self.cards:
            card.tools.finish()
            card.tools.hide()
        super().begin_resize_preview()

    def refresh(self, state, *, rebuild=False):
        super().refresh(state, rebuild=rebuild)
        for card in self.cards:
            card.refresh(state)
        self.shared_blocks.refresh(state.analysis)

    def apply_theme(self):
        super().apply_theme()
        if self.state:
            for card in self.cards:
                card.refresh(self.state)
            self.shared_blocks.refresh(self.state.analysis)

    def column_count(self):
        if self.plot_layout == 'stacked':
            return 1
        return max(1, min(4, len(self.cards) or 1,
                         (self.viewport().width() - self.grid.contentsMargins().right() + self.grid.spacing()) //
                         (CARD_SIZE.minimum.width() + self.grid.spacing())))

    def toggle_card(self, card):
        self.maximise_card(card)

    def _toggle_card(self, card):
        self.maximised = None if self.maximised is card else card
        self._relayout()

    def _relayout(self):
        if self.shared_blocks is None:
            return
        stacked = self.plot_layout == 'stacked'
        self.setViewportMargins(0, 0, 0, 18 if stacked and self.cards else 0)
        self.shared_blocks.setVisible(stacked and bool(self.cards))
        self.shared_blocks.setGeometry(self.viewport().x(), self.viewport().geometry().bottom() + 1,
                                       self.viewport().width(), 18)
        if not self.cards:
            self.window().block_header = None
            return
        columns = self.column_count() if self.maximised is None else 1
        for card in self.cards:
            self.grid.removeWidget(card)
        for row in range(self.grid.rowCount() + 1):
            self.grid.setRowStretch(row, 0)
        visible = [self.maximised] if self.maximised else self.cards
        for card in self.cards:
            card.setVisible(card in visible)
        rows = max(1, (len(visible) + columns - 1) // columns)
        spacing = self.grid.spacing()
        available = self.viewport().height()
        minimum_height = 182 if stacked else CARD_SIZE.minimum.height()
        bottom = visible[-1].plot
        if self.shared_blocks.plot is not bottom:
            self._bind_shared_blocks(bottom)
        self.window().block_header = self.shared_blocks if stacked else visible[0].blocks
        for card in self.cards:
            card.setMinimumWidth(160 if stacked else CARD_SIZE.minimum.width())
            card.plot.getPlotItem().showAxis('bottom', not stacked or card is visible[-1])
        # When scrolling is needed, fill an integral number of complete rows.
        visible_rows = min(rows, max(1, (available + spacing) // (minimum_height + spacing)))
        height = max(minimum_height, min(CARD_SIZE.maximum.height(),
                     (available - spacing * (visible_rows - 1)) // visible_rows))
        for index, card in enumerate(visible):
            card.setFixedHeight(height)
            self.grid.addWidget(card, index // columns, index % columns)
        for column in range(max(self.grid.columnCount(), columns)):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self.grid.setRowStretch(rows, 1)
        self.shared_blocks.align_axis()


def reduced_motion(widget):
    """Suite overrides, Qt accessibility, and the platform style preference."""
    disabled = any(os.environ.get(name, '').lower() not in ('', '0', 'false') for name in
                   ('UPBRPY_REDUCE_MOTION', 'UPBLAB_REDUCE_MOTION'))
    hints = QtWidgets.QApplication.styleHints()
    if hasattr(hints, 'accessibility'):
        disabled = disabled or hints.accessibility().motionPreference().name == 'ReducedMotion'
    return disabled or not widget.style().styleHint(QtWidgets.QStyle.StyleHint.SH_Widget_Animate, None, widget)


class CollapsiblePanel(QtWidgets.QWidget):
    panel_size = INSPECTOR_SIZE

    def __init__(self, content, settings):
        super().__init__()
        self.content, self.settings = content, settings
        self.default = self.panel_size.default.width()
        self.maximum = self.panel_size.maximum.width()
        self.key = 'review/wall/inspector_collapsed_v2'
        self.width_key = 'review/wall/inspector_width_v2'
        self.expanded_width = settings.value(self.width_key, self.default, type=int)
        self.collapsed = settings.value(self.key, False, type=bool)
        self.setMinimumWidth(30)
        self.setMaximumWidth(30 if self.collapsed else self.maximum)
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.button = tool('‹' if self.collapsed else 'Inspector ›', 'Collapse / expand inspector (⌘/Ctrl+Shift+I)', self.toggle)
        self.button.setFixedHeight(22)
        self.button.setStyleSheet('QToolButton { padding: 0 4px; min-width: 0; min-height: 20px; max-height: 20px; }')
        box.addWidget(self.button)
        box.addWidget(content, 1)
        self.tabs = QtWidgets.QWidget()
        tabs = QtWidgets.QVBoxLayout(self.tabs)
        tabs.setContentsMargins(0, 0, 0, 0)
        for index, name in enumerate(('Stats', 'Rules', 'Corrections', 'Export')):
            button = tool(name[0], name, lambda _checked=False, i=index: self.window().review_shell.show_inspector_tab(i))
            button.setFixedWidth(30)
            button.setStyleSheet('QToolButton { padding: 6px 0; }')
            tabs.addWidget(button)
        tabs.addStretch()
        box.addWidget(self.tabs, 1)
        self.animation = QtCore.QVariantAnimation(self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._resize)
        self.animation.finished.connect(self._finished)
        self.content.setVisible(not self.collapsed)
        self.tabs.setVisible(self.collapsed)

    def _resize(self, width):
        splitter = self.parentWidget()
        if not isinstance(splitter, ReviewSplitter):
            return
        sizes = splitter.sizes()
        difference = int(width) - sizes[1]
        splitter.setSizes([sizes[0] - difference, int(width)])

    def _finished(self):
        self.content.setVisible(not self.collapsed)
        self.tabs.setVisible(self.collapsed)
        self.setMinimumWidth(30 if self.collapsed else self.panel_size.minimum.width())
        self.setMaximumWidth(30 if self.collapsed else self.maximum)
        if isinstance(self.parentWidget(), ReviewSplitter):
            self.parentWidget().save()

    def toggle(self):
        self.set_collapsed(not self.collapsed, animate=bool(getattr(self.sender(), 'mouse_activated', False)))

    def set_collapsed(self, collapsed, *, animate=True, persist=True):
        self.animation.stop()
        persist = persist and not getattr(getattr(self.window(), "review_shell", None), "focused", False)
        if collapsed and not self.collapsed:
            self.expanded_width = self.width()
            if persist:
                self.settings.setValue(self.width_key, self.expanded_width)
        self.collapsed = collapsed
        if persist:
            self.settings.setValue(self.key, collapsed)
        self.button.setText('‹' if collapsed else 'Inspector ›')
        self.content.setVisible(not collapsed)
        self.tabs.setVisible(False)
        self.setMinimumWidth(30)
        self.setMaximumWidth(self.maximum)
        target = 30 if collapsed else min(self.maximum, max(self.panel_size.minimum.width(), self.expanded_width))
        if animate and not reduced_motion(self):
            self.animation.setStartValue(self.width())
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._resize(target)
            self._finished()


class ReviewShell(QtWidgets.QWidget):
    panel_size = WORK_SIZE

    def __init__(self, window, old_rail, centre, inspector):
        super().__init__()
        self.owner = window
        self.outer_maximised = False
        self._restore_stack = []
        self.setObjectName('ReviewShell')
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.toolbar = ReviewToolbar()
        self.toolbar.setFixedHeight(34)
        self.rail = old_rail
        self.rail_button = tool('☰', 'Fractions and workflow', self.toggle_rail)
        self.rail_button.setFixedWidth(26)
        self.toolbar.add_control(self.rail_button, 'Workflow', -10)
        self.picker = QtWidgets.QComboBox()
        self.picker.setMinimumWidth(140)
        self.picker.setMinimumContentsLength(22)
        self.picker.setMaximumWidth(260)
        self.picker.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.picker.activated.connect(self.select_run)
        self.toolbar.add_control(self.picker, 'Run / fraction', -10)
        window.mode_bar.setFixedWidth(242)
        window.mode_bar.layout().setContentsMargins(1, 0, 1, 0)
        for button in window.mode_buttons.values():
            button.setMinimumWidth(65)
        self.toolbar.add_control(window.mode_bar, 'View', 3)
        self.toolbar.add_control(window.function_button, 'Functions', 1)
        self.options_button = tool('Options', 'Scale, fit and shared selection', lambda: None)
        self.options_menu = QtWidgets.QMenu(self.options_button)
        self.options_menu.addActions([window.log_action, window.fit_all_action, window.synch_action])
        self.options_menu.addSeparator()
        navigation = self.options_menu.addMenu('Mouse mode for all plots')
        group = QtGui.QActionGroup(navigation)
        for mode, label in (('review', 'Review / select cycles'), ('pan', 'Pan'), ('zoom', 'Box zoom')):
            action = navigation.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == 'review')
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, m=mode: window.plot_wall.set_navigation_mode(m))
        self.options_menu.addSeparator()
        self.options_menu.addAction('Why shared selection?', window.show_shared_selection_help)
        self.options_button.setMenu(self.options_menu)
        self.options_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.add_control(self.options_button, 'Options', 2)
        self.toolbar.add_control(window.undo_button, 'Undo', 4)
        self.toolbar.add_control(window.redo_button, 'Redo', 5)
        self.focus_action = window._action('Focus on the plot', self.set_focus, 'Ctrl+Shift+F', checkable=True)
        self.focus_button = QtWidgets.QToolButton()
        self.focus_button.setDefaultAction(self.focus_action)
        self.focus_action.setIconText('Focus')
        self.focus_button.setText('Focus')
        self.toolbar.add_control(self.focus_button, 'Focus', -5)
        self.info_button = tool('Run info', 'Run information and warnings', lambda: window.show_correction_page('Run info'))
        self.toolbar.add_control(self.info_button, 'Run information', 6)
        self.more_menu = self.toolbar.menu
        self.more_menu.addSeparator()
        self.more_menu.addActions([window.open_files_action, window.open_folder_action, window.save_action])
        self.more_menu.addSeparator()
        self.more_menu.addAction(window.reset_analysis_action)
        self.more_menu.addAction('Maximise / restore plots', self.toggle_outer)
        self.toolbar.always_overflow = True
        toolbar_row = QtWidgets.QHBoxLayout()
        toolbar_row.setContentsMargins(0, 0, 0, 0)
        toolbar_row.setSpacing(6)
        toolbar_row.addWidget(self.toolbar, 1)
        toolbar_row.addWidget(window.update_controls)
        box.addLayout(toolbar_row)
        # Old controls remain as classic fixtures; all wall commands above share
        # their actions, so shortcuts, enablement and history have one source.
        window.wall_header.hide()
        self.state = ElidedLabel('No fraction selected')
        self.state.setFixedHeight(18)
        self.state.setMinimumWidth(0)
        window.legend.hide()
        window.review_page.layout().setSpacing(2)
        centre.layout().setSpacing(2)
        window.warning_chip.hide()
        self.focused = False
        self._focus_saved = None
        self.splitter = ReviewSplitter(window.settings)
        self.splitter.dragStarted.connect(window.plot_wall.begin_resize_preview)
        self.splitter.dragFinished.connect(window.plot_wall.finish_resize_preview)
        old_rail.setParent(self)
        old_rail.setVisible(window.settings.value('review/wall/rail_visible_v1', False, type=bool))
        inspector.layout().itemAt(0).widget().hide()
        inspector.layout().setContentsMargins(6, 0, 6, 6)
        inspector.layout().setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        inspector.setMinimumWidth(0)
        inspector.setMaximumWidth(16777215)
        centre.panel_size = WORK_SIZE
        centre.setMinimumWidth(WORK_SIZE.minimum.width())
        centre.setMaximumWidth(WORK_SIZE.maximum.width())
        centre.layout().setContentsMargins(4, 4, 4, 2)
        self.splitter.addWidget(centre)
        self.inspector = CollapsiblePanel(inspector, window.settings)
        self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.restore()
        self.splitter.reset_panels = self.reset_panels
        self.work_row = QtWidgets.QHBoxLayout()
        self.work_row.setContentsMargins(0, 0, 0, 0)
        self.work_row.setSpacing(2)
        self.rail_strip = tool('›', 'Unfold workflow and fractions', self.toggle_rail)
        self.rail_strip.setFixedWidth(22)
        self.rail_strip.setStyleSheet('QToolButton { padding: 0; min-width: 0; min-height: 0; }')
        self.rail_strip.hide()
        self.work_row.addWidget(self.rail_strip, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self.work_row.addWidget(old_rail)
        self.work_row.addWidget(self.splitter, 1)
        box.addLayout(self.work_row, 1)
        self.layout_bar = SegmentedBar()
        self.layout_bar.setObjectName('StageSegmentBar')
        self.layout_bar.setAccessibleName('Plot layout')
        row = QtWidgets.QHBoxLayout(self.layout_bar)
        row.setContentsMargins(1, 1, 1, 1)
        row.setSpacing(1)
        buttons = QtWidgets.QButtonGroup(self.layout_bar)
        self.layout_buttons = {}
        self.layout_actions = {}
        actions = QtGui.QActionGroup(self)
        actions.setExclusive(True)
        window.view_menu.addSeparator()
        for mode, label, tip in (
            ('stacked', 'Stacked', 'Full-width plots with one shared cycle axis and block strip'),
            ('auto-fit', 'Auto-fit', 'Fit plot columns to the available width with a block strip per card'),
        ):
            button = SegmentButton()
            button.setText(label)
            button.setToolTip(tip)
            button.setAccessibleName(f'{label} plot layout')
            button.setCheckable(True)
            button.setProperty('modeToggle', True)
            buttons.addButton(button)
            row.addWidget(button)
            self.layout_bar.add_segment(button)
            button.clicked.connect(lambda _checked=False, m=mode: window.plot_wall.set_plot_layout(m))
            action = window.view_menu.addAction(f'{label} plots')
            action.setCheckable(True)
            action.setToolTip(tip)
            actions.addAction(action)
            action.triggered.connect(lambda _checked=False, m=mode: window.plot_wall.set_plot_layout(m))
            self.layout_buttons[mode] = button
            self.layout_actions[mode] = action
        window.plot_wall.layoutChanged.connect(self.sync_plot_layout)
        window.review_page.layout().insertWidget(window.review_page.layout().indexOf(window.view_stack), self.layout_bar,
                                     0, QtCore.Qt.AlignmentFlag.AlignLeft)
        window.plot_wall.settings = window.settings
        window.plot_wall.set_plot_layout(window.settings.value(window.plot_wall.layout_key, 'stacked', type=str))
        self.centre = centre
        window.plot_wall.maximise_card = self.toggle_card
        self.max_action = window._action('Maximise Work Panel', self.maximise_focused, 'Ctrl+Shift+Return')
        self.inspector_action = window._action('Toggle Inspector', lambda: self.inspector.set_collapsed(
            not self.inspector.collapsed, animate=False), 'Ctrl+Shift+I')
        for action in (self.focus_action, self.inspector_action, self.max_action):
            window.view_menu.addAction(action)
        if window.settings.value('review/wall/focus_v1', False, type=bool):
            QtCore.QTimer.singleShot(0, self, lambda: self.set_focus(True))

    def sync_plot_layout(self, mode):
        self.layout_buttons[mode].setChecked(True)
        self.layout_actions[mode].setChecked(True)
        self.layout_bar.select_checked()

    def reset_panels(self):
        self.set_focus(False)
        self.rail.hide()
        self.restore_all()
        self.inspector.expanded_width = self.inspector.default
        self.inspector.set_collapsed(False, animate=False)

    def fit_width(self):
        self.inspector.maximum = min(INSPECTOR_SIZE.maximum.width(), int(self.owner.width() * .30))
        if not self.inspector.collapsed and self.inspector.animation.state() != QtCore.QAbstractAnimation.State.Running:
            self.inspector.setMinimumWidth(INSPECTOR_SIZE.minimum.width())
            self.inspector.setMaximumWidth(self.inspector.maximum)

    def fit_controls(self):
        self.toolbar.reflow()

    def toggle_rail(self):
        self.rail.setVisible(self.rail.isHidden())
        self.rail_strip.setVisible(self.focused and self.rail.isHidden())
        if not self.focused:
            self.owner.settings.setValue('review/wall/rail_visible_v1', not self.rail.isHidden())

    def set_focus(self, enabled):
        """Studio 780498c / 17c970a: mark folded before changing geometry.

        Keep the saved user widths separate from transient Focus geometry.
        Unfolding either handle affects only its own panel.
        """
        enabled = bool(enabled)
        if enabled == self.focused:
            return
        self.restore_all()
        self.focused = enabled
        self.focus_action.setChecked(enabled)
        if enabled:
            self._focus_saved = (self.splitter.sizes(), self.inspector.collapsed,
                                 self.inspector.expanded_width, not self.rail.isHidden())
            self.splitter.transient = True
            self.rail.hide()
            self.rail_strip.show()
            self.inspector.set_collapsed(True, animate=False, persist=False)
        else:
            sizes, collapsed, expanded, rail_visible = self._focus_saved
            self.rail.setVisible(rail_visible)
            self.rail_strip.hide()
            self.inspector.expanded_width = expanded
            self.inspector.set_collapsed(collapsed, animate=False, persist=False)
            self.splitter.setSizes(sizes)
            self.splitter.transient = False
        self.owner.settings.setValue('review/wall/focus_v1', enabled)

    def show_inspector_tab(self, index):
        self.owner.inspector_tabs.setCurrentIndex(index)
        self.inspector.set_collapsed(False, animate=False)

    def select_run(self, index):
        data = self.picker.itemData(index)
        if data:
            self.restore_all()
            self.owner.select_run(*data)

    def refresh(self):
        window = self.owner
        self.picker.blockSignals(True)
        self.picker.clear()
        for fraction in sorted(window.workspace.fractions, key=lambda f: natural_sort_key(f.fraction_id)):
            for element, analysis in (('Pb', fraction.pb), ('U', fraction.u)):
                if analysis is not None:
                    self.picker.addItem(f'{fraction.fraction_id} · {element}', (fraction, element))
                    self.picker.setItemData(self.picker.count() - 1, analysis.run.raw.name, QtCore.Qt.ItemDataRole.ToolTipRole)
                    if window.current == (fraction, element):
                        self.picker.setCurrentIndex(self.picker.count() - 1)
        self.picker.blockSignals(False)
        if window.current:
            state, reasons = window.workspace.fraction_status(window.current[0])
            used, total = window.cycles_used()
            self.state.setText(f'● {state.capitalize()} · {used}/{total} cycles used · History {window.analysis.history_count}'
                               + (' · redo available' if window.analysis.can_redo else '')
                               + '     ■ used   □ excluded   SE · 1σ · 2σ     ⌘-click / ⇧-drag select · Delete reject · B block')
            self.state.setToolTip(('\n'.join(reasons) or 'Fraction ready for export') + '\n' + window.legend.toolTip())
            set_style(self.state, f'font-size: 10px; color: {active_theme().muted};')
        else:
            self.state.setText('No fraction selected')
        locked = window.analysis is not None and not window.synch_action.isEnabled()
        set_style(window.synch_button,
            f'QToolButton {{ background: transparent; border: none; color: {active_theme().muted}; font-weight: normal; }}'
            if locked else '')
        warnings = window.analysis.run.warnings if window.analysis is not None else []
        self.info_button.setText(f'⚠ {len(warnings)}' if warnings else 'Run info')
        self.info_button.setToolTip('\n'.join(warnings) if warnings else 'Run information and method')
        self.toolbar.entries = [(w, menu, content, -4 if warnings else 6) if w is self.info_button
                                else (w, menu, content, priority)
                                for w, menu, content, priority in self.toolbar.entries]
        window.warning_chip.hide()
        self.fit_controls()

    def _snapshot(self):
        self._restore_stack.append((self.outer_maximised, self.owner.plot_wall.maximised, self.splitter.sizes(),
                                    (not self.rail.isHidden(), not self.rail_strip.isHidden())))

    def _apply(self, outer, card, sizes=None, rail_visibility=None):
        self.splitter.transient = outer or self.focused
        self.outer_maximised = outer
        self.inspector.setVisible(not outer)
        if outer:
            self.rail.hide()
            self.rail_strip.hide()
        elif rail_visibility is not None:
            self.rail.setVisible(rail_visibility[0])
            self.rail_strip.setVisible(rail_visibility[1])
        self.owner.plot_wall.maximised = card
        if sizes and not outer:
            self.splitter.setSizes(sizes)
        self.owner.plot_wall._relayout()

    def toggle_card(self, card):
        if self.owner.plot_wall.maximised is card:
            self.restore()
        else:
            self._snapshot()
            self._apply(True, card)

    def toggle_outer(self):
        if self.outer_maximised and self.owner.plot_wall.maximised is None:
            self.restore()
        else:
            self._snapshot()
            self._apply(True, None)

    def maximise_focused(self):
        widget = QtWidgets.QApplication.focusWidget()
        # Focus in another panel must not prevent a hovered plot from maximising.
        for candidate in (widget, QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())):
            for card in self.owner.plot_wall.cards:
                if candidate is card or (candidate is not None and card.isAncestorOf(candidate)):
                    self.toggle_card(card)
                    return
            header = self.owner.wall_header
            if candidate is header or (candidate is not None and header.isAncestorOf(candidate)):
                self.toggle_outer()
                return
        self.toggle_outer()

    def restore(self):
        if not self._restore_stack:
            return False
        outer, card, sizes, rail_visibility = self._restore_stack.pop()
        self._apply(outer, card, sizes, rail_visibility)
        return True

    def restore_all(self):
        while self.restore():
            pass
