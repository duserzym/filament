"""The fraction list under the workflow rail (SPEC F5, section 5).

One row per fraction: a state dot, its ID, editable in place (double-click,
Enter to keep, Escape to cancel), and a Pb and a U chip. A filled chip is a
run that is open; a dashed one is missing. Clicking a filled chip shows that
run.

The state dot (:class:`StateDot`) says whether the fraction can go to the
contract file: *ready* (a filled green dot: both runs, a valid row),
*attention* (a red ring with a bar: a row cannot be made or has problems) or
*incomplete* (a dashed grey ring: a run is missing). Shape and colour both
change, and the tooltip gives the reasons.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.fractions import Fraction
from rawtims_gui.studio.naming import natural_sort_key
from rawtims_gui.studio.theme import active_theme, theme_color
from rawtims_gui.studio.widgets import ChipButton, ElidedLabel

CHIP_COLORS = {"Pb": "#4f78d0", "U": "#24906b"}
CHIP_SIZE = QtCore.QSize(28, 28)
STATES = ("ready", "attention", "incomplete")
STATE_LABELS = {"ready": "Ready to export", "attention": "Needs attention", "incomplete": "Incomplete: a run is missing"}


class RunChip(ChipButton):
    """The vendored isotope tile without a mass line: the element is centred and the
    state marker sits in the top-right corner, clear of the letters (28-pixel chips)."""

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self.tile_active:
            background = QtGui.QColor(self.tile_color)
            background = background.lighter(112) if self.hovered else background
        else:
            background = QtGui.QColor("#242a34" if self.dark_theme else "#edf0f4")
        if self.tile_selected:
            border = QtGui.QColor("#ffffff" if self.dark_theme else "#111827")
        else:
            border = self.tile_color.darker(145) if self.tile_active else QtGui.QColor("#667085" if self.dark_theme else "#98a2b3")
        pen = QtGui.QPen(border, 2.6 if self.tile_selected else 1.2)
        if not self.tile_active:
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 8, 8)
        luminance = 0.2126 * background.redF() + 0.7152 * background.greenF() + 0.0722 * background.blueF()
        foreground = QtGui.QColor("#111318" if luminance > 0.58 else "#ffffff")
        if not self.tile_active:
            foreground = QtGui.QColor("#98a2b3" if self.dark_theme else "#667085")
        painter.setPen(foreground)
        font = QtGui.QFont(self.font())
        font.setPointSizeF(max(10.0, self.height() * 0.36))
        font.setWeight(QtGui.QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(rect.adjusted(-1, 3, -3, 0), QtCore.Qt.AlignmentFlag.AlignCenter, self.element)
        marker = QtCore.QPointF(rect.right() - 5.2, rect.top() + 5.2)
        painter.setPen(QtGui.QPen(foreground, 1.2))
        painter.setBrush(foreground if self.tile_active else QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(marker, 2.2, 2.2)
        painter.end()


class StateDot(QtWidgets.QWidget):
    """A small marker for the fraction's export state; see the module docstring."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = "incomplete"
        self.setFixedSize(14, 28)
        self.setObjectName("FractionState")

    def set_state(self, state: str, reasons: list[str] | tuple[str, ...] = ()) -> None:
        if state not in STATES:
            raise ValueError(state)
        self.state = state
        tip = STATE_LABELS[state]
        if reasons:
            tip += ":\n" + "\n".join(f"• {reason}" for reason in reasons)
        self.setToolTip(tip)
        self.setAccessibleName(STATE_LABELS[state])
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        del event
        theme = active_theme()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        centre = QtCore.QPointF(self.width() / 2, self.height() / 2)
        if self.state == "ready":
            color = QtGui.QColor(theme.success)
            painter.setPen(QtGui.QPen(color, 1))
            painter.setBrush(color)
            painter.drawEllipse(centre, 4.5, 4.5)
        elif self.state == "attention":
            color = QtGui.QColor(theme.danger)
            painter.setPen(QtGui.QPen(color, 2))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, 4.5, 4.5)
            painter.drawLine(QtCore.QPointF(centre.x(), centre.y() - 2.2), QtCore.QPointF(centre.x(), centre.y() + 0.6))
        else:
            pen = QtGui.QPen(QtGui.QColor(theme.faint), 1.3)
            pen.setStyle(QtCore.Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, 4.5, 4.5)
        painter.end()


