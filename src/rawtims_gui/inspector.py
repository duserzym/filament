"""The inspector's Stats tab (SPEC F11; the Rules, Corrections and Export tabs come in the next step).

The top table lists the functions mapped to contract ratios (bold, in
contract order) and then the other plotted functions: mean, 1σ % standard
error of the mean (Tripoli's smaller-side convention for geometric ratio
means) and cycles used / total. The block table below shows the same per
block for one function; double-clicking a block toggles it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims import stats as _stats
from rawtims.analysis import Analysis
from rawtims.mapping import ElementMapping, MappedRatio, mapped_values, ratio_stats
from rawtims_gui.plots import format_number, plot_stats
from rawtims_gui.studio.theme import active_theme

STATS_COLUMNS = ("Function", "Mean", "% SE", "n")
BLOCK_COLUMNS = ("Block", "Mean", "% SE", "n")


@dataclass(frozen=True)
class StatsRow:
    key: str
    label: str
    stats: _stats.Stats
    ratio: str | None  # contract ratio when mapped


def stats_rows(analysis: Analysis, mapping: ElementMapping | None, plotted: Sequence[str]) -> list[StatsRow]:
    rows: list[StatsRow] = []
    seen: set[str] = set()
    if mapping is not None:
        for ratio, mapped in mapping.ratios.items():
            label = f"1/({mapped.name})" if mapped.inverted else mapped.key
            rows.append(StatsRow(mapped.key, label, ratio_stats(analysis, mapped), ratio))
            if not mapped.inverted:
                seen.add(mapped.key)
    for key in plotted:
        if key not in seen:
            rows.append(StatsRow(key, key, plot_stats(analysis, mapping, key), None))
            seen.add(key)
    return rows


def _item(text: str, *, align_right: bool = False, bold: bool = False, tooltip: str | None = None) -> QtWidgets.QTableWidgetItem:
    item = QtWidgets.QTableWidgetItem(text)
    item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
    if align_right:
        item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
    if bold:
        font = QtGui.QFont()
        font.setBold(True)
        item.setFont(font)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def _table(columns: Sequence[str]) -> QtWidgets.QTableWidget:
    table = QtWidgets.QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(24)
    table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setWordWrap(False)
    table.setStyleSheet("QTableWidget { font-size: 12px; } QHeaderView::section { font-size: 12px; padding: 4px 6px; }")
    table.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
    header = table.horizontalHeader()
    header.setMaximumSectionSize(150)
    header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
    for column in range(2, len(columns)):
        header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    return table


class StatsPanel(QtWidgets.QWidget):
    blockToggleRequested = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(6)
        self.note = QtWidgets.QLabel("Open a run to see its statistics.")
        self.note.setObjectName("SecondaryText")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.table = _table(STATS_COLUMNS)
        self.table.setObjectName("StatsTable")
        layout.addWidget(self.table, 3)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        label = QtWidgets.QLabel("Blocks of")
        label.setObjectName("SecondaryText")
        row.addWidget(label)
        self.block_function = QtWidgets.QComboBox()
        self.block_function.setObjectName("BlockFunction")
        self.block_function.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.block_function.setMinimumContentsLength(8)
        self.block_function.currentIndexChanged.connect(self._fill_blocks)
        row.addWidget(self.block_function, 1)
        layout.addLayout(row)
        self.block_table = _table(BLOCK_COLUMNS)
        self.block_table.setObjectName("BlockStatsTable")
        self.block_table.setToolTip("Double-click a block to include or exclude it")
        self.block_table.cellDoubleClicked.connect(self._block_double_clicked)
        layout.addWidget(self.block_table, 2)
        self.analysis: Analysis | None = None
        self.mapping: ElementMapping | None = None
        self.rows: list[StatsRow] = []

    def update_stats(self, analysis: Analysis | None, mapping: ElementMapping | None, plotted: Sequence[str]) -> None:
        self.analysis, self.mapping = analysis, mapping
        self.rows = stats_rows(analysis, mapping, plotted) if analysis is not None else []
        mode = analysis.settings.stat_mode if analysis is not None else "geometric"
        self.note.setText(
            "Open a run to see its statistics." if analysis is None else
            f"{'Geometric' if mode == 'geometric' else 'Arithmetic'} means for ratios, arithmetic for intensities. "
            "% SE is the 1σ standard error of the mean. Bold: mapped to the contract."
        )
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            stats = row.stats
            tip = f"{row.label} → {row.ratio} (contract)" if row.ratio else row.label
            self.table.setItem(index, 0, _item(row.label, bold=row.ratio is not None, tooltip=tip))
            self.table.setItem(index, 1, _item(format_number(stats.mean), align_right=True, tooltip=repr(stats.mean)))
            self.table.setItem(index, 2, _item(format_number(stats.se_pct, 3), align_right=True))
            self.table.setItem(index, 3, _item(f"{stats.n_used}/{stats.n_total}", align_right=True))
        current = self.block_function.currentData()
        self.block_function.blockSignals(True)
        self.block_function.clear()
        for row in self.rows:
            self.block_function.addItem(row.label, row.key)
        if current is not None and self.block_function.findData(current) >= 0:
            self.block_function.setCurrentIndex(self.block_function.findData(current))
        self.block_function.blockSignals(False)
        self._fill_blocks()

    def _fill_blocks(self, *_args) -> None:
        analysis = self.analysis
        key = self.block_function.currentData()
        if analysis is None or key is None:
            self.block_table.setRowCount(0)
            return
        mapped = self._mapped(key)
        if mapped is not None:
            values, include = mapped_values(analysis, mapped)
            per_block = _stats.block_stats(values, include, analysis.run.block, is_ratio=True, ratio_mode=analysis.settings.stat_mode)  # type: ignore[arg-type]
        else:
            per_block = analysis.block_stats(key)
        theme = active_theme()
        self.block_table.setRowCount(len(analysis.blocks))
        for index, (block, included) in enumerate(zip(analysis.blocks, analysis.block_included)):
            stats = per_block.get(int(block))
            label = str(int(block)) if included else f"{int(block)} (excluded)"
            cells = [
                _item(label),
                _item(format_number(stats.mean) if stats else "–", align_right=True),
                _item(format_number(stats.se_pct, 3) if stats else "–", align_right=True),
                _item(f"{stats.n_used}/{stats.n_total}" if stats else "–", align_right=True),
            ]
            for column, cell in enumerate(cells):
                if not included:
                    cell.setForeground(QtGui.QBrush(QtGui.QColor(theme.danger)))
                self.block_table.setItem(index, column, cell)

    def _mapped(self, key: str) -> MappedRatio | None:
        for row in self.rows:
            if row.key == key and row.ratio is not None and self.mapping is not None:
                return self.mapping.ratios[row.ratio]
        return None

    def _block_double_clicked(self, row: int, _column: int) -> None:
        if self.analysis is not None and 0 <= row < len(self.analysis.blocks):
            self.blockToggleRequested.emit(int(self.analysis.blocks[row]))


def placeholder_tab(text: str) -> QtWidgets.QWidget:
    page = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(page)
    layout.setContentsMargins(4, 16, 4, 4)
    label = QtWidgets.QLabel(text)
    label.setObjectName("SecondaryText")
    label.setWordWrap(True)
    label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop)
    layout.addWidget(label)
    layout.addStretch(1)
    return page


__all__ = ["StatsPanel", "StatsRow", "placeholder_tab", "stats_rows"]
