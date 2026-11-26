"""Independent, read-only method/reference inspection and physical display."""

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets

from rawtims.methods import CATALOG_VERSION, INSTRUMENTS, SYNTHETIC_DETECTORS, nuclides
from rawtims.phoenix_method import read_method_xml
from rawtims.physical_units import (
    IntensityUnit,
    display_availability,
    display_intensity,
)
from rawtims_gui.plot_palette import plot_palette


def _table(headers):
    table = QtWidgets.QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(
        QtWidgets.QHeaderView.ResizeMode.Stretch
    )
    table.verticalHeader().setVisible(False)
    return table


def _fill(table, rows):
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            table.setItem(i, j, QtWidgets.QTableWidgetItem(str(value)))


class MethodInspector(QtWidgets.QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.run = owner.analysis.run if owner.analysis else None
        self.method = None
        self.setWindowTitle("Method and instrument references")
        self.resize(940, 620)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "Read-only references · "
            + CATALOG_VERSION
            + " · imported methods never change reduction settings"
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        method_page = QtWidgets.QWidget()
        method_layout = QtWidgets.QVBoxLayout(method_page)
        button = QtWidgets.QPushButton("Inspect Phoenix method XML…")
        button.clicked.connect(self.open_xml)
        method_layout.addWidget(button)
        self.method_notice = QtWidgets.QLabel(
            "No method imported. Validation covers the pinned Java string schema; real vendor specimens are still needed."
        )
        self.method_notice.setWordWrap(True)
        method_layout.addWidget(self.method_notice)
        self.method_tabs = QtWidgets.QTabWidget()
        method_layout.addWidget(self.method_tabs, 1)
        self.baselines = _table(["Collector", "Baseline", "Sequence", "Mass"])
        self.sequences = _table(["Collector", "Sequence", "Species", "Baselines"])
        self.fields = QtWidgets.QPlainTextEdit()
        self.fields.setReadOnly(True)
        for widget, title in (
            (self.baselines, "Baseline cells"),
            (self.sequences, "On-peak cells"),
            (self.fields, "Original fields"),
        ):
            self.method_tabs.addTab(widget, title)
        self.tabs.addTab(method_page, "Method XML")
        catalog = QtWidgets.QWidget()
        catalog_layout = QtWidgets.QVBoxLayout(catalog)
        self.instruments = _table(
            [
                "Instrument",
                "Collector width (mm)",
                "Magnet radius (mm)",
                "Beam width (mm)",
            ]
        )
        _fill(
            self.instruments,
            [
                (i.name, i.collector_width_mm, i.magnet_radius_mm, i.beam_width_mm)
                for i in INSTRUMENTS
            ],
        )
        catalog_layout.addWidget(self.instruments)
        label = QtWidgets.QLabel(
            "Java synthetic detector setup · reference defaults only; zero gains are not calibration"
        )
        label.setWordWrap(True)
        catalog_layout.addWidget(label)
        self.detectors = _table(
            [
                "Collector",
                "Ordinal",
                "Type",
                "Amplifier",
                "R (Ω)",
                "Gain",
                "Efficiency",
                "Dead time",
            ]
        )
        _fill(
            self.detectors,
            [
                (
                    d.name,
                    d.ordinal,
                    d.kind,
                    d.amplifier,
                    f"{d.resistance_ohm:.3g}",
                    d.gain,
                    d.efficiency,
                    d.dead_time,
                )
                for d in SYNTHETIC_DETECTORS
            ],
        )
        catalog_layout.addWidget(self.detectors, 2)
        self.tabs.addTab(catalog, "Instruments")
        species = QtWidgets.QWidget()
        species_layout = QtWidgets.QVBoxLayout(species)
        self.element = QtWidgets.QComboBox()
        self.element.addItems(sorted({n.symbol for n in nuclides()}))
        species_layout.addWidget(self.element)
        self.species = _table(
            ["Isotope", "Mass (u)", "Abundance (%)", "Half-life (yr)"]
        )
        species_layout.addWidget(self.species, 1)
        provenance = QtWidgets.QLabel(
            "Pinned NuclidesChartData.csv, Java 00dc941. Upstream missing values remain unavailable; independent abundance provenance is not established."
        )
        provenance.setWordWrap(True)
        species_layout.addWidget(provenance)
        self.element.currentTextChanged.connect(self.refresh_species)
        self.element.setCurrentText("Pb")
        self.refresh_species()
        self.tabs.addTab(species, "Isotopes")
        units = QtWidgets.QWidget()
        units_layout = QtWidgets.QVBoxLayout(units)
        controls = QtWidgets.QHBoxLayout()
        self.function = QtWidgets.QComboBox()
        if self.run:
            for f in self.run.functions:
                if f.kind == "intensity":
                    self.function.addItem(f.name, f.key)
        controls.addWidget(self.function, 1)
        self.unit = QtWidgets.QComboBox()
        self.unit.addItem("Acquired values", None)
        for unit in IntensityUnit:
            self.unit.addItem(unit.value, unit)
        controls.addWidget(self.unit)
        units_layout.addLayout(controls)
        self.unit_notice = QtWidgets.QLabel()
        self.unit_notice.setWordWrap(True)
        units_layout.addWidget(self.unit_notice)
        self.plot = pg.PlotWidget()
        units_layout.addWidget(self.plot, 1)
        self.function.currentIndexChanged.connect(self.refresh_units)
        self.unit.currentIndexChanged.connect(self.refresh_units)
        self.tabs.addTab(units, "Intensity display")
        self.refresh_units()
        close = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def open_xml(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Inspect Phoenix method XML",
            "",
            "Phoenix method (*.xml);;All files (*)",
        )
        if path:
            self.import_xml(path)

    def import_xml(self, path):
        try:
            method = read_method_xml(path)
        except (ValueError, OSError, UnicodeError) as error:
            self.method_notice.setText(f"Import refused: {error}")
            return
        self.method = method
        comparison = (
            method.compare_data_method(self.run.metadata.method or "")
            if self.run
            else ""
        )
        self.method_notice.setText(
            f"{Path(path).name} · SHA-256 {method.source_sha256}\n"
            "Synthetic reference detector setup; no hardware verification. "
            + comparison
        )
        _fill(
            self.baselines,
            [
                (c.detector, c.baseline, c.sequence, f"{c.mass:g}")
                for c in method.baseline_cells
            ],
        )
        _fill(
            self.sequences,
            [
                (
                    c.detector,
                    c.sequence,
                    f"{c.species.mass_number}{c.species.symbol}",
                    ", ".join(c.baseline_refs),
                )
                for c in method.sequence_cells
            ],
        )
        sections = [
            ("HEADER", method.header),
            ("SETTINGS", method.settings),
            *[(f"BASELINE {i + 1}", row) for i, row in enumerate(method.baselines)],
            *[(f"ONPEAK {i + 1}", row) for i, row in enumerate(method.on_peak)],
            ("EQUILIBRATION", method.equilibration),
        ]
        self.fields.setPlainText(
            "\n\n".join(
                name + "\n" + "\n".join(f"{k}: {v}" for k, v in row.fields)
                for name, row in sections
            )
        )

    def refresh_species(self):
        _fill(
            self.species,
            [
                (
                    f"{n.mass_number}{n.symbol}",
                    n.atomic_mass or "Unavailable",
                    n.abundance_percent or "Unavailable",
                    "Stable"
                    if n.half_life_annum == -1
                    else n.half_life_annum or "Unavailable",
                )
                for n in nuclides()
                if n.symbol == self.element.currentText()
            ],
        )

    def refresh_units(self):
        self.plot.clear()
        self.displayed_values = None
        key = self.function.currentData()
        if not self.run or key is None:
            self.unit.setEnabled(False)
            self.unit_notice.setText(
                "No intensity column is available in the current work product."
            )
            return
        availability = display_availability(self.run, key)
        self.unit.setEnabled(availability.available)
        target = self.unit.currentData()
        self.unit_notice.setText(availability.reason)
        if target is not None and not availability.available:
            return
        values = (
            self.run.column(key).copy()
            if target is None
            else display_intensity(self.run, key, target)
        )
        self.displayed_values = values
        palette = plot_palette()
        self.plot.setBackground(palette.background)
        for side in ("left", "bottom"):
            self.plot.getAxis(side).setTextPen(palette.axisText)
            self.plot.getAxis(side).setPen(palette.axisLine)
        finite = np.isfinite(values)
        self.plot.plot(
            self.run.cycle[finite],
            values[finite],
            pen=None,
            symbol="s",
            symbolSize=4.5,
            symbolBrush=palette.included,
            symbolPen=palette.pointHalo,
        )
        self.plot.setLabel("bottom", "Original cycle", color=palette.axisText)
        label = target.value if target is not None else "Acquired values"
        self.plot.setLabel("left", label, color=palette.axisText)


def show_method_inspector(window):
    MethodInspector(window).exec()
