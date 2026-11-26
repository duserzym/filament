"""Separate diagnostic expression library, member composition and block comparison."""
from dataclasses import replace

import numpy as np
from PySide6 import QtCore, QtWidgets

from rawtims.block_diagnostics import (
    java_snapshot_block_diagnostic,
    member_block_indices,
    standard_block_diagnostic,
)
from rawtims.composition import Composition, CompositionBook, Member, compose
from rawtims.expressions import ExpressionSpec, ratio_spec
from rawtims.model import uuid7
from rawtims.stats import block_stats


def _text(value):
    return f'{value:.9g}' if isinstance(value, (float, np.floating)) and np.isfinite(value) else '—' if isinstance(value, (float, np.floating)) else str(value)


class CycleModel(QtCore.QAbstractTableModel):
    headers = ('Member', 'Cycle', 'Block', 'Time (s)', 'Value', 'Use')

    def __init__(self, table, column, names, parent=None):
        super().__init__(parent)
        self.table, self.column, self.names = table, column, names

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.table.cycle)

    def columnCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else 6

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self.headers[section] if orientation == QtCore.Qt.Orientation.Horizontal else str(section + 1)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None
        row, col = index.row(), self.column
        t = self.table
        values = (self.names[t.run_ids[row]], t.cycle[row], t.block[row], t.time[row], t.values[row, col],
                  'Invalid' if t.invalid[row, col] else 'Included' if t.included[row, col] else 'Excluded')
        return _text(values[index.column()])


class CompositionDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.sources = {a.run.run_id: a for a in window.workspace.analyses()}
        self.book = CompositionBook.from_dict(window.workspace.composition)
        self.recipe = None
        self.table = None
        self.setWindowTitle('Composable analysis · diagnostics')
        self.resize(900, 690)
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel('Expressions and concatenated acquisitions are saved as separate diagnostic objects. '
                                 'Fraction exports and the cycle estimator use the original analyses.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QtWidgets.QHBoxLayout()
        layout.addLayout(row)
        self.objects = QtWidgets.QComboBox()
        self.objects.setMinimumContentsLength(18)
        self.objects.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.objects, 1)
        for label, callback in [('Current run', self.current_run), ('Concatenate…', self.members_dialog),
                                ('Delete object', self.remove_object), ('Undo', self.undo), ('Redo', self.redo)]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.history = QtWidgets.QLabel()
        layout.addWidget(self.history)
        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        editor = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout(editor)
        inputs = QtWidgets.QFormLayout()
        form.addLayout(inputs)
        self.library = QtWidgets.QComboBox()
        inputs.addRow('Expression library', self.library)
        self.output_key, self.output_name, self.formula = QtWidgets.QLineEdit(), QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.output_key.setPlaceholderText('derived:user1')
        self.output_name.setPlaceholderText('Diagnostic name')
        self.formula.setPlaceholderText('[exact function key] / 2')
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(['other', 'ratio', 'intensity'])
        for label, widget in [('Stable output key', self.output_key), ('Name', self.output_name), ('Expression', self.formula), ('Output kind', self.kind)]:
            inputs.addRow(label, widget)
        help_text = QtWidgets.QLabel('Use [exact key], + − * / ^, log (base 10), ln, exp, sqrt and parentheses. '
                                     'Nonfinite/domain failures are flagged per cycle; uncertainties are not propagated.')
        help_text.setWordWrap(True)
        form.addWidget(help_text)
        buttons = QtWidgets.QHBoxLayout()
        form.addLayout(buttons)
        for label, callback in [('Save expression', self.save_expression), ('New expression', self.new_expression), ('Delete expression', self.remove_expression)]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        ratio_box = QtWidgets.QGroupBox('Build a ratio from existing columns')
        ratio_form = QtWidgets.QFormLayout(ratio_box)
        self.numerator, self.denominator = QtWidgets.QComboBox(), QtWidgets.QComboBox()
        ratio_form.addRow('Numerator', self.numerator)
        ratio_form.addRow('Denominator', self.denominator)
        build = QtWidgets.QPushButton('Fill ratio expression')
        build.clicked.connect(self.fill_ratio)
        ratio_form.addRow(build)
        form.addWidget(ratio_box)
        form.addStretch()
        self.tabs.addTab(editor, 'Expressions')
        cycle_page = QtWidgets.QWidget()
        cycle_layout = QtWidgets.QVBoxLayout(cycle_page)
        self.function = QtWidgets.QComboBox()
        cycle_layout.addWidget(self.function)
        self.cycles = QtWidgets.QTableView()
        self.cycles.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        cycle_layout.addWidget(self.cycles)
        self.tabs.addTab(cycle_page, 'Cycles')
        block_page = QtWidgets.QWidget()
        block_layout = QtWidgets.QVBoxLayout(block_page)
        self.block_function = QtWidgets.QComboBox()
        block_layout.addWidget(self.block_function)
        self.estimators = QtWidgets.QLabel()
        self.estimators.setWordWrap(True)
        self.estimators.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        block_layout.addWidget(self.estimators)
        self.blocks = QtWidgets.QTableWidget(0, 6)
        self.blocks.setHorizontalHeaderLabels(['Block / member', 'Used', 'Center', 'SD', 'SE', 'Scale'])
        self.blocks.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.blocks.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        block_layout.addWidget(self.blocks)
        self.tabs.addTab(block_page, 'Block diagnostics')
        self.provenance = QtWidgets.QPlainTextEdit()
        self.provenance.setReadOnly(True)
        self.tabs.addTab(self.provenance, 'Members / provenance')
        self.notice = QtWidgets.QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        layout.addWidget(self.notice)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.objects.currentIndexChanged.connect(self.load_object)
        self.library.currentIndexChanged.connect(self.load_expression)
        self.function.currentIndexChanged.connect(self.refresh_cycles)
        self.block_function.currentIndexChanged.connect(self.refresh_blocks)
        self.refresh_objects()
        if window.analysis:
            self.current_run()

    def current_run(self):
        a = self.window.analysis
        if a:
            key = 'run:' + a.run.run_id
            self.recipe = next((r for r in self.book.objects if r.key == key), Composition(key, a.run.raw.name, (Member(a.run.run_id),)))
            self.refresh()

    def refresh_objects(self, key=None):
        self.objects.blockSignals(True)
        self.objects.clear()
        for r in self.book.objects:
            self.objects.addItem(r.name, r.key)
        self.objects.setCurrentIndex(self.objects.findData(key) if key else -1)
        self.objects.blockSignals(False)
        state = self.book.to_dict()
        self.history.setText(f'Composition history: {state["applied"]} applied · {len(state["events"]) - state["applied"]} redo')

    def load_object(self):
        self.recipe = next((r for r in self.book.objects if r.key == self.objects.currentData()), None)
        self.refresh()

    def changed(self, key):
        self.window.workspace.composition = self.book.to_dict()
        self.window._after_edit()
        self.refresh_objects(key)
        self.recipe = next((r for r in self.book.objects if r.key == key), None)
        if self.recipe is None and self.window.analysis:
            self.current_run()
        else:
            self.refresh()

    def save_recipe(self, recipe):
        try:
            self.book.put(recipe, self.sources)
        except ValueError as error:
            self.notice.setText(str(error))
            return False
        self.changed(recipe.key)
        return True

    def save_expression(self):
        if not self.recipe:
            return
        try:
            spec = ExpressionSpec(self.output_key.text().strip(), self.output_name.text().strip(), self.formula.text(), self.kind.currentText())
            specs = tuple(s for s in self.recipe.expressions if s.key != spec.key) + (spec,)
            self.save_recipe(replace(self.recipe, expressions=specs))
        except ValueError as error:
            self.notice.setText(str(error))

    def new_expression(self):
        used = {s.key for s in self.recipe.expressions} if self.recipe else set()
        i = 1
        while f'derived:user{i}' in used:
            i += 1
        self.output_key.setText(f'derived:user{i}')
        self.output_name.clear()
        self.formula.clear()
        self.kind.setCurrentText('other')

    def load_expression(self):
        if not self.recipe:
            return
        spec = next((s for s in self.recipe.expressions if s.key == self.library.currentData()), None)
        if spec:
            self.output_key.setText(spec.key)
            self.output_name.setText(spec.name)
            self.formula.setText(spec.expression)
            self.kind.setCurrentText(spec.kind)
        else:
            self.new_expression()

    def remove_expression(self):
        if self.recipe and self.library.currentData():
            self.save_recipe(replace(self.recipe, expressions=tuple(s for s in self.recipe.expressions if s.key != self.library.currentData())))

    def remove_object(self):
        if self.recipe and any(r.key == self.recipe.key for r in self.book.objects):
            key = self.recipe.key
            self.book.remove(key)
            self.changed(key)

    def undo(self):
        state = self.book.to_dict()
        key = state['events'][state['applied'] - 1]['key'] if self.book.can_undo else None
        if self.book.undo():
            self.changed(key)

    def redo(self):
        state = self.book.to_dict()
        key = state['events'][state['applied']]['key'] if self.book.can_redo else None
        if self.book.redo():
            self.changed(key)

    def fill_ratio(self):
        if not self.table:
            return
        try:
            a = next(f for f in self.table.functions if f.key == self.numerator.currentData())
            b = next(f for f in self.table.functions if f.key == self.denominator.currentData())
            if a.unit != b.unit or a.kind != b.kind:
                raise ValueError('Choose columns with matching kinds and units; no unit conversion is applied')
            spec = ratio_spec(self.output_key.text().strip(), self.output_name.text().strip() or 'Derived ratio', a.key, b.key)
            self.output_name.setText(spec.name)
            self.formula.setText(spec.expression)
            self.kind.setCurrentText('ratio')
        except ValueError as error:
            self.notice.setText(str(error))

    def members_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Concatenate matching acquisitions')
        dialog.resize(700, 430)
        layout = QtWidgets.QVBoxLayout(dialog)
        label = QtWidgets.QLabel('Select members and optional comma-separated original block numbers. '
                                 'Recorded times determine order; overlapping times or different method/function/unit identities are refused.')
        label.setWordWrap(True)
        layout.addWidget(label)
        name = QtWidgets.QLineEdit('Concatenated diagnostic')
        layout.addWidget(name)
        table = QtWidgets.QTableWidget(len(self.sources), 3)
        table.setHorizontalHeaderLabels(['Use', 'Acquisition', 'Blocks (empty = all)'])
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for row, a in enumerate(self.sources.values()):
            check = QtWidgets.QTableWidgetItem()
            check.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(QtCore.Qt.CheckState.Unchecked)
            check.setData(QtCore.Qt.ItemDataRole.UserRole, a.run.run_id)
            table.setItem(row, 0, check)
            title = QtWidgets.QTableWidgetItem(a.run.raw.name)
            title.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            table.setItem(row, 1, title)
            table.setItem(row, 2, QtWidgets.QTableWidgetItem(''))
        layout.addWidget(table)
        error_label = QtWidgets.QLabel()
        error_label.setWordWrap(True)
        layout.addWidget(error_label)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        def save():
            try:
                members = tuple(Member(table.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole), tuple(int(b.strip()) for b in table.item(r, 2).text().split(',') if b.strip()))
                                for r in range(table.rowCount()) if table.item(r, 0).checkState() == QtCore.Qt.CheckState.Checked)
                recipe = Composition('concat:' + str(uuid7()), name.text(), members)
                if self.save_recipe(recipe):
                    dialog.accept()
                else:
                    error_label.setText(self.notice.text())
            except ValueError as error:
                error_label.setText(str(error))
        buttons.accepted.connect(save)
        dialog.exec()

    def refresh(self):
        self.table = None
        self.notice.clear()
        if self.recipe:
            try:
                self.table = compose(self.recipe, self.sources)
            except ValueError as error:
                self.notice.setText(str(error))
        self.library.blockSignals(True)
        self.library.clear()
        if self.recipe:
            for spec in self.recipe.expressions:
                self.library.addItem(spec.name, spec.key)
        self.library.blockSignals(False)
        self.load_expression()
        for combo in (self.function, self.block_function, self.numerator, self.denominator):
            old = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if self.table:
                for f in self.table.functions:
                    combo.addItem(f.name if f.name == f.key else f.name + ' · ' + f.key, f.key)
                combo.setCurrentIndex(max(0, combo.findData(old)))
            combo.blockSignals(False)
        if self.table:
            self.notice.setText('; '.join(issue for d in self.table.derived for issue in d.issues))
            lines = [self.recipe.name, 'Member boundaries (row offsets): ' + str(self.table.boundaries)]
            for m in self.recipe.members:
                a = self.sources[m.run_id]
                lines += ['', a.run.raw.name, 'Run: ' + m.run_id, 'SHA-256: ' + a.run.raw.sha256,
                          'Blocks: ' + (str(m.blocks) if m.blocks else 'all'),
                          'Start: ' + str(a.run.metadata.analysis_start)]
            lines += ['', 'Cycle/block IDs and elapsed seconds remain those of each member.',
                      'Recorded acquisition timestamps are start + member elapsed seconds.']
            self.provenance.setPlainText('\n'.join(lines))
        else:
            self.provenance.clear()
        self.refresh_cycles()
        self.refresh_blocks()

    def refresh_cycles(self):
        if self.table and self.function.currentIndex() >= 0:
            names = {rid: a.run.raw.name for rid, a in self.sources.items()}
            self.cycles.setModel(CycleModel(self.table, self.function.currentIndex(), names, self.cycles))
        else:
            self.cycles.setModel(None)

    def refresh_blocks(self):
        self.blocks.setRowCount(0)
        self.estimators.clear()
        if self.table is None or self.block_function.currentIndex() < 0:
            return
        t, col = self.table, self.block_function.currentIndex()
        f = t.functions[col]
        block = member_block_indices(t.run_ids, t.block)
        mode = self.sources[t.run_ids[0]].settings.stat_mode
        kwargs = {'is_ratio': f.is_ratio, 'ratio_mode': mode}
        values, include = t.values[:, col], t.included[:, col]
        labels = []
        try:
            for fn in (standard_block_diagnostic, java_snapshot_block_diagnostic):
                diagnostic = fn(values, include, block, **kwargs)
                result = diagnostic.result
                labels.append(f'{diagnostic.label}: {_text(result.mean)} · 1σ (statistics scale) {_text(result.sigma)} · '
                              f'{diagnostic.dispersion_label}: {_text(result.mswd)} · {result.n_blocks} blocks\n{diagnostic.notice}')
            stats = block_stats(values, include, block, **kwargs)
        except (ValueError, OverflowError) as error:
            self.estimators.setText(f'Diagnostic unavailable: {error}')
            return
        self.estimators.setText('\n'.join(labels))
        self.blocks.setRowCount(len(stats))
        for row, (b, s) in enumerate(stats.items()):
            source_row = int(np.flatnonzero(block == b)[0])
            a = self.sources[t.run_ids[source_row]]
            cells = (str(t.block[source_row]) + ' · ' + a.run.raw.name, s.n_used, s.center, s.sd, s.se, 'ln(ratio)' if s.mode == 'geometric' else 'linear')
            for column, value in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(_text(value))
                item.setToolTip(str(value))
                self.blocks.setItem(row, column, item)


def show_composition(window):
    CompositionDialog(window).exec()
