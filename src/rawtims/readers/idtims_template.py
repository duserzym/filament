"""OGTripoli's ID-TIMS cycle CSV template (distinct from fractions CSV)."""

from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
from pathlib import Path

import numpy as np

from rawtims.model import RawFile, RunMetadata
from rawtims.readers.common import assemble_run, to_int
from rawtims.readers.functions import build_functions
from rawtims.readers.timsdp import decode

FORMAT = "idtims_template_csv"
SIGNATURE = "EARTHTIME ID-TIMS DATA IMPORT TEMPLATE FOR TRIPOLI"


def signature(text):
    first = text.partition("\n")[0].partition(",")[0].strip()
    return first in (SIGNATURE, '"' + SIGNATURE + '"')


def read_template(path, data=None):
    data = Path(path).read_bytes() if data is None else data
    text = decode(data)
    if not signature(text):
        raise ValueError("Not an ID-TIMS import template")
    rows = list(csv.reader(StringIO(text)))
    start = next(
        (i for i, r in enumerate(rows) if r and r[0].strip().upper() == "START DATA"),
        None,
    )
    if start is None or start + 1 >= len(rows):
        raise ValueError("Template needs START DATA and function captions")
    header = {
        r[0].strip().lower().rstrip(":"): r[1].strip()
        for r in rows[:start]
        if len(r) > 1 and r[0].strip()
    }
    cpb = to_int(header.get("cycles/blk"))
    if cpb is None or cpb < 0:
        raise ValueError("Template cycles/blk must be a nonnegative integer")
    names = rows[start + 1][1:]
    while names and not names[-1].strip():
        names.pop()
    names = [n.strip() for n in names]
    if not names or not all(names):
        raise ValueError("Template needs nonempty function captions")
    values, source_cycles = [], []
    for row in rows[start + 2 :]:
        if not any(c.strip() for c in row):
            continue
        cycle = to_int(row[0])
        if cycle is None or cycle < 1:
            raise ValueError("Template cycle must be a positive integer")
        cells = row[1 : len(names) + 1]
        if len(cells) != len(names) or any(c.strip() for c in row[len(names) + 1 :]):
            raise ValueError("Template row width differs from captions")
        try:
            numbers = [float(c) if c.strip() else float("nan") for c in cells]
        except ValueError as error:
            raise ValueError("Invalid template numeric cell") from error
        values.append(numbers)
        source_cycles.append(cycle)
    if not values:
        raise ValueError("Empty import template: add cycle data below the captions")
    if len(set(source_cycles)) != len(source_cycles) or np.any(
        np.diff(source_cycles) <= 0
    ):
        raise ValueError("Template cycles must be unique and increasing")
    # OG groups by row count and pads the final block to the largest block.
    block_size = min(cpb or len(values), len(values))
    n = ((len(values) + block_size - 1) // block_size) * block_size
    array = np.zeros((n, len(names)))
    array[: len(values)] = values
    array[array <= 0] = 0
    raw_date = header.get("date")
    date = None
    for fmt in ("%m/%d/%Y", "%b/%d/%Y"):
        try:
            date = datetime.strptime(raw_date or "", fmt)
            break
        except ValueError:
            pass
    metadata = RunMetadata(
        sample_id=header.get("sample"),
        analysis_start=date,
        analysis_start_raw=raw_date,
        cycles_per_block=block_size,
        extra={
            "header": header,
            "source_text": text,
            "fraction_id": header.get("fraction"),
            "source_cycles": source_cycles,
            "padded_cycles": n - len(values),
            "time_basis": "unavailable",
        },
    )
    run = assemble_run(
        RawFile.describe(path, data, FORMAT),
        metadata,
        build_functions(names),
        np.arange(1, n + 1),
        np.full(n, np.nan),
        array,
    )
    run.invalid |= ~np.isfinite(array) | (array <= 0)
    return run
