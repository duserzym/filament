"""Strict, explicit legacy calibration adapters. Never used by reduction.

Only source-specified named BIFF8 ranges are read for gains. No layout guessing,
formula execution, external workbook access, Excel automation or binary writeback.
Standards .trip support uses the existing inert NRBF decoder. Aggregate .triphis
is inspection-only until saved specimens validate its graph and date semantics.
"""

import io
import math
from pathlib import Path

import numpy as np
import xlrd

from rawtims.history import digest, record, summary
from rawtims.model import RawFile
from rawtims.readers import UnsupportedFile
from rawtims.readers.common import parse_instrument_datetime
from rawtims.readers.trip import MAX_BYTES, read_trip


def read_gains(path):
    """OGTripoli/source/GainsFile.cs:132-278, d906f70.

    Preserve its unusual 1-based collector loop: col=startNameColumn..count,
    data column=col+startNameColumn. No reinterpretation as a modern layout.
    """
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise UnsupportedFile("gains workbook size limit exceeded")
    data = path.read_bytes()
    try:
        book = xlrd.open_workbook(file_contents=data, logfile=io.StringIO())
        if book.biff_version != 80 or not {"CTRL", "Gains"} <= set(book.sheet_names()):
            raise ValueError("expected BIFF8 CTRL/Gains workbook")

        def area(name, sheet):
            candidates = book.name_map.get(name.lower(), [])
            candidates = [
                n
                for n in candidates
                if n.scope in (-1, book.sheet_names().index(sheet))
            ]
            if len(candidates) != 1:
                raise ValueError(f"missing/ambiguous named range {name}")
            sh, r, rhi, c, chi = candidates[0].area2d(clipped=False)
            if sh.name != sheet or r < 0 or c < 0 or rhi > sh.nrows or chi > sh.ncols:
                raise ValueError(f"unsupported named range {name}")
            return sh, r, c

        def cell(name):
            sh, r, c = area(name, "CTRL")
            return sh.cell_value(r, c)

        if str(cell("ILV_ErrorMessage")).strip().endswith("ABORTED!"):
            raise ValueError("aborted gains acquisition")
        cycles, count = cell("CCG_TotalCycles"), cell("ILV_NoCollectors")
        if (
            type(cycles) not in (int, float)
            or type(count) not in (int, float)
            or not 1 <= cycles <= 100000
            or int(cycles) != cycles
            or not 1 <= count <= 64
            or int(count) != count
        ):
            raise ValueError("invalid cycle/collector count")
        date_value = cell("ILV_StartTime")
        # The reference uses Convert.ToDateTime(Value2); numeric OLE dates are
        # not specified by that call. Support only the unambiguous text subset.
        date = (
            parse_instrument_datetime(date_value)
            if isinstance(date_value, str)
            else None
        )
        if date is None:
            raise ValueError(
                "unsupported gains date; require explicit instrument date text"
            )
        gains, row, _ = area("CCG_Gains", "Gains")
        ctrl, namerow, namecol = area("ILV_CollNames", "CTRL")
        start_col = namecol + 1
        series, collectors = [], []
        for col in range(start_col, int(count) + 1):
            c = (
                col + start_col - 1
            )  # convert reference's doubled one-based column to Python
            name = str(ctrl.cell_value(namerow, c)).strip()
            kind = str(ctrl.cell_value(namerow + 1, c)).strip()
            number = ctrl.cell_value(namerow + 2, c)
            number = (
                int(number)
                if isinstance(number, (int, float)) and math.isfinite(number)
                else 0
            )
            if name.startswith(("High", "Low")) and (
                kind.startswith("Faraday") or (kind.startswith("-") and number > 0)
            ):
                values = [gains.cell_value(r, c) for r in range(row, row + int(cycles))]
                if any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in values
                ):
                    raise ValueError("unknown/non-numeric gain cycle")
                values = [max(0.0, v) for v in values]
                series.append(summary(name, [v for v in values if v > 0]))
                collectors.append(
                    {"name": name, "type": kind, "number": number, "cycles": values}
                )
        if not series or len({s["key"] for s in series}) != len(series):
            raise ValueError("no supported collectors or duplicate collector names")
        raw = RawFile.describe(path, data, "og gains BIFF8", "source-d906f70")
        return record(
            "gains",
            date.isoformat(),
            path.name,
            {
                "path": str(path),
                "sha256": raw.sha256,
                "format": raw.format,
                "version": raw.format_version,
            },
            {
                "schema": "GainsFile.cs d906f70 named ranges",
                "sha256": digest(collectors),
                "collectors": collectors,
            },
            {},
            series,
            "OG gains source schema; negatives become missing zero; positive-cycle arithmetic summary",
        )
    except (
        ValueError,
        TypeError,
        IndexError,
        KeyError,
        AssertionError,
        xlrd.XLRDError,
    ) as error:
        raise UnsupportedFile(
            f"{path.name}: unsupported gains workbook ({error})"
        ) from None


def read_standard(path):
    """OGTripoli/source/StandardsFile.cs:88-138,164-201 (d906f70).

    Signed nonpositive legacy values are missing. The source obtains acquisition
    dates by reopening a separate vendor workbook (TripoliHistoryFolderStandards.cs:
    173-194). Do not follow that path or substitute a save/file timestamp here.
    """
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise UnsupportedFile("standard size limit exceeded")
    data = path.read_bytes()
    project = read_trip(path)
    if data != path.read_bytes():
        raise UnsupportedFile("standard changed while reading")
    series = []
    for ratio in project.ratios:
        n = ratio.cycles_per_block
        if n < 1 or not len(ratio.values) or len(ratio.values) % n:
            raise UnsupportedFile("standard requires complete rectangular blocks")
        means = [
            float(np.mean(block[block > 0])) if np.any(block > 0) else float("nan")
            for block in ratio.values.reshape(-1, n)
        ]
        series.append(summary(ratio.name + " (means)", means, block_means=means))
    if not series:
        raise UnsupportedFile("standard has no ratios")
    raw = RawFile.describe(path, data, "og standard trip", project.version)
    # Preserve the entire inert graph (including tracer/unknown members) as
    # content-addressed evidence; never reinterpret an unknown correction model.
    from rawtims.readers.legacy_saved import graph_document

    graph = graph_document(project.raw)
    return record(
        "standard",
        None,
        path.name,
        {
            "path": str(path),
            "sha256": raw.sha256,
            "format": raw.format,
            "version": raw.format_version,
        },
        {"sha256": digest(graph), "graph": graph},
        {"date_notice": "acquisition date unavailable; external source not followed"},
        series,
        "StandardsFile.cs d906f70 positive-cycle arithmetic block means, equal-block summary",
    )
