"""Opt-in Review layouts. All data edits still go through MainWindow/Analysis."""
from __future__ import annotations

import os

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.branding import DISPLAY_NAME
from rawtims_gui.plots import PlotWall, format_number, plot_stats
from rawtims_gui.studio.theme import active_theme
from rawtims_gui.studio.widgets import ElidedLabel


class ReviewToolButton(QtWidgets.QToolButton):
    """Remember input source so keyboard actions never animate."""
    mouse_activated = False

    def mousePressEvent(self, event):
        self.mouse_activated = True
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        self.mouse_activated = False
        super().keyPressEvent(event)


class PanelHeader(QtWidgets.QWidget):
    doubleClicked = QtCore.Signal()

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


class ResetHandle(QtWidgets.QSplitterHandle):
    def mouseDoubleClickEvent(self, event):
        self.splitter().reset_sizes()
        event.accept()


class ReviewSplitter(QtWidgets.QSplitter):
    def __init__(self, settings, layout):
        super().__init__(QtCore.Qt.Orientation.Horizontal)
        self.settings = settings
        self.key = f'review/{layout}/splitter_v1'
        self.defaults = []
        self.setHandleWidth(8)
        self.setChildrenCollapsible(False)
        self.splitterMoved.connect(self.save)

    def createHandle(self):
        return ResetHandle(self.orientation(), self)

    def save(self, *_args):
        self.settings.setValue(self.key, self.saveState())

    def reset_sizes(self):
        if hasattr(self, "reset_panels"):
            self.reset_panels()
        self.setSizes(self.defaults)
        self.save()

    def restore(self):
        state = self.settings.value(self.key)
        if not isinstance(state, QtCore.QByteArray) or not self.restoreState(state):
            self.setSizes(self.defaults)


class SharedBlocks(QtWidgets.QScrollArea):
    """One group selection, represented once above all ratio plots."""
    blockClicked = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName('SharedBlocks')
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setFixedHeight(45)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QtWidgets.QWidget()
        self.row = QtWidgets.QHBoxLayout(self.body)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(4)
        self.setWidget(self.body)
        self.cells = {}

    def refresh(self, analysis):
        blocks = list(map(int, analysis.blocks)) if analysis is not None else []
        if list(self.cells) != blocks:
            while self.row.count():
                self.row.takeAt(0).widget().deleteLater()
            self.cells = {}
            for block in blocks:
                cell = QtWidgets.QToolButton()
                cell.setCheckable(True)
                cell.setMinimumWidth(64)
                cell.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
                cell.clicked.connect(lambda _checked=False, b=block: self.blockClicked.emit(b))
                self.cells[block] = cell
                self.row.addWidget(cell)
        if analysis is None:
            return
        columns = [analysis.index(k) for k in analysis.group_keys]
        effective = analysis.effective[:, columns].all(axis=1) if columns else np.ones(analysis.n_cycles, dtype=bool)
        theme = active_theme()
        for block, included in zip(blocks, analysis.block_included):
            rows = analysis.run.block == block
            used, total = int(effective[rows].sum()), int(rows.sum())
            cell = self.cells[block]
            cell.setText(f'{block} · {used}/{total}')
            cell.setChecked(bool(included))
            cell.setAccessibleName(f'Block {block}: {used}/{total} cycles used')
            cell.setToolTip(f'Block {block}: {used}/{total} cycles used across group ratios. Click to toggle the whole block (undoable).')
            cell.setStyleSheet(f'QToolButton {{ padding: 5px; color: {theme.text if included else theme.danger}; '
                              f'background: {theme.surface if included else "#18" + theme.danger.lstrip("#")}; border: 1px solid {theme.axis_line if included else theme.danger}; border-radius: 5px; }} '
                              'QToolButton:pressed { background: #c9d7df; }')


