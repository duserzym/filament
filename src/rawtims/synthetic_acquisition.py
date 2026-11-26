"""Structural Java synthetic Version 1.00 parsing only; never a Run/raw reader.

PhoenixMassSpec.java:163-231,420-449,488-590 in TripoliCore/src/main/java/
org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/
phoenix (00dc941). No detector, calibration, generating truth or units inferred.
"""

import csv
from dataclasses import dataclass
from io import StringIO
from itertools import pairwise
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Integration:
    sequence: str
    block: int
    cycle: int
    integration: int
    time: float
    mass: float
    intensities: tuple[float, ...]


@dataclass(frozen=True)
class SyntheticBlock:
    number: int
    baseline: tuple[Integration, ...]
    on_peak: tuple[Integration, ...]

    @property
    def cycle_starts(self):
        return tuple(
            i
            for i, row in enumerate(self.on_peak)
            if i == 0 or row.cycle != self.on_peak[i - 1].cycle
        )


@dataclass(frozen=True)
class SyntheticAcquisition:
    header: tuple[tuple[str, ...], ...]
    columns: tuple[str, ...]
    blocks: tuple[SyntheticBlock, ...]
    omitted_baseline_only_tail: bool
    schema: str = "rawtims-java-synthetic/1"


def parse_java_synthetic(text: str) -> SyntheticAcquisition:
    rows = [
        tuple(v.strip() for v in row)
        for row in csv.reader(StringIO(text))
        if row and any(v.strip() for v in row)
    ]
    if not rows or rows[0] != ("Version", "1.00") or ("#START",) not in rows:
        raise ValueError("Only Java synthetic Version,1.00 / #START is supported")
    start = rows.index(("#START",))
    header = tuple(rows[:start])
    if start + 1 >= len(rows):
        raise ValueError("Missing synthetic columns")
    columns = rows[start + 1]
    if (
        columns[:6] != ("ID", "Block", "Cycle", "Integ", "Time", "Mass")
        or len(columns) < 7
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("Unknown synthetic column layout")
    grouped = {}
    ended = False
    for row in rows[start + 2 :]:
        if row[0] == "#END":
            ended = True
            continue
        if ended or len(row) != len(columns):
            raise ValueError("Unexpected/truncated synthetic data row")
        try:
            block, cycle, integ = map(int, row[1:4])
            time, mass, *intensities = map(float, row[4:])
        except ValueError:
            raise ValueError("Non-numeric synthetic integration") from None
        baseline = row[0].startswith("BL") and row[0][2:].isdigit()
        peak = row[0].startswith("S") and row[0][1:].isdigit()
        if (
            block < 1
            or integ < 1
            or not ((baseline and cycle == 0) or (peak and cycle >= 1))
            or not np.isfinite([time, mass, *intensities]).all()
        ):
            raise ValueError("Invalid synthetic identity or non-finite integration")
        if (
            grouped
            and block != next(reversed(grouped))
            and block != next(reversed(grouped)) + 1
        ):
            raise ValueError("Synthetic blocks must be contiguous and ordered")
        if not grouped and block != 1:
            raise ValueError("Synthetic blocks must start at 1")
        grouped.setdefault(block, []).append(
            Integration(row[0], block, cycle, integ, time, mass, tuple(intensities))
        )
    if not grouped:
        raise ValueError("No synthetic integrations")
    blocks, omitted = [], False
    for number, integrations in grouped.items():
        base = tuple(r for r in integrations if r.cycle == 0)
        peak = tuple(r for r in integrations if r.cycle > 0)
        if integrations != list(base + peak) or not base:
            raise ValueError(
                "Expected baseline integrations before on-peak integrations"
            )
        if any(b.time <= a.time for a, b in pairwise(integrations)):
            raise ValueError("Integration times must increase within each block")
        if not peak:
            if number != next(reversed(grouped)):
                raise ValueError("Baseline-only block before end")
            omitted = True  # Java omits the terminal baseline-only block.
            continue
        cycles = [r.cycle for r in peak]
        if cycles[0] != 1 or any(b - a not in (0, 1) for a, b in pairwise(cycles)):
            raise ValueError("On-peak cycles must be contiguous and ordered from 1")
        blocks.append(SyntheticBlock(number, base, peak))
    return SyntheticAcquisition(header, columns, tuple(blocks), omitted)


def read_java_synthetic(path):
    return parse_java_synthetic(Path(path).read_text(encoding="utf-8"))
