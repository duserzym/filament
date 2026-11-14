"""IsotopX IsoLinx ``.TIMSDP`` files (Phoenix TIMS, plain comma-separated text with ``#SECTION`` markers).

Sections seen: ``#HEADER``, ``#SAMPLELIST``, ``#COLLECTORS``, ``#USERTABLES``,
``#ELECTRONIC_OFFSETS``, ``#BASELINES``, ``#CYCLES``, ``#BLOCKS``,
``#SUMMARY``, ``#FUNCTIONS``, ``#END,<status>``. Kept:

* ``#HEADER`` and ``#SAMPLELIST`` key/value lines (``key,value``; the value is
  everything after the first comma, stripped) in ``extra["header"]`` and
  ``extra["samplelist"]``;
* the ``#COLLECTORS`` table as a list of row dicts in ``extra["collectors"]``,
  ``#USERTABLES`` rows in ``extra["usertables"]`` and the end status;
* ``#CYCLES``: ``Cycle,Time,<function comments…>`` and one row per cycle; the
  values are IsoLinx-processed functions. A repeated ``#CYCLES`` marker (seen
  in some Purdue files) is ignored;
* ``#FUNCTIONS`` (``id, comment, formula``; the formula may contain commas):
  each column's IsoLinx id and formula go into its ``Function.metadata``,
  matched by comment and order of occurrence, so repeated names pair up.

Block numbers come from ``CyclesToMeasure``: block = (cycle − 1) // CyclesToMeasure + 1.
Unlike IonVantage, ``BeamInterpCycles,True`` adds no row: in every fixture
with it on, the ``#BLOCKS`` section's ``Total`` per block equals
``CyclesToMeasure``.

``Version,2.0.11,1.20`` is read as software version 2.0.11 and file format
1.20 (``RawFile.format_version``); the two numbers' meaning is inferred from
the files, not documented.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from rawtims.model import FORMAT_ISOLINX_TIMSDP, RawFile, Run, RunMetadata
from rawtims.readers.common import assemble_run, parse_instrument_datetime, to_float, to_int
from rawtims.readers.functions import build_functions

REQUIRED_HEADER_KEYS = ("Version", "MethodName")


class TimsdpError(ValueError):
    """The file looks like IsoLinx text but its cycle table cannot be read."""


def decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text


def split_sections(text: str) -> tuple[list[tuple[str, list[str]]], str | None]:
    """Return ([(section name, lines)], end status). Blank lines are dropped."""
    sections: list[tuple[str, list[str]]] = []
    end_status = None
    current: list[str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            marker, _, rest = line.partition(",")
            name = marker[1:].strip().upper()
            if name == "END":
                end_status = rest.strip() or None
                current = None
                continue
            if sections and sections[-1][0] == name and name == "CYCLES":
                continue  # duplicated #CYCLES marker
            current = []
            sections.append((name, current))
            continue
        if current is not None:
            current.append(line)
    return sections, end_status


def _key_values(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    pairs: dict[str, str] = {}
    loose: list[str] = []
    for line in lines:
        key, comma, value = line.partition(",")
        if not comma:
            loose.append(line)
            continue
        key = key.strip()
        if key and key not in pairs:
            pairs[key] = value.strip()
    return pairs, loose


def _table(lines: list[str]) -> list[dict[str, str]]:
    if not lines:
        return []
    columns = [cell.strip() for cell in lines[0].split(",")]
    return [dict(zip(columns, (cell.strip() for cell in line.split(",")))) for line in lines[1:]]


def looks_like_timsdp(text: str) -> tuple[bool, str]:
    """(True, "") when the text is an IsoLinx data file with a #CYCLES table, else (False, reason)."""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first.partition(",")[0].upper() != "#HEADER":
        return False, "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
    sections, _ = split_sections(text)
    names = [name for name, _ in sections]
    header, _ = _key_values(sections[0][1]) if sections else ({}, [])
    missing = [key for key in REQUIRED_HEADER_KEYS if key not in header]
    if missing:
        return False, f"#HEADER without {', '.join(missing)} (not an IsoLinx data file)"
    if "CYCLES" not in names:
        return False, "IsoLinx file without a #CYCLES table (raw-integration exports are not read)"
    return True, ""


