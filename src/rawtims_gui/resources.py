"""Independent read-only resources, matching the existing lab theme/widgets."""

import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from rawtims.educational import demo_catalog, open_demo
from rawtims.reference_data import RESOURCE_VERSION, element_nuclides, elements
from rawtims_gui.method_inspector import _fill, _table
from rawtims_gui.plot_palette import plot_palette


def _note(text):
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    return label


def _close_button(dialog, layout):
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.StandardButton.Close
    )
    buttons.rejected.connect(dialog.close)
    layout.addWidget(buttons)


class PeriodicTable(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Periodic table and nuclides · read-only reference")
        self.resize(1050, 680)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            _note(
                "Read-only reference · "
                + RESOURCE_VERSION
                + " · CIRDLES/Tripoli, Apache-2.0. Reference values never set reduction parameters."
            )
        )
        self.element = QtWidgets.QComboBox()
        for e in elements():
            self.element.addItem(f"{e.number} · {e.symbol} · {e.name}", e.symbol)
        # The nuclide chart includes a free neutron outside the element table.
        self.element.addItem("0 · n · Neutron", "n")
        layout.addWidget(self.element)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(2)
        self.buttons = {}
        for e in elements():
            button = QtWidgets.QPushButton(e.symbol)
            button.setCheckable(True)
            button.setMinimumSize(0, 26)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed
            )
            button.setToolTip(f"{e.number} · {e.name}")
            button.clicked.connect(lambda _=False, symbol=e.symbol: self.select(symbol))
            grid.addWidget(button, e.row, e.column)
            self.buttons[e.symbol] = button
        layout.addLayout(grid)
        self.heading = _note("")
        layout.addWidget(self.heading)
        self.species = _table(
            ["Isotope", "Mass (u)", "Abundance (%)", "Half-life (yr)"]
        )
        layout.addWidget(self.species, 1)
        layout.addWidget(
            _note(
                "Pinned Java 00dc941 data; independent abundance provenance is not established. "
                "Unavailable values remain unavailable; zero abundance is an upstream missing-value sentinel."
            )
        )
        _close_button(self, layout)
        self.element.currentIndexChanged.connect(self.refresh)
        self.select("Pb")

    def select(self, symbol):
        self.element.setCurrentIndex(self.element.findData(symbol))

    def refresh(self):
        symbol = self.element.currentData()
        for name, button in self.buttons.items():
            button.setChecked(name == symbol)
            if button.property("accent") != (name == symbol):
                button.setProperty("accent", name == symbol)
                button.style().unpolish(button)
                button.style().polish(button)
        self.heading.setText(self.element.currentText())
        _fill(
            self.species,
            [
                (
                    f"{n.mass_number}{n.symbol}",
                    n.atomic_mass if n.atomic_mass else "unavailable",
                    n.abundance_percent if n.abundance_percent else "unavailable",
                    "stable"
                    if n.half_life_annum == -1
                    else n.half_life_annum or "unavailable",
                )
                for n in element_nuclides(symbol)
            ],
        )


