"""IsotopX IonVantage ``.xls`` workbooks (IsoWorks run workbooks, older Phoenix/IsoprobeT software).

Only two sheets are read, on demand:

* ``CYCLE``: A1 is ``CYCLE Data``. The row whose column B is ``Function:``
  names the functions from column C on. The per-cycle table starts after the
  row whose columns A and B are ``Cycle`` and ``Time (s)`` (row 16 in every
  file seen, but located, not assumed) and ends at the first row without a
  cycle number. Values are IonVantage/IsoWorks-processed functions.
* ``CTRL``: label/value pairs (label text ending in ``:``, value in the next
  column to the right), found by label text rather than by coordinates.

Block numbers. With ``Beam Interpolation (BI)`` on, IonVantage writes one
more cycle row per block than the method's ``Cycles per Block``. Evidence
from the fixtures: the Boise State workbook (15 cycles per block, BI on) has
16 cycles per block in the ``BLOCK`` sheet's ``Total`` row and the long
inter-block time gaps fall after cycles 16, 32, 48 …; KU GHR1 Pb (10, BI on)
has ``Total`` 11 and gaps every 11 cycles; KU GHR1 U and NBS981 (BI off) have
110 and 15 as written. Tripoli adds 1 for BI in the same way. So the block
size is ``Cycles per Block + BI`` and block = (cycle − 1) // that + 1;
``RunMetadata.cycles_per_block`` holds that row count and
``extra["cycles_per_block_method"]`` the method's value.
"""

from __future__ import annotations

import os
import re
from typing import Any

import numpy as np
from xlrd.biffh import XL_CELL_BOOLEAN, XL_CELL_NUMBER, XL_CELL_TEXT

from rawtims.model import FORMAT_IONVANTAGE_XLS, RawFile, Run, RunMetadata
from rawtims.readers._xls import open_xls
from rawtims.readers.common import assemble_run, completion, parse_instrument_datetime, to_int
from rawtims.readers.functions import build_functions

CYCLE_SHEET = "CYCLE"
CTRL_SHEET = "CTRL"
CYCLE_TITLE = "CYCLE Data"


class IonVantageError(ValueError):
    """The workbook is an IonVantage file but its cycle table cannot be read."""


def is_ionvantage_book(book) -> tuple[bool, str]:
    """(True, "") for a workbook with a CYCLE sheet whose A1 is 'CYCLE Data', else (False, reason)."""
    if CYCLE_SHEET not in book.sheet_names():
        return False, "Excel workbook without a CYCLE sheet (not an IonVantage run workbook)"
    sheet = book.sheet_by_name(CYCLE_SHEET)
    title = sheet.cell_value(0, 0) if sheet.nrows and sheet.ncols else ""
    if not (isinstance(title, str) and title.strip() == CYCLE_TITLE):
        return False, f"Excel workbook whose CYCLE sheet does not start with '{CYCLE_TITLE}'"
    return True, ""


def _cell(sheet, row: int, col: int) -> Any:
    """A cell as a Python value: str (stripped), float, bool, or None for blanks and errors."""
    if row >= sheet.nrows or col >= sheet.ncols:
        return None
    cell = sheet.cell(row, col)
    if cell.ctype == XL_CELL_TEXT:
        return cell.value.strip()
    if cell.ctype == XL_CELL_NUMBER:
        return float(cell.value)
    if cell.ctype == XL_CELL_BOOLEAN:
        return bool(cell.value)
    return None


def read_ctrl(sheet) -> dict[str, Any]:
    """Every ``Label:`` → value pair of the CTRL sheet (first occurrence of a label wins)."""
    pairs: dict[str, Any] = {}
    for row in range(sheet.nrows):
        for col in range(sheet.ncols - 1):
            label = _cell(sheet, row, col)
            if isinstance(label, str) and label.endswith(":") and len(label) > 1:
                key = label[:-1].strip()
                if key and key not in pairs:
                    pairs[key] = _cell(sheet, row, col + 1)
    return pairs


def _find_row(sheet, predicate, start: int = 0) -> int | None:
    for row in range(start, sheet.nrows):
        if predicate(row):
            return row
    return None


