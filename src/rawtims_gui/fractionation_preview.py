"""Session-only fractionation diagnostics. Nothing is assigned to Analysis."""

from dataclasses import fields

import numpy as np
from PySide6 import QtWidgets

from rawtims.fractionation_preview import (
    PreviewBook,
    UComponents,
    preview_pb,
    preview_u,
)
from rawtims.mapping import ratio_stats
from rawtims.session import mask_sha256
from rawtims.tracers import Estimate, Tracer, add_tracer, read_tracer

PRESENTATION_KEY = "fractionation_preview"
COMPONENT_LABELS = (
    "U blank (pg)",
    "Blank 238/235",
    "Sample 238/235",
    "Tracer mass (g)",
    "235U molar mass (g/mol)",
    "238U molar mass (g/mol)",
)


def capture_preview(analysis, mapping, tracer, components=None):
    """Freeze mapped measured summaries, source/settings/masks and model bytes.

    C# TripoliWorkProduct.cs:2332-2420 reports the applied tracer/alpha;
    here that provenance is isolated from measured results and exports.
    """
    if mapping is None or not mapping.ratios:
        raise ValueError("No verified measured-ratio mapping for this run")
    measured = {}
    counts = {}
    for name, mapped in mapping.ratios.items():
        stat = ratio_stats(analysis, mapped)
        if stat.n_used < 2 or not np.isfinite(stat.se_pct):
            raise ValueError(f"{name} needs at least two usable cycles and finite SE")
        measured[name] = Estimate(stat.mean, abs(stat.mean * stat.se_pct / 100))
        counts[name] = stat.n_used
    element = mapping.element
    result = (
        preview_pb(measured, tracer)
        if element == "Pb"
        else preview_u(measured, tracer, components)
    )
    return {
        "run_id": analysis.run.run_id,
        "run_name": analysis.run.raw.name,
        "element": element,
        "source_sha256": analysis.run.raw.sha256,
        "mask_sha256": mask_sha256(analysis),
        "settings": analysis.settings.to_dict(),
        "settings_sha256": PreviewBook.key(analysis.settings.to_dict()),
        "reduction_parameters": analysis.run.reduction_parameters.to_dict(),
        "reduction_parameters_sha256": analysis.run.reduction_parameters.sha256,
        "mapping": mapping.to_method_mapping().to_dict(),
        "mapping_sha256": PreviewBook.key(mapping.to_method_mapping().to_dict()),
        "accepted_counts": counts,
        "tracer": tracer.to_dict() if tracer else None,
        "tracer_identity": tracer.identity if tracer else "No tracer — unchanged",
        "result": result,
        "scope": "Frozen measured-summary preview, not per-cycle reduction; measured ratios exported. Age app authoritative.",
    }


