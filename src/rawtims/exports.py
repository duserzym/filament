"""Tripoli clipboard text and the cycles CSV (SPEC F16, F17).

**Clipboard.** Tripoli's clipboard export is a series of blocks
``<function name><sep>(Mean, %StdErr)``, the mean and the 1σ % standard error,
one per line, blocks separated by a blank line. Boise State pastes it into the
``Raw Data Input`` sheet of the UPbR spreadsheet (``BSULab_UPbR26XML.xls``),
whose rows expect, in this order: Pb 206/204, 206/207, 206/205, 207/205,
204/205, 208/205, 202/205 (when measured); U 238/235, 233/235, 238/233.

The headers in Yiming's spreadsheets have **two** spaces before the
parenthesis (``206/204 D  (Mean, %StdErr)``, ``238/233 oxide  (Mean,
%StdErr)``), while the IonVantage function names carry no trailing space and
Tripoli's ``Oracle-*`` short reports use one space. The default separator
(:data:`CLIPBOARD_SEPARATOR`) is two spaces to match the spreadsheets;
``separator=" "`` gives the short-report form. The header is only a label: the
spreadsheet reads the two value rows. Names are the functions' names as in the
file; an inverted mapping is written ``1/(<name>)`` with the inverted values.
The default is the legacy clipboard format: C# ``E7`` numbers, CRLF lines,
and a blank line after every block, including the last. ``full_precision=True``
keeps all digits (Python ``repr``) with the same block structure.

**Cycles CSV.** One header row (no comment lines), then one row per cycle:
``Block``, ``Cycle``, ``Time (s)``, then for each function two columns,
``<key>`` (the value, empty when the file has none) and ``<key> included``
(``1`` when the cycle is effectively included for that function: cycle flag,
block flag and valid value; else ``0``). Function keys are the analysis's
unique keys (``"<name> #2"`` for a repeated name), derived oxide columns
included. UTF-8, comma, ``\\n`` line endings, numbers in full precision.
"""

from __future__ import annotations

from collections.abc import Sequence
import csv
import io
import math
import os
from pathlib import Path

from rawtims.analysis import Analysis
from rawtims.fractions import Fraction, FractionError
from rawtims.mapping import MappingError, element_ratios, ratio_stats

CLIPBOARD_SEPARATOR = "  "
CLIPBOARD_SUFFIX = "(Mean, %StdErr)"


def clipboard_entries(fraction: Fraction, element: str) -> list[tuple[str, float, float]]:
    """``(header name, mean, % SE)`` for each mapped ratio of one element, in the spreadsheet's order."""
    analysis = fraction.analysis(element)
    if analysis is None:
        return []
    mapping = fraction.mapping(element)
    assert mapping is not None
    if not mapping.complete:
        raise FractionError(f"fraction {fraction.fraction_id!r}: the {element} run lacks contract ratios: {mapping.describe_missing()}")
    entries = []
    for ratio in element_ratios(element):
        mapped = mapping.ratios.get(ratio)
        if mapped is None:
            continue
        try:
            stats = ratio_stats(analysis, mapped)
        except MappingError as error:
            raise FractionError(str(error)) from None
        name = f"1/({mapped.name})" if mapped.inverted else mapped.name
        entries.append((name, stats.mean, stats.se_pct))
    return entries


def _number(value: float) -> str:
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else repr(float(value))


def legacy_e7(value: float) -> str:
    """C# ``ToString("E7")``: eight significant digits and a signed, 3-digit exponent."""
    if not math.isfinite(value):
        return "NaN" if math.isnan(value) else ("-Infinity" if value < 0 else "Infinity")
    mantissa, exponent = format(value, ".7E").split("E")
    return f"{mantissa}E{int(exponent):+04d}"


def clipboard_text(fraction: Fraction, element: str | None = None, *, separator: str = CLIPBOARD_SEPARATOR,
                   full_precision: bool = False) -> str:
    """Tripoli-style clipboard text for one element (``"Pb"``/``"U"``) or, with ``element=None``, Pb then U."""
    elements = ("Pb", "U") if element is None else (element,)
    number = _number if full_precision else legacy_e7
    blocks = []
    for item in elements:
        for name, mean, pct in clipboard_entries(fraction, item):
            blocks.append(f"{name}{separator}{CLIPBOARD_SUFFIX}\r\n{number(mean)}\r\n{number(pct)}\r\n\r\n")
    return "".join(blocks)


def cycles_csv_text(analysis: Analysis, keys: Sequence[str] | None = None) -> str:
    """The cycles CSV of one analysis (see the module docstring); ``keys`` default to every function."""
    keys = list(analysis.keys if keys is None else keys)
    columns = [analysis.index(key) for key in keys]
    effective = analysis.effective
    run = analysis.run
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    header = ["Block", "Cycle", "Time (s)"]
    for key in keys:
        header += [key, f"{key} included"]
    writer.writerow(header)
    for row in range(analysis.n_cycles):
        cells = [str(int(run.block[row])), str(int(run.cycle[row])), _number(float(run.time[row]))]
        for column in columns:
            cells += [_number(float(analysis.values[row, column])), "1" if effective[row, column] else "0"]
        writer.writerow(cells)
    return buffer.getvalue()


def write_cycles_csv(analysis: Analysis, path: str | os.PathLike[str], keys: Sequence[str] | None = None) -> Path:
    path = Path(path)
    path.write_text(cycles_csv_text(analysis, keys), encoding="utf-8", newline="")
    return path


__all__ = ["CLIPBOARD_SEPARATOR", "CLIPBOARD_SUFFIX", "clipboard_entries", "clipboard_text", "legacy_e7", "cycles_csv_text", "write_cycles_csv"]
