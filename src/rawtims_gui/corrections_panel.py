"""The inspector's Corrections tab: the UO2 oxide correction and the function-to-contract mapping (SPEC F12, F14).

**Oxide (U runs).** The status says what the engine does with the run
(:attr:`rawtims.analysis.Analysis.oxide`): *computed* by this app with the
chosen formula and 18O/16O; *pass-through* of functions the file already carries
oxide-corrected (18O/16O read from the function names, formula not known); or *not applicable*. The 18O/16O field (default 0.00205, quick
button for Boise State's 0.00206) and the formula go through
``Analysis.set_setting``, so they are in the history and undoable. The
``tripoli_java_00dc941`` formula is a labelled comparison option with a
visible warning (docs/oxide-correction.md).

**Mapping.** One row per contract ratio of the run's element, with a combo of
the candidate functions (``[D]``/``[F]`` collector marks, ``1/(…)`` for an
inverted orientation) and the issues found inline (missing, ambiguous,
refused, warnings). For Pb the fraction's Collector (D/F) steers the
proposal. "Remember for method" stores the mapping in the viewer's QSettings
keyed by the method name; the next run of the same method gets it
automatically; "Forget" removes it.
"""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from rawtims.analysis import Analysis
from rawtims.fractions import Fraction
from rawtims.mapping import ElementMapping, MappingError, RatioCandidate, element_ratios, ratio_candidates
from rawtims.oxide import DEFAULT_R18

BSU_R18 = 0.00206
FORMULA_CHOICES = {
    "isobar_233_18O": ("isobar_233_18O (default)",
                       "Removes 233U16O18O isobar on mass 267 (ET_Redux, legacy Tripoli, Triton)"),
    "tripoli_java_00dc941": ("tripoli_java_00dc941 (comparison)",
                             "Comparison only: current Tripoli Java form"),
}
FORMULA_WARNING = ("Comparison only. This is the 238/235 form of current Tripoli (Java, commit 00dc941); its correction "
                   "grows with the sample-to-spike ratio, and the exported row says U Oxide Formula = tripoli_java_00dc941. "
                   "Use isobar_233_18O for results.")
PASS_THROUGH_TEXT = "already oxide-corrected in the file; passed through, not recomputed (formula not known)"
COLLECTOR_CHOICES = ((None, "Not set (Daly preferred)"), ("D", "D: Daly"), ("F", "F: Faraday"))
ISSUE_COLORS = {"missing": "danger", "refused": "danger", "ambiguous": "warning", "warning": "warning"}
WARNING_COLORS = {"light": "#a26300", "dark": "#f0b429"}
SOURCE_TEXT = {
    "edited": "Edited here for this run.",
    "remembered": "Remembered for method “{method}”.",
    "proposed": "Proposed from the function names.",
}


def candidate_label(candidate: RatioCandidate) -> str:
    name = f"1/({candidate.key})" if candidate.inverted else candidate.key
    marks = [candidate.collector] if candidate.collector else []
    if candidate.raw:
        marks.append("raw")
    return f"{name}  [{', '.join(marks)}]" if marks else name


def oxide_status_text(analysis: Analysis | None) -> tuple[str, str]:
    """``(state, text)``; state is ``computed``, ``pass_through``, ``not_applicable`` or ``pb``."""
    if analysis is None:
        return "none", "Open a run to see its corrections."
    if analysis.run.element != "U":
        return "pb", "The oxide correction applies only to U runs (UO2+). This is a Pb run."
    oxide = analysis.oxide
    if oxide.status == "computed":
        inputs = ", ".join(f"{name} = {how}" for name, how in oxide.inputs.items())
        return "computed", (f"Computed here: {oxide.formula} formula, 18O/16O = {oxide.r18:g}, from {inputs}. "
                            "Derived functions 233/235oc, 238/235oc, 238/233oc.")
    if oxide.status == "pass_through":
        r18 = f"{oxide.r18:g}" if oxide.r18 is not None else "not in the names"
        keys = ", ".join(oxide.pass_through_keys)
        text = (f"Pass-through: {keys} are {PASS_THROUGH_TEXT}. "
                f"18O/16O = {r18} (from the function names). Nothing is recomputed; the export says U Oxide Formula = instrument.")
        if oxide.reason:
            text += f" Note: {oxide.reason}."
        return "pass_through", text
    return "not_applicable", f"Not applicable: {oxide.reason}."


