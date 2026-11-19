"""The inspector's Rules tab: preview a rejection rule, apply exactly that proposal, and the edit history (SPEC F9, F10).

Nothing is rejected by opening a run or by changing a parameter (SPEC section
0, decision 3). "Preview" asks the window for a
:class:`rawtims.rules.RuleProposal` and shows what it would reject (the
plots and the table highlight the cycles) without touching the mask;
"Apply" hands that same proposal to :meth:`rawtims.analysis.Analysis.apply_rule`,
which records it in the history; "Discard" drops it. Any other edit, a
parameter change or a run switch discards the preview, so what is applied is
always what is shown.

The rule parameters are the analysis settings (``chauvenet_probability``,
``chauvenet_min_n``, ``k_sigma``, ``k_sigma_max_iterations``, ``synced``); the
window commits them through ``Analysis.set_setting`` before a preview, so each
change is in the history and undoable. Scope and function set belong to one
proposal and are recorded in it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.analysis import Analysis
from rawtims.rules import RuleProposal

RULES = {"chauvenet": "Java Chauvenet (one pass)", "k_sigma": "k-σ, iterative",
         "legacy_two_sigma": "Legacy 2σ (one pass)", "legacy_chauvenet": "Legacy Chauvenet (repeated)"}
SCOPES = {"run": "Whole run", "block": "Per block"}
FUNCTION_SETS = {"mapped": "Group union", "one": "One chosen ratio", "plotted": "Plotted functions"}
SHARED_SELECTION_TOOLTIP = ("Correlated ratios share one cycle selection: their errors are correlated through "
                            "205Pb (Pb) or the 267 beam (U).")
TRIPOLI_NOTE = ("Tripoli's Chauvenet: raw cycle values (not ln r), each function on its own upstream (no SYNCH), "
                "one pass, only with n ≥ 20 included values, P = 0.5.")
SETTING_LABELS = {
    "stat_mode": "statistics",
    "r18": "18O/16O",
    "oxide_formula": "oxide formula",
    "chauvenet_probability": "Chauvenet P",
    "chauvenet_min_n": "Chauvenet min n",
    "k_sigma": "k-σ k",
    "k_sigma_max_iterations": "k-σ max passes",
    "synced": "SYNCH",
}


def _cycles_text(analysis: Analysis, rows: Sequence[int], limit: int = 6) -> str:
    numbers = [int(analysis.run.cycle[int(row)]) for row in rows]
    shown = ", ".join(str(n) for n in numbers[:limit])
    if len(numbers) > limit:
        shown += f", … ({len(numbers)} cycles)"
    return shown


def _value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def describe_op(analysis: Analysis, op: dict[str, Any]) -> str:
    """One line for a history entry, with instrument cycle numbers."""
    kind = op.get("op")
    if op.get("label"):
        return op["label"] + (f" · {op['keys'][0]}" if op.get("keys") else "")
    if kind == "toggle_cycles":
        cycles = op.get("cycles", [])
        word = "Included" if op.get("include") else "Excluded"
        noun = "cycle" if len(cycles) == 1 else "cycles"
        keys = op.get("keys")
        where = "every function" if keys is None else (keys[0] if len(keys) == 1 else f"{len(keys)} functions")
        return f"{word} {noun} {_cycles_text(analysis, cycles)} in {where}"
    if kind == "toggle_block":
        return f"{'Included' if op.get('include') else 'Excluded'} block {op.get('block')}"
    if kind == "apply_rule":
        changed = {int(row) for row, _ in op.get("changed", [])}
        return f"Rule: {op.get('description', op.get('rule'))}, {len(changed)} cycle{'s' if len(changed) != 1 else ''} newly excluded"
    if kind == "set_reduction_parameters":
        return "Reduction parameters changed (undoable)"
    if kind == "set_mapping":
        return "Mapping changed; joining functions adopted the shared selection"
    if kind == "set_setting":
        name = op.get("name", "")
        return f"Setting: {SETTING_LABELS.get(name, name)} {_value_text(op.get('old'))} → {_value_text(op.get('new'))}"
    if kind == "reset":
        return "Reset: every cycle and block included"
    return str(kind)


def _narrow(combo: QtWidgets.QComboBox, characters: int = 10) -> None:
    combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(characters)
    combo.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
    combo.setMinimumWidth(72)  # an explicit minimum: the styled padding would otherwise ask for ~160 px


def _spin(decimals: int, minimum: float, maximum: float, step: float) -> QtWidgets.QDoubleSpinBox:
    spin = QtWidgets.QDoubleSpinBox()
    spin.setDecimals(decimals)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setKeyboardTracking(False)
    spin.setMinimumWidth(60)
    spin.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
    return spin


def _int_spin(minimum: int, maximum: int) -> QtWidgets.QSpinBox:
    spin = QtWidgets.QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setKeyboardTracking(False)
    spin.setMinimumWidth(60)
    spin.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
    return spin


class RulesPanel(QtWidgets.QWidget):
    previewRequested = QtCore.Signal()
    applyRequested = QtCore.Signal()
    discardRequested = QtCore.Signal()
    parametersEdited = QtCore.Signal()
    synchToggled = QtCore.Signal(bool)
    whyRequested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        outer.setSpacing(6)
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(5)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.rule_combo = QtWidgets.QComboBox()
        self.rule_combo.setObjectName("RuleChoice")
        _narrow(self.rule_combo)
        for key, label in RULES.items():
            self.rule_combo.addItem(label, key)
        form.addRow("Rule", self.rule_combo)
        self.param_stack = QtWidgets.QStackedWidget()
        chauvenet = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(chauvenet)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.probability = _spin(3, 0.0, 1.0, 0.05)
        self.probability.setToolTip("Reject a value when n · erfc(|z|/√2) is below P")
        self.min_n = _int_spin(2, 100_000)
        self.min_n.setToolTip("Run the criterion only when at least this many values are included")
        self.probability.setPrefix("P ")
        self.min_n.setPrefix("n ≥ ")
        row.addWidget(self.probability, 1)
        row.addWidget(self.min_n, 1)
        k_sigma = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(k_sigma)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.k = _spin(2, 0.5, 10.0, 0.5)
        self.k.setToolTip("Reject values farther than k standard deviations from the mean (ln r for ratios), then repeat")
        self.max_iterations = _int_spin(1, 100)
        self.max_iterations.setToolTip("Stop after this many passes")
        self.k.setPrefix("k ")
        self.max_iterations.setPrefix("max ")
        self.max_iterations.setSuffix(" passes")
        row.addWidget(self.k, 1)
        row.addWidget(self.max_iterations, 1)
        self.param_stack.addWidget(chauvenet)
        self.param_stack.addWidget(k_sigma)
        legacy_note = QtWidgets.QLabel("Strict |x − mean| > 2 SD; positive accepted cycles.")
        legacy_note.setWordWrap(True)
        self.param_stack.addWidget(legacy_note)
        self.param_stack.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Fixed)
        form.addRow("Limits", self.param_stack)
        self.scope_combo = QtWidgets.QComboBox()
        self.scope_combo.setObjectName("RuleScope")
        _narrow(self.scope_combo)
        for key, label in SCOPES.items():
            self.scope_combo.addItem(label, key)
        form.addRow("Scope", self.scope_combo)
        self.function_combo = QtWidgets.QComboBox()
        self.function_combo.setObjectName("RuleFunctions")
        _narrow(self.function_combo)
        for key, label in FUNCTION_SETS.items():
            self.function_combo.addItem(label, key)
        self.function_combo.setToolTip("Group union evaluates every group ratio; one chosen ratio evaluates only that ratio. Both reject group-wide. Plotted functions also allows free functions.")
        form.addRow("Evaluate", self.function_combo)
        self.ratio_combo = QtWidgets.QComboBox()
        _narrow(self.ratio_combo)
        form.addRow("Chosen ratio", self.ratio_combo)
        self.per_ratio_box = QtWidgets.QCheckBox("Per-ratio masks (legacy)")
        self.per_ratio_box.setToolTip("Legacy rules only. Reject separately in each evaluated ratio; ordinary export is blocked while group masks differ. Use the union of rejections before hand-off.")
        self.per_ratio_box.toggled.connect(self._edited)
        form.addRow(self.per_ratio_box)
        self.ratio_combo.currentIndexChanged.connect(self._edited)
        self.synch_box = QtWidgets.QCheckBox("SYNCH (union in all)")
        self.synch_box.setObjectName("RuleSynch")
        self.synch_box.setToolTip("On: a cycle any examined function flags is excluded in every function. Off: each function loses only its own cycles.")
        lock_row = QtWidgets.QWidget()
        lock_layout = QtWidgets.QHBoxLayout(lock_row)
        lock_layout.setContentsMargins(0, 0, 0, 0)
        self.synch_box.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.synch_box.setMinimumWidth(80)
        lock_layout.addWidget(self.synch_box, 1)
        self.why_link = QtWidgets.QLabel('<a href="shared">Why?</a>')
        self.why_link.linkActivated.connect(lambda _url: self.whyRequested.emit())
        lock_layout.addWidget(self.why_link)
        form.addRow("", lock_row)
        outer.addLayout(form)
        self.note = QtWidgets.QLabel(TRIPOLI_NOTE)
        self.note.setObjectName("SecondaryText")
        self.note.setWordWrap(True)
        outer.addWidget(self.note)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(4)
        self.preview_button = QtWidgets.QPushButton("Preview")
        self.preview_button.setObjectName("RulePreview")
        self.preview_button.setToolTip("Show what the rule would reject; nothing changes yet")
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setObjectName("RuleApply")
        self.apply_button.setToolTip("Exclude exactly the previewed cycles (undoable)")
        self.discard_button = QtWidgets.QPushButton("Discard")
        self.discard_button.setObjectName("RuleDiscard")
        self.discard_button.setToolTip("Drop the preview")
        for button in (self.preview_button, self.apply_button, self.discard_button):
            button.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
            button.setMinimumWidth(56)
            buttons.addWidget(button, 1)
        outer.addLayout(buttons)
        self.result_label = QtWidgets.QLabel("No preview.")
        self.result_label.setObjectName("RuleResult")
        self.result_label.setWordWrap(True)
        outer.addWidget(self.result_label)
        self.result_list = QtWidgets.QListWidget()
        self.result_list.setObjectName("RuleResultList")
        self.result_list.setMinimumHeight(60)
        self.result_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.result_list.setWordWrap(True)
        self.result_list.setStyleSheet("QListWidget { font-size: 12px; }")
        outer.addWidget(self.result_list, 2)

        self.preview_caption = QtWidgets.QLabel("Before → after (dry run). Flags: each ratio alone.")
        self.preview_caption.setWordWrap(True)
        outer.addWidget(self.preview_caption)
        self.preview_table = QtWidgets.QTableWidget(0, 4)
        self.preview_table.setObjectName("RuleBeforeAfter")
        self.preview_table.setHorizontalHeaderLabels(["Ratio", "Flags", "n →", "% SE →"])
        self.preview_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview_table.verticalHeader().hide()
        self.preview_table.verticalHeader().setDefaultSectionSize(24)
        self.preview_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_table.setMinimumWidth(0)
        self.preview_table.setStyleSheet("QTableWidget { font-size: 11px; padding: 0; } QTableWidget::item { padding: 0; } QHeaderView::section { font-size: 11px; padding: 2px; }")
        header = self.preview_table.horizontalHeader()
        header.setMinimumSectionSize(28)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 30), (2, 54), (3, 100)):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeMode.Fixed)
            self.preview_table.setColumnWidth(col, width)
        outer.addWidget(self.preview_table)
        history_title = QtWidgets.QLabel("History")
        history_title.setObjectName("SectionTitle")
        outer.addWidget(history_title)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.setObjectName("HistoryList")
        self.history_list.setMinimumHeight(80)
        self.history_list.setWordWrap(True)
        self.history_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_list.setStyleSheet("QListWidget { font-size: 12px; }")
        self.history_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        outer.addWidget(self.history_list, 3)
        self.history_note = QtWidgets.QLabel("")
        self.history_note.setObjectName("SecondaryText")
        self.history_note.setWordWrap(True)
        outer.addWidget(self.history_note)

        self.rule_combo.currentIndexChanged.connect(self._rule_changed)
        for spin in (self.probability, self.min_n, self.k, self.max_iterations):
            spin.valueChanged.connect(self._edited)
        self.scope_combo.currentIndexChanged.connect(self._edited)
        self.function_combo.currentIndexChanged.connect(self._functions_changed)
        self.synch_box.toggled.connect(self.synchToggled)
        self.preview_button.clicked.connect(self.previewRequested)
        self.apply_button.clicked.connect(self.applyRequested)
        self.discard_button.clicked.connect(self.discardRequested)
        self._loading = False
        self.update_panel(None, None)

    # --------------------------------------------------------- parameters
    def parameters(self) -> dict[str, Any]:
        return {
            "rule": self.rule_combo.currentData(),
            "chauvenet_probability": float(self.probability.value()),
            "chauvenet_min_n": int(self.min_n.value()),
            "k_sigma": float(self.k.value()),
            "k_sigma_max_iterations": int(self.max_iterations.value()),
            "scope": self.scope_combo.currentData(),
            "function_set": self.function_combo.currentData(),
            "ratio_key": self.ratio_combo.currentData(),
            "per_ratio": self.per_ratio_box.isChecked() and self.rule_combo.currentData().startswith("legacy_"),
        }

    def set_rule(self, rule: str) -> None:
        self.rule_combo.setCurrentIndex(self.rule_combo.findData(rule))

    def _show_limits(self):
        rule = self.rule_combo.currentData()
        self.param_stack.setCurrentIndex(2 if rule == "legacy_two_sigma" else 1 if rule == "k_sigma" else 0)
        self.min_n.setVisible(rule == "chauvenet")
        self.per_ratio_box.setVisible(rule.startswith("legacy_"))

    def _rule_changed(self, *_args) -> None:
        self._show_limits()
        self.note.setVisible(self.rule_combo.currentData() == "chauvenet")
        self._edited()

    def _functions_changed(self, *_args) -> None:
        self.ratio_combo.setEnabled(self.function_combo.currentData() == "one")
        self._edited()

    def _edited(self, *_args) -> None:
        if not self._loading:
            self.parametersEdited.emit()

    # ------------------------------------------------------------ display
    def update_panel(self, analysis: Analysis | None, proposal: RuleProposal | None) -> None:
        self._loading = True
        try:
            enabled = analysis is not None
            for widget in (self.rule_combo, self.param_stack, self.scope_combo, self.function_combo, self.synch_box, self.preview_button):
                widget.setEnabled(enabled)
            if analysis is not None:
                settings = analysis.settings
                self.probability.setValue(settings.chauvenet_probability)
                self.min_n.setValue(settings.chauvenet_min_n)
                self.k.setValue(settings.k_sigma)
                self.max_iterations.setValue(settings.k_sigma_max_iterations)
                per_ratio = self.parameters()["per_ratio"]
                group = bool(analysis.group_keys) and self.function_combo.currentData() != "plotted" and not per_ratio
                self.synch_box.blockSignals(True)
                self.synch_box.setChecked(False if per_ratio else True if group else settings.synced)
                self.synch_box.blockSignals(False)
                self.synch_box.setEnabled(not group)
                if per_ratio:
                    self.synch_box.setEnabled(False)
                self.synch_box.setText("SYNCH · locked" if group else "SYNCH (free functions)")
                self.synch_box.setToolTip(SHARED_SELECTION_TOOLTIP if group else "Apply the union to free functions only")
                chosen = self.ratio_combo.currentData()
                wanted = analysis.group_keys
                if [self.ratio_combo.itemData(i) for i in range(self.ratio_combo.count())] != wanted:
                    self.ratio_combo.clear()
                    for key in wanted:
                        self.ratio_combo.addItem(key, key)
                    if chosen in wanted:
                        self.ratio_combo.setCurrentIndex(wanted.index(chosen))
                self.ratio_combo.setEnabled(self.function_combo.currentData() == "one")
                self.note.setText("Flagged cycles will be rejected in every group ratio. Preview first, then Apply."
                                  if group else TRIPOLI_NOTE)
                if per_ratio:
                    self.note.setText("Per-ratio legacy masks. Preview first; Apply is undoable. Ordinary export is blocked while masks differ; use the union before hand-off.")
                    self.note.show()
            self._show_limits()
        finally:
            self._loading = False
        self.apply_button.setEnabled(proposal is not None and not proposal.is_empty)
        self.discard_button.setEnabled(proposal is not None)
        self.result_list.clear()
        has_table = proposal is not None and bool(proposal.before_after)
        self.preview_caption.setVisible(has_table)
        self.preview_table.setVisible(has_table)
        self.result_list.setVisible(not has_table)
        self.preview_table.setRowCount(0)
        if has_table:
            from rawtims_gui.plots import format_number
            self.preview_table.setRowCount(len(proposal.before_after))
            self.preview_table.setFixedHeight(28 + 24 * len(proposal.before_after))
            for row, (key, change) in enumerate(proposal.before_after.items()):
                b, a = change["before"], change["after"]
                cells = [key, str(len(proposal.flagged.get(key, ()))), f'{b["n"]}→{a["n"]}',
                         f'{format_number(b["se_pct"], 3)}→{format_number(a["se_pct"], 3)}']
                for col, text in enumerate(cells):
                    item = QtWidgets.QTableWidgetItem(text)
                    item.setToolTip(f'{key}: {len(proposal.flagged.get(key, ()))} flags; cycles '
                                    f'{_cycles_text(analysis, proposal.flagged.get(key, ()), 100)}; '
                                    f'n {b["n"]} → {a["n"]}; % SE {b["se_pct"]} → {a["se_pct"]}'
                                    + (" (diagnostic only; not chosen)" if key not in proposal.keys else ""))
                    self.preview_table.setItem(row, col, item)
        if analysis is None:
            self.result_label.setText("Open a run to preview a rule.")
        elif proposal is None:
            self.result_label.setText("No preview. Preview shows what the rule would reject; nothing changes until Apply.")
        else:
            cycles = proposal.cycles
            mode = "in all group ratios" if proposal.group_keys else "in free functions (SYNCH)" if proposal.synced else "each in its own function"
            if not cycles:
                self.result_label.setText(f"{proposal.describe()}. Nothing would be rejected.")
            else:
                self.result_label.setText(
                    f"Would reject {len(cycles)} cycle{'s' if len(cycles) != 1 else ''} {mode}: "
                    f"{_cycles_text(analysis, cycles, 10)}. Union: {len(cycles)}. "
                    + ("One ratio chosen; other counts are diagnostic." if proposal.evaluation == "one" else "Highlighted in every group plot."))
            for key in proposal.keys:
                rows = proposal.rejected.get(key, ())
                item = QtWidgets.QListWidgetItem(f"{key}: {len(rows)}" + (f"  (cycles {_cycles_text(analysis, rows, 5)})" if rows else ""))
                item.setData(QtCore.Qt.ItemDataRole.UserRole, key)
                if not rows:
                    item.setForeground(QtGui.QBrush(self.palette().color(QtGui.QPalette.ColorRole.PlaceholderText)))
                item.setToolTip(item.text())
                self.result_list.addItem(item)
        self._fill_history(analysis)

    def _fill_history(self, analysis: Analysis | None) -> None:
        self.history_list.clear()
        if analysis is None:
            self.history_note.setText("")
            return
        history = list(analysis._history_view())
        start = QtWidgets.QListWidgetItem("0  Opened: every valid cycle included")
        self.history_list.addItem(start)
        for number, op in enumerate(history, start=1):
            self.history_list.addItem(QtWidgets.QListWidgetItem(f"{number}  {describe_op(analysis, op)}"))
        current = self.history_list.item(self.history_list.count() - 1)
        font = current.font()
        font.setBold(True)
        current.setFont(font)
        current.setText(current.text() + "   ◀ now")
        for index in range(self.history_list.count()):
            item = self.history_list.item(index)
            item.setToolTip(item.text())
        self.history_list.scrollToItem(current)
        note = f"{len(history)} edit{'s' if len(history) != 1 else ''} applied."
        if analysis.can_redo:
            note += " Undone edits can be redone (Redo)."
        self.history_note.setText(note + " Undo and Redo walk this list.")

    def history_texts(self) -> list[str]:
        return [self.history_list.item(i).text() for i in range(self.history_list.count())]


__all__ = ["RulesPanel", "describe_op"]
