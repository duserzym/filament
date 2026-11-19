"""The inspector's Stats tab (SPEC F11). Rules, Corrections and Export have their own modules.

Wall shows the selected function's SD/SE and its per-block statistics.
The one-release classic fallback retains its function summary table. Double-clicking
any block row toggles inclusion through the same shared Analysis history.
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
from rawtims_gui.studio.widgets import set_table_item

STATS_COLUMNS = ("Function", "Mean", "% SE", "n")
BLOCK_COLUMNS = ("Block", "Mean", "SE", "% SE", "n")


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
    # The numbers keep their full width; the name column gives way and elides (full name in the tooltip).
    header = table.horizontalHeader()
    header.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
    header.setMinimumSectionSize(36)
    header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
    for column in range(1, len(columns)):
        header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    return table


class StatsPanel(QtWidgets.QWidget):
    blockToggleRequested = QtCore.Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, detail_only: bool = False) -> None:
        super().__init__(parent)
        self.detail_only = detail_only
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
        self.table.setVisible(not detail_only)
        self.detail = QtWidgets.QLabel()
        self.detail.setWordWrap(True)
        self.detail.setObjectName("SecondaryText")
        self.detail.setVisible(detail_only)
        layout.addWidget(self.detail)
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
        self.weighted = QtWidgets.QLabel()
        self.weighted.setWordWrap(True)
        self.weighted.setObjectName("BlockWeightedMean")
        layout.addWidget(self.weighted)
        self.analysis: Analysis | None = None
        self.mapping: ElementMapping | None = None
        self.rows: list[StatsRow] = []

    def update_stats(self, analysis: Analysis | None, mapping: ElementMapping | None, plotted: Sequence[str]) -> None:
        self.analysis, self.mapping = analysis, mapping
        self.rows = stats_rows(analysis, mapping, plotted) if analysis is not None else []
        mode = analysis.settings.stat_mode if analysis is not None else "arithmetic"
        self.note.setText(
            "Open a run to see its statistics." if analysis is None else
            f"{'Geometric' if mode == 'geometric' else 'Arithmetic'} means for ratios, arithmetic for intensities. "
            "% SE is the 1σ standard error of the mean. Bold: mapped to the contract."
        )
        if self.detail_only and analysis is not None:
            self.note.setText(f"{'Geometric' if mode == 'geometric' else 'Arithmetic'} means for ratios. "
                              "Double-click a block row to toggle inclusion. % SE is 1σ.")
        self.table.setRowCount(len(self.rows))
        for index, row in enumerate(self.rows):
            stats = row.stats
            tip = f"{row.label} → {row.ratio} (contract)" if row.ratio else row.label
            set_table_item(self.table, index, 0, _item(row.label, bold=row.ratio is not None, tooltip=tip))
            set_table_item(self.table, index, 1, _item(format_number(stats.mean), align_right=True, tooltip=repr(stats.mean)))
            set_table_item(self.table, index, 2, _item(format_number(stats.se_pct, 3), align_right=True))
            set_table_item(self.table, index, 3, _item(f"{stats.n_used}/{stats.n_total}", align_right=True))
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
            self.weighted.clear()
            return
        mapped = self._mapped(key)
        if mapped is not None and (mapped.inverted or not analysis.function(key).is_ratio):
            values, include = mapped_values(analysis, mapped)
            per_block = _stats.block_stats(values, include, analysis.run.block, is_ratio=True, ratio_mode=analysis.settings.stat_mode)  # type: ignore[arg-type]
            weighted = _stats.block_weighted_mean(values, include, analysis.run.block, is_ratio=True,
                                                 ratio_mode=analysis.settings.stat_mode, convention="standard")
        else:
            per_block = analysis.block_stats(key)
            weighted = analysis.block_weighted_mean(key, convention="standard")
        scale = " on ln scale" if weighted.mode == "geometric" else ""
        self.weighted.setText(f"Weighted mean of block means (1/SE²{scale}): {format_number(weighted.mean)} ± "
                              f"{format_number(weighted.sigma_pct)} % SE (1σ)\nMSWD of block means: "
                              f"{format_number(weighted.mswd)} · {weighted.n_blocks} blocks. "
                              "Fraction export uses the cycle mean.")
        stats = next((row.stats for row in self.rows if row.key == key), None)
        if stats is not None:
            self.detail.setText(f"Function detail · {stats.mode}{' (ln scale)' if stats.mode == 'geometric' else ''}\n"
                                f"Mean {format_number(stats.mean)} · n {stats.n_used}/{stats.n_total}\n"
                                f"1σ SD {format_number(stats.sd)} · 1σ SE {format_number(stats.se)}\n"
                                f"% SE (1σ) {format_number(stats.se_pct)}")
        theme = active_theme()
        self.block_table.setRowCount(len(analysis.blocks))
        for index, (block, included) in enumerate(zip(analysis.blocks, analysis.block_included)):
            stats = per_block.get(int(block))
            label = str(int(block)) if included else f"{int(block)} (excluded)"
            cells = [
                _item(label),
                _item(format_number(stats.mean) if stats else "–", align_right=True),
                _item(format_number(stats.se, 3) if stats else "–", align_right=True),
                _item(format_number(stats.se_pct, 3) if stats else "–", align_right=True),
                _item(f"{stats.n_used}/{stats.n_total}" if stats else "–", align_right=True),
            ]
            for column, cell in enumerate(cells):
                if not included:
                    cell.setForeground(QtGui.QBrush(QtGui.QColor(theme.danger)))
                set_table_item(self.block_table, index, column, cell)

    def _mapped(self, key: str) -> MappedRatio | None:
        for row in self.rows:
            if row.key == key and row.ratio is not None and self.mapping is not None:
                return self.mapping.ratios[row.ratio]
        return None

    def _block_double_clicked(self, row: int, _column: int) -> None:
        if self.analysis is not None and 0 <= row < len(self.analysis.blocks):
            self.blockToggleRequested.emit(int(self.analysis.blocks[row]))


__all__ = ["StatsPanel", "StatsRow", "stats_rows"]