def read_cycle_table(sheet) -> tuple[list[str], list[int], np.ndarray, np.ndarray, np.ndarray]:
    """Return (names, source columns, cycle, time, values) of the CYCLE sheet."""
    names_row = _find_row(sheet, lambda r: _cell(sheet, r, 1) == "Function:")
    if names_row is None:
        raise IonVantageError("CYCLE sheet has no 'Function:' row naming the functions")
    header_row = _find_row(
        sheet,
        lambda r: _cell(sheet, r, 0) == "Cycle" and isinstance(_cell(sheet, r, 1), str) and _cell(sheet, r, 1).startswith("Time"),
        names_row + 1,
    )
    if header_row is None:
        raise IonVantageError("CYCLE sheet has no 'Cycle' / 'Time (s)' header row")
    names, columns = [], []
    for col in range(2, sheet.ncols):
        name = _cell(sheet, names_row, col)
        if isinstance(name, float):
            name = f"{name:g}"
        if name:
            names.append(name)
            columns.append(col)
    if not names:
        raise IonVantageError("CYCLE sheet names no functions")
    cycles, times, rows = [], [], []
    for row in range(header_row + 1, sheet.nrows):
        number = _cell(sheet, row, 0)
        if not isinstance(number, float):
            break  # first row without a cycle number ends the table
        cycles.append(int(number))
        time = _cell(sheet, row, 1)
        times.append(time if isinstance(time, float) else np.nan)
        row_values = []
        for col in columns:
            value = _cell(sheet, row, col)
            row_values.append(value if isinstance(value, float) else np.nan)
        rows.append(row_values)
    values = np.array(rows, dtype=np.float64).reshape(len(rows), len(names))
    return names, columns, np.array(cycles, dtype=np.int64), np.array(times, dtype=np.float64), values


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return str(int(value)) if value == int(value) else repr(value)
    text = str(value).strip()
    return text or None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return False


def read_ionvantage(path: str | os.PathLike[str], data: bytes | None = None) -> Run:
    """Read an IonVantage run workbook into a :class:`~rawtims.model.Run`."""
    if data is None:
        with open(path, "rb") as handle:
            data = handle.read()
    book = open_xls(file_contents=data, on_demand=True)
    try:
        ok, reason = is_ionvantage_book(book)
        if not ok:
            raise IonVantageError(reason)
        names, columns, cycle, time, values = read_cycle_table(book.sheet_by_name(CYCLE_SHEET))
        ctrl = read_ctrl(book.sheet_by_name(CTRL_SHEET)) if CTRL_SHEET in book.sheet_names() else {}
        from rawtims.reduction_params import capture_acquired
        functions_for_params = build_functions(names)
        acquired = capture_acquired(book, ctrl, functions_for_params, path)
    finally:
        book.release_resources()

    method_cycles = to_int(ctrl.get("Cycles per Block"))
    beam_interpolation = _truthy(ctrl.get("Beam Interpolation (BI)"))
    cycles_per_block = None if method_cycles is None else method_cycles + (1 if beam_interpolation else 0)
    blocks = to_int(ctrl.get("Number of Blocks"))
    error_message = _text(ctrl.get("IsoWorks Error Message"))
    complete, stopped_early = completion(len(cycle), blocks, cycles_per_block)
    aborted_reason = None
    if _truthy(ctrl.get("Run Terminated")):
        aborted_reason = "CTRL Run Terminated = 1"
    elif error_message and re.search(r"abort", error_message, re.IGNORECASE):
        aborted_reason = f"CTRL IsoWorks Error Message: {error_message}"
    start_raw = _text(ctrl.get("Analysis Start Time"))
    rejection = {}
    if ctrl.get("Rejection %") is not None:
        rejection["percent"] = ctrl["Rejection %"]
    if ctrl.get("Sigma Level") is not None:
        rejection["sigma"] = ctrl["Sigma Level"]
    extra = dict(ctrl)
    extra["acquired_reduction_parameters"] = acquired.to_dict()
    extra["cycles_per_block_method"] = method_cycles
    extra["beam_interpolation"] = beam_interpolation
    metadata = RunMetadata(
        sample_id=_text(ctrl.get("Sample Name (ID)")) or _text(ctrl.get("Sample ID")),
        serial=_text(ctrl.get("Serial Number")),
        method=_text(ctrl.get("Method Name")),
        instrument=None,
        software="IonVantage",
        analysis_start=parse_instrument_datetime(start_raw),
        analysis_start_raw=start_raw,
        blocks=blocks,
        cycles_per_block=cycles_per_block,
        complete=complete,
        stopped_early=stopped_early,
        aborted=aborted_reason is not None,
        aborted_reason=aborted_reason,
        rejection=rejection,
        extra=extra,
    )
    unit = _text(ctrl.get("Units - Standard"))
    functions = build_functions(names, extra=[{"source_column": col} for col in columns], default_unit=unit)
    raw = RawFile.describe(path, data, FORMAT_IONVANTAGE_XLS, _text(ctrl.get("Workbook Version")))
    run = assemble_run(raw, metadata, functions, cycle, time, values)
    run.reduction_parameters = acquired
    warnings = []
    if run.element == "U" and "270/267" in run.keys and "270" in run.keys and np.array_equal(run.column("270/267"), run.column("270")):
        warnings.append("U 270/267 is mislabeled: it contains 270 intensity; oxide reduction uses intensities or 270/265 × 265/267")
        run.metadata.extra["270/267_intensity_alias"] = True
    if len(time) > 1 and time[-1] == time[-2]:
        warnings.append("duplicated terminal timestamp in workbook; raw route uses the distinct final acquisition and preserves row count")
    run.warnings = tuple(warnings)
    return run


__all__ = ["IonVantageError", "is_ionvantage_book", "read_ctrl", "read_cycle_table", "read_ionvantage"]
