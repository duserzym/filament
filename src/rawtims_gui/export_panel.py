"""The inspector's Export tab: identity and setup of the fraction, the contract preview and the exports (SPEC F15-F17).

The form edits the current fraction's contract fields (Fraction ID is edited
in the fraction list, so it is read-only here). Values are checked as they
are committed: weights must be numbers, the time zone an IANA name; Spike
Type and Collector are choices.

The preview (at the top) lists every open fraction with its state and the problems that
keep it out of the contract file: :class:`rawtims.fractions.FractionError`
messages and :meth:`rawtims.contract.FractionRow.problems`, in plain words.
Below it, the cells of the current fraction's row. "Save contract CSV…" writes
every exportable fraction (atomically); "Copy Tripoli clipboard" copies the
current fraction's block; "Save cycles CSV…" writes the current run's cycles.

Above the buttons a line says where ``Raw App Session`` stands: filled with the
session file name and its SHA-256 while the session is saved and unchanged;
otherwise it says plainly that the column stays empty and offers "Save session
first" (save the session, then save the contract CSV).
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.contract import FractionRow
from rawtims.fractions import COLLECTORS, SPIKE_TYPES, Fraction

TEXT_FIELDS = (
    ("sample", "Sample"),
    ("beaker", "Beaker"),
    ("source_grain", "Source Grain"),
    ("source_spot", "Source Spot"),
    ("source_mount", "Mount"),
    ("aliquot", "Aliquot"),
)
NUMBER_FIELDS = (("sample_weight_mg", "Sample Weight (mg)"), ("spike_weight_g", "Spike Weight (g)"))
SPIKE_SUGGESTIONS = ("", "ET535", "ET2535", "BSU1B")
TIMEZONE_SUGGESTIONS = ("", "America/Boise", "America/Denver", "America/Chicago", "America/New_York", "Europe/London", "UTC")
SEPARATORS = (("  ", "2 spaces (BSU sheets)"), (" ", "1 space (Tripoli report)"))
STATE_TEXT = {"ready": "ready", "attention": "needs attention", "incomplete": "incomplete"}


class ElidingLineEdit(QtWidgets.QLineEdit):
    """Keep the complete editable value; middle-elide only its unfocused display."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
        self.textChanged.connect(self.setToolTip)

    def text_rect(self) -> QtCore.QRect:
        option = QtWidgets.QStyleOptionFrame()
        self.initStyleOption(option)
        rect = self.style().subElementRect(QtWidgets.QStyle.SubElement.SE_LineEditContents, option, self)
        margins = self.textMargins()
        return rect.adjusted(margins.left() + 2, margins.top(), -margins.right() - 2, -margins.bottom())

    def displayed_text(self) -> str:
        return self.fontMetrics().elidedText(self.text(), QtCore.Qt.TextElideMode.ElideMiddle,
                                            max(0, self.text_rect().width()))

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt API
        if self.hasFocus() and not self.isReadOnly():
            super().paintEvent(event)
            return
        option = QtWidgets.QStyleOptionFrame()
        self.initStyleOption(option)
        painter = QtWidgets.QStylePainter(self)
        painter.drawPrimitive(QtWidgets.QStyle.PrimitiveElement.PE_PanelLineEdit, option)
        rect = self.text_rect()
        painter.setClipRect(rect)
        role = QtGui.QPalette.ColorRole.Text if self.text() else QtGui.QPalette.ColorRole.PlaceholderText
        painter.setPen(self.palette().color(role))
        painter.drawText(rect, self.alignment() | QtCore.Qt.AlignmentFlag.AlignVCenter,
                         self.displayed_text() if self.text() else self.placeholderText())


