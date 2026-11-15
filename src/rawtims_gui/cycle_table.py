"""The cycle table: block, cycle, time, the plotted functions and the include flag (SPEC F7).

A NumPy-backed model in the role of Studio's ``DataFrameTableModel`` (this
app has no pandas). The Include column is checked when the cycle is used in
every function the edits address (the contract-mapped ones, or the plotted
ones when nothing is mapped), unchecked when it is used in none and partly
checked otherwise. Ticking it asks the window for the same toggle a click on
the plot makes. Excluded values are shown in the danger colour, invalid ones
in grey italics. Cells a previewed rule would reject get an amber background
(the Include cell when any shown function would lose the cycle).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.analysis import Analysis
from rawtims_gui.plots import preview_color
from rawtims_gui.studio.theme import active_theme
from rawtims_gui.studio.widgets import FrozenColumnsView

FIXED_COLUMNS = ("Include", "Block", "Cycle", "Time (s)")
FROZEN_NAMES = ("Block", "Cycle")


class CycleTableModel(QtCore.QAbstractTableModel):
    includeToggled = QtCore.Signal(int, bool)  # row, include

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.analysis: Analysis | None = None
        self.keys: list[str] = []
        self.include_keys: list[str] = []
        self._columns: list[int] = []
        self.preview: dict[str, frozenset[int]] = {}
        self._preview_any: frozenset[int] = frozenset()

    def set_preview(self, preview: Mapping[str, frozenset[int]] | None) -> None:
        self.preview = {key: frozenset(rows) for key, rows in (preview or {}).items()}
        shown = set(self.keys) | set(self.include_keys)
        self._preview_any = frozenset().union(*[rows for key, rows in self.preview.items() if key in shown]) if self.preview else frozenset()
        self.refresh()

    def _preview_brush(self) -> QtGui.QBrush:
        color = QtGui.QColor(preview_color())
        color.setAlpha(70)
        return QtGui.QBrush(color)

    def set_analysis(self, analysis: Analysis | None, keys: Sequence[str], include_keys: Sequence[str]) -> None:
        self.beginResetModel()
        self.analysis = analysis
        self.keys = list(keys) if analysis is not None else []
        self.include_keys = list(include_keys) if analysis is not None else []
        self._columns = [analysis.index(key) for key in self.keys] if analysis is not None else []
        self.endResetModel()

    def refresh(self) -> None:
        if self.rowCount() and self.columnCount():
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1))

    def include_state(self, row: int) -> QtCore.Qt.CheckState:
        analysis = self.analysis
        assert analysis is not None
        columns = [analysis.index(key) for key in self.include_keys] or self._columns
        used = analysis.effective[row, columns] if columns else np.array([True])
        if used.all():
            return QtCore.Qt.CheckState.Checked
        if not used.any():
            return QtCore.Qt.CheckState.Unchecked
        return QtCore.Qt.CheckState.PartiallyChecked

    # ------------------------------------------------------------ Qt API
    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() or self.analysis is None else self.analysis.n_cycles

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() or self.analysis is None else len(FIXED_COLUMNS) + len(self.keys)

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and index.column() == 0:
            flags |= QtCore.Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.analysis is None:
            return None
        analysis = self.analysis
        row, column = index.row(), index.column()
        run = analysis.run
        if column == 0:
            if role == QtCore.Qt.ItemDataRole.CheckStateRole:
                return self.include_state(row)
            if role == QtCore.Qt.ItemDataRole.BackgroundRole and row in self._preview_any:
                return self._preview_brush()
            if role == QtCore.Qt.ItemDataRole.ToolTipRole and row in self._preview_any:
                return "The previewed rule would reject this cycle"
            return None
        if role == QtCore.Qt.ItemDataRole.TextAlignmentRole:
            return int(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        if column < len(FIXED_COLUMNS):
            if role == QtCore.Qt.ItemDataRole.DisplayRole:
                if column == 1:
                    return str(int(run.block[row]))
                if column == 2:
                    return str(int(run.cycle[row]))
                value = float(run.time[row])
                return "" if not np.isfinite(value) else f"{value:.1f}"
            if role == QtCore.Qt.ItemDataRole.ForegroundRole and column == 1:
                position = int(np.flatnonzero(analysis.blocks == run.block[row])[0])
                if not analysis.block_included[position]:
                    return QtGui.QBrush(QtGui.QColor(active_theme().danger))
            return None
        col = self._columns[column - len(FIXED_COLUMNS)]
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            key = self.keys[column - len(FIXED_COLUMNS)]
            return self._preview_brush() if row in self.preview.get(key, ()) else None
        invalid = bool(analysis.invalid[row, col])
        used = bool(analysis.effective[row, col])
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            value = float(analysis.values[row, col])
            return "" if not np.isfinite(value) else f"{value:.7g}"
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            theme = active_theme()
            if invalid:
                return QtGui.QBrush(QtGui.QColor(theme.faint))
            if not used:
                return QtGui.QBrush(QtGui.QColor(theme.danger))
        if role == QtCore.Qt.ItemDataRole.FontRole and (invalid or not used):
            font = QtGui.QFont()
            font.setItalic(invalid)
            font.setStrikeOut(not invalid and not used)
            return font
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return "Invalid value: never used" if invalid else ("Excluded" if not used else None)
        return None

    def setData(self, index: QtCore.QModelIndex, value, role: int = QtCore.Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if index.isValid() and index.column() == 0 and role == QtCore.Qt.ItemDataRole.CheckStateRole:
            include = value in (QtCore.Qt.CheckState.Checked, QtCore.Qt.CheckState.Checked.value)
            self.includeToggled.emit(index.row(), bool(include))
            return True
        return False

    def headerData(self, section: int, orientation: QtCore.Qt.Orientation, role: int = QtCore.Qt.ItemDataRole.DisplayRole):
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            if role == QtCore.Qt.ItemDataRole.ToolTipRole and orientation == QtCore.Qt.Orientation.Horizontal and section >= len(FIXED_COLUMNS):
                return self.keys[section - len(FIXED_COLUMNS)]
            return None
        if orientation == QtCore.Qt.Orientation.Horizontal:
            if section < len(FIXED_COLUMNS):
                return FIXED_COLUMNS[section]
            return self.keys[section - len(FIXED_COLUMNS)]
        return str(section + 1)


class CycleTable(QtWidgets.QTableView):
    """The table view, with function columns paged to fit without horizontal scrolling."""

    rowsSelected = QtCore.Signal(list)
    columnPageChanged = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._first_function = 0
        self._page_capacity = 1
        self._fitting = False
        self.setObjectName("CycleTable")
        self.cycle_model = CycleTableModel(self)
        self.setModel(self.cycle_model)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(24)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setDefaultSectionSize(96)
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.frozen = FrozenColumnsView(self, FROZEN_NAMES)
        self.frozen.setSortingEnabled(False)
        self.frozen.verticalHeader().setDefaultSectionSize(self.verticalHeader().defaultSectionSize())
        self.frozen.verticalHeader().setMinimumSectionSize(self.verticalHeader().minimumSectionSize())
        self.cycle_model.modelReset.connect(self._size_columns)
        self.selectionModel().selectionChanged.connect(self._emit_selection)
        self._quiet = False
        self.apply_theme()

    def _size_columns(self) -> None:
        for column, width in enumerate((64, 52, 54, 70)):
            if column < self.cycle_model.columnCount():
                self.setColumnWidth(column, width)
        self.frozen._refresh()
        self._fit_columns()

    @property
    def visible_function_range(self) -> tuple[int, int, int]:
        total = len(self.cycle_model.keys)
        return self._first_function, min(total, self._first_function + self._page_capacity), total

    def change_column_page(self, direction: int) -> None:
        total = len(self.cycle_model.keys)
        self._first_function = max(0, min(max(0, total - 1), self._first_function + direction * self._page_capacity))
        self._fit_columns()

    def _fit_columns(self) -> None:
        if self._fitting or not hasattr(self, "frozen"):
            return
        self._fitting = True
        try:
            fixed = len(FIXED_COLUMNS)
            total = len(self.cycle_model.keys)
            available = max(1, self.viewport().width() - sum(self.columnWidth(c) for c in range(fixed)))
            self._page_capacity = max(1, available // 116)
            self._first_function = min(self._first_function, max(0, total - 1))
            count = min(self._page_capacity, total - self._first_function)
            width = available // max(1, count)
            for position in range(total):
                shown = self._first_function <= position < self._first_function + count
                self.setColumnHidden(fixed + position, not shown)
                if shown:
                    self.setColumnWidth(fixed + position, width)
            self.horizontalScrollBar().setValue(0)
            self.frozen.update_geometry()
        finally:
            self._fitting = False
        self.columnPageChanged.emit()

    def apply_theme(self) -> None:
        theme = active_theme()
        self.frozen.setStyleSheet(
            f"QTableView#FrozenColumns {{ border: none; border-right: 1px solid {theme.input_border}; "
            f"padding: 0px; border-radius: 0px; background: {theme.surface}; }}")
        self.frozen.verticalHeader().setDefaultSectionSize(self.verticalHeader().defaultSectionSize())
        self.cycle_model.refresh()

    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.selectionModel().selectedRows()})

    def select_rows(self, rows: Sequence[int]) -> None:
        """Select rows without echoing the selection back."""
        self._quiet = True
        try:
            selection = QtCore.QItemSelection()
            last = self.cycle_model.columnCount() - 1
            for row in sorted(set(rows)):
                if 0 <= row < self.cycle_model.rowCount():
                    selection.select(self.cycle_model.index(row, 0), self.cycle_model.index(row, last))
            self.selectionModel().select(selection, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
            if rows:
                self.scrollTo(self.cycle_model.index(min(rows), 1))
        finally:
            self._quiet = False

    def _emit_selection(self, *_args) -> None:
        if not self._quiet:
            self.rowsSelected.emit(self.selected_rows())

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit_columns()
        self.frozen.update_geometry()

    def updateGeometries(self) -> None:  # noqa: N802 - Qt API
        super().updateGeometries()
        if hasattr(self, "frozen"):
            self.frozen.update_geometry()


__all__ = ["CycleTable", "CycleTableModel"]
