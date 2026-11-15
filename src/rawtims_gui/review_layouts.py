"""The default Review wall; edits remain on MainWindow's shared Analysis path."""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.branding import DISPLAY_NAME
from rawtims_gui.plots import PlotWall, format_number, plot_stats
from rawtims_gui.studio.theme import active_theme
from rawtims_gui.studio.widgets import ElidedLabel


@dataclass(frozen=True)
class PanelSize:
    """Logical pixels; splitter users may resize between these limits."""
    default: QtCore.QSize
    minimum: QtCore.QSize
    maximum: QtCore.QSize


WORK_SIZE = PanelSize(QtCore.QSize(940, 680), QtCore.QSize(420, 180), QtCore.QSize(16777215, 16777215))
CARD_SIZE = PanelSize(QtCore.QSize(440, 200), QtCore.QSize(160, 182), QtCore.QSize(16777215, 900))
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


class ResetHandle(QtWidgets.QSplitterHandle):
    def mouseDoubleClickEvent(self, event):
        self.splitter().reset_sizes()
        event.accept()


class ReviewSplitter(QtWidgets.QSplitter):
    def __init__(self, settings):
        super().__init__(QtCore.Qt.Orientation.Horizontal)
        self.settings = settings
        self.key = 'review/wall/splitter_v2'
        self.defaults = [940, 300]
        self.transient = False
        self.setHandleWidth(8)
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
    """Tab/Space toggle; arrow keys move through the shared block sequence."""
    def keyPressEvent(self, event):
        direction = {QtCore.Qt.Key.Key_Left: -1, QtCore.Qt.Key.Key_Right: 1,
                     QtCore.Qt.Key.Key_Home: -10000, QtCore.Qt.Key.Key_End: 10000}.get(event.key())
        if direction is not None:
            cells = list(self.parentWidget().findChildren(BlockCell))
            index = max(0, min(len(cells) - 1, cells.index(self) + direction))
            cells[index].setFocus()
            self.window().block_header.ensureWidgetVisible(cells[index])
            event.accept()
        elif event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.click()
            event.accept()
        else:
            super().keyPressEvent(event)