class RatioCard(QtWidgets.QFrame):
    def __init__(self, plot, strips, maximise):
        super().__init__()
        self.plot = plot
        self.strips = strips
        self.setMinimumWidth(0)
        self.setObjectName('RatioCard')
        layout = QtWidgets.QHBoxLayout(self) if strips else QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 4, 4)
        layout.setSpacing(2)
        self.header = PanelHeader()
        header = QtWidgets.QVBoxLayout(self.header) if strips else QtWidgets.QHBoxLayout(self.header)
        header.setContentsMargins(2, 0, 2, 0)
        self.summary = QtWidgets.QLabel('') if strips else ElidedLabel('')
        self.summary.setMinimumWidth(0)
        self.summary.setStyleSheet('font-size: 12px;' if strips else 'font-size: 11px;')
        header.addWidget(self.summary, 1)
        self.max_button = tool('⤢', f'Maximise / restore {plot.key}', lambda: maximise(self))
        self.max_button.setFixedSize(26, 26)
        self.max_button.setStyleSheet("QToolButton { padding: 0; font-size: 16px; }")
        header.addWidget(self.max_button)
        self.header.doubleClicked.connect(lambda: maximise(self))
        if strips:
            self.header.setFixedWidth(150)
        layout.addWidget(self.header)
        layout.addWidget(plot, 1)

    def refresh(self, state):
        stats = plot_stats(state.analysis, state.mapping, self.plot.key)
        name = f'ln({self.plot.key})' if state.log_ratio and self.plot._ratio_scale else self.plot.key
        mean, se = format_number(stats.mean), format_number(stats.se_pct, 3)
        if self.strips:
            text = f'{name}\n{mean}\n{se} % SE (1σ)\nn {stats.n_used}/{stats.n_total}'
        else:
            text = f'{name}   {mean} ± {se}% · n {stats.n_used}/{stats.n_total}'
        self.summary.setText(text)
        self.summary.setToolTip(f'{name}: mean {mean}, {se}% SE (1σ), n {stats.n_used}/{stats.n_total}')
        self.plot.getPlotItem().setTitle(None)
        theme = active_theme()
        self.setStyleSheet(f'#RatioCard {{ background: {theme.plot_background}; border: 1px solid {theme.axis_line}; border-radius: 8px; }}')