class _IdEditor(QtWidgets.QStackedWidget):
    """A label that turns into a line edit on double-click."""

    committed = QtCore.Signal(str)

    def __init__(self, text: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = ElidedLabel(text)
        self.label.setObjectName("FractionId")
        self.label.setToolTip(f"{text}\nDouble-click to edit the Fraction ID")
        self.edit = QtWidgets.QLineEdit(text)
        self.edit.setObjectName("FractionIdEdit")
        self.addWidget(self.label)
        self.addWidget(self.edit)
        self.edit.editingFinished.connect(self._finish)
        self.edit.installEventFilter(self)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setFixedHeight(28)

    def start_editing(self) -> None:
        self.edit.setText(self.label.text())
        self.setCurrentWidget(self.edit)
        self.edit.setFocus()
        self.edit.selectAll()

    def _finish(self) -> None:
        if self.currentWidget() is not self.edit:
            return
        self.setCurrentWidget(self.label)
        text = self.edit.text().strip()
        if text and text != self.label.text():
            self.committed.emit(text)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.edit and event.type() == QtCore.QEvent.Type.ShortcutOverride and event.key() == QtCore.Qt.Key.Key_Escape:
            event.accept()  # Escape cancels the edit here instead of triggering the window's Clear Selection
            return True
        if watched is self.edit and event.type() == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Escape:
            self.edit.setText(self.label.text())
            self.setCurrentWidget(self.label)
            return True
        return False

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        self.start_editing()
        event.accept()


class FractionRow(QtWidgets.QFrame):
    chipClicked = QtCore.Signal(str)
    renameRequested = QtCore.Signal(str)

    def __init__(self, fraction: Fraction, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FractionRow")
        self.fraction = fraction
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        self.state_dot = StateDot()
        layout.addWidget(self.state_dot)
        self.id_editor = _IdEditor(fraction.fraction_id)
        self.id_editor.committed.connect(self.renameRequested)
        layout.addWidget(self.id_editor, 1)
        self.chips: dict[str, ChipButton] = {}
        for element in ("Pb", "U"):
            chip = RunChip(element, "")
            chip.setFixedSize(CHIP_SIZE)
            chip.setObjectName(f"Chip{element}")
            chip.clicked.connect(lambda _checked=False, e=element: self._chip(e))
            self.chips[element] = chip
            layout.addWidget(chip)
        self.set_current(None)

    def analysis(self, element: str):
        return self.fraction.pb if element == "Pb" else self.fraction.u

    def _chip(self, element: str) -> None:
        if self.analysis(element) is not None:
            self.chipClicked.emit(element)

    def set_current(self, element: str | None) -> None:
        theme = active_theme()
        dark = theme.name == "dark"
        for name, chip in self.chips.items():
            analysis = self.analysis(name)
            chip.set_visual_state(CHIP_COLORS[name], active=analysis is not None, selected=name == element and analysis is not None, dark_theme=dark)
            chip.setToolTip(f"{name} run: {analysis.run.raw.name}" if analysis is not None else f"No {name} run in this fraction")
            chip.setCursor(QtCore.Qt.CursorShape.PointingHandCursor if analysis is not None else QtCore.Qt.CursorShape.ArrowCursor)
            chip.setAccessibleName(f"{name} run of {self.fraction.fraction_id}" + ("" if analysis is not None else " (missing)"))
        self.setProperty("current", element is not None)
        background = theme_color(theme.accent_soft).name(QtGui.QColor.NameFormat.HexArgb) if element is not None else "transparent"
        self.setStyleSheet(f"#FractionRow {{ background: {background}; border-radius: 10px; }}")


class FractionList(QtWidgets.QScrollArea):
    runSelected = QtCore.Signal(object, str)  # Fraction, element
    renameRequested = QtCore.Signal(object, str)  # Fraction, new id

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FractionList")
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        body.setObjectName("FractionListBody")
        body.setStyleSheet("#FractionListBody { background: transparent; }")
        self.viewport().setAutoFillBackground(False)
        self.rows_layout = QtWidgets.QVBoxLayout(body)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(2)
        self.empty_label = QtWidgets.QLabel("Fractions appear here after import.")
        self.empty_label.setObjectName("SecondaryText")
        self.empty_label.setWordWrap(True)
        self.rows_layout.addWidget(self.empty_label)
        self.rows_layout.addStretch(1)
        self.setWidget(body)
        self.rows: list[FractionRow] = []
        self.compact = False

    def set_fractions(self, fractions: Sequence[Fraction], current: tuple[Fraction, str] | None) -> None:
        for row in self.rows:
            self.rows_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.rows = []
        for position, fraction in enumerate(fractions):
            row = FractionRow(fraction)
            row.chipClicked.connect(lambda element, f=fraction: self.runSelected.emit(f, element))
            row.renameRequested.connect(lambda text, f=fraction: self.renameRequested.emit(f, text))
            self.rows_layout.insertWidget(position, row)
            self.rows.append(row)
        # Keep the backing list/import API stable; sort the visual rows, as a
        # sorted model view would, without changing session/export order.
        for position, row in enumerate(sorted(self.rows, key=lambda r: natural_sort_key(r.fraction.fraction_id))):
            self.rows_layout.removeWidget(row)
            self.rows_layout.insertWidget(position, row)
        self.set_compact(self.compact)
        self.empty_label.setVisible(not self.rows)
        self.set_current(current)

    def set_compact(self, compact: bool) -> None:
        """A 56 px rail of existing run chips; full IDs remain in tooltips."""
        self.compact = compact
        for row in self.rows:
            row.id_editor.setVisible(not compact)
            row.state_dot.setVisible(not compact)
            row.layout().setDirection(QtWidgets.QBoxLayout.Direction.TopToBottom if compact
                                      else QtWidgets.QBoxLayout.Direction.LeftToRight)
            row.setToolTip(row.fraction.fraction_id)

    def set_states(self, states: dict[int, tuple[str, list[str]]]) -> None:
        """``{id(fraction): (state, reasons)}`` from :meth:`rawtims_gui.workspace.Workspace.fraction_status`."""
        for row in self.rows:
            state, reasons = states.get(id(row.fraction), ("incomplete", []))
            row.state_dot.set_state(state, reasons)

    def states(self) -> list[tuple[str, str]]:
        """(fraction ID, state) per row, for tests."""
        return [(row.fraction.fraction_id, row.state_dot.state) for row in self.rows]

    def set_current(self, current: tuple[Fraction, str] | None) -> None:
        for row in self.rows:
            row.set_current(current[1] if current is not None and current[0] is row.fraction else None)

    def row_for(self, fraction: Fraction) -> FractionRow:
        for row in self.rows:
            if row.fraction is fraction:
                return row
        raise KeyError(fraction.fraction_id)

    def contents(self) -> list[tuple[str, str | None, str | None]]:
        """(fraction ID, Pb file name, U file name) per row, for tests and accessibility checks."""
        return [
            (row.fraction.fraction_id,
             row.fraction.pb.run.raw.name if row.fraction.pb is not None else None,
             row.fraction.u.run.raw.name if row.fraction.u is not None else None)
            for row in self.rows
        ]


__all__ = ["FractionList", "FractionRow", "RunChip", "StateDot"]
