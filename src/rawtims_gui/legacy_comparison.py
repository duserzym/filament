"""The Export tab's read-only legacy Tripoli comparison window."""
from PySide6 import QtCore, QtWidgets

from rawtims.legacy import legacy_comparison
from rawtims_gui.plots import format_number


class LegacyComparisonDialog(QtWidgets.QDialog):
    def __init__(self, analysis, mapping, parent=None):
        super().__init__(parent)
        self.analysis, self.mapping = analysis, mapping
        self.setWindowTitle('Compare with legacy Tripoli (per-ratio)')
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(740, 540)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel('Comparison only · read-only · arithmetic means and per-ratio masks. '
                                'These numbers never enter the contract export.')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.rule_combo = QtWidgets.QComboBox()
        self.rule_combo.addItem('Saved legacy masks, otherwise shared selection', None)
        self.rule_combo.addItem('Chauvenet per ratio (current P and minimum n)', 'chauvenet')
        self.rule_combo.addItem('k-σ per ratio (current k and passes)', 'k_sigma')
        layout.addWidget(self.rule_combo)
        self.source_label = QtWidgets.QLabel()
        self.source_label.setWordWrap(True)
        layout.addWidget(self.source_label)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Ratio / function', 'Arithmetic mean', '% SE', 'n'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        layout.addWidget(QtWidgets.QLabel('Legacy clipboard text · comparison only'))
        self.clipboard_preview = QtWidgets.QPlainTextEdit()
        self.clipboard_preview.setReadOnly(True)
        layout.addWidget(self.clipboard_preview)
        self.copy_button = QtWidgets.QPushButton('Copy legacy clipboard (comparison only)')
        self.copy_button.clicked.connect(self.copy_clipboard)
        layout.addWidget(self.copy_button)
        self.rule_combo.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args):
        self.comparison = legacy_comparison(self.analysis, self.mapping, self.rule_combo.currentData())
        self.source_label.setText(self.comparison.source)
        self.table.setRowCount(len(self.comparison.rows))
        for row, result in enumerate(self.comparison.rows):
            for col, text in enumerate((result.name, format_number(result.stats.mean, 12),
                                        format_number(result.stats.se_pct, 8), str(result.stats.n_used))):
                item = QtWidgets.QTableWidgetItem(text)
                item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(row, col, item)
        self.clipboard_preview.setPlainText(self.comparison.clipboard_text)

    def copy_clipboard(self):
        QtWidgets.QApplication.clipboard().setText(self.comparison.clipboard_text)
