"""Read Tripoli's ``Oracle-*`` expected outputs (test helper, not engine code).

Cycle reports (``Oracle-*-report.tsv``), short reports (``Oracle-*.txt``) and
full reports (``Oracle-*-report.csv``). Cycle-report layout: a few preamble lines, then a tab-separated table whose header starts
with ``Cycle`` and ``Time``; cells are space-padded, discarded values are
wrapped in ``&`` and missing values are blank.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class CycleReport:
    names: list[str]
    cycle: np.ndarray
    time: np.ndarray
    values: np.ndarray  # n_cycles x len(names), NaN for blanks
    discarded: np.ndarray  # True where the value was wrapped in &


def _cell(text: str) -> tuple[float, bool]:
    text = text.strip()
    discarded = text.startswith("&") and text.endswith("&") and len(text) >= 2
    if discarded:
        text = text[1:-1].strip()
    return (float(text) if text else float("nan")), discarded


def read_cycle_report(path: Path) -> CycleReport:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.split("\t")[0].strip() == "Cycle")
    header = [cell.strip() for cell in lines[start].split("\t")]
    assert header[1] == "Time", header[:2]
    names = header[2:]
    cycles, times, rows, flags = [], [], [], []
    for line in lines[start + 1 :]:
        if not line.strip():
            continue
        cells = line.split("\t")
        cells += [""] * (len(header) - len(cells))
        cycles.append(int(cells[0].strip()))
        times.append(_cell(cells[1])[0])
        parsed = [_cell(cell) for cell in cells[2 : len(header)]]
        rows.append([value for value, _ in parsed])
        flags.append([flag for _, flag in parsed])
    return CycleReport(names, np.array(cycles), np.array(times), np.array(rows, dtype=float), np.array(flags, dtype=bool))


def read_short_report(path: Path) -> list[tuple[str, float, float]]:
    """Tripoli's clipboard/short report: blocks of ``name (Mean, %StdErr)``, mean, percent SE.

    Returns ``(name, mean, pct)`` in file order; repeated names stay repeated.
    """
    entries = []
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        assert len(lines) == 3 and lines[0].endswith(" (Mean, %StdErr)"), lines
        entries.append((lines[0][: -len(" (Mean, %StdErr)")], float(lines[1]), float(lines[2])))
    return entries


@dataclass
class FullReportColumn:
    name: str
    mean: float
    se_header: str  # "%StdErr" (ratio, percent) or "StdErr" (absolute)
    se: float
    sd_header: str  # "%StdDev" or "StdDev"
    sd: float


def read_full_report(path: Path) -> tuple[dict[str, str], list[FullReportColumn]]:
    """Tripoli's full CSV report: one header row, one value row.

    The leading identity columns (Analysis Name … Method Name) come back as a
    dict; then each function contributes three columns ``<name> Mean``,
    ``%StdErr``/``StdErr`` and ``%StdDev``/``StdDev``.
    """
    import csv

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == 2, len(rows)
    header, values = rows
    first = next(i for i, name in enumerate(header) if name.endswith(" Mean"))
    identity = dict(zip(header[:first], values[:first]))
    columns = []
    for i in range(first, len(header), 3):
        assert header[i].endswith(" Mean"), header[i]
        columns.append(FullReportColumn(header[i][: -len(" Mean")], float(values[i]), header[i + 1], float(values[i + 1]), header[i + 2], float(values[i + 2])))
    return identity, columns
