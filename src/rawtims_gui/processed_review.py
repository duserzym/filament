"""Independent processed-data review for isotope systems outside Pb/U fractions."""

from pathlib import Path

import numpy as np
from PySide6 import QtWidgets

from rawtims.exports import cycles_csv_text
from rawtims_gui.cycle_table import CycleTable
from rawtims_gui.exchange import save_chosen
from rawtims_gui.plots import PlotState, PlotWall, format_number


class ProcessedReviewDialog(QtWidgets.QDialog):
    """Uses the existing plots/table and undoable Analysis masks, without a fraction slot."""

    def __init__(self, analysis, parent=None):
        super().__init__(parent)
        self.analysis = analysis
        self.setWindowTitle("Processed run review · " + analysis.run.raw.name)
        self.resize(1100, 700)
        layout = QtWidgets.QVBoxLayout(self)
        self.notice = QtWidgets.QLabel(
            "Independent run review · no Pb/U fraction mapping. Edits last while this window is open; "
            "save cycle CSV to keep reviewed values and masks. Vendor X flags are retained, not applied automatically."
        )
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        controls = QtWidgets.QHBoxLayout()
        self.functions = QtWidgets.QComboBox()
        self.functions.setMinimumContentsLength(15)
        self.functions.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.functions.addItems(analysis.keys)
        controls.addWidget(self.functions, 1)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["Arithmetic", "Geometric ratios"])
        controls.addWidget(self.mode)
        self.vendor = QtWidgets.QPushButton("Use X flags for this function")
        self.vendor.clicked.connect(self.use_vendor_flags)
        controls.addWidget(self.vendor)
        self.undo_button = QtWidgets.QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        controls.addWidget(self.undo_button)
        layout.addLayout(controls)
        self.tabs = QtWidgets.QTabWidget()
        self.wall = PlotWall()
        self.table = CycleTable()
        self.source = QtWidgets.QPlainTextEdit()
        self.source.setReadOnly(True)
        run = analysis.run
        self.source.setPlainText(run.metadata.extra["source_text"])
        self.tabs.addTab(self.wall, "Plot")
        self.tabs.addTab(self.table, "Cycles")
        self.tabs.addTab(self.source, "Source and flags")
        layout.addWidget(self.tabs, 1)
        self.statistics = QtWidgets.QLabel()
        self.statistics.setWordWrap(True)
        layout.addWidget(self.statistics)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        buttons.rejected.connect(self.close)
        self.save_button = buttons.addButton(
            "Save cycle CSV…", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
        )
        self.save_button.clicked.connect(self.save)
        layout.addWidget(buttons)
        self.functions.currentTextChanged.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.wall.toggleRequested.connect(self.toggle)
        self.wall.blockToggleRequested.connect(self.toggle_block)
        self.table.cycle_model.includeToggled.connect(self.toggle_row)
        self.refresh()

    def state(self):
        return PlotState(self.analysis, None, False, frozenset())

    def refresh(self, *_):
        key = self.functions.currentText()
        self.wall.set_plots([key], self.state())
        self.table.cycle_model.set_analysis(self.analysis, self.analysis.keys, [key])
        s = self.analysis.stats(key)
        self.statistics.setText(
            f"{key} · {s.mode} · {s.n_used}/{s.n_total} cycles · "
            f"Mean {format_number(s.mean)} · 1σ SE {format_number(s.se)}"
        )
        self.undo_button.setEnabled(self.analysis.can_undo)
        flags = self.analysis.run.metadata.extra.get("vendor_rejected")
        self.vendor.setEnabled(
            flags is not None
            and bool(np.asarray(flags)[:, self.analysis.index(key)].any())
        )

    def change_mode(self, index):
        self.analysis.set_setting("stat_mode", "geometric" if index else "arithmetic")
        self.refresh()

    def toggle(self, key, rows):
        self.analysis.toggle_cycles(rows, [key])
        self.refresh()

    def toggle_row(self, row, included):
        self.analysis.toggle_cycles([row], [self.functions.currentText()], included)
        self.refresh()

    def toggle_block(self, _key, row):
        self.analysis.toggle_block(int(self.analysis.run.block[row]))
        self.refresh()

    def use_vendor_flags(self):
        key = self.functions.currentText()
        flags = np.asarray(self.analysis.run.metadata.extra["vendor_rejected"])[
            :, self.analysis.index(key)
        ]
        self.analysis.toggle_cycles(np.flatnonzero(flags), [key], False)
        self.refresh()

    def undo(self):
        self.analysis.undo()
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(int(self.analysis.settings.stat_mode == "geometric"))
        self.mode.blockSignals(False)
        self.refresh()

    def save(self, _checked=False, path=None):
        if path is None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Save reviewed cycles",
                Path(self.analysis.run.raw.name).stem + ".cycles.csv",
                "Cycle CSV (*.csv)",
                options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite,
            )
        if path:
            try:
                return save_chosen(self, path, cycles_csv_text(self.analysis))
            except OSError as error:
                self.statistics.setText(f"Could not save cycles: {error}")
        return None