def _color(kind: str) -> str:
    from rawtims_gui.studio.theme import active_theme

    theme = active_theme()
    if kind == "danger":
        return theme.danger
    if kind == "warning":
        return WARNING_COLORS.get(theme.name, WARNING_COLORS["light"])
    return theme.muted


class CorrectionsPanel(QtWidgets.QWidget):
    settingRequested = QtCore.Signal(str, object)  # setting name, value
    mappingEdited = QtCore.Signal(object)  # {ratio: {"function", "inverted"} | None}
    collectorChanged = QtCore.Signal(object)  # None, "D" or "F"
    rememberRequested = QtCore.Signal()
    forgetRequested = QtCore.Signal()
    revertRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.analysis: Analysis | None = None
        self.mapping: ElementMapping | None = None
        self._loading = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 4, 4)
        layout.setSpacing(6)

        title = QtWidgets.QLabel("Oxide correction")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self.oxide_status = QtWidgets.QLabel("")
        self.oxide_status.setObjectName("OxideStatus")
        self.oxide_status.setWordWrap(True)
        self.oxide_status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.oxide_status)
        self.oxide_controls = QtWidgets.QWidget()
        controls = QtWidgets.QGridLayout(self.oxide_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setHorizontalSpacing(6)
        controls.setVerticalSpacing(5)
        controls.addWidget(QtWidgets.QLabel("18O/16O"), 0, 0)
        r18_buttons = QtWidgets.QHBoxLayout()
        r18_buttons.setSpacing(4)
        self.r18 = QtWidgets.QDoubleSpinBox()
        self.r18.setObjectName("R18")
        self.r18.setDecimals(5)
        self.r18.setRange(0.0, 0.09999)
        self.r18.setSingleStep(0.00001)
        self.r18.setKeyboardTracking(False)
        self.r18.setToolTip(f"18O/16O used by the oxide correction (default {DEFAULT_R18:g}, Tripoli's)")
        controls.addWidget(self.r18, 0, 1)
        controls.addLayout(r18_buttons, 1, 0, 1, 2)
        self.bsu_button = QtWidgets.QPushButton(f"BSU {BSU_R18:g}")
        self.bsu_button.setObjectName("R18Bsu")
        self.bsu_button.setToolTip("Boise State's 18O/16O, as in the BSU spreadsheets")
        r18_buttons.addWidget(self.bsu_button, 1)
        self.default_r18_button = QtWidgets.QPushButton("Default")
        self.default_r18_button.setToolTip(f"Back to {DEFAULT_R18:g}")
        r18_buttons.addWidget(self.default_r18_button, 1)
        for button in (self.bsu_button, self.default_r18_button):
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(56)
        controls.addWidget(QtWidgets.QLabel("Formula"), 2, 0)
        self.formula = QtWidgets.QComboBox()
        self.formula.setObjectName("OxideFormula")
        _narrow(self.formula)
        for index, (key, (label, description)) in enumerate(FORMULA_CHOICES.items()):
            self.formula.addItem(label, key)
            self.formula.setItemData(index, description, QtCore.Qt.ItemDataRole.ToolTipRole)
        controls.addWidget(self.formula, 3, 0, 1, 2)
        controls.setColumnStretch(1, 1)
        layout.addWidget(self.oxide_controls)
        self.formula_description = QtWidgets.QLabel("")
        self.formula_description.setObjectName("SecondaryText")
        self.formula_description.setWordWrap(True)
        layout.addWidget(self.formula_description)
        self.formula_warning = QtWidgets.QLabel(FORMULA_WARNING)
        self.formula_warning.setObjectName("FormulaWarning")
        self.formula_warning.setWordWrap(True)
        layout.addWidget(self.formula_warning)

        layout.addSpacing(4)
        self.mapping_title = QtWidgets.QLabel("Mapping to the contract")
        self.mapping_title.setObjectName("SectionTitle")
        layout.addWidget(self.mapping_title)
        self.collector_row = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.collector_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(QtWidgets.QLabel("Collector"))
        self.collector = QtWidgets.QComboBox()
        self.collector.setObjectName("MappingCollector")
        _narrow(self.collector)
        self.collector.setToolTip("The detector the Pb fractionation factor applies to (contract column Collector); "
                                  "the proposal prefers functions of this collector")
        for value, label in COLLECTOR_CHOICES:
            self.collector.addItem(label, value)
        row.addWidget(self.collector, 1)
        layout.addWidget(self.collector_row)
        self.mapping_grid_host = QtWidgets.QWidget()
        self.mapping_grid = QtWidgets.QGridLayout(self.mapping_grid_host)
        self.mapping_grid.setContentsMargins(0, 0, 0, 0)
        self.mapping_grid.setHorizontalSpacing(6)
        self.mapping_grid.setVerticalSpacing(3)
        self.mapping_grid.setColumnStretch(1, 1)
        layout.addWidget(self.mapping_grid_host)
        self.mapping_source = QtWidgets.QLabel("")
        self.mapping_source.setObjectName("MappingSource")
        self.mapping_source.setWordWrap(True)
        layout.addWidget(self.mapping_source)
        buttons = QtWidgets.QGridLayout()
        buttons.setSpacing(4)
        self.remember_button = QtWidgets.QPushButton("Remember for this method")
        self.remember_button.setObjectName("RememberMapping")
        self.forget_button = QtWidgets.QPushButton("Forget")
        self.forget_button.setObjectName("ForgetMapping")
        self.revert_button = QtWidgets.QPushButton("Use proposal")
        self.revert_button.setObjectName("RevertMapping")
        self.revert_button.setToolTip("Drop the edits of this run and use the remembered mapping or the proposal")
        for button in (self.remember_button, self.forget_button, self.revert_button):
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(56)
        buttons.addWidget(self.remember_button, 0, 0, 1, 2)
        buttons.addWidget(self.forget_button, 1, 0)
        buttons.addWidget(self.revert_button, 1, 1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self.combos: dict[str, QtWidgets.QComboBox] = {}
        self.candidates: dict[str, list[RatioCandidate]] = {}
        self.issue_labels: dict[str, QtWidgets.QLabel] = {}
        self._grid_element: str | None = None
        self.r18.editingFinished.connect(self._r18_edited)
        self.bsu_button.clicked.connect(lambda: self.settingRequested.emit("r18", BSU_R18))
        self.default_r18_button.clicked.connect(lambda: self.settingRequested.emit("r18", DEFAULT_R18))
        self.formula.currentIndexChanged.connect(self._formula_changed)
        self.collector.currentIndexChanged.connect(self._collector_changed)
        self.remember_button.clicked.connect(self.rememberRequested)
        self.forget_button.clicked.connect(self.forgetRequested)
        self.revert_button.clicked.connect(self.revertRequested)
        self.update_panel(None, None, None, "proposed", False)

    # ------------------------------------------------------------ signals
    def _r18_edited(self) -> None:
        if not self._loading and self.analysis is not None and self.r18.value() != self.analysis.settings.r18:
            self.settingRequested.emit("r18", float(round(self.r18.value(), 5)))

    def _formula_changed(self, *_args) -> None:
        self._show_formula_text()
        if not self._loading and self.analysis is not None and self.formula.currentData() != self.analysis.settings.oxide_formula:
            self.settingRequested.emit("oxide_formula", self.formula.currentData())

    def _collector_changed(self, *_args) -> None:
        if not self._loading:
            self.collectorChanged.emit(self.collector.currentData())

    def _combo_changed(self, *_args) -> None:
        if self._loading:
            return
        choice: dict[str, Any] = {}
        for ratio, picked in self.chosen().items():
            choice[ratio] = None if picked is None else {"function": picked[0], "inverted": picked[1]}
        self.mappingEdited.emit(choice)

    def _show_formula_text(self) -> None:
        key = self.formula.currentData() or "isobar_233_18O"
        self.formula_description.setText(FORMULA_CHOICES[key][1])
        comparison = key == "tripoli_java_00dc941"
        self.formula_warning.setVisible(comparison and self.oxide_controls.isEnabled())

    # ------------------------------------------------------------ display
    def update_panel(self, analysis: Analysis | None, fraction: Fraction | None, mapping: ElementMapping | None,
                     source: str, remembered: bool) -> None:
        self.analysis, self.mapping = analysis, mapping
        self._loading = True
        try:
            state, text = oxide_status_text(analysis)
            self.oxide_status.setText(text)
            computed = state == "computed"
            self.oxide_controls.setVisible(state in ("computed", "pass_through", "not_applicable"))
            self.oxide_controls.setEnabled(computed)
            if not computed and analysis is not None and state != "pb":
                self.oxide_controls.setToolTip("18O/16O and the formula apply only when this app computes the correction")
            else:
                self.oxide_controls.setToolTip("")
            if analysis is not None:
                self.r18.setValue(analysis.settings.r18)
                self.formula.setCurrentIndex(self.formula.findData(analysis.settings.oxide_formula))
            self.formula_description.setVisible(self.oxide_controls.isVisible())
            self._show_formula_text()
            warning = _color("warning")
            self.formula_warning.setStyleSheet(f"#FormulaWarning {{ color: {warning}; font-weight: 600; }}")
            element = analysis.run.element if analysis is not None else None
            self.collector_row.setVisible(element == "Pb")
            if fraction is not None:
                self.collector.setCurrentIndex(max(0, self.collector.findData(fraction.collector)))
            self._fill_mapping(analysis, mapping)
            if analysis is None or mapping is None:
                self.mapping_title.setText("Mapping to the contract")
                self.mapping_source.setText("" if analysis is None else "This run's element is not known, so it cannot be mapped.")
            else:
                self.mapping_title.setText(f"{element} mapping to the contract")
                method = analysis.run.metadata.method or "(no method name)"
                text = SOURCE_TEXT.get(source, "").format(method=method)
                if remembered and source != "remembered":
                    text += f" A mapping is remembered for “{method}” but does not fit this run completely."
                self.mapping_source.setText(text)
            has_method = analysis is not None and bool(analysis.run.metadata.method) and mapping is not None
            self.remember_button.setEnabled(has_method)
            self.remember_button.setToolTip(
                f"Store this mapping for method “{analysis.run.metadata.method}”; the next run of that method gets it automatically"
                if has_method else "This run has no method name")
            self.forget_button.setEnabled(remembered)
            self.forget_button.setToolTip("Forget the mapping remembered for this method" if remembered else "Nothing is remembered for this method")
            self.revert_button.setEnabled(source == "edited")
        finally:
            self._loading = False

    def _fill_mapping(self, analysis: Analysis | None, mapping: ElementMapping | None) -> None:
        element = analysis.run.element if analysis is not None and mapping is not None else None
        if element != self._grid_element:
            while self.mapping_grid.count():
                item = self.mapping_grid.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
            self.combos, self.issue_labels = {}, {}
            self._grid_element = element
            if element is not None:
                for position, ratio in enumerate(element_ratios(element)):
                    label = QtWidgets.QLabel(ratio)
                    combo = QtWidgets.QComboBox()
                    combo.setObjectName(f"Map {ratio}")
                    _narrow(combo)
                    combo.currentIndexChanged.connect(self._combo_changed)
                    issue = QtWidgets.QLabel("")
                    issue.setWordWrap(True)
                    issue.setObjectName("MappingIssue")
                    self.mapping_grid.addWidget(label, 2 * position, 0)
                    self.mapping_grid.addWidget(combo, 2 * position, 1)
                    self.mapping_grid.addWidget(issue, 2 * position + 1, 0, 1, 2)
                    self.combos[ratio] = combo
                    self.issue_labels[ratio] = issue
        if element is None or analysis is None or mapping is None:
            return
        try:
            candidates = ratio_candidates(analysis, element)
        except MappingError:
            candidates = {ratio: [] for ratio in element_ratios(element)}
        self.candidates = {ratio: list(candidates.get(ratio, [])) for ratio in self.combos}
        for ratio, combo in self.combos.items():
            combo.clear()
            combo.addItem("(none)", -1)
            index = 0
            mapped = mapping.ratios.get(ratio)
            for position, candidate in enumerate(self.candidates[ratio]):
                combo.addItem(candidate_label(candidate), position)
                combo.setItemData(combo.count() - 1, f"{candidate.name} ({candidate.source})", QtCore.Qt.ItemDataRole.ToolTipRole)
                if mapped is not None and (candidate.key, candidate.inverted) == (mapped.key, mapped.inverted):
                    index = combo.count() - 1
            combo.setCurrentIndex(index)
            combo.setToolTip(combo.currentText())
            issues = mapping.issues_for(ratio)
            texts = []
            worst = None
            for issue in issues:
                message = "no function chosen" if issue.message == "not in the remembered mapping" else issue.message
                texts.append(f"{issue.kind}: {message}")
                kind = ISSUE_COLORS.get(issue.kind, "warning")
                worst = "danger" if kind == "danger" or worst == "danger" else kind
            if mapped is not None and mapped.alternatives:
                texts.append(f"identical columns also: {', '.join(mapped.alternatives)}")
            label = self.issue_labels[ratio]
            label.setText("\n".join(texts))
            label.setVisible(bool(texts))
            label.setStyleSheet(f"#MappingIssue {{ color: {_color(worst or 'muted')}; font-size: 11px; }}")

    def chosen(self) -> dict[str, tuple[str, bool] | None]:
        """Contract ratio → (function key, inverted) shown in each combo, None for "(none)"."""
        result: dict[str, tuple[str, bool] | None] = {}
        for ratio, combo in self.combos.items():
            position = combo.currentData()
            candidates = self.candidates.get(ratio, [])
            if position is None or position < 0 or position >= len(candidates):
                result[ratio] = None
            else:
                result[ratio] = (candidates[position].key, candidates[position].inverted)
        return result

    def choose(self, ratio: str, key: str | None, inverted: bool = False) -> None:
        """Pick a candidate in one combo as a user would (None picks "(none)")."""
        combo = self.combos[ratio]
        if key is None:
            combo.setCurrentIndex(0)
            return
        for position, candidate in enumerate(self.candidates.get(ratio, [])):
            if (candidate.key, candidate.inverted) == (key, inverted):
                combo.setCurrentIndex(position + 1)
                return
        raise KeyError(f"{key!r} is not a candidate for {ratio}")


def _narrow(combo: QtWidgets.QComboBox, characters: int = 10) -> None:
    """A combo that may be narrower than its longest item (the inspector is about 280 px wide)."""
    combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(characters)
    combo.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
    combo.setMinimumWidth(72)  # an explicit minimum: the styled padding would otherwise ask for ~160 px


__all__ = ["BSU_R18", "FORMULA_CHOICES", "PASS_THROUGH_TEXT", "CorrectionsPanel", "candidate_label", "oxide_status_text"]
