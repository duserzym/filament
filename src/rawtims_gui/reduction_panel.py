"""Staged acquisition controls: Apply, cancel-safe workers and cached undo.

Interaction follows UPbRPy 428b57f (costly changes need Apply).
"""
from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from weakref import WeakKeyDictionary

from PySide6 import QtCore, QtWidgets

from rawtims.analysis import Analysis
from rawtims.mapping import ratio_stats
from rawtims.readers.ionvantage_raw import raw_folder
from rawtims.reduction_params import (
    Baseline,
    BeamInterpolation,
    IntegrationRejection,
    as_acquired,
)
from rawtims.reprocess import reprocess
from rawtims_gui.studio.workers import FunctionWorker


def note(text):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def number(value):
    return "" if value is None else f"{value:.12g}"


def _flatten(data, prefix=""):
    result = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, name))
        else:
            result[name] = value
    return result


def reduction_diff(analysis, run, params):
    """JSON-safe change report for every mapped/exported ratio, retaining cycle masks."""
    old = _flatten(analysis.run.reduction_parameters.to_dict())
    new = _flatten(params.to_dict())
    changes = [f"{key}: {old.get(key)} → {new.get(key)}" for key in sorted(old.keys() | new.keys())
               if old.get(key) != new.get(key)]
    after = Analysis(run, analysis.settings)
    after.included[:] = analysis.included
    after.block_included[:] = analysis.block_included
    after.mapping = analysis.mapping
    ratios = []
    if analysis.mapping:
        for ratio, mapped in analysis.mapping.ratios.items():
            b, a = ratio_stats(analysis, mapped), ratio_stats(after, mapped)
            def finite(v):
                return v if math.isfinite(v) else None
            ratios.append({"ratio": ratio, "old_mean": finite(b.mean), "new_mean": finite(a.mean),
                           "delta_mean": finite(a.mean-b.mean),
                           "mean_ppm": finite((a.mean/b.mean-1)*1e6) if b.mean else None,
                           "old_se_pct": finite(b.se_pct), "new_se_pct": finite(a.se_pct),
                           "delta_se_pct": finite(a.se_pct-b.se_pct),
                           "se_relative_percent": finite((a.se_pct/b.se_pct-1)*100) if b.se_pct else None})
    return {"parameters": changes, "ratios": ratios}