class SharedBlocks(QtWidgets.QScrollArea):
    """One group mask, compact enough for twenty blocks at laptop widths."""
    panel_size = PanelSize(QtCore.QSize(940, 26), QtCore.QSize(0, 26), QtCore.QSize(16777215, 42))
    blockClicked = QtCore.Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName('SharedBlocks')
        self.setMinimumWidth(self.panel_size.minimum.width())
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setFixedHeight(26)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QtWidgets.QWidget()
        self.row = QtWidgets.QHBoxLayout(self.body)
        self.row.setContentsMargins(0, 0, 4, 0)
        self.row.setSpacing(2)
        self.setWidget(self.body)
        self.cells = {}
        self.axis_aligned = False

    def align_axis(self, enabled):
        self.axis_aligned = enabled
        required = sum(max(c.minimumWidth(), c.minimumSizeHint().width()) for c in self.cells.values())
        required += max(0, len(self.cells) - 1) * self.row.spacing()
        aligned = enabled and self.viewport().width() >= required + 82
        self.row.setContentsMargins(70 if aligned else 0, 0, 12 if aligned else 4, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.align_axis(self.axis_aligned)

    def refresh(self, analysis):
        blocks = list(map(int, analysis.blocks)) if analysis is not None else []
        compact = len(blocks) > 12
        self.setFixedHeight(42 if compact else 26)
        if list(self.cells) != blocks:
            while self.row.count():
                self.row.takeAt(0).widget().deleteLater()
            self.cells = {}
            for block in blocks:
                cell = BlockCell()
                cell.setCheckable(True)
                cell.setMinimumWidth(28 if compact else 54)
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
            self.row.setStretch(blocks.index(block), total)
            cell = self.cells[block]
            cell.setText(f'{block}\n{used}/{total}' if compact else f'{block} · {used}/{total}')
            cell.setChecked(bool(included))
            cell.setAccessibleName(f'Block {block}: {used}/{total} cycles used')
            cycles = ', '.join(str(int(c)) for c in analysis.run.cycle[rows])
            cell.setToolTip(f'Block {block} · cycles {cycles}\n{used}/{total} used across shared ratios. '
                            'Click or Space/Return: toggle (undoable). ← →: move between blocks.')
            cell.setStyleSheet(f'QToolButton {{ padding: 3px 1px; font-size: {10 if compact else 11}px; '
                              f'color: {theme.text if included else theme.danger}; '
                              f'background: {theme.surface if included else "#18" + theme.danger.lstrip("#")}; '
                              f'border: 1px solid {theme.axis_line if included else theme.danger}; border-radius: 5px; }} '
                              f'QToolButton:pressed, QToolButton:focus {{ background: {theme.accent_soft}; border-color: {theme.accent}; }}')
        self.align_axis(self.axis_aligned)


class RatioCard(QtWidgets.QFrame):
    panel_size = CARD_SIZE

    def __init__(self, plot, maximise):
        super().__init__()
        self.plot = plot
        self.setMinimumWidth(self.panel_size.minimum.width())
        self.setMaximumHeight(self.panel_size.maximum.height())
        self.setObjectName('RatioCard')
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)
        self.header = PanelHeader()
        self.header.setFixedHeight(22)
        plot.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Expanding)
        header = QtWidgets.QHBoxLayout(self.header)
        header.setContentsMargins(4, 0, 0, 0)
        header.setSpacing(4)
        self.name = QtWidgets.QLabel(plot.key)
        self.name.setStyleSheet('font-size: 11px; font-weight: 600;')
        header.addWidget(self.name)
        self.summary = ElidedLabel('')
        self.summary.setMinimumWidth(0)
        self.summary.setStyleSheet('font-size: 11px;')
        header.addWidget(self.summary, 1)
        self.max_button = tool('⤢', f'Maximise / restore {plot.key}', lambda: maximise(self))
        self.max_button.setFixedSize(22, 22)
        self.max_button.setStyleSheet('QToolButton { padding: 0; font-size: 16px; }')
        header.addWidget(self.max_button)
        self.header.doubleClicked.connect(lambda: maximise(self))
        layout.addWidget(self.header)
        layout.addWidget(plot, 1)

    def refresh(self, state):
        stats = plot_stats(state.analysis, state.mapping, self.plot.key)
        name = f'ln({self.plot.key})' if state.log_ratio and self.plot._ratio_scale else self.plot.key
        mean, se = format_number(stats.mean), format_number(stats.se_pct, 3)
        self.name.setText(name)
        self.summary.setText(f'{mean} ± {se}% SE · n {stats.n_used}/{stats.n_total}')
        self.summary.setToolTip(f'{name}: mean {mean}, {se}% SE (1σ), n {stats.n_used}/{stats.n_total}')
        self.plot.getPlotItem().setTitle(None)
        theme = active_theme()
        self.setStyleSheet(f'#RatioCard {{ background: {theme.plot_background}; border: 1px solid {theme.axis_line}; border-radius: 8px; }}')