class EducationalSession(QtWidgets.QDialog):
    """Owns a fresh DemoSession, with no Workspace, Analysis, save or export actions."""

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.session = open_demo(key)
        self.setWindowTitle("Educational session · " + self.session.title)
        self.resize(1000, 660)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            _note(
                "EDUCATIONAL · read-only separate session · "
                + self.session.title
                + " · no production reduction or export"
            )
        )
        self.notice = _note("")
        layout.addWidget(self.notice)
        controls = QtWidgets.QHBoxLayout()
        self.channel = QtWidgets.QComboBox()
        self.basis = QtWidgets.QComboBox()
        self.basis.addItems(["linear", "cubic"])
        if self.session.observations is not None:
            self.channel.addItem("Baseline · Ax", (0, 4))
            self.channel.addItem("Baseline · H1", (0, 6))
            for name, identity in (
                ("206Pb · Ax Faraday", (1, 4)),
                ("208Pb · H1 Faraday", (2, 6)),
                ("206Pb · PM", (1, 5)),
                ("208Pb · PM", (2, 5)),
            ):
                self.channel.addItem(name, identity)
            self.channel.setCurrentIndex(2)
            controls.addWidget(QtWidgets.QLabel("Channel"))
            controls.addWidget(self.channel, 1)
            controls.addWidget(QtWidgets.QLabel("Intensity basis"))
            controls.addWidget(self.basis)
        else:
            self.channel.hide()
            self.basis.hide()
        layout.addLayout(controls)
        self.tabs = QtWidgets.QTabWidget()
        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.residual = pg.PlotWidget()
        self.residual.setMenuEnabled(False)
        self.table = _table([])
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.tabs.addTab(
            self.plot,
            "Observed and model" if self.session.scan is None else "Recorded scan",
        )
        if self.session.scan is None:
            self.tabs.addTab(self.residual, "Residuals")
        self.tabs.addTab(self.table, "Values")
        self.tabs.addTab(self.details, "Source and limits")
        layout.addWidget(self.tabs, 1)
        _close_button(self, layout)
        self.channel.currentIndexChanged.connect(self.refresh)
        self.basis.currentTextChanged.connect(self.change_basis)
        self.refresh()

    def change_basis(self, kind):
        self.session = open_demo(self.session.key, kind=kind)
        self.refresh()

    def refresh(self):
        s = self.session
        palette = plot_palette()
        for plot in (self.plot, self.residual):
            plot.clear()
            plot.setBackground(palette.background)
            for side in ("bottom", "left"):
                plot.getAxis(side).setPen(palette.axisLine)
                plot.getAxis(side).setTextPen(palette.axisText)
        if s.scan is not None:
            x, observed = s.scan.mass, s.scan.intensity
            headers = ["Mass (u)", "Recorded intensity"]
            rows = list(zip(x, observed))
            self.notice.setText(
                "Public Tripoli peak-scan input only; no fitted beam shape, width or calibration. Intensity units are not inferred."
            )
            self.plot.setLabel("bottom", "Mass (u)")
            self.plot.setLabel("left", "Recorded intensity")
            metadata = "\n".join(f"{k}: {v}" for k, v in s.scan.metadata)
        else:
            data, result = s.observations, s.initialization.evaluation
            species, detector = self.channel.currentData()
            selected = (data.species == species) & (data.detector == detector)
            x = data.time_index[selected]
            observed, model, residual = (
                a[selected] for a in (data.observed, result.model, result.residual)
            )
            headers = [
                "Time index",
                "Observed (counts)",
                "Initial model",
                "Residual",
                "Variance",
            ]
            rows = list(zip(x, observed, model, residual, result.variance[selected]))
            self.plot.plot(x, model, pen=pg.mkPen(palette.mean, width=2))
            self.residual.plot(
                x,
                residual,
                pen=None,
                symbol="s",
                symbolSize=4.5,
                symbolBrush=palette.included,
                symbolPen=palette.pointHalo,
            )
            self.residual.setLabel("bottom", "Synthetic time index")
            self.residual.setLabel("left", "Observed − model (counts)")
            self.plot.setLabel("bottom", "Synthetic time index")
            self.plot.setLabel("left", "Counts")
            self.notice.setText(
                "Deterministic MCMC1 initialization only · points: observed · line: initial model · generating truth unavailable; no sampler or posterior. Baselines are excluded from the initial misfit."
            )
            p = s.initialization.parameters
            metadata = (
                f"Basis: {self.basis.currentText()}\nObservations: {len(data.observed)}\n"
                f"Initial gain: {p.gain}\nLog ratios: {p.log_ratios}\n"
                f"Gain fallback: {s.initialization.gain_fallback_reason or 'none'}\n"
                "Literal Java ratio-indexing and fixed noise conventions are retained; see P8 documentation."
            )
        self.plot.plot(
            x,
            observed,
            pen=None,
            symbol="s",
            symbolSize=4.5,
            symbolBrush=palette.included,
            symbolPen=palette.pointHalo,
        )
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        _fill(self.table, rows)
        self.details.setPlainText(
            f"{s.schema}\nCIRDLES/Tripoli 00dc941 · Apache-2.0\n{s.source_path}\n"
            f"SHA-256: {s.source_sha256}\n\n{metadata}"
        )


def show_resource(window, key=None):
    dialog = PeriodicTable(window) if key is None else EducationalSession(key, window)
    dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()
    return dialog


def build_menu(window):
    menu = window.menuBar().addMenu("Resources")
    menu.addAction("Periodic table and nuclides…", lambda: show_resource(window))
    demos = menu.addMenu("Educational demos · read-only")
    for key, entry in demo_catalog().items():
        demos.addAction(
            entry["title"] + "…", lambda _=False, k=key: show_resource(window, k)
        )
    return menu
