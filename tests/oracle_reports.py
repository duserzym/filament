"""Read Tripoli's ``Oracle-*-report.tsv`` cycle reports (test helper, not engine code).

Layout: a few preamble lines, then a tab-separated table whose header starts
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
