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

RULES = {"chauvenet": "Chauvenet", "k_sigma": "k-σ, iterative"}
SCOPES = {"run": "Whole run", "block": "Per block"}
FUNCTION_SETS = {"mapped": "Contract ratios", "plotted": "Plotted ratios"}
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
        self.function_combo.setToolTip("The functions the rule examines: those mapped to the contract, or the ratios plotted now")
        form.addRow("Functions", self.function_combo)
        self.synch_box = QtWidgets.QCheckBox("SYNCH (union in all)")
        self.synch_box.setObjectName("RuleSynch")
        self.synch_box.setToolTip("On: a cycle any examined function flags is excluded in every function. Off: each function loses only its own cycles.")
        form.addRow("", self.synch_box)
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
        self.result_list.setStyleSheet("QListWidget { font-size: 12px; }")
        outer.addWidget(self.result_list, 2)

        history_title = QtWidgets.QLabel("History")
        history_title.setObjectName("SectionTitle")
        outer.addWidget(history_title)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.setObjectName("HistoryList")
        self.history_list.setMinimumHeight(80)
        self.history_list.setWordWrap(True)
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
        self.function_combo.currentIndexChanged.connect(self._edited)
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
        }

    def set_rule(self, rule: str) -> None:
        self.rule_combo.setCurrentIndex(self.rule_combo.findData(rule))

    def _rule_changed(self, *_args) -> None:
        self.param_stack.setCurrentIndex(0 if self.rule_combo.currentData() == "chauvenet" else 1)
        self.note.setVisible(self.rule_combo.currentData() == "chauvenet")
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
                self.synch_box.setChecked(settings.synced)
            self.param_stack.setCurrentIndex(0 if self.rule_combo.currentData() == "chauvenet" else 1)
        finally:
            self._loading = False
        self.apply_button.setEnabled(proposal is not None and not proposal.is_empty)
        self.discard_button.setEnabled(proposal is not None)
        self.result_list.clear()
        if analysis is None:
            self.result_label.setText("Open a run to preview a rule.")
        elif proposal is None:
            self.result_label.setText("No preview. Preview shows what the rule would reject; nothing changes until Apply.")
        else:
            cycles = proposal.cycles
            mode = "in every function (SYNCH)" if proposal.synced else "each in its own function"
            if not cycles:
                self.result_label.setText(f"{proposal.describe()}. Nothing would be rejected.")
            else:
                self.result_label.setText(
                    f"Would reject {len(cycles)} cycle{'s' if len(cycles) != 1 else ''} {mode}: "
                    f"{_cycles_text(analysis, cycles, 10)}. Highlighted on the plots and in the table.")
            for key in proposal.keys:
                rows = proposal.rejected.get(key, ())
                item = QtWidgets.QListWidgetItem(f"{key}: {len(rows)}" + (f"  (cycles {_cycles_text(analysis, rows, 5)})" if rows else ""))
                item.setData(QtCore.Qt.ItemDataRole.UserRole, key)
                if not rows:
                    item.setForeground(QtGui.QBrush(self.palette().color(QtGui.QPalette.ColorRole.PlaceholderText)))
                self.result_list.addItem(item)
        self._fill_history(analysis)

    def _fill_history(self, analysis: Analysis | None) -> None:
        self.history_list.clear()
        if analysis is None:
            self.history_note.setText("")
            return
        history = analysis.history
        start = QtWidgets.QListWidgetItem("0  Opened: every valid cycle included")
        self.history_list.addItem(start)
        for number, op in enumerate(history, start=1):
            self.history_list.addItem(QtWidgets.QListWidgetItem(f"{number}  {describe_op(analysis, op)}"))
        current = self.history_list.item(self.history_list.count() - 1)
        font = current.font()
        font.setBold(True)
        current.setFont(font)
        current.setText(current.text() + "   ◀ now")
        self.history_list.scrollToItem(current)
        note = f"{len(history)} edit{'s' if len(history) != 1 else ''} applied."
        if analysis.can_redo:
            note += " Undone edits can be redone (Redo)."
        self.history_note.setText(note + " Undo and Redo walk this list.")

    def history_texts(self) -> list[str]:
        return [self.history_list.item(i).text() for i in range(self.history_list.count())]


__all__ = ["RulesPanel", "describe_op"]