class ElidingComboBox(QtWidgets.QComboBox):
    def __init__(self) -> None:
        super().__init__()
        self.currentTextChanged.connect(self.setToolTip)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt API
        option = QtWidgets.QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = self.style().subControlRect(QtWidgets.QStyle.ComplexControl.CC_ComboBox, option,
                                          QtWidgets.QStyle.SubControl.SC_ComboBoxEditField, self)
        option.currentText = self.fontMetrics().elidedText(option.currentText, QtCore.Qt.TextElideMode.ElideMiddle,
                                                          max(0, rect.width() - 4))
        painter = QtWidgets.QStylePainter(self)
        painter.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QtWidgets.QStyle.ControlElement.CE_ComboBoxLabel, option)


def _narrow(combo: QtWidgets.QComboBox, characters: int = 8) -> QtWidgets.QComboBox:
    combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(characters)
    combo.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
    combo.setMinimumWidth(72)  # an explicit minimum: the styled padding would otherwise ask for ~160 px
    return combo


def _line(object_name: str) -> QtWidgets.QLineEdit:
    edit = ElidingLineEdit()
    edit.setObjectName(object_name)
    edit.setClearButtonEnabled(False)
    return edit


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value)


class ExportPanel(QtWidgets.QWidget):
    fieldEdited = QtCore.Signal(str, object)  # Fraction attribute, value
    saveContractRequested = QtCore.Signal()
    copyClipboardRequested = QtCore.Signal()
    saveCyclesRequested = QtCore.Signal()
    saveSessionFirstRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.fraction: Fraction | None = None
        self._loading = False
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        outer.setSpacing(6)
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("ExportScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QtWidgets.QWidget()
        body.setObjectName("ExportBody")
        body.setStyleSheet("#ExportBody { background: transparent; }")
        scroll.viewport().setAutoFillBackground(False)
        layout = QtWidgets.QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(6)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        title = QtWidgets.QLabel("Contract preview")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self.fraction_table = QtWidgets.QTableWidget(0, 3)
        self.fraction_table.setObjectName("ExportFractions")
        self.fraction_table.setHorizontalHeaderLabels(["Fraction", "Runs", "State"])
        self._style_table(self.fraction_table)
        header = self.fraction_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.fraction_table)
        self.statistics_note = QtWidgets.QLabel("")
        self.statistics_note.setObjectName("StatisticsNote")
        self.statistics_note.setWordWrap(True)
        layout.addWidget(self.statistics_note)
        self.problems = QtWidgets.QLabel("")
        self.problems.setObjectName("ExportProblems")
        self.problems.setWordWrap(True)
        self.problems.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.problems)
        self.row_title = QtWidgets.QLabel("Row")
        self.row_title.setObjectName("SectionTitle")
        layout.addWidget(self.row_title)
        self.row_table = QtWidgets.QTableWidget(0, 2)
        self.row_table.setObjectName("ExportRow")
        self.row_table.setHorizontalHeaderLabels(["Column", "Value"])
        self._style_table(self.row_table)
        self.row_table.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)
        self.row_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.row_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.row_table.setColumnWidth(0, 104)
        self.row_table.setFixedHeight(204)
        layout.addWidget(self.row_table)
        self.separator = _narrow(ElidingComboBox())
        self.separator.setObjectName("ClipboardSeparator")
        for value, label in SEPARATORS:
            self.separator.addItem(label, value)
        self.separator.setToolTip("Space before “(Mean, %StdErr)”: two as in legacy Tripoli, one as in Java Tripoli's reports")
        self.full_precision = QtWidgets.QCheckBox("Full precision")
        self.full_precision.setObjectName("ClipboardFullPrecision")
        self.full_precision.setToolTip("Off: legacy clipboard format (C# E7, eight significant digits). On: every digit. Contract CSV always keeps full precision.")
        title = QtWidgets.QLabel("Fraction")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.fields: dict[str, QtWidgets.QWidget] = {}
        self.fraction_id = _line("FieldFractionId")
        self.fraction_id.setReadOnly(True)
        self.fraction_id.setToolTip("Edit the Fraction ID in the fraction list (double-click it)")
        form.addRow("Fraction ID", self.fraction_id)
        for attribute, label in TEXT_FIELDS:
            edit = _line(f"Field {label}")
            edit.editingFinished.connect(lambda a=attribute, e=edit: self._text_committed(a, e))
            form.addRow(label, edit)
            self.fields[attribute] = edit
        for attribute, label in NUMBER_FIELDS:
            edit = _line(f"Field {label}")
            edit.setPlaceholderText("number")
            edit.editingFinished.connect(lambda a=attribute, e=edit, l=label: self._number_committed(a, e, l))
            form.addRow(label, edit)
            self.fields[attribute] = edit
        self.spike_type = _narrow(ElidingComboBox())
        self.spike_type.setObjectName("Field Spike Type")
        for value in ("", *SPIKE_TYPES):
            self.spike_type.addItem(value or "(not set)", value or None)
        self.spike_type.currentIndexChanged.connect(lambda *_: self._choice_committed("spike_type", self.spike_type))
        form.addRow("Spike Type", self.spike_type)
        self.fields["spike_type"] = self.spike_type
        self.spike = _narrow(ElidingComboBox())
        self.spike.setObjectName("Field Spike")
        self.spike.setEditable(True)
        self.spike.setLineEdit(ElidingLineEdit(self.spike))
        self.spike.addItems(list(SPIKE_SUGGESTIONS))
        self.spike.lineEdit().editingFinished.connect(lambda: self._text_committed("spike", self.spike.lineEdit()))
        self.spike.activated.connect(lambda *_: self._text_committed("spike", self.spike.lineEdit()))
        form.addRow("Spike", self.spike)
        self.fields["spike"] = self.spike
        self.collector = _narrow(ElidingComboBox())
        self.collector.setObjectName("Field Collector")
        for value in ("", *COLLECTORS):
            self.collector.addItem({"": "(not set)", "F": "F: Faraday", "D": "D: Daly"}[value], value or None)
        self.collector.currentIndexChanged.connect(lambda *_: self._choice_committed("collector", self.collector))
        form.addRow("Collector", self.collector)
        self.fields["collector"] = self.collector
        self.timezone = _narrow(ElidingComboBox())
        self.timezone.setObjectName("Field Timezone")
        self.timezone.setEditable(True)
        self.timezone.setLineEdit(ElidingLineEdit(self.timezone))
        self.timezone.addItems(list(TIMEZONE_SUGGESTIONS))
        self.timezone.setToolTip("Time zone of the instrument clock (IANA name, optional). With it, Run Start is written "
                                 "as ISO 8601 with offset; without it, the local start time goes to Notes.")
        self.timezone.lineEdit().setPlaceholderText("optional, e.g. America/Boise")
        self.timezone.lineEdit().editingFinished.connect(self._timezone_committed)
        self.timezone.activated.connect(lambda *_: self._timezone_committed())
        form.addRow("Time zone", self.timezone)
        self.fields["timezone"] = self.timezone
        form.addRow("Clipboard", self.separator)
        form.addRow("", self.full_precision)
        # Long weight labels wrap so the field column can use the panel width.
        for row in range(form.rowCount()):
            label_item = form.itemAt(row, QtWidgets.QFormLayout.ItemRole.LabelRole)
            if label_item is not None and isinstance(label_item.widget(), QtWidgets.QLabel):
                label_item.widget().setWordWrap(True)
                label_item.widget().setMaximumWidth(96)
        layout.addLayout(form)
        self.form_message = QtWidgets.QLabel("")
        self.form_message.setObjectName("FormMessage")
        self.form_message.setWordWrap(True)
        self.form_message.setVisible(False)
        layout.addWidget(self.form_message)

        layout.addStretch(1)

        self.session_note = QtWidgets.QLabel("")
        self.session_note.setObjectName("SessionNote")
        self.session_note.setWordWrap(True)
        outer.addWidget(self.session_note)
        self.session_first_button = QtWidgets.QPushButton("Save session first")
        self.session_first_button.setObjectName("SaveSessionFirst")
        self.session_first_button.setToolTip("Save the session, then save the contract CSV with Raw App Session filled")
        self.session_first_button.clicked.connect(self.saveSessionFirstRequested)
        outer.addWidget(self.session_first_button)
        self.session_state = "empty"
        buttons = QtWidgets.QGridLayout()
        buttons.setSpacing(4)
        self.save_button = QtWidgets.QPushButton("Save contract CSV…")
        self.save_button.setObjectName("SaveContract")
        self.save_button.setToolTip("Write every exportable fraction as an idtims-fractions/1 file")
        self.copy_button = QtWidgets.QPushButton("Copy Tripoli clipboard")
        self.copy_button.setObjectName("CopyClipboard")
        self.copy_button.setToolTip("Copy the current fraction as Tripoli's “name (Mean, %StdErr)” blocks, for the BSU spreadsheet")
        self.cycles_button = QtWidgets.QPushButton("Save cycles CSV…")
        self.cycles_button.setObjectName("SaveCycles")
        self.cycles_button.setToolTip("Write the current run's cycles with their include flags")
        buttons.addWidget(self.save_button, 0, 0, 1, 2)
        buttons.addWidget(self.copy_button, 1, 0, 1, 2)
        buttons.addWidget(self.cycles_button, 2, 0, 1, 2)
        outer.addLayout(buttons)
        self.save_button.clicked.connect(self.saveContractRequested)
        self.copy_button.clicked.connect(self.copyClipboardRequested)
        self.cycles_button.clicked.connect(self.saveCyclesRequested)
        self.update_panel(None, [], None, None, None)

    @staticmethod
    def _style_table(table: QtWidgets.QTableWidget) -> None:
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setWordWrap(False)
        table.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setStyleSheet("QTableWidget { font-size: 12px; } QHeaderView::section { font-size: 12px; padding: 3px 6px; }")

    # ---------------------------------------------------------- commits
    def _message(self, text: str) -> None:
        from rawtims_gui.studio.theme import active_theme

        self.form_message.setText(text)
        self.form_message.setStyleSheet(f"#FormMessage {{ color: {active_theme().danger}; }}")
        self.form_message.setVisible(bool(text))

    def _text_committed(self, attribute: str, edit: QtWidgets.QLineEdit) -> None:
        if self._loading or self.fraction is None:
            return
        value = edit.text().strip() or None
        if value != getattr(self.fraction, attribute):
            self.fieldEdited.emit(attribute, value)

    def _number_committed(self, attribute: str, edit: QtWidgets.QLineEdit, label: str) -> None:
        if self._loading or self.fraction is None:
            return
        text = edit.text().strip()
        if not text:
            value = None
        else:
            try:
                value = float(text)
            except ValueError:
                edit.setProperty("invalid", True)
                edit.setStyleSheet("QLineEdit { border: 1px solid #c2413b; }")
                self._message(f"{label}: “{text}” is not a number.")
                return
            if not value > 0:
                edit.setStyleSheet("QLineEdit { border: 1px solid #c2413b; }")
                self._message(f"{label} must be positive.")
                return
        edit.setStyleSheet("")
        self._message("")
        if value != getattr(self.fraction, attribute):
            self.fieldEdited.emit(attribute, value)

    def _choice_committed(self, attribute: str, combo: QtWidgets.QComboBox) -> None:
        if self._loading or self.fraction is None:
            return
        value = combo.currentData()
        if value != getattr(self.fraction, attribute):
            self.fieldEdited.emit(attribute, value)

    def _timezone_committed(self) -> None:
        if self._loading or self.fraction is None:
            return
        text = self.timezone.currentText().strip()
        if text:
            try:
                ZoneInfo(text)
            except (ZoneInfoNotFoundError, ValueError):
                self.timezone.setStyleSheet("QComboBox { border: 1px solid #c2413b; }")
                self._message(f"Time zone “{text}” is not an IANA name such as America/Boise.")
                return
        self.timezone.setStyleSheet("")
        self._message("")
        value = text or None
        if value != self.fraction.timezone:
            self.fieldEdited.emit("timezone", value)

    def set_field(self, attribute: str, text: str) -> None:
        """Type a value into a form field and commit it, as a user would (tests, scripted use)."""
        widget = self.fields[attribute]
        if isinstance(widget, QtWidgets.QLineEdit):
            widget.setText(text)
            widget.editingFinished.emit()
        elif widget is self.timezone or widget is self.spike:
            widget.setEditText(text)
            widget.lineEdit().editingFinished.emit()
        else:
            index = widget.findData(text or None)
            if index < 0:
                raise ValueError(f"{text!r} is not a choice for {attribute}")
            widget.setCurrentIndex(index)

    # ---------------------------------------------------------- display
    def update_panel(self, fraction: Fraction | None, statuses: list[tuple[Fraction, str, list[str]]],
                     row: FractionRow | None, row_error: str | None, element: str | None) -> None:
        self.fraction = fraction
        self._loading = True
        try:
            for widget in (*self.fields.values(), self.fraction_id):
                widget.setEnabled(fraction is not None)
            self.fraction_id.setText(fraction.fraction_id if fraction is not None else "")
            self.fraction_id.setCursorPosition(0)
            if fraction is not None:
                for attribute, _label in TEXT_FIELDS + NUMBER_FIELDS:
                    self.fields[attribute].setText(_text(getattr(fraction, attribute)))  # type: ignore[attr-defined]
                    self.fields[attribute].setCursorPosition(0)  # type: ignore[attr-defined]
                    self.fields[attribute].setStyleSheet("")
                self.spike_type.setCurrentIndex(max(0, self.spike_type.findData(fraction.spike_type)))
                self.collector.setCurrentIndex(max(0, self.collector.findData(fraction.collector)))
                self.spike.setEditText(fraction.spike or "")
                self.timezone.setEditText(fraction.timezone or "")
        finally:
            self._loading = False
        self._fill_fractions(statuses)
        self._fill_row(fraction, row, row_error)
        ready = [f for f, state, _reasons in statuses if state != "attention"]
        self.save_button.setEnabled(bool(ready))
        self.save_button.setText(f"Save contract CSV… ({len(ready)} fraction{'s' if len(ready) != 1 else ''})" if statuses else "Save contract CSV…")
        self.copy_button.setEnabled(row is not None)
        self.cycles_button.setEnabled(element is not None)

    def _fill_fractions(self, statuses: list[tuple[Fraction, str, list[str]]]) -> None:
        from rawtims_gui.studio.theme import active_theme

        theme = active_theme()
        colors = {"ready": theme.success, "attention": theme.danger, "incomplete": theme.faint}
        self.fraction_table.setRowCount(len(statuses))
        lines = []
        for index, (fraction, state, reasons) in enumerate(statuses):
            runs = " + ".join(element for element, analysis in (("Pb", fraction.pb), ("U", fraction.u)) if analysis is not None)
            cells = [QtWidgets.QTableWidgetItem(fraction.fraction_id), QtWidgets.QTableWidgetItem(runs),
                     QtWidgets.QTableWidgetItem(STATE_TEXT[state])]
            cells[0].setToolTip(fraction.fraction_id)
            cells[2].setForeground(QtGui.QBrush(QtGui.QColor(colors[state])))
            cells[2].setToolTip("\n".join(reasons) or "Exportable: both runs and a valid contract row")
            if fraction is self.fraction:
                font = cells[0].font()
                font.setBold(True)
                cells[0].setFont(font)
            for column, cell in enumerate(cells):
                self.fraction_table.setItem(index, column, cell)
            if state == "attention":
                lines += [f"• {fraction.fraction_id}: {reason}" for reason in reasons]
            elif state == "incomplete":
                lines += [f"• {fraction.fraction_id}: {reason} (exported as a one-block row)" for reason in reasons]
        height = self.fraction_table.horizontalHeader().height() + 22 * max(1, len(statuses)) + 4
        self.fraction_table.setFixedHeight(min(height, 22 * 6 + 30))
        if lines:
            self.problems.setText("\n".join(lines))
            self.problems.setStyleSheet(f"#ExportProblems {{ color: {theme.text}; font-size: 12px; }}")
        else:
            self.problems.setText("Every fraction is ready." if statuses else "Open runs to see their contract rows.")
            self.problems.setStyleSheet(f"#ExportProblems {{ color: {theme.muted}; font-size: 12px; }}")

    def _fill_row(self, fraction: Fraction | None, row: FractionRow | None, error: str | None) -> None:
        self.row_title.setText(f"Row of {fraction.fraction_id}" if fraction is not None else "Row")
        if row is None:
            self.row_table.setRowCount(1 if error else 0)
            if error:
                item = QtWidgets.QTableWidgetItem("cannot export")
                value = QtWidgets.QTableWidgetItem(error)
                value.setToolTip(error)
                self.row_table.setItem(0, 0, item)
                self.row_table.setItem(0, 1, value)
            return
        cells = row.to_csv()
        self.row_table.setRowCount(len(cells))
        for index, (name, text) in enumerate(cells.items()):
            key = QtWidgets.QTableWidgetItem(name)
            key.setToolTip(name)
            value = QtWidgets.QTableWidgetItem(text)
            value.setToolTip(text)
            self.row_table.setItem(index, 0, key)
            self.row_table.setItem(index, 1, value)

    def set_session_state(self, state: str, name: str | None) -> None:
        """``saved`` (unchanged since saved), ``modified``, ``untitled`` (never saved) or ``empty`` (nothing open)."""
        from rawtims_gui.studio.theme import active_theme

        theme = active_theme()
        self.session_state = state
        texts = {
            "saved": f"Rows point to the saved session “{name}” (Raw App Session and its SHA-256).",
            "modified": f"The session “{name}” has unsaved changes, so Raw App Session stays empty in the rows.",
            "untitled": "This session is not saved, so Raw App Session stays empty in the rows.",
            "unlinked": "The saved session file changed or is missing on disk, so Raw App Session stays empty in the rows.",
            "empty": "",
        }
        self.session_note.setText(texts[state])
        self.session_note.setVisible(state != "empty")
        color = theme.muted if state == "saved" else theme.text
        self.session_note.setStyleSheet(f"#SessionNote {{ color: {color}; font-size: 12px; }}")
        self.session_first_button.setVisible(state in ("modified", "untitled", "unlinked"))

    def set_project_statistics(self, mode: str, problem: str | None) -> None:
        from rawtims_gui.studio.theme import active_theme

        label = {"arithmetic": "arithmetic (legacy Tripoli)", "geometric": "geometric (Java Tripoli)"}[mode]
        self.statistics_note.setText(problem or f"Means and % SE: {label}")
        color = active_theme().danger if problem else active_theme().muted
        self.statistics_note.setStyleSheet(f"#StatisticsNote {{ color: {color}; font-size: 12px; }}")
        if problem:
            for button in (self.save_button, self.copy_button, self.cycles_button, self.session_first_button):
                button.setEnabled(False)
        else:
            self.session_first_button.setEnabled(True)

    def row_cells(self) -> dict[str, str]:
        return {self.row_table.item(i, 0).text(): self.row_table.item(i, 1).text() for i in range(self.row_table.rowCount())}


__all__ = ["ExportPanel", "SEPARATORS"]
