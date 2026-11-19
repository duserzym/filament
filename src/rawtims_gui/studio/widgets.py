# Copied from UPbRPy commit 0b16f36, path GUI/widgets.py, on 2026-11-14.
# Copied pieces, unchanged (source lines):
# - _RoundedCanvas, RoundedPlotWidget (43-54)
# - SegmentButton (159-170), _WorkflowRailDelegate (173-195), SegmentedBar (198-255)
# - ChipButton (504-634)
# - ElidedLabel, scrolling_page, elide_tab_titles (2671-2756)
# - FrozenColumnsView (3402-3483)
# DataFrameTableModel is not copied: it needs pandas, which this app does not
# use; rawtims_gui.cycle_table holds a NumPy model with the same role.
# Local changes:
# - imports: only what these classes need; the theme import points at the
#   vendored rawtims_gui.studio.theme instead of GUI.theme.
from __future__ import annotations

import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from rawtims_gui.studio.theme import active_theme, theme_color


class _RoundedCanvas:
    """Clip only the outer canvas corners; plot items retain normal rendering."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 11, 11)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))


class RoundedPlotWidget(_RoundedCanvas, pg.PlotWidget):
    """An opaque scientific plot with rounded outer corners."""


class SegmentButton(QtWidgets.QToolButton):
    """A segment whose full title stays in its tooltip when space is tight."""

    def minimumSizeHint(self):
        return QtCore.QSize(24, self.sizeHint().height())

    def paintEvent(self, event):
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = self.fontMetrics().elidedText(self.text(), QtCore.Qt.TextElideMode.ElideRight, max(8, self.width()-8))
        painter = QtWidgets.QStylePainter(self)
        painter.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ToolButton, option)


class _WorkflowRailDelegate(QtWidgets.QStyledItemDelegate):
    """Keep stage icons and number badges readable in the compact rail."""

    def paint(self, painter, option, index):
        if not self.parent().property("compactRail"):
            return super().paint(painter, option, index)
        theme = active_theme()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(1, 1, -1, -1)
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        if selected or option.state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(theme_color(theme.accent_soft if selected else theme.row_hover))
            painter.drawRoundedRect(QtCore.QRectF(rect), 9, 9)
        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        icon.paint(painter, QtCore.QRect(rect.left()+5, rect.center().y()-10, 20, 20))
        font = option.font
        font.setPixelSize(9)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(theme.accent if selected else theme.muted))
        painter.drawText(rect.adjusted(27, 0, -2, 0), QtCore.Qt.AlignmentFlag.AlignCenter, str(index.row()+1))
        painter.restore()


class SegmentedBar(QtWidgets.QFrame):
    """A stage bar with a short, painted selection transition."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pill = QtCore.QRectF()
        self._selected = None
        self._motion = QtCore.QVariantAnimation(self)
        self._motion.setDuration(180)
        self._motion.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._motion.valueChanged.connect(self._move_pill)

    def add_segment(self, button):
        button.setProperty("segmentChild", True)
        button.toggled.connect(lambda checked: self._select(button, checked))

    def select_checked(self):
        for button in self.findChildren(SegmentButton):
            if button.isChecked():
                self._select(button, True)
                break

    def _move_pill(self, rect):
        self._pill = rect
        self.update()

    def _select(self, button, checked):
        if not checked:
            return
        self._selected = button
        target = QtCore.QRectF(button.geometry())
        self._motion.stop()
        # Tabs and chips switch instantly, including keyboard and reduced motion.
        self._move_pill(target)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._motion.stop()
        QtCore.QTimer.singleShot(0, self, self._sync_pill)

    def _sync_pill(self):
        if self._selected is not None:
            self._move_pill(QtCore.QRectF(self._selected.geometry()))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._pill.isEmpty():
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(theme_color(active_theme().accent_soft))
        painter.drawRoundedRect(self._pill, 9, 9)



