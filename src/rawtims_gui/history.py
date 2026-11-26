"""Read-only calibration evidence and explicit, manual completed-folder ingestion."""

from datetime import datetime
from pathlib import Path

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from rawtims.calibration_formats import read_gains, read_standard
from rawtims.completed_folder import CompletedFolder
from rawtims.history import HistoryBook, capture
from rawtims_gui.plot_palette import plot_palette


def show_history(window):
    dialog = HistoryDialog(window)
    dialog.exec()


class HistoryDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.book = HistoryBook.from_dict(window.workspace.calibration_history)
        self.folder = None
        self.setWindowTitle("Calibration history · read-only evidence")
        self.resize(940, 690)
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "History never applies a correction. Capture gains or explicitly select a standard; "
            "derived records stay fixed when the run is edited. Exclusions affect this history only."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        history = QtWidgets.QWidget()
        panel = QtWidgets.QVBoxLayout(history)
        row = QtWidgets.QHBoxLayout()
        self.runs = QtWidgets.QComboBox()
        self.runs.setMinimumContentsLength(18)
        self.runs.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        for analysis in window.workspace.analyses():
            self.runs.addItem(
                analysis.run.metadata.sample_id or analysis.run.raw.name, analysis
            )
        row.addWidget(self.runs, 1)
        for label, callback in [
            ("Capture gains", lambda: self.capture("gains")),
            ("Capture standard", lambda: self.capture("standard")),
            ("Import legacy…", self.import_legacy),
        ]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        panel.addLayout(row)
        self.records = QtWidgets.QTableWidget(0, 4)
        self.records.setHorizontalHeaderLabels(
            ["Acquisition date", "Record", "Kind", "History use"]
        )
        self.records.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.records.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.records.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.records.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.records.setMaximumHeight(150)
        self.records.itemSelectionChanged.connect(self.select_record)
        panel.addWidget(self.records)
        controls = QtWidgets.QHBoxLayout()
        self.reason = QtWidgets.QLineEdit()
        self.reason.setPlaceholderText(
            "Reason for excluding or restoring this history record"
        )
        controls.addWidget(self.reason, 1)
        for label, callback in [
            ("Exclude / restore", self.exclude),
            ("Undo", self.undo),
            ("Redo", self.redo),
        ]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        panel.addLayout(controls)
        self.series = QtWidgets.QComboBox()
        self.series.currentIndexChanged.connect(self.plot_history)
        panel.addWidget(self.series)
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(utcOffset=0)})
        self.plot.setMinimumHeight(120)
        panel.addWidget(self.plot, 1)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(110)
        panel.addWidget(self.details)
        self.tabs.addTab(history, "Gains / standards")
        folder_page = QtWidgets.QWidget()
        folder_layout = QtWidgets.QVBoxLayout(folder_page)
        note = QtWidgets.QLabel(
            "Choose a completed C# IonVantage cycle folder (-Bblock-Ccycle.txt). "
            "Refresh twice, at least one second apart. Files must settle with no gaps or conflicting duplicates. "
            "This dialect has no completion flag, elapsed times or instrument method name. "
            "The Method acquisition path is preserved. No background watch or automatic rejection runs."
        )
        note.setWordWrap(True)
        folder_layout.addWidget(note)
        buttons = QtWidgets.QHBoxLayout()
        for label, callback in [
            ("Choose folder…", self.choose_folder),
            ("Refresh", self.refresh_folder),
        ]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        self.open_button = QtWidgets.QPushButton("Open completed snapshot…")
        self.open_button.clicked.connect(self.open_completed)
        self.open_button.setEnabled(False)
        buttons.addWidget(self.open_button)
        folder_layout.addLayout(buttons)
        self.folder_path = QtWidgets.QLabel("No cycle folder selected")
        self.folder_path.setWordWrap(True)
        folder_layout.addWidget(self.folder_path)
        self.folder_status = QtWidgets.QLabel()
        self.folder_status.setWordWrap(True)
        folder_layout.addWidget(self.folder_status)
        folder_layout.addStretch(1)
        self.tabs.addTab(folder_page, "Completed cycle folder")
        self.notice = QtWidgets.QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        close = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh_records()

    def changed(self):
        self.window.workspace.calibration_history = self.book.to_dict()
        self.window._after_edit()
        self.refresh_records()

    def capture(self, kind):
        analysis = self.runs.currentData()
        if analysis is None:
            self.notice.setText("Open a run first.")
            return
        try:
            added = self.book.add(capture(analysis, kind))
            self.notice.setText(
                "Captured immutable history record."
                if added
                else "This exact revision is already in history."
            )
            if added:
                self.changed()
        except ValueError as error:
            self.notice.setText(str(error))

    def import_legacy(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import source-specified legacy calibration",
            "",
            "Gains workbook or standard (*.xls *.trip);;All files (*)",
        )
        if not path:
            return
        try:
            if Path(path).suffix.lower() == ".trip":
                item = read_standard(path)
            else:
                item = read_gains(path)
            if self.book.add(item):
                self.changed()
            self.notice.setText(
                "Imported source-schema record. Synthetic format tests do not establish real-lab validation."
            )
        except (ValueError, OSError) as error:
            self.notice.setText(str(error))

    def selected(self):
        row = self.records.currentRow()
        return (
            self.records.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
            if row >= 0
            else None
        )

    def refresh_records(self):
        selected = self.selected()
        self.records.blockSignals(True)
        self.records.setRowCount(len(self.book.records))
        for row, entry in enumerate(self.book.records):
            data = entry.data
            for col, text in enumerate(
                (
                    data["date"] or "Unavailable",
                    data["label"],
                    data["kind"],
                    "Excluded" if self.book.excluded(entry.key) else "Included",
                )
            ):
                item = QtWidgets.QTableWidgetItem(text)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, entry.key)
                self.records.setItem(row, col, item)
            if entry.key == selected:
                self.records.selectRow(row)
        self.records.blockSignals(False)
        key = self.series.currentData()
        self.series.blockSignals(True)
        self.series.clear()
        choices = sorted(
            {
                (r.data["kind"], s["key"], s["unit"] or "")
                for r in self.book.records
                for s in r.data["series"]
            }
        )
        for kind, name, unit in choices:
            self.series.addItem(
                f"{kind} · {name}" + (f" ({unit})" if unit else ""), (kind, name, unit)
            )
        index = self.series.findData(key)
        self.series.setCurrentIndex(max(0, index))
        self.series.blockSignals(False)
        self.select_record()
        self.plot_history()

    def select_record(self):
        key = self.selected()
        entry = next((r for r in self.book.records if r.key == key), None)
        if entry:
            data = entry.data
            events = [
                e
                for e in self.book.to_dict()["events"][: self.book.applied]
                if e["key"] == key
            ]
            self.details.setPlainText(
                f"Revision SHA-256: {entry.key}\nSource: {data['source']}\n"
                f"Calibration version: {data['calibration'].get('sha256', 'unavailable')}\n"
                f"Derivation: {data['derivation']}\nHistory exclusions/notes: {events}"
            )
        else:
            self.details.clear()

    def exclude(self):
        key = self.selected()
        if key:
            try:
                self.book.exclude(key, not self.book.excluded(key), self.reason.text())
                self.changed()
            except ValueError as error:
                self.notice.setText(str(error))

    def undo(self):
        if self.book.undo():
            self.changed()

    def redo(self):
        if self.book.redo():
            self.changed()

    def plot_history(self):
        self.plot.clear()
        palette = plot_palette()
        self.plot.setBackground(palette.background)
        for side in ("left", "bottom"):
            self.plot.getAxis(side).setTextPen(palette.axisText)
            self.plot.getAxis(side).setPen(palette.axisLine)
        choice = self.series.currentData()
        self.coordinates = []
        if not choice:
            return
        kind, key, unit = choice
        for entry in self.book.records:
            data = entry.data
            series = next(
                (
                    s
                    for s in data["series"]
                    if s["key"] == key and (s["unit"] or "") == unit
                ),
                None,
            )
            if (
                data["kind"] != kind
                or series is None
                or data["date"] is None
                or series["mean"] is None
            ):
                continue
            # Instrument timestamps are wall times, deliberately independent of OS zone.
            x = (
                datetime.fromisoformat(data["date"]) - datetime(1970, 1, 1)
            ).total_seconds()
            y = series["mean"]
            excluded = self.book.excluded(entry.key)
            self.coordinates.append((x, y, excluded))
            self.plot.plot(
                [x],
                [y],
                pen=None,
                symbol="s",
                symbolSize=7,
                symbolBrush=palette.background if excluded else palette.included,
                symbolPen=palette.excluded if excluded else palette.pointHalo,
            )
        self.plot.setLabel(
            "bottom",
            "Recorded acquisition wall date · unavailable dates omitted",
            color=palette.axisText,
        )
        self.plot.setLabel(
            "left", "Mean", units=unit or None, color=palette.axisText
        )
        self.plot.autoRange()
        if self.coordinates:
            dates = [point[0] for point in self.coordinates]
            if max(dates) - min(dates) < 86400:
                self.plot.setXRange(min(dates) - 43200, max(dates) + 43200, padding=0)

    def set_folder(self, path):
        self.folder = CompletedFolder(path)
        self.folder_path.setText(str(self.folder.path))
        self.open_button.setEnabled(False)
        self.folder_status.setText(self.folder.notice)

    def choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose completed cycle folder"
        )
        if path:
            self.set_folder(path)

    def refresh_folder(self):
        if self.folder:
            ready = self.folder.refresh()
            self.open_button.setEnabled(ready)
            self.folder_status.setText(self.folder.notice)

    def open_completed(self):
        if self.folder is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Confirm completed acquisition",
            "Has acquisition finished? Stable files alone cannot prove completion. "
            "This opens a new immutable snapshot and does not append to or reconcile an existing review.",
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save portable completed-cycle snapshot",
            "",
            "Cycle snapshot (*.json)",
        )
        if not path:
            return
        try:
            data = self.folder.snapshot_bytes(completed=True)
            if Path(path).resolve().parent == self.folder.path:
                raise ValueError("Save the snapshot outside the source cycle folder.")
            from rawtims.completed_folder import read_snapshot

            read_snapshot(path, data)  # Validate before writing/opening.
            from rawtims.session import _write_atomic

            _write_atomic(Path(path), data.decode())
            self.window.open_paths([path], synchronous=True)
            self.folder_status.setText(
                "Opened completed snapshot. The source folder and existing reviews remain separate."
            )
        except (ValueError, OSError) as error:
            self.folder_status.setText(str(error))
            self.open_button.setEnabled(False)
