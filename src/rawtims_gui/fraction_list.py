"""The fraction list under the workflow rail (SPEC F5, section 5).

One row per fraction: its ID, editable in place (double-click, Enter to keep,
Escape to cancel), and a Pb and a U chip. A filled chip is a run that is
open; a dashed one is missing. Clicking a filled chip shows that run.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.fractions import Fraction
from rawtims_gui.studio.theme import active_theme, theme_color
from rawtims_gui.studio.widgets import ChipButton, ElidedLabel

CHIP_COLORS = {"Pb": "#4f78d0", "U": "#24906b"}
CHIP_SIZE = QtCore.QSize(28, 28)


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

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self.edit and event.type() == QtCore.QEvent.Type.ShortcutOverride and event.key() == QtCore.Qt.Key.Key_Escape:
            event.accept()  # Escape cancels the edit here instead of triggering the window's Clear Selection
            return True
        if watched is self.edit and event.type() == QtCore.QEvent.Type.KeyPress and event.key() == QtCore.Qt.Key.Key_Escape:
            self.edit.setText(self.label.text())
            self.setCurrentWidget(self.label)
            return True
        return False

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: N802 - Qt API
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
        layout.setContentsMargins(6, 3, 4, 3)
        layout.setSpacing(4)
        self.id_editor = _IdEditor(fraction.fraction_id)
        self.id_editor.committed.connect(self.renameRequested)
        layout.addWidget(self.id_editor, 1)
        self.chips: dict[str, ChipButton] = {}
        for element in ("Pb", "U"):
            chip = ChipButton(element, "")
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

    def set_fractions(self, fractions: Sequence[Fraction], current: tuple[Fraction, str] | None) -> None:
        for row in self.rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self.rows = []
        for position, fraction in enumerate(fractions):
            row = FractionRow(fraction)
            row.chipClicked.connect(lambda element, f=fraction: self.runSelected.emit(f, element))
            row.renameRequested.connect(lambda text, f=fraction: self.renameRequested.emit(f, text))
            self.rows_layout.insertWidget(position, row)
            self.rows.append(row)
        self.empty_label.setVisible(not self.rows)
        self.set_current(current)

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


__all__ = ["FractionList", "FractionRow"]