class FractionationPreview(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.book = PreviewBook(window.workspace.presentation.get(PRESENTATION_KEY))
        self.batch_failures = []
        self.setWindowTitle("Fractionation preview (not exported)")
        self.resize(960, 680)
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Opt-in diagnostic · IDTIMS_UPbRPy remains authoritative. Measured ratios are exported. "
            "Frozen mean-level linear-law previews use independent inputs and first-order absolute 1σ. "
            "No spike stripping or interference correction is applied."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        setup = QtWidgets.QWidget()
        panel = QtWidgets.QVBoxLayout(setup)
        form = QtWidgets.QFormLayout()
        self.tracers = QtWidgets.QComboBox()
        self.tracers.setMinimumContentsLength(22)
        self.tracers.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        form.addRow("Active tracer for next revision", self.tracers)
        self.runs = QtWidgets.QComboBox()
        self.runs.setMinimumContentsLength(22)
        self.runs.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        for analysis in window.workspace.analyses():
            self.runs.addItem(analysis.run.raw.name, analysis)
        if window.analysis:
            self.runs.setCurrentIndex(self.runs.findData(window.analysis))
        form.addRow("Measured run", self.runs)
        panel.addLayout(form)
        import_button = QtWidgets.QPushButton("Read local tracer XML…")
        import_button.clicked.connect(self.choose_tracer)
        panel.addWidget(import_button)
        self.model_details = QtWidgets.QPlainTextEdit()
        self.model_details.setReadOnly(True)
        self.model_details.setMaximumHeight(125)
        panel.addWidget(self.model_details)
        note = QtWidgets.QLabel(
            "U 233/235 calibration components · enter values and absolute 1σ explicitly. "
            "Zero 1σ fixes that component. Batch uses these same components for every U run; "
            "use individual previews for different tracer masses or blanks. 233/236 fractionation is unavailable."
        )
        note.setWordWrap(True)
        panel.addWidget(note)
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Value"), 0, 1)
        grid.addWidget(QtWidgets.QLabel("Absolute 1σ"), 0, 2)
        self.components = []
        for i, label in enumerate(COMPONENT_LABELS, 1):
            value, sigma = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
            value.setAccessibleName(label)
            sigma.setAccessibleName(label + " absolute 1σ")
            grid.addWidget(QtWidgets.QLabel(label), i, 0)
            grid.addWidget(value, i, 1)
            grid.addWidget(sigma, i, 2)
            self.components.append((value, sigma))
        panel.addLayout(grid)
        buttons = QtWidgets.QHBoxLayout()
        for label, callback in (
            ("Create preview revision", self.create_current),
            ("Batch preview all runs", self.create_batch),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        panel.addLayout(buttons)
        panel.addStretch(1)
        self.tabs.addTab(setup, "Tracer / U components")
        report = QtWidgets.QWidget()
        report_layout = QtWidgets.QVBoxLayout(report)
        row = QtWidgets.QHBoxLayout()
        self.revisions = QtWidgets.QComboBox()
        self.revisions.setMinimumContentsLength(22)
        self.revisions.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        row.addWidget(self.revisions, 1)
        for label, callback in (
            ("Undo preview", self.undo),
            ("Redo preview", self.redo),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        report_layout.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Ratio / alpha", "Measured", "Measured 1σ", "Preview", "Preview 1σ"]
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        report_layout.addWidget(self.table, 1)
        self.report = QtWidgets.QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(220)
        report_layout.addWidget(self.report)
        self.tabs.addTab(report, "Correction report / revisions")
        self.notice = QtWidgets.QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        close = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.tracers.currentIndexChanged.connect(self.select_model)
        self.revisions.currentIndexChanged.connect(self.show_revision)
        self.refresh_tracers()
        self.refresh_revisions()

    def refresh_tracers(self):
        previous = self.book.data.get("active_tracer")
        self.tracers.blockSignals(True)
        self.tracers.clear()
        self.tracers.addItem("No tracer · unchanged preview", None)
        for record in self.book.data["library"]:
            tracer = Tracer.from_dict(record)
            self.tracers.addItem(tracer.identity, tracer.source_sha256)
        self.tracers.setCurrentIndex(max(0, self.tracers.findData(previous)))
        self.tracers.blockSignals(False)
        self.show_model()

    def select_model(self):
        self.book.data["active_tracer"] = self.tracers.currentData()
        self.changed()
        self.show_model()

    def active_tracer(self):
        key = self.tracers.currentData()
        return next(
            (
                Tracer.from_dict(r)
                for r in self.book.data["library"]
                if r["sha256"] == key
            ),
            None,
        )

    def show_model(self):
        tracer = self.active_tracer()
        self.model_details.setPlainText(
            f"{tracer.identity} · {tracer.tracer_type}\nLab: {tracer.lab} · Certified: {tracer.certified}\n"
            f"XML SHA-256: {tracer.source_sha256}\n"
            + "\n".join(
                f"{k}: {e.value:.10g} ± {e.sigma:.6g} (absolute 1σ)"
                for k, e in tracer.values
            )
            if tracer
            else "No tracer selected. Alpha is zero and measured values/uncertainties are preserved."
        )

    def choose_tracer(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Read local C# tracer XML", "", "Tracer XML (*.xml)"
        )
        if path:
            self.import_xml(path)

    def import_xml(self, path):
        try:
            tracer = read_tracer(path)
            self.book.data["library"] = add_tracer(self.book.data["library"], tracer)
            self.changed()
            self.refresh_tracers()
            self.tracers.setCurrentIndex(self.tracers.findData(tracer.source_sha256))
            self.notice.setText(
                "Read local versioned tracer. Existing preview revisions retain their applied XML."
            )
        except (ValueError, OSError) as error:
            self.notice.setText(f"Tracer import refused: {error}")

    def u_components(self):
        values = {}
        for field, (value, sigma) in zip(fields(UComponents), self.components):
            try:
                values[field.name] = Estimate(float(value.text()), float(sigma.text()))
            except ValueError as error:
                raise ValueError(
                    f"Enter {field.name} and its absolute 1σ: {error}"
                ) from error
        return UComponents(**values)

    def create(self, analyses):
        count, failures = 0, []
        tracer = self.active_tracer()
        for analysis in analyses:
            try:
                mapping = self.window.workspace.mapping(analysis)
                components = (
                    self.u_components()
                    if tracer and mapping and mapping.element == "U"
                    else None
                )
                record = capture_preview(analysis, mapping, tracer, components)
                self.book.add(record)
                count += 1
            except ValueError as error:
                failures.append(f"{analysis.run.raw.name}: {error}")
        self.batch_failures = failures
        if count:
            self.changed()
        else:
            self.show_revision()
        if count or failures:
            self.tabs.setCurrentIndex(1)
        self.notice.setText(
            f"Created {count} derived revision(s). "
            + (
                f"{len(failures)} run(s) refused; see the correction report."
                if failures
                else ""
            )
        )

    def create_current(self):
        analysis = self.runs.currentData()
        self.create([analysis] if analysis else [])

    def create_batch(self):
        self.create(self.window.workspace.analyses())

    def changed(self):
        self.window.workspace.presentation[PRESENTATION_KEY] = self.book.to_dict()
        self.window._after_edit()
        self.refresh_revisions()

    def undo(self):
        if self.book.undo():
            self.changed()

    def redo(self):
        if self.book.redo():
            self.changed()

    def refresh_revisions(self):
        self.revisions.clear()
        for i, record in self.book.visible():
            data = record["data"]
            self.revisions.addItem(
                f"Revision {i + 1} · {data['run_name']} · {data['tracer_identity']}", i
            )
        self.revisions.setCurrentIndex(self.revisions.count() - 1)
        self.show_revision()

    def show_revision(self):
        index = self.revisions.currentData()
        self.table.setRowCount(0)
        self.report.clear()
        if index is None:
            if self.batch_failures:
                self.report.setPlainText(
                    "Preview refusals:\n" + "\n".join(self.batch_failures)
                )
            return
        record = self.book.data["records"][index]
        data, result = record["data"], record["data"]["result"]
        self.table.setRowCount(len(result["names"]))
        for row, (name, value, sigma) in enumerate(
            zip(result["names"], result["values"], result["sigma"])
        ):
            measured = result["inputs"].get(name)
            cells = [
                "alpha (per amu)" if name == "alpha" else name,
                measured["value"] if measured else "—",
                measured["sigma"] if measured else "—",
                value,
                sigma,
            ]
            for col, cell in enumerate(cells):
                self.table.setItem(
                    row,
                    col,
                    QtWidgets.QTableWidgetItem(
                        f"{cell:.10g}" if isinstance(cell, float) else str(cell)
                    ),
                )
        self.report.setPlainText(
            f"Fractionation preview (not exported)\n{data['scope']}\n"
            f"Applied tracer: {data['tracer_identity']}\nAlgorithm: {result['algorithm']}\n"
            f"Measured statistic: {data['settings']['stat_mode']}\n"
            f"{result['uncertainty']}\n{result.get('control', '')}\n"
            f"Revision SHA-256: {record['key']}\nSource SHA-256: {data['source_sha256']}\n"
            f"Mask SHA-256: {data['mask_sha256']}\n"
            f"Settings SHA-256: {data['settings_sha256']}\nMapping SHA-256: {data['mapping_sha256']}\n"
            f"Reduction parameters SHA-256: {data['reduction_parameters_sha256']}\n"
            + (
                f"Applied XML SHA-256: {data['tracer']['sha256']}\n"
                if data["tracer"]
                else "No calibration applied.\n"
            )
            + "Inputs (absolute 1σ):\n"
            + "\n".join(
                f"{k}: {v['value']:.10g} ± {v['sigma']:.6g}"
                for k, v in result["inputs"].items()
            )
            + "\nAccepted counts: "
            + str(data["accepted_counts"])
            + (
                "\nPreview refusals:\n" + "\n".join(self.batch_failures)
                if self.batch_failures
                else ""
            )
        )


def show_fractionation_preview(window):
    FractionationPreview(window).exec()