class ReductionPanel(QtWidgets.QWidget):
    applyRequested = QtCore.Signal()
    cancelRequested = QtCore.Signal()
    resetRequested = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(0)
        self.analysis = None
        self._identity = None
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        outer.setSpacing(6)
        self.status = note("Open a run to stage reduction parameters.")
        outer.addWidget(self.status)
        self.form_body = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.form_body)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.WrapLongRows)
        self.fields = {}
        self.route = QtWidgets.QComboBox()
        self.route.addItem("Workbook (cached/approx.)", "workbook")
        self.route.addItem("Raw acquisitions", "raw")
        self.route.setToolTip("Cached workbook values; parameter changes use a labelled approximation. Raw acquisitions require verified decoding.")
        self.route.setMinimumWidth(0)
        self.route.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.route.setMinimumContentsLength(8)
        self.form.addRow("Route", self.route)
        self.raw_notice = note("Checking raw route…")
        self.form.addRow(self.raw_notice)
        self.dead_time = self.add_number("Daly dead time (ns)", "daly_dead_time_ns")
        self.multiplier_gain = self.add_number("Daly gain multiplier", "multiplier_gain")
        self.multiplier_gain.setToolTip("Acquisition calibration multiplier; changes require the raw route. Faraday/Daly cross-calibration remains the verified per-cycle 206-beam measurement.")
        self.gains = QtWidgets.QLineEdit()
        self.gains.setToolTip("Collector=value, separated by commas; every acquired collector must remain present")
        self.form.addRow("Faraday gains", self.gains)
        self.gain_mode = QtWidgets.QComboBox()
        self.gain_mode.addItem("Acquired gains", True)
        self.gain_mode.addItem("Unity gains", False)
        self.form.addRow("Gain mode", self.gain_mode)
        self.form.addRow(note("Faraday/Daly gain mode: measured per cycle from the 206 beams. Only this mode is validated; Tau Time/Gain and HT Scaling are not decoded. The Daly multiplier is acquisition calibration."))
        self.baseline_mode = QtWidgets.QComboBox()
        for mode in ("as_acquired", "measured", "offset"):
            self.baseline_mode.addItem(mode.replace('_', ' '), mode)
        self.form.addRow("Baseline mode", self.baseline_mode)
        self.offsets = QtWidgets.QLineEdit()
        self.offsets.setPlaceholderText("Collector=offset, …")
        self.offsets.setToolTip("Additional offsets: Pb cps, U V. Mode must be offset.")
        self.form.addRow("Baseline offsets", self.offsets)
        self.bi = QtWidgets.QCheckBox("Beam interpolation")
        self.form.addRow(self.bi)
        self.history = self.add_number("BI history cycles (2–3)", "history_cycles")
        self.sigma = self.add_number("Acquisition σ", "sigma")
        self.max_percent = self.add_number("Maximum rejected %", "max_percent")
        self.r18 = self.add_number("U oxide 18O/16O", "oxide_r18")
        for combo in self.form_body.findChildren(QtWidgets.QComboBox):
            combo.setMinimumWidth(170)
            combo.setMinimumContentsLength(6)
            combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
            combo.setToolTip(combo.currentText())
            combo.currentTextChanged.connect(combo.setToolTip)
        self.form_toggle = QtWidgets.QToolButton()
        self.form_toggle.setText("Edit parameters (staged)")
        self.form_toggle.setCheckable(True)
        self.form_toggle.setChecked(True)
        self.form_toggle.toggled.connect(self.form_body.setVisible)
        outer.addWidget(self.form_toggle)
        outer.addWidget(self.form_body)
        row = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.reset_button = QtWidgets.QPushButton("Reset")
        self.reset_button.setToolTip("Stage the original acquisition parameters; Apply to re-reduce (undoable)")
        for button in (self.apply_button, self.cancel_button, self.reset_button):
            row.addWidget(button)
        outer.addLayout(row)
        self._busy = False
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.diff = note("")
        self.diff.setObjectName("ReductionDiff")
        outer.addWidget(self.diff)
        outer.addWidget(note("Fractionation and spike calibration: set in the age app. This app exports non-fractionation-corrected ratios; spike identity and weight in Export are hand-off metadata."))
        outer.addStretch()
        self.apply_button.clicked.connect(self.applyRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.reset_button.clicked.connect(self.resetRequested)
        self.set_busy(False)

    def add_number(self, label, key):
        edit = QtWidgets.QLineEdit()
        edit.setMinimumWidth(40)
        self.fields[key] = edit
        self.form.addRow(label, edit)
        return edit

    @staticmethod
    def parse_map(text):
        result = {}
        if text.strip():
            for entry in text.split(','):
                key, value = entry.strip().split('=')
                if key.strip() in result:
                    raise ValueError(f"Duplicate collector {key.strip()}")
                result[key.strip()] = float(value)
        return result

    def stage(self, params):
        self.route.setCurrentIndex(self.route.findData(params.route))
        self.dead_time.setText(number(params.daly_dead_time_ns))
        self.multiplier_gain.setText(number(params.multiplier_gain))
        self.gains.setText(', '.join(f'{k}={number(v)}' for k, v in params.faraday_gains.items()))
        self.gain_mode.setCurrentIndex(self.gain_mode.findData(params.apply_faraday_gains))
        self.baseline_mode.setCurrentIndex(self.baseline_mode.findData(params.baseline.mode))
        self.offsets.setText(', '.join(f'{k}={number(v)}' for k, v in params.baseline.offsets.items()))
        self.bi.setChecked(params.beam_interpolation.enabled)
        self.history.setText(str(params.beam_interpolation.history_cycles))
        self.sigma.setText(number(params.integration_rejection.sigma))
        self.max_percent.setText(number(params.integration_rejection.max_percent))
        self.r18.setText(number(params.oxide_r18))
        self.r18.setEnabled(self.analysis is not None and self.analysis.run.element == 'U')

    def parameters(self):
        current = self.analysis.run.reduction_parameters
        return replace(current, route=self.route.currentData(),
                       daly_dead_time_ns=float(self.dead_time.text()) if self.dead_time.text().strip() else None,
                       multiplier_gain=float(self.multiplier_gain.text()),
                       faraday_gains=self.parse_map(self.gains.text()), apply_faraday_gains=self.gain_mode.currentData(),
                       baseline=Baseline(self.baseline_mode.currentData(), self.parse_map(self.offsets.text())),
                       beam_interpolation=BeamInterpolation(self.bi.isChecked(), int(self.history.text())),
                       integration_rejection=IntegrationRejection(float(self.sigma.text()), float(self.max_percent.text())),
                       oxide_r18=float(self.r18.text()) if self.r18.text().strip() else None)

    def update_panel(self, analysis, support):
        self.analysis = analysis
        identity = (analysis, id(analysis.run)) if analysis else None
        if identity != self._identity:
            self._identity = identity
            if analysis:
                self.stage(analysis.run.reduction_parameters)
                self.form_toggle.setChecked(not any(op["op"] == "set_reduction_parameters" for op in analysis._history_view()))
                self.status.setText("Changes are staged. Apply re-reduces this run; Undo restores the cached previous result.")
            self.show_diff(analysis)
        self.form_body.setEnabled(analysis is not None and not self._busy)
        self.apply_button.setEnabled(analysis is not None and not self._busy)
        self.reset_button.setEnabled(analysis is not None and not self._busy)
        allowed, reason = support
        self.route.model().item(1).setEnabled(allowed)
        self.raw_notice.setText(reason)
        self.route.setItemData(1, reason, QtCore.Qt.ItemDataRole.ToolTipRole)

    def set_busy(self, busy):
        self._busy = busy
        self.progress.setVisible(busy)
        self.form_body.setEnabled(not busy and self.analysis is not None)
        self.apply_button.setEnabled(not busy and self.analysis is not None)
        self.reset_button.setEnabled(not busy and self.analysis is not None)
        self.cancel_button.setText("Cancel" if busy else "Discard")
        self.cancel_button.setToolTip("Cancel calculation" if busy else "Discard staged edits")

    def show_diff(self, analysis):
        ops = [op for op in analysis._history_view() if op['op'] == 'set_reduction_parameters'] if analysis else []
        report = ops[-1].get('diff') if ops else None
        if not report:
            self.diff.setText("")
            return
        lines = ["Change from previous parameters", *report['parameters']]
        for ratio in report['ratios']:
            def fmt(key, ratio=ratio):
                v = ratio[key]
                return 'undefined' if v is None else f'{v:.9g}'
            lines.append(f"{ratio['ratio']}\nMean {fmt('old_mean')} → {fmt('new_mean')}\n"
                         f"Δ {fmt('delta_mean')} ({fmt('mean_ppm')} ppm)\n"
                         f"% SE {fmt('old_se_pct')} → {fmt('new_se_pct')}\n"
                         f"Δ {fmt('delta_se_pct')} percentage points ({fmt('se_relative_percent')}% relative)")
        self.diff.setText('\n\n'.join(lines))


class ReductionController(QtCore.QObject):
    """Workers only produce new Runs; the GUI commits after checking its generation."""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.support = WeakKeyDictionary()
        self.checking = set()
        self.token = None
        self.last_seconds = None

    def refresh(self):
        a = self.window.analysis
        if a and a not in self.support and a not in self.checking:
            if raw_folder(Path(a.run.raw.path)) is None:
                self.support[a] = (False, "Raw unavailable: no acquisition folder. Workbook route is used.")
            else:
                self.checking.add(a)
                source = a.run
                def probe():
                    try:
                        reprocess(source, replace(as_acquired(source), route='raw'))
                        return True, "Decoded and verified raw/workbook row correspondence."
                    except (ValueError, OSError) as error:
                        return False, f"Raw unavailable: {error}. Workbook route is used."
                self.start_worker(probe, lambda result: self.probed(a, result), lambda message: self.probed(a, (False, message)))
        support = self.support.get(a, (False, "Checking raw acquisition method…")) if a is not None else (False, "Open a run to inspect its acquisition method.")
        self.window.reduction_panel.update_panel(a, support)
        self.window.run_info_panel.update_run(a, support[1])

    def probed(self, analysis, result):
        self.checking.discard(analysis)
        self.support[analysis] = result
        self.refresh()

    def start_worker(self, function, success, failure):
        worker = FunctionWorker(function)
        worker.signals.succeeded.connect(success)
        worker.signals.failed.connect(lambda message, trace: failure(message))
        worker.signals.finished.connect(lambda: self.window._workers.discard(worker))
        self.window._workers.add(worker)
        QtCore.QThreadPool.globalInstance().start(worker)

    def apply(self, *, synchronous=False):
        a = self.window.analysis
        if a is None or self.token is not None:
            return
        panel = self.window.reduction_panel
        try:
            params = panel.parameters()
            if params.route == 'raw' and not self.support.get(a, (False, ''))[0]:
                raise ValueError(panel.raw_notice.text())
        except (ValueError, TypeError) as error:
            panel.status.setText(str(error))
            return
        if params == a.run.reduction_parameters:
            panel.status.setText("No parameter changes to apply.")
            return
        token = object()
        self.token = token
        source, history = a.run, a.history
        workspace = self.window.workspace
        panel.set_busy(True)
        panel.status.setText("Re-reducing… Cancel leaves the current result in place.")
        def calculate():
            start = perf_counter()
            run = reprocess(source, params)
            return run, perf_counter()-start
        def succeeded(result):
            if self.token is not token:
                return
            self.token = None
            panel.set_busy(False)
            if self.window.workspace is not workspace or a.run is not source or a.history != history:
                panel.status.setText("Run changed during calculation; result discarded. Apply again.")
                return
            run, self.last_seconds = result
            try:
                diff = reduction_diff(a, run, params)
                a.set_reduction_parameters(params, prepared_run=run, diff=diff)
            except (ValueError, OSError) as error:
                panel.status.setText(f"Reduction failed: {error}")
                return
            self.window._after_edit(rebuild=True)
            panel.status.setText(f"Applied in {self.last_seconds*1000:.1f} ms. Undo restores the previous parameters and result.")
        def failed(message):
            if self.token is token:
                self.token = None
                panel.set_busy(False)
                panel.status.setText(f"Reduction failed: {message}")
        if synchronous:
            try:
                result = calculate()
            except (ValueError, OSError) as error:
                failed(str(error))
            else:
                succeeded(result)
        else:
            self.start_worker(calculate, succeeded, failed)

    def cancel(self):
        self.token = None
        panel = self.window.reduction_panel
        panel.set_busy(False)
        if self.window.analysis:
            panel.stage(self.window.analysis.run.reduction_parameters)
        panel.status.setText("Staged changes discarded; current result retained.")

    def reset(self):
        if self.window.analysis:
            self.window.reduction_panel.form_toggle.setChecked(True)
            self.window.reduction_panel.stage(as_acquired(self.window.analysis.run))
            self.window.reduction_panel.status.setText("As-acquired parameters staged. Apply to re-reduce; Undo remains available.")
