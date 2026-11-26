"""Processed Triton EXP, Neptune EXP and Nu TIMS individual answers.

Only the exact report signatures below enter these readers. Original captions,
header/footer lines, cell flags and time strings remain available for review.
No acquisition corrections or automatic vendor rejection are applied.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np

from rawtims.model import RawFile, Run, RunMetadata
from rawtims.readers.common import assemble_run, to_int
from rawtims.readers.functions import build_functions, classify
from rawtims.readers.timsdp import decode

TRITON = "triton_exp"
NEPTUNE = "neptune_exp"
NU_TIMS = "nu_tims_txt"
FORMATS = (TRITON, NEPTUNE, NU_TIMS)
_NU_KEYS = (
    "Version number",
    "Sample name",
    "Analysis file name",
    "Number of measurements per block",
    "Total number of blocks (assuming completed run)",
    "Number of answers",
    "Caption (1)",
)
# Match instrument species including sequence prefixes and oxide/decimal tails.
_SPECIES = r"(?:\d+:)?\d{2,3}(?:\.\d+)?[A-Za-z.0-9]*"
_RATIO = re.compile(rf"^(?P<num>{_SPECIES})/(?P<den>{_SPECIES})(?=$|\s)")
_JAVA_RATIO = re.compile(
    r"[^alph].*\d?:?\(?\d{2,3}.{0,2}/[^alph].*\d?:?\d{2,3}.{0,2}.*"
)


def signature(text: str) -> str | None:
    lines = text.splitlines()
    first = lines[0].rstrip("\t ") if lines else ""
    if first == "Triton Analysis Data Report":
        return TRITON
    if first == "Neptune Analysis Data Report":
        return NEPTUNE
    if (
        len(lines) >= len(_NU_KEYS)
        and tuple(l.split("\t")[0] for l in lines[:7]) == _NU_KEYS
    ):
        return NU_TIMS
    return None


def _functions(names):
    result = []
    for f in build_functions(names):
        metadata = dict(
            f.metadata,
            source_function_index=f.index,
            tripoli_ratio=bool(_JAVA_RATIO.fullmatch(f.name)),
            tripoli_name=f.name.replace("°", "").replace("�", ""),
        )
        match = _RATIO.match(f.name)
        if match:
            num, den = match.group("num", "den")
            # Classify with the sequence and molecular punctuation removed;
            # names and equations on the Function remain exactly as imported.
            canonical = re.sub(r"\b\d+:", "", num + "/" + den).replace(".O2", "O2")
            fields = classify(canonical)
            fields.pop("metadata")
            if fields["kind"] != "ratio":
                fields = {"kind": "ratio", "numerator": num, "denominator": den}
            f = replace(f, **fields)
        else:
            canonical = re.sub(r"^\d+:", "", f.name).replace(".O2", "O2")
            canonical = canonical.replace(" (V)", " V")
            fields = classify(canonical)
            fields.pop("metadata")
            if fields["kind"] == "intensity":
                f = replace(f, **fields)
        result.append(replace(f, metadata=metadata))
    return tuple(result)


def _number(cell: str) -> float:
    cell = cell.strip()
    if cell.startswith(("X", "D")):
        cell = cell[1:].strip()
    if not cell or cell == "Invalid Norm":
        return float("nan")
    if cell in ("∞", "+∞", "-∞", "�"):
        return float("-inf") if cell.startswith("-") else float("inf")
    try:
        return float(cell)
    except ValueError as error:
        raise ValueError(f"Invalid processed numeric cell: {cell!r}") from error


def _start(header):
    raw = " ".join(
        filter(None, (header.get("Analysis date"), header.get("Analysis time")))
    )
    if not raw:
        return None, None
    # Follow the snapshot's day-first ETH and month-first AM/PM convention.
    # Keep the original date strings; never rely on the process locale.
    formats = (
        ("%m/%d/%Y %I:%M:%S %p",)
        if re.search(r"\b[AP]M$", raw)
        else ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S")
    )
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt), raw
        except ValueError:
            pass
    return None, raw


def _time(cell):
    if ":" in cell:
        parts = cell.split(":")
        if len(parts) in (3, 4):
            h, m, s = map(int, parts[:3])
            return (
                h * 3600 + m * 60 + s + (int(parts[3]) / 1000 if len(parts) == 4 else 0)
            )
        raise ValueError(f"Invalid time cell: {cell!r}")
    return _number(cell)


def read_processed(path, data: bytes | None = None) -> Run:
    data = Path(path).read_bytes() if data is None else data
    text = decode(data)
    fmt = signature(text)
    if fmt is None:
        raise ValueError("Not a supported processed vendor report")
    lines = text.splitlines()
    header, footer, raw_rows, times, cycles = {}, [], [], [], []
    unmeasured = []
    if fmt == NU_TIMS:
        captions = [
            l.split("\t", 1)[1].strip() for l in lines if l.startswith("Caption (")
        ]
        start = 6 + len(captions)
        for line in lines[:6]:
            key, value = line.split("\t", 1)
            header[key] = value.strip()
        if to_int(header["Number of answers"]) != len(captions):
            raise ValueError("Nu TIMS caption count differs from Number of answers")
        names = captions
        cpb = to_int(header["Number of measurements per block"])
        if cpb is None or cpb < 1:
            raise ValueError("Nu TIMS needs positive measurements per block")
        for line in lines[start:]:
            if not line.strip():
                continue
            cells = line.split("\t")
            if len(cells) != len(names):
                raise ValueError("Nu TIMS row width differs from captions")
            raw_rows.append(cells)
            cycles.append(len(cycles) + 1)
            times.append("")
    else:
        marker = "Cycle\tTime\t" if fmt == TRITON else "Block\tTime\t"
        start = next((i for i, l in enumerate(lines) if l.startswith(marker)), None)
        if start is None:
            raise ValueError("Processed report has no cycle table")
        names = lines[start].rstrip("\t").split("\t")[2:]
        for line in lines[1:start]:
            key, sep, value = line.rstrip("\t").partition(": ")
            if sep:
                header[key.strip()] = value.strip()
        cpb = (
            10 if fmt == TRITON else None
        )  # Java method fallback; no Neptune cycle grouping
        for line in lines[start + 1 :]:
            if line.startswith("***") or footer:
                footer.append(line)
                continue
            if not line.strip():
                continue
            cells = line.split("\t")
            if all(not c.strip() for c in cells[1:]):
                unmeasured.append(cells[0])
                continue
            if len(cells) > len(names) + 2 and any(
                c.strip() for c in cells[len(names) + 2 :]
            ):
                raise ValueError("Unexpected extra processed columns")
            cells = cells[: len(names) + 2]
            if len(cells) < len(names) + 2:
                raise ValueError("Truncated processed cycle row")
            cycle = to_int(cells[0])
            if cycle is None or cycle < 1:
                raise ValueError("Cycle must be a positive integer")
            cycles.append(cycle)
            times.append(cells[1].strip())
            raw_rows.append(cells[2:])
    if not raw_rows or not names:
        raise ValueError("Processed report contains no cycle data")
    if len(set(cycles)) != len(cycles) or np.any(np.diff(cycles) <= 0):
        raise ValueError("Cycles must be unique and increasing")
    values = np.array([[_number(c) for c in row] for row in raw_rows])
    rejected = [[c.strip().startswith("X") for c in row] for row in raw_rows]
    missing = [
        [
            not c.strip() or c.strip().startswith("D") or c.strip() == "Invalid Norm"
            for c in row
        ]
        for row in raw_rows
    ]
    functions = _functions(names)
    start_time, start_raw = _start(header)
    method = header.get("Method Name", header.get("Analysis file name", ""))
    method = method.rsplit("\\", 1)[-1]
    if fmt != NU_TIMS:
        method = method.removesuffix(".met")
    metadata = RunMetadata(
        sample_id=header.get("Sample ID", header.get("Sample name")),
        method=method or None,
        instrument={TRITON: "Triton", NEPTUNE: "Neptune", NU_TIMS: "Nu TIMS"}[fmt],
        software=header.get("Data Version", header.get("Version number")),
        analysis_start=start_time,
        analysis_start_raw=start_raw,
        cycles_per_block=cpb,
        blocks=to_int(header.get("Total number of blocks (assuming completed run)")),
        extra={
            "header": header,
            "footer": footer,
            "source_text": text,
            "source_cells": raw_rows,
            "source_times": times,
            "vendor_rejected": rejected,
            "vendor_missing": missing,
            "unmeasured_cycles": unmeasured,
            "time_basis": "unavailable"
            if fmt == NU_TIMS
            else "clock seconds"
            if any(":" in t for t in times)
            else "vendor numeric seconds",
            "block_basis": "Tripoli fallback: 10 cycles"
            if fmt == TRITON
            else "single block"
            if fmt == NEPTUNE
            else "vendor measurements per block",
        },
    )
    run = assemble_run(
        RawFile.describe(path, data, fmt),
        metadata,
        functions,
        np.array(cycles),
        np.array([_time(t) if t else np.nan for t in times]),
        values,
    )
    run.invalid |= np.asarray(missing)
    run.warnings = (
        "Vendor X flags retained; no automatic rejection. D/blank cells are missing.",
    )
    return run


def tripoli_comparison_arrays(run: Run) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Opt-in Java 00dc941 reader view, for snapshot comparison only.

    Java removes X/D flags, makes blank Neptune cells zero and Invalid Norm
    zero, assigns Nu time 1, and strips colons from Triton times. Its oracle
    snapshots retain values and exclude nonpositive ratio cells. Never installs this view into a Run/Analysis.
    """
    if run.raw.format not in FORMATS:
        raise ValueError("Comparison requires a processed vendor run")
    rows = run.metadata.extra["source_cells"]
    values = np.array(
        [
            [
                0.0
                if c.strip() == "Invalid Norm"
                or (not c.strip() and run.raw.format == NEPTUNE)
                else _number(c)
                for c in row
            ]
            for row in rows
        ]
    )
    times = np.array(
        [
            1.0
            if run.raw.format == NU_TIMS
            else float(t.replace(":", "") if run.raw.format == TRITON else t)
            for t in run.metadata.extra["source_times"]
        ]
    )
    ratios = np.array([f.metadata["tripoli_ratio"] for f in run.functions])
    included = np.ones(values.shape, dtype=bool)
    included[:, ratios] = values[:, ratios] > 0
    return values, included, times