class ChipButton(QtWidgets.QPushButton):
    """Accessible periodic-table isotope tile with an explicit active marker."""

    doubleClicked = QtCore.Signal()

    def __init__(
        self,
        element: str,
        mass: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """Create a tile whose mass and element use separate typography."""
        super().__init__(parent)
        self.element = element
        self.mass = mass
        self.tile_color = QtGui.QColor("#6177a2")
        self.tile_active = True
        self.tile_selected = False
        self.dark_theme = True
        self.hovered = False
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{mass}{element} isotope channel")

    def set_visual_state(
        self,
        color: str,
        *,
        active: bool,
        selected: bool,
        dark_theme: bool,
    ) -> None:
        """Update the tile without relying on hue as the only state cue."""
        self.tile_color = QtGui.QColor(color)
        self.tile_active = active
        self.tile_selected = selected
        self.dark_theme = dark_theme
        self.update()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Paint a high-contrast miniature periodic-table cell."""
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)

        if self.tile_active:
            background = QtGui.QColor(self.tile_color)
            background = (
                background.lighter(112)
                if self.hovered
                else background
            )
        else:
            background = QtGui.QColor(
                "#242a34" if self.dark_theme else "#edf0f4"
            )

        border = QtGui.QColor(
            "#ffffff" if self.dark_theme else "#111827"
        )
        if not self.tile_selected:
            border = (
                self.tile_color.darker(145)
                if self.tile_active
                else QtGui.QColor(
                    "#667085" if self.dark_theme else "#98a2b3"
                )
            )
        pen = QtGui.QPen(border, 2.6 if self.tile_selected else 1.2)
        if not self.tile_active:
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 8, 8)

        luminance = (
            0.2126 * background.redF()
            + 0.7152 * background.greenF()
            + 0.0722 * background.blueF()
        )
        foreground = QtGui.QColor(
            "#111318" if luminance > 0.58 else "#ffffff"
        )
        if not self.tile_active:
            foreground = QtGui.QColor(
                "#98a2b3" if self.dark_theme else "#667085"
            )
        painter.setPen(foreground)

        mass_font = QtGui.QFont(self.font())
        mass_font.setPointSizeF(max(7.0, self.height() * 0.17))
        mass_font.setWeight(QtGui.QFont.Weight.DemiBold)
        painter.setFont(mass_font)
        painter.drawText(
            QtCore.QRectF(rect.left() + 5, rect.top() + 2, 22, 12),
            QtCore.Qt.AlignmentFlag.AlignLeft,
            self.mass,
        )

        element_font = QtGui.QFont(self.font())
        element_font.setPointSizeF(max(10.0, self.height() * 0.28))
        element_font.setWeight(QtGui.QFont.Weight.Bold)
        painter.setFont(element_font)
        painter.drawText(
            rect.adjusted(0, 8, 0, 0),
            QtCore.Qt.AlignmentFlag.AlignCenter,
            self.element,
        )

        marker_center = QtCore.QPointF(rect.right() - 6, rect.bottom() - 6)
        marker_pen = QtGui.QPen(foreground, 1.4)
        painter.setPen(marker_pen)
        painter.setBrush(
            foreground if self.tile_active else QtCore.Qt.BrushStyle.NoBrush
        )
        painter.drawEllipse(marker_center, 2.6, 2.6)
        painter.end()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # type: ignore[override]
        self.doubleClicked.emit()
        event.accept()


class ElidedLabel(QtWidgets.QLabel):
    """A one-line label that shortens its text with "…" instead of forcing
    its parent wider; the full text is the tooltip while it is shortened.

    Small screens (a 14-inch laptop) cannot give every header label its
    natural width, and a plain ``QLabel`` would either widen the window or
    be cut off mid-character.
    """

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None, *,
                 elide_mode=QtCore.Qt.TextElideMode.ElideRight) -> None:
        super().__init__(parent)
        self._elide_mode = elide_mode
        self._full_text = ""
        self._own_tooltip = ""
        self.setWordWrap(False)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        self._elide()

    def text(self) -> str:
        return self._full_text

    def setToolTip(self, tooltip: str) -> None:
        self._own_tooltip = tooltip
        super().setToolTip(tooltip)

    def sizeHint(self) -> QtCore.QSize:
        metrics = self.fontMetrics()
        margins = self.contentsMargins()
        return QtCore.QSize(
            metrics.horizontalAdvance(self._full_text) + margins.left() + margins.right() + 2,
            super().sizeHint().height(),
        )

    def minimumSizeHint(self) -> QtCore.QSize:
        metrics = self.fontMetrics()
        return QtCore.QSize(
            metrics.horizontalAdvance("…") + 4,
            super().minimumSizeHint().height(),
        )

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QtCore.QEvent.Type.FontChange, QtCore.QEvent.Type.StyleChange):
            self._elide()

    def _elide(self) -> None:
        margins = self.contentsMargins()
        width = max(0, self.width() - margins.left() - margins.right())
        shown = self.fontMetrics().elidedText(
            self._full_text, self._elide_mode, width
        )
        super().setText(shown)
        elided = shown != self._full_text
        super().setToolTip(self._full_text if elided and not self._own_tooltip else self._own_tooltip)


def scrolling_page(page: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
    """Put a tab page in a frameless scroll area: it fills the tab when
    there is room and scrolls instead of imposing its minimum size."""
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    scroll.setWidget(page)
    return scroll


def elide_tab_titles(tabs: QtWidgets.QTabWidget) -> None:
    """Shorten tab titles with "…" on narrow panels instead of showing the
    tab bar's scroll arrows; each title stays readable as its tooltip."""
    tabs.setElideMode(QtCore.Qt.TextElideMode.ElideRight)
    tabs.setUsesScrollButtons(False)
    for index in range(tabs.count()):
        if not tabs.tabToolTip(index):
            tabs.setTabToolTip(index, tabs.tabText(index))


class FrozenColumnsView(QtWidgets.QTableView):
    """Keeps a table's first columns (Include, sample, spot) visible while it scrolls.

    It shares the table's model and selection and sits over its left edge.
    """

    def __init__(self, table: QtWidgets.QTableView, frozen_names) -> None:
        super().__init__(table)
        self._table = table
        self._frozen_names = tuple(frozen_names)
        self.setObjectName("FrozenColumns")
        self.setModel(table.model())
        self.setSelectionModel(table.selectionModel())
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.verticalHeader().setVisible(False)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(table.verticalScrollMode())
        self.setSelectionBehavior(table.selectionBehavior())
        self.setSelectionMode(table.selectionMode())
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
        theme = active_theme()
        self.setStyleSheet(
            f"QTableView#FrozenColumns {{ border: none; border-right: 1px solid {theme.input_border}; "
            f"background: {theme.surface}; }}")
        self.viewport().setAutoFillBackground(True)
        # One-way: the table owns the scroll position; wheel events over the
        # frozen columns are passed to it.
        table.verticalScrollBar().valueChanged.connect(self._follow_table_scroll)
        table.verticalScrollBar().rangeChanged.connect(lambda *_args: self._follow_table_scroll())
        table.horizontalHeader().sectionResized.connect(self._refresh)
        table.horizontalHeader().sortIndicatorChanged.connect(
            lambda column, order: self.horizontalHeader().setSortIndicator(column, order))
        model = table.model()
        for signal in (model.modelReset, model.layoutChanged, model.columnsInserted, model.columnsRemoved):
            signal.connect(self._refresh)
        self.viewport().installEventFilter(self)
        self._refresh()

    def _follow_table_scroll(self, *_args) -> None:
        bar = self.verticalScrollBar()
        bar.setRange(self._table.verticalScrollBar().minimum(), self._table.verticalScrollBar().maximum())
        bar.setValue(self._table.verticalScrollBar().value())

    def wheelEvent(self, event) -> None:
        QtWidgets.QApplication.sendEvent(self._table.viewport(), event)

    def frozen_columns(self) -> list[int]:
        model = self._table.model()
        names = [model.headerData(column, QtCore.Qt.Orientation.Horizontal) for column in range(model.columnCount())]
        count = 0
        for index, name in enumerate(names):
            if index == 0 and name in {"Include", "Shown"} or name in self._frozen_names:
                count = index + 1
            else:
                break
        return list(range(count))

    def frozen_width(self) -> int:
        return sum(self._table.columnWidth(column) for column in self.frozen_columns()
                   if not self._table.isColumnHidden(column))

    def _refresh(self, *_args) -> None:
        frozen = set(self.frozen_columns())
        for column in range(self.model().columnCount()):
            self.setColumnHidden(column, column not in frozen or self._table.isColumnHidden(column))
            if column in frozen:
                self.setColumnWidth(column, self._table.columnWidth(column))
        self.setVisible(bool(frozen))
        self.update_geometry()

    def update_geometry(self) -> None:
        table = self._table
        frame = table.frameWidth()
        left = table.verticalHeader().width() if table.verticalHeader().isVisible() else 0
        self.setGeometry(frame + left, frame, self.frozen_width() + 1,
                         table.viewport().height() + table.horizontalHeader().height())
        self._follow_table_scroll()




def set_table_item(table, row, column, item):
    """Reuse cells; unchanged text must not trigger another column-size/layout pass."""
    existing = table.item(row, column)
    if existing is None:
        table.setItem(row, column, item)
        return
    if existing.text() != item.text():
        existing.setText(item.text())
    if existing.toolTip() != item.toolTip():
        existing.setToolTip(item.toolTip())
    if existing.font() != item.font():
        existing.setFont(item.font())
    if existing.foreground() != item.foreground():
        existing.setForeground(item.foreground())


def set_style(widget, style):
    """Avoid repolishing the whole widget tree when its style did not change."""
    if widget.styleSheet() != style:
        widget.setStyleSheet(style)