class ReviewPlotWall(PlotWall):
    panel_size = WORK_SIZE

    def __init__(self, parent=None):
        self.cards = []
        self.maximised = None
        self.maximise_card = self._toggle_card
        super().__init__(parent)

    def set_plots(self, keys, state):
        if self.maximised and hasattr(self.window(), 'review_shell'):
            self.window().review_shell.restore_all()
        self.maximised = None
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.cards = []
        super().set_plots(keys, state)
        for plot in self.plots:
            self.grid.removeWidget(plot)
            plot.setMinimumHeight(154)
            card = RatioCard(plot, self.toggle_card)
            self.cards.append(card)
            card.refresh(state)
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
        width = self.window().width()
        return 3 if width >= 1440 else 2 if width >= 1100 else 1

    def toggle_card(self, card):
        self.maximise_card(card)

    def _toggle_card(self, card):
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
        rows = max(1, (len(visible) + columns - 1) // columns)
        height = max(CARD_SIZE.minimum.height(), min(CARD_SIZE.maximum.height(),
                     (self.viewport().height() - 8 * (rows - 1)) // rows))
        for index, card in enumerate(visible):
            card.setFixedHeight(height)
            self.grid.addWidget(card, index // columns, index % columns)
        for column in range(3):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)
        self.grid.setRowStretch(rows, 1)
        if hasattr(self.window(), "block_header"):
            # In a single column the shared cells follow the cycle axis. With
            # multiple columns the single group row uses the whole wall width.
            self.window().block_header.align_axis(columns == 1)


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

    def set_collapsed(self, collapsed, *, animate=True):
        self.animation.stop()
        if collapsed and not self.collapsed:
            self.expanded_width = self.width()
            self.settings.setValue(self.width_key, self.expanded_width)
        self.collapsed = collapsed
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
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel(f'{DISPLAY_NAME}  /  Review'))
        open_button = tool('Open…', 'Open run files', window.choose_files)
        open_button.setStyleSheet("QToolButton { padding: 4px 10px; }")
        top.addWidget(open_button)
        self.picker = QtWidgets.QComboBox()
        self.picker.setStyleSheet("QComboBox { padding: 3px 10px; }")
        self.picker.setMinimumWidth(120)
        self.picker.setMaximumWidth(400)
        self.picker.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.picker.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.picker.activated.connect(self.select_run)
        top.addWidget(self.picker, 1)
        self.state = ElidedLabel('No fraction selected')
        self.state.setMinimumWidth(180)
        top.addWidget(self.state, 1)
        box.addLayout(top)
        self.splitter = ReviewSplitter(window.settings)
        old_rail.setParent(self)
        old_rail.hide()
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
        box.addWidget(self.splitter, 1)
        self.centre = centre
        window.plot_wall.maximise_card = self.toggle_card
        window.plot_control_bar.installEventFilter(self)
        self.max_action = window._action('Maximise Work Panel', self.maximise_focused, 'Ctrl+Shift+Return')
        self.inspector_action = window._action('Toggle Inspector', lambda: self.inspector.set_collapsed(
            not self.inspector.collapsed, animate=False), 'Ctrl+Shift+I')
        for action in (self.inspector_action, self.max_action):
            window.view_menu.addAction(action)

    def reset_panels(self):
        self.restore_all()
        self.inspector.expanded_width = self.inspector.default
        self.inspector.set_collapsed(False, animate=False)

    def fit_width(self):
        self.inspector.maximum = min(INSPECTOR_SIZE.maximum.width(), int(self.owner.width() * .30))
        if not self.inspector.collapsed and self.inspector.animation.state() != QtCore.QAbstractAnimation.State.Running:
            self.inspector.setMinimumWidth(INSPECTOR_SIZE.minimum.width())
            self.inspector.setMaximumWidth(self.inspector.maximum)

    def fit_controls(self):
        window = self.owner
        compact = window.plot_control_bar.width() < 560
        window.log_button.setVisible(not compact and window.plot_kind == 'ratios')
        window.fit_all_button.setVisible(not compact)
        window.redo_button.setVisible(not compact)

    def eventFilter(self, watched, event):
        if watched is self.owner.plot_control_bar and event.type() == QtCore.QEvent.Type.Resize:
            self.fit_controls()
        return super().eventFilter(watched, event)

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
            self.state.setText(f'● {state.capitalize()}   ·   {used}/{total} cycles used')
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

    def _snapshot(self):
        self._restore_stack.append((self.outer_maximised, self.owner.plot_wall.maximised, self.splitter.sizes()))

    def _apply(self, outer, card, sizes=None):
        self.splitter.transient = outer
        self.outer_maximised = outer
        self.inspector.setVisible(not outer)
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
        outer, card, sizes = self._restore_stack.pop()
        self._apply(outer, card, sizes)
        return True

    def restore_all(self):
        while self.restore():
            pass