def read_timsdp(path: str | os.PathLike[str], data: bytes | None = None) -> Run:
    """Read an IsoLinx ``.TIMSDP`` file into a :class:`~rawtims.model.Run`."""
    if data is None:
        with open(path, "rb") as handle:
            data = handle.read()
    text = decode(data)
    ok, reason = looks_like_timsdp(text)
    if not ok:
        raise TimsdpError(reason)
    sections, end_status = split_sections(text)
    by_name: dict[str, list[str]] = {}
    for name, lines in sections:
        by_name.setdefault(name, lines)
    header, header_loose = _key_values(by_name.get("HEADER", []))
    samplelist, _ = _key_values(by_name.get("SAMPLELIST", []))
    collectors = _table(by_name.get("COLLECTORS", []))
    usertables = {}
    for line in by_name.get("USERTABLES", []):
        key, _, rest = line.partition(",")
        usertables[key.strip()] = [cell.strip() for cell in rest.split(",")]

    cycle_lines = by_name["CYCLES"]
    if not cycle_lines:
        raise TimsdpError("#CYCLES section is empty")
    columns = [cell.strip() for cell in cycle_lines[0].split(",")]
    if len(columns) < 3 or columns[0].lower() != "cycle" or not columns[1].lower().startswith("time"):
        raise TimsdpError(f"#CYCLES header does not start with Cycle,Time: {cycle_lines[0][:80]!r}")
    names = columns[2:]
    cycles, times, rows = [], [], []
    for line in cycle_lines[1:]:
        cells = [cell.strip() for cell in line.split(",")]
        if cells and cells[0].lower() == "cycle":
            continue  # a repeated header line
        number = to_int(cells[0]) if cells else None
        if number is None:
            raise TimsdpError(f"#CYCLES row without a cycle number: {line[:80]!r}")
        cycles.append(number)
        times.append(to_float(cells[1]) if len(cells) > 1 else np.nan)
        row = [to_float(cell) for cell in cells[2 : 2 + len(names)]]
        row += [np.nan] * (len(names) - len(row))
        rows.append(row)
    values = np.array(rows, dtype=np.float64).reshape(len(rows), len(names))

    formulas = []
    for line in by_name.get("FUNCTIONS", [])[1:]:
        function_id, _, rest = line.partition(",")
        comment, _, formula = rest.partition(",")
        formulas.append((function_id.strip(), comment.strip(), formula.strip()))
    extras: list[dict[str, Any]] = []
    used: set[int] = set()
    for name in names:
        match = next((i for i, (_, comment, _) in enumerate(formulas) if comment == name and i not in used), None)
        if match is None:
            extras.append({})
        else:
            used.add(match)
            extras.append({"function_id": formulas[match][0], "formula": formulas[match][2]})

    version_parts = [part.strip() for part in header.get("Version", "").split(",")]
    software_version = version_parts[0] if version_parts and version_parts[0] else None
    format_version = version_parts[1] if len(version_parts) > 1 and version_parts[1] else None
    cycles_per_block = to_int(header.get("CyclesToMeasure"))
    blocks = to_int(header.get("BlocksToMeasure"))
    planned = None if blocks is None or cycles_per_block is None else blocks * cycles_per_block
    rejection = {}
    if "RejectionSigma" in header:
        rejection["sigma"] = to_float(header["RejectionSigma"])
    if "RejectionPercentage" in header:
        rejection["percent"] = to_float(header["RejectionPercentage"])
    start_raw = header.get("AnalysisStart") or None
    metadata = RunMetadata(
        sample_id=samplelist.get("SampleID") or None,
        serial=samplelist.get("SampleSerialNo") or None,
        method=header.get("MethodName") or samplelist.get("AnalysisMethod") or None,
        instrument=None,
        software=f"IsoLinx {software_version}" if software_version else "IsoLinx",
        analysis_start=parse_instrument_datetime(start_raw),
        analysis_start_raw=start_raw,
        blocks=blocks,
        cycles_per_block=cycles_per_block,
        aborted=planned is not None and len(cycles) < planned,
        rejection=rejection,
        extra={
            "header": header,
            "header_lines": header_loose,
            "samplelist": samplelist,
            "collectors": collectors,
            "usertables": usertables,
            "end_status": end_status,
            "sections": [name for name, _ in sections],
        },
    )
    functions = build_functions(names, extra=extras, default_unit=header.get("ProcessingUnits"))
    raw = RawFile.describe(path, data, FORMAT_ISOLINX_TIMSDP, format_version)
    return assemble_run(raw, metadata, functions, np.array(cycles), np.array(times, dtype=np.float64), values)
