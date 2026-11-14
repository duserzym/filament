"""Pieces shared by the format readers: date parsing, number coercion and run assembly."""

from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any

import numpy as np

from rawtims.model import Function, RawFile, Run, RunMetadata, uuid7
from rawtims.readers.functions import detect_element

_MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
            ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}
_WEEKDAY = r"(?:mon|tues|wednes|thurs|fri|satur|sun)day,?"
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{1,2}):(\d{1,2})(?:\.\d+)?(?:\s*([AaPp][Mm]))?$")
_SLASHED = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{1,2}):(\d{1,2})(?:\s*([AaPp][Mm]))?$")
_WORDS = re.compile(rf"^(?:{_WEEKDAY}\s+)?(\d{{1,2}})\s+([A-Za-z]+)\s+(\d{{4}})\s+(\d{{1,2}}):(\d{{1,2}}):(\d{{1,2}})$", re.IGNORECASE)


def _hour(hour: int, meridiem: str | None) -> int:
    if meridiem is None:
        return hour
    if not 1 <= hour <= 12:
        raise ValueError("12-hour clock out of range")
    return hour % 12 + (12 if meridiem.lower() == "pm" else 0)


def parse_instrument_datetime(text: str | None) -> datetime | None:
    """Parse the start-time formats IsotopX software writes; None when unrecognised.

    * ``2022-11-28 6:30:05 AM`` (IsoLinx 2.0, Purdue) and ``2022-11-28 06:30:05``;
    * ``26/09/2023 12:53:31`` (IsoLinx, day first, 24-hour). A slashed date with
      AM/PM is read month first (``7/3/2018 7:46:33 AM`` = 3 July, as in the
      IonVantage CTRL sheet), and a first field above 12 is always the day;
    * ``Tuesday 3 July 2018 7:46:32`` (IonVantage CTRL; English names, parsed
      without the process locale).

    The result is naive: the files carry no timezone.
    """
    if text is None:
        return None
    value = " ".join(str(text).split())
    try:
        if match := _ISO.match(value):
            y, mo, d, h, mi, s, ampm = match.groups()
            return datetime(int(y), int(mo), int(d), _hour(int(h), ampm), int(mi), int(s))
        if match := _SLASHED.match(value):
            a, b, y, h, mi, s, ampm = match.groups()
            first, second = int(a), int(b)
            day_first = ampm is None or first > 12
            day, month = (first, second) if day_first else (second, first)
            return datetime(int(y), month, day, _hour(int(h), ampm), int(mi), int(s))
        if match := _WORDS.match(value):
            d, month_name, y, h, mi, s = match.groups()
            month = _MONTHS.get(month_name.lower())
            if month is None:
                return None
            return datetime(int(y), month, int(d), int(h), int(mi), int(s))
    except ValueError:
        return None
    return None


def to_float(value: Any) -> float:
    """A cell or field as float; NaN for blanks, text and anything non-numeric."""
    if isinstance(value, bool):
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return float("nan")
        try:
            return float(text)
        except ValueError:
            return float("nan")
    return float("nan")


def to_int(value: Any) -> int | None:
    number = to_float(value)
    if math.isnan(number) or number != int(number):
        return None
    return int(number)


def invalid_mask(values: np.ndarray, functions: tuple[Function, ...]) -> np.ndarray:
    """Non-finite anywhere, or ≤ 0 in a ratio column."""
    invalid = ~np.isfinite(values)
    ratio = np.array([function.is_ratio for function in functions], dtype=bool)
    if ratio.any():
        with np.errstate(invalid="ignore"):
            invalid[:, ratio] |= ~(values[:, ratio] > 0)
    return invalid


def block_numbers(cycle: np.ndarray, cycles_per_block: int | None) -> np.ndarray:
    """Block = (cycle − 1) // cycles per block + 1; all ones when the block size is unknown."""
    if not cycles_per_block or cycles_per_block < 1:
        return np.ones(cycle.shape, dtype=np.int64)
    return (cycle - 1) // cycles_per_block + 1


def assemble_run(raw: RawFile, metadata: RunMetadata, functions: tuple[Function, ...], cycle: np.ndarray, time: np.ndarray, values: np.ndarray) -> Run:
    cycle = np.asarray(cycle, dtype=np.int64)
    values = np.asarray(values, dtype=np.float64).reshape(len(cycle), len(functions))
    return Run(
        run_id=str(uuid7()),
        raw=raw,
        element=detect_element(functions),
        metadata=metadata,
        functions=functions,
        cycle=cycle,
        block=block_numbers(cycle, metadata.cycles_per_block),
        time=np.asarray(time, dtype=np.float64),
        values=values,
        invalid=invalid_mask(values, functions),
    )