class VariantPlotWall(PlotWall):
    def __init__(self, layout, parent=None):
        self.layout_name = layout
        self.cards = []
        self.maximised = None
        super().__init__(parent)

    def set_plots(self, keys, state):
        self.maximised = None
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.cards = []
        # Parent implementation creates and connects the existing CyclePlots.
        super().set_plots(keys, state)
        for plot in self.plots:
            self.grid.removeWidget(plot)
            plot.setMinimumHeight(60)
            card = RatioCard(plot, self.layout_name == 'strips', self.toggle_card)
            self.cards.append(card)
            card.refresh(state)
        if self.layout_name == 'strips' and self.plots:
            for plot in self.plots[1:]:
                plot.setXLink(self.plots[0])
        self._relayout()

    def refresh(self, state, *, rebuild=False):
        super().refresh(state, rebuild=rebuild)
        for card in self.cards:
            card.refresh(state)

    def apply_theme(self):
        super().apply_theme()
        if self.state:
            for card in self.cards:
                card.refresh(self.state)

    def column_count(self):
        if self.layout_name == 'strips':
            return 1
        width = self.window().width()
        return 3 if width >= 1440 else 2 if width >= 1100 else 1

    def toggle_card(self, card):
        self.maximised = None if self.maximised is card else card
        self._relayout()

    def _relayout(self):
        if not self.cards:
            return
        columns = self.column_count() if self.maximised is None else 1
        for card in self.cards:
            self.grid.removeWidget(card)
        for row in range(self.grid.rowCount() + 1):
            self.grid.setRowStretch(row, 0)
        visible = [self.maximised] if self.maximised else self.cards
        for card in self.cards:
            card.setVisible(card in visible)
        if self.maximised:
            height = max(220, self.viewport().height() - 4)
        elif self.layout_name == 'strips':
            height = 140
        else:
            rows = max(1, (len(visible) + columns - 1) // columns)
            height = max(150, min(220, (self.viewport().height() - 8 * (rows - 1)) // rows))
        for index, card in enumerate(visible):
            card.setFixedHeight(height)
            card.plot.setFixedHeight(height - (8 if card.strips else 42))
            self.grid.addWidget(card, index // columns, index % columns)
        for column in range(3):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self.grid.setRowStretch((len(visible) + columns - 1) // columns, 1)


def reduced_motion(widget):
    """Respect suite overrides and the platform's Qt animation preference."""
    disabled = any(os.environ.get(name, '').lower() not in ('', '0', 'false') for name in
                   ('UPBRPY_REDUCE_MOTION', 'UPBLAB_REDUCE_MOTION'))
    hints = QtWidgets.QApplication.styleHints()
    accessibility = hints.accessibility()
    disabled = disabled or accessibility.motionPreference().name == 'ReducedMotion'
    return disabled or not widget.style().styleHint(QtWidgets.QStyle.StyleHint.SH_Widget_Animate, None, widget)


class CollapsiblePanel(QtWidgets.QWidget):
    def __init__(self, content, title, default, maximum, settings, key):
        super().__init__()
        self.content, self.default, self.maximum = content, default, maximum
        self.settings, self.key = settings, key
        self.collapsed = False
        self.setMinimumWidth(30)
        self.setMaximumWidth(maximum)
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self.button = tool(f'{title} ›', f'Collapse / expand {title}', self.toggle)
        box.addWidget(self.button)
        box.addWidget(content, 1)
        self.animation = QtCore.QVariantAnimation(self)
        self.animation.setDuration(180)
        self.animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._resize)
        self.animation.finished.connect(self._finished)
        self.title = title
        self.set_collapsed(settings.value(key, False, type=bool), animate=False)

    def _resize(self, width):
        splitter = self.parentWidget()
        if not isinstance(splitter, QtWidgets.QSplitter):
            return
        sizes = splitter.sizes()
        index = splitter.indexOf(self)
        difference = int(width) - sizes[index]
        sizes[index] = int(width)
        centre = 1 if splitter.count() == 3 else 0
        sizes[centre] -= difference
        splitter.setSizes(sizes)

    def _finished(self):
        self.content.setVisible(not self.collapsed)
        if hasattr(self, "tabs"):
            self.tabs.setVisible(self.collapsed)
        self.setMinimumWidth(30 if self.collapsed else self.default)
        self.setMaximumWidth(30 if self.collapsed else self.maximum)
        if isinstance(self.parentWidget(), ReviewSplitter):
            self.parentWidget().save()

    def toggle(self):
        self.set_collapsed(not self.collapsed, animate=bool(getattr(self.sender(), 'mouse_activated', False)))

    def set_collapsed(self, collapsed, *, animate=True):
        self.animation.stop()
        self.collapsed = collapsed
        self.settings.setValue(self.key, collapsed)
        self.button.setText('‹' if collapsed else f'{self.title} ›')
        self.content.setVisible(not collapsed)
        self.setMinimumWidth(30)
        self.setMaximumWidth(self.maximum)
        target = 30 if collapsed else self.default
        reduced = reduced_motion(self)
        if animate and not reduced:
            self.animation.setStartValue(self.width())
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._resize(target)
            self._finished()


class ReviewShell(QtWidgets.QWidget):
    def __init__(self, window, old_rail, centre, inspector):
        super().__init__()
        self.owner = window
        self.outer_maximised = False
        self.saved_sizes = []
        self.setObjectName('ReviewShell')
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel(f'{DISPLAY_NAME}  /  Review'))
        top.addWidget(tool('Open…', 'Open run files', window.choose_files))
        self.picker = QtWidgets.QComboBox()
        self.picker.setMinimumWidth(120)
        self.picker.setMaximumWidth(340)
        self.picker.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.picker.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.picker.activated.connect(self.select_run)
        top.addWidget(self.picker, 1)
        self.state = ElidedLabel('No fraction selected')
        self.state.setMinimumWidth(130)
        top.addWidget(self.state, 1)
        box.addLayout(top)
        self.splitter = ReviewSplitter(window.settings, window.layout_name)
        old_rail.setParent(self)
        old_rail.hide()
        if window.layout_name == 'strips':
            window.fraction_list.setParent(None)
            if not window.settings.contains('review/strips/rail_collapsed'):
                window.settings.setValue('review/strips/rail_collapsed', True)
            self.rail = CollapsiblePanel(window.fraction_list, 'Fractions', 220, 300,
                                         window.settings, 'review/strips/rail_collapsed')
            self.rail.setMinimumWidth(56)
            self.rail.button.clicked.disconnect()
            self.rail.button.clicked.connect(self.toggle_rail)
            self.rail.collapsed = window.settings.value('review/strips/rail_collapsed', True, type=bool)
            self.rail.content.show()
            self.rail.setMinimumWidth(56)
            self.rail.setMaximumWidth(56 if self.rail.collapsed else 300)
            self.rail.button.setText('☰' if self.rail.collapsed else 'Fractions ‹')
            window.fraction_list.set_compact(self.rail.collapsed)
            self.rail_motion = QtCore.QVariantAnimation(self)
            self.rail_motion.setDuration(180)
            self.rail_motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
            self.rail_motion.valueChanged.connect(self.rail._resize)
            self.rail_motion.finished.connect(self._finish_rail)
            self.rail.installEventFilter(self)
            self.splitter.addWidget(self.rail)
        inspector.layout().itemAt(0).widget().hide()
        inspector.layout().setContentsMargins(8, 8, 8, 8)
        inspector.layout().setSizeConstraint(QtWidgets.QLayout.SizeConstraint.SetNoConstraint)
        inspector.setMinimumWidth(0)
        inspector.setMaximumWidth(16777215)
        centre.setMinimumWidth(420)
        self.splitter.addWidget(centre)
        self.inspector = CollapsiblePanel(inspector, 'Inspector', 300 if window.layout_name == 'strips' else 320,
                                          480, window.settings, f'review/{window.layout_name}/inspector_collapsed')
        self.inspector.tabs = QtWidgets.QWidget()
        tabs = QtWidgets.QVBoxLayout(self.inspector.tabs)
        tabs.setContentsMargins(0, 0, 0, 0)
        for index, name in enumerate(('Stats', 'Rules', 'Corrections', 'Export')):
            button = tool(name[0], name, lambda _checked=False, i=index: self.show_inspector_tab(i))
            button.setFixedWidth(30)
            button.setStyleSheet("QToolButton { padding: 6px 0; }")
            tabs.addWidget(button)
        tabs.addStretch()
        self.inspector.layout().addWidget(self.inspector.tabs, 1)
        self.inspector.tabs.setVisible(self.inspector.collapsed)
        self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(self.splitter.indexOf(centre), 1)
        self.splitter.defaults = [56, 900, 300] if window.layout_name == 'strips' else [940, 320]
        self.splitter.restore()
        self.splitter.reset_panels = self.reset_panels
        box.addWidget(self.splitter, 1)
        self.centre = centre
        window.plot_control_bar.installEventFilter(self)
        self.max_action = window._action('Maximise Work Panel', self.maximise_focused, 'Ctrl+Shift+Return')

    def reset_panels(self):
        self.inspector.set_collapsed(False, animate=False)
        if hasattr(self, 'rail') and not self.rail.collapsed:
            self.toggle_rail()

    def _finish_rail(self):
        self.rail.setMaximumWidth(56 if self.rail.collapsed else 300)
        self.splitter.save()

    def toggle_rail(self, *, animate=None):
        if animate is None:
            animate = bool(getattr(self.sender(), 'mouse_activated', False))
        if self.sender() is self.rail.button and getattr(self, '_hover_open', False):
            self._hover_open = False  # clicking a hover-open rail pins it open
            return
        self.rail_motion.stop()
        self.rail.collapsed = not self.rail.collapsed
        compact = self.rail.collapsed
        self.owner.fraction_list.set_compact(compact)
        self.rail.button.setText('☰' if compact else 'Fractions ‹')
        self.rail.setMaximumWidth(300)
        self.owner.settings.setValue('review/strips/rail_collapsed', compact)
        target = 56 if compact else 220
        if animate and not reduced_motion(self.rail):
            self.rail_motion.setStartValue(self.rail.width())
            self.rail_motion.setEndValue(target)
            self.rail_motion.start()
        else:
            self.rail._resize(target)
            self._finish_rail()

    def fit_controls(self):
        window = self.owner
        compact = window.plot_control_bar.width() < 560
        window.log_button.setVisible(not compact and window.plot_kind == 'ratios')
        window.fit_all_button.setVisible(not compact)
        window.redo_button.setVisible(not compact)

    def eventFilter(self, watched, event):
        if watched is self.owner.plot_control_bar and event.type() == QtCore.QEvent.Type.Resize:
            self.fit_controls()
        if watched is getattr(self, 'rail', None) and event.type() == QtCore.QEvent.Type.Enter and self.rail.collapsed:
            self.toggle_rail(animate=True)
            self._hover_open = True
        elif watched is getattr(self, 'rail', None) and event.type() == QtCore.QEvent.Type.Leave and getattr(self, '_hover_open', False):
            self._hover_open = False
            if not self.rail.collapsed:
                self.toggle_rail(animate=True)
        return super().eventFilter(watched, event)

    def show_inspector_tab(self, index):
        self.owner.inspector_tabs.setCurrentIndex(index)
        self.inspector.set_collapsed(False, animate=False)

    def select_run(self, index):
        data = self.picker.itemData(index)
        if data:
            self.owner.select_run(*data)

    def refresh(self):
        window = self.owner
        self.picker.blockSignals(True)
        self.picker.clear()
        for fraction in window.workspace.fractions:
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
            self.state.setText(f'{state.capitalize()} · {used}/{total} cycles used')
            self.state.setToolTip('\n'.join(reasons) or 'Fraction ready for export')
            self.state.setStyleSheet(f'font-weight: 600; color: {active_theme().success if state == "ready" else active_theme().text};')
        else:
            self.state.setText('No fraction selected')
        locked = window.analysis is not None and not window.synch_action.isEnabled()
        window.synch_button.setStyleSheet(
            f'QToolButton {{ background: transparent; border: none; color: {active_theme().muted}; font-weight: normal; }}'
            if locked else '')
        window.block_header.refresh(window.analysis)
        self.fit_controls()

    def toggle_outer(self):
        self.outer_maximised = not self.outer_maximised
        if self.outer_maximised:
            self.saved_sizes = self.splitter.sizes()
        self.inspector.setVisible(not self.outer_maximised)
        if hasattr(self, 'rail'):
            self.rail.setVisible(not self.outer_maximised)
        if not self.outer_maximised:
            self.splitter.setSizes(self.saved_sizes)

    def maximise_focused(self):
        widget = QtWidgets.QApplication.focusWidget()
        if widget is None or not self.isAncestorOf(widget):
            widget = QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())
        for card in self.owner.plot_wall.cards:
            if widget is card or (widget is not None and card.isAncestorOf(widget)):
                self.owner.plot_wall.toggle_card(card)
                return
        self.toggle_outer()

    def restore(self):
        wall = self.owner.plot_wall
        if wall.maximised:
            wall.toggle_card(wall.maximised)
            return True
        if self.outer_maximised:
            self.toggle_outer()
            return True
        return False
