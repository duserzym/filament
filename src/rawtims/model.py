"""What the readers produce: the raw file identity, the functions and the run (SPEC section 3).

Plain dataclasses and NumPy arrays; nothing here imports Qt. Rejection masks,
edit history, statistics and fractions arrive in later steps and build on
:class:`Run` without changing it: a run is the immutable content of one raw file.

Columns are identified by their position (``Function.index``) and by a unique
``Function.key``. Instrument files can repeat a function name (the Boise State
IonVantage workbook has two ``Daly/Faraday Gain`` columns), so the key is the
name for the first occurrence and ``"<name> #2"``, ``"<name> #3"`` … for later
ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
import secrets
import time
from typing import Any, Literal
import uuid

import numpy as np

FunctionKind = Literal["ratio", "intensity", "other"]
Element = Literal["Pb", "U"]

FORMAT_IONVANTAGE_XLS = "ionvantage_xls"
FORMAT_ISOLINX_TIMSDP = "isolinx_timsdp"


def uuid7() -> uuid.UUID:
    """Return a new UUID version 7 (RFC 9562): 48-bit Unix milliseconds, then random bits.

    Python 3.14 has ``uuid.uuid7``; 3.12 and 3.13 do not, so this builds one
    from the clock and ``secrets``. Values are time-ordered to the millisecond.
    """
    stdlib = getattr(uuid, "uuid7", None)
    if stdlib is not None:
        return stdlib()
    millis = time.time_ns() // 1_000_000
    value = (millis & ((1 << 48) - 1)) << 80
    value |= secrets.randbits(80)
    value &= ~(0xF << 76)
    value |= 0x7 << 76  # version
    value &= ~(0x3 << 62)
    value |= 0x2 << 62  # RFC 4122 variant
    return uuid.UUID(int=value)


@dataclass(frozen=True)
class RawFile:
    """Identity of the data: the file as opened, its size and SHA-256, and the detected format."""

    path: str
    name: str
    size: int
    sha256: str
    format: str
    format_version: str | None = None

    @classmethod
    def describe(cls, path: str | os.PathLike[str], data: bytes, fmt: str, format_version: str | None = None) -> RawFile:
        import hashlib

        path = os.fspath(path)
        return cls(path=path, name=os.path.basename(path), size=len(data), sha256=hashlib.sha256(data).hexdigest(), format=fmt, format_version=format_version)


@dataclass(frozen=True)
class Function:
    """One per-cycle column of the instrument file.

    ``numerator``/``denominator`` are the species labels as written (``"206"``,
    ``"Pb206+At206"``, ``"Tl205"``) and ``numerator_mass``/``denominator_mass``
    their mass numbers. ``mass`` is the mass number of an intensity column.
    ``collector`` is ``"D"`` (Daly) or ``"F"`` (Faraday) when the name says so
    unambiguously; mixed suffixes such as ``F-D`` stay in ``metadata["collector_suffix"]``.
    ``metadata`` holds reader details: the source column, the IsoLinx function id
    and formula, ``oxide_corrected`` and ``oxide_r18`` for names like
    ``238/235 oxide R18 0.00206``.
    """

    index: int
    name: str
    key: str
    kind: FunctionKind
    numerator: str | None = None
    denominator: str | None = None
    numerator_mass: int | None = None
    denominator_mass: int | None = None
    mass: int | None = None
    collector: Literal["D", "F"] | None = None
    unit: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def is_ratio(self) -> bool:
        return self.kind == "ratio"


@dataclass
class RunMetadata:
    """Header facts of a run. ``extra`` keeps every other header field the file has.

    ``analysis_start`` is the instrument's wall-clock start time. The files carry
    no timezone, so the datetime is naive unless a reader learns the zone; the
    text as written is always kept in ``analysis_start_raw``. ``aborted`` means
    the run stopped before the planned blocks × cycles. ``cycles_per_block`` is
    the number of cycle rows per block as written in the file (for IonVantage
    with beam interpolation on, the method's cycles per block + 1).
    """

    sample_id: str | None = None
    serial: str | None = None
    method: str | None = None
    instrument: str | None = None
    software: str | None = None
    analysis_start: datetime | None = None
    analysis_start_raw: str | None = None
    blocks: int | None = None
    cycles_per_block: int | None = None
    aborted: bool = False
    rejection: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(eq=False)
class Run:
    """One analysis: the functions and the per-cycle values of one raw file.

    ``values`` is ``n_cycles × n_functions`` (float, NaN where the file has no
    number). ``invalid`` flags values that never enter statistics: non-numeric
    or NaN anywhere, and ≤ 0 in ratio columns (legacy Tripoli's rule, made
    visible). ``cycle``, ``block`` and ``time`` are per-row arrays.
    """

    run_id: str
    raw: RawFile
    element: Element | None
    metadata: RunMetadata
    functions: tuple[Function, ...]
    cycle: np.ndarray
    block: np.ndarray
    time: np.ndarray
    values: np.ndarray
    invalid: np.ndarray

    @property
    def n_cycles(self) -> int:
        return int(self.values.shape[0])

    @property
    def n_functions(self) -> int:
        return len(self.functions)

    @property
    def keys(self) -> list[str]:
        return [function.key for function in self.functions]

    @property
    def names(self) -> list[str]:
        return [function.name for function in self.functions]

    @property
    def blocks_measured(self) -> int:
        return int(np.unique(self.block).size)

    def function(self, key: str) -> Function:
        for function in self.functions:
            if function.key == key:
                return function
        raise KeyError(key)

    def column(self, key: str) -> np.ndarray:
        return self.values[:, self.function(key).index]


def unique_keys(names: list[str]) -> list[str]:
    """``name`` for a first occurrence, ``name #2``, ``name #3`` … for repeats."""
    seen: dict[str, int] = {}
    used: set[str] = set()
    keys = []
    for name in names:
        count = seen.get(name, 0) + 1
        key = name if count == 1 else f"{name} #{count}"
        while key in used:  # a file that already has a column literally named "X #2"
            count += 1
            key = f"{name} #{count}"
        seen[name] = count
        used.add(key)
        keys.append(key)
    return keys
