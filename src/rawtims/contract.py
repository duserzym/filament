"""The ``idtims-fractions/1`` CSV contract: column names, rows, writer, reader and merge (SPEC F15, section 4).

The contract text is ``docs/contract-idtims-fractions-v1.md``; this module is
one implementation of it and the single source of the header names used in
this package (:data:`COLUMNS`).

Writer choices (the contract leaves them free):

* **Column subset.** :func:`write_csv` writes ``Contract`` and ``Fraction ID``
  plus every known column that has a value in at least one row, in the
  canonical order of :data:`COLUMNS`, then unknown extra columns in the order
  they were first seen. A column that is empty in every row is left out (an
  empty cell and a missing column mean the same: missing). So a Pb-only file
  has no U columns and no file carries two dozen empty ``rho`` columns.
* **Numbers** are written with Python ``repr`` (the shortest text that reads
  back to the identical double), never rounded. Integers (cycle counts) are
  written as integers. NaN is written as an empty cell; infinities are refused.
* UTF-8 without BOM, comma separator, ``\\n`` line endings, minimal quoting
  (Python ``csv``). The file is written to a temporary file and moved into
  place.

Reader rules: a BOM is tolerated; ``Contract`` must be ``idtims-fractions/1``
on every row (another major version is rejected with a message); unknown
columns are kept as text in :attr:`FractionRow.extra` and written back; a file
without a ``Contract`` column is read as a legacy CSV (the
IDTIMS_UPbRPy/Tripoli layout of ``examples/MA1_zircon_CA-ID-TIMS.csv``) with
``Grain ID`` taken as ``Fraction ID``.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
import io
import itertools
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Literal

CONTRACT_NAME = "idtims-fractions"
CONTRACT_MAJOR = 1
CONTRACT_ID = f"{CONTRACT_NAME}/{CONTRACT_MAJOR}"

# Allowed values of `U Oxide Formula` (contract clarification 6); each is defined by its formula there.
U_OXIDE_FORMULAS = ("tripoli_java_00dc941", "isobar_233_18O", "instrument")
MEAN_STATISTICS = ("arithmetic", "geometric")
MEAN_STATISTIC_COLUMNS = ("Pb Mean Statistic", "U Mean Statistic")

# Allowed values of `Pb/U Cycle Selection` (contract clarification 8); missing means unknown.
CYCLE_SELECTIONS = ("shared", "per_ratio")
CYCLE_SELECTION_COLUMNS = ("Pb Cycle Selection", "U Cycle Selection")

PB_RATIOS: tuple[str, ...] = ("206Pb/204Pb", "206Pb/207Pb", "206Pb/205Pb", "207Pb/205Pb", "204Pb/205Pb", "208Pb/205Pb", "202Pb/205Pb")
PB_REQUIRED_RATIOS: tuple[str, ...] = PB_RATIOS[:6]
"""Required whenever the Pb block is present; ``202Pb/205Pb`` is required too when ``Spike Type`` is 2535."""
PB_OPTIONAL_INVERSES: tuple[str, ...] = ("204Pb/206Pb", "207Pb/206Pb")
"""A writer *may* add these; this writer does not (readers derive them from 206/204 and 206/207)."""
U_RATIOS: tuple[str, ...] = ("238U/235U", "233U/235U", "238U/233U")
U_REQUIRED_RATIOS: tuple[str, ...] = U_RATIOS
RATIOS: tuple[str, ...] = PB_RATIOS + U_RATIOS
RATIO_ELEMENT: dict[str, str] = {**{r: "Pb" for r in PB_RATIOS + PB_OPTIONAL_INVERSES}, **{r: "U" for r in U_RATIOS}}
_RATIO_NAME = re.compile(r"^(\d{3})(Pb|U)/(\d{3})(Pb|U)$")


def ratio_masses(ratio: str) -> tuple[int, int]:
    """``"206Pb/204Pb"`` → ``(206, 204)``."""
    match = _RATIO_NAME.match(ratio)
    if not match:
        raise ValueError(f"not a contract ratio name: {ratio!r}")
    return int(match.group(1)), int(match.group(3))


def mean_column(ratio: str) -> str:
    return f"{ratio} Mean"


def se_column(ratio: str) -> str:
    return f"{ratio} % Standard Error"


def rho_column(ratio_a: str, ratio_b: str) -> str:
    return f"rho {ratio_a}|{ratio_b}"


def ratio_pairs(element: str) -> list[tuple[str, str]]:
    """The ``(A, B)`` pairs with a ``rho A|B`` column for one block, A before B in contract order."""
    ratios = PB_RATIOS if element == "Pb" else U_RATIOS
    return list(itertools.combinations(ratios, 2))


ColumnKind = Literal["text", "float", "int"]


@dataclass(frozen=True)
class Column:
    name: str
    kind: ColumnKind
    group: str
    required: bool = False


def _build_columns() -> tuple[Column, ...]:
    columns: list[Column] = [
        Column("Contract", "text", "identity", required=True),
        Column("Fraction ID", "text", "identity", required=True),
    ]
    columns += [Column(name, "text", "identity") for name in ("Sample", "Beaker", "Source Mount", "Source Grain", "Source Spot", "Aliquot")]
    columns += [
        Column("Sample Weight (mg)", "float", "setup"),
        Column("Spike Weight (g)", "float", "setup"),
        Column("Spike Type", "text", "setup"),
        Column("Spike", "text", "setup"),
        Column("Collector", "text", "setup"),
        Column("Pb Collector Detail", "text", "setup"),
        Column("Pb Method", "text", "setup"),
        Column("U Method", "text", "setup"),
    ]
    for ratio in PB_RATIOS + PB_OPTIONAL_INVERSES + U_RATIOS:
        columns += [Column(mean_column(ratio), "float", "ratios"), Column(se_column(ratio), "float", "ratios")]
    for element in ("Pb", "U"):
        columns += [Column(rho_column(a, b), "float", "correlations") for a, b in ratio_pairs(element)]
    provenance: list[tuple[str, ColumnKind]] = [
        ("Pb Raw File", "text"), ("U Raw File", "text"),
        ("Pb Raw SHA256", "text"), ("U Raw SHA256", "text"),
        ("Pb Run Start", "text"), ("U Run Start", "text"),
        ("Instrument", "text"),
        ("Pb Cycles Used", "int"), ("Pb Cycles Total", "int"), ("U Cycles Used", "int"), ("U Cycles Total", "int"),
        ("Filter Rule", "text"),
        ("U Oxide 18O/16O", "float"),
        ("U Oxide Formula", "text"),
        ("Pb Mean Statistic", "text"), ("U Mean Statistic", "text"),
        ("Pb Cycle Selection", "text"), ("U Cycle Selection", "text"),
        ("Raw App", "text"),
        ("Raw App Session", "text"), ("Raw App Session SHA256", "text"),
        ("Exported At", "text"),
        ("Notes", "text"),
    ]
    columns += [Column(name, kind, "provenance") for name, kind in provenance]
    return tuple(columns)


COLUMNS: tuple[Column, ...] = _build_columns()
COLUMN_NAMES: tuple[str, ...] = tuple(column.name for column in COLUMNS)
COLUMN_BY_NAME: dict[str, Column] = {column.name: column for column in COLUMNS}
REQUIRED_COLUMNS: tuple[str, ...] = tuple(column.name for column in COLUMNS if column.required)
LEGACY_ID_COLUMN = "Grain ID"


class ContractError(ValueError):
    """A file or row that does not follow the contract; the message says what and where."""


class MergeConflict(ContractError):
    """Two files give different non-empty values for the same fraction and column (contract "Rows and merging")."""


def format_value(value: Any, kind: ColumnKind) -> str:
    """The cell text of one value (empty for None/NaN). See the module docstring for the number format."""
    if value is None:
        return ""
    if kind == "text":
        return str(value)
    if isinstance(value, bool):
        raise ContractError(f"boolean {value!r} in a numeric column")
    if kind == "int":
        return str(int(value))
    number = float(value)
    if math.isnan(number):
        return ""
    if math.isinf(number):
        raise ContractError(f"infinite value {value!r} cannot be written")
    return repr(number)


def parse_value(text: str, kind: ColumnKind, *, column: str = "") -> Any:
    """Parse one non-empty cell for a known column."""
    if kind == "text":
        return text
    try:
        number = float(text)
    except ValueError:
        raise ContractError(f"column {column!r}: {text!r} is not a number") from None
    if kind == "int":
        if not number.is_integer():
            raise ContractError(f"column {column!r}: {text!r} is not an integer")
        return int(number)
    return number


def _coerce(name: str, value: Any) -> Any:
    kind = COLUMN_BY_NAME[name].kind
    if value is None:
        return None
    if kind == "text":
        if not isinstance(value, str):
            raise ContractError(f"column {name!r} holds text, got {type(value).__name__}")
        return value or None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"column {name!r} holds numbers, got {type(value).__name__}")
    if kind == "int":
        if isinstance(value, float):
            if not value.is_integer():
                raise ContractError(f"column {name!r} holds integers, got {value!r}")
            value = int(value)
        return int(value)
    value = float(value)
    if math.isnan(value):
        return None
    if math.isinf(value):
        raise ContractError(f"column {name!r}: infinite value")
    return value


@dataclass
class FractionRow:
    """One contract row: typed values of known columns and the text of unknown extra columns.

    ``values`` maps exact column names from :data:`COLUMNS` to ``str``,
    ``float`` or ``int`` (per :attr:`Column.kind`); a missing value is simply
    absent. ``extra`` keeps unknown columns as text, to be written back.
    ``legacy`` is True for a row read from a file without ``Contract``.
    """

    values: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)
    legacy: bool = False

    def __post_init__(self) -> None:
        clean: dict[str, Any] = {}
        for name, value in self.values.items():
            if name not in COLUMN_BY_NAME:
                raise ContractError(f"unknown column {name!r}; put columns outside the contract into 'extra'")
            coerced = _coerce(name, value)
            if coerced is not None:
                clean[name] = coerced
        self.values = clean
        clash = set(self.extra) & set(COLUMN_BY_NAME)
        if clash:
            raise ContractError(f"extra columns {sorted(clash)} are contract columns")
        self.extra = {name: str(text) for name, text in self.extra.items() if text not in (None, "")}

    # ------------------------------------------------------------- access
    @property
    def fraction_id(self) -> str | None:
        return self.values.get("Fraction ID")

    def get(self, name: str, default: Any = None) -> Any:
        # Keep missing cells absent for lossless re-export, but interpret the
        # optional statistic as arithmetic (contract clarification 7).
        if name in MEAN_STATISTIC_COLUMNS:
            return self.values.get(name, "arithmetic")
        if name in COLUMN_BY_NAME:
            return self.values.get(name, default)
        return self.extra.get(name, default)

    def mean(self, ratio: str) -> float | None:
        return self.values.get(mean_column(ratio))

    def se_pct(self, ratio: str) -> float | None:
        return self.values.get(se_column(ratio))

    def rho(self, ratio_a: str, ratio_b: str) -> float | None:
        return self.values.get(rho_column(ratio_a, ratio_b))

    def has_block(self, element: str) -> bool:
        ratios = (PB_RATIOS + PB_OPTIONAL_INVERSES) if element == "Pb" else U_RATIOS
        return any(mean_column(r) in self.values or se_column(r) in self.values for r in ratios)

    def problems(self) -> list[str]:
        """What keeps this row from being a valid contract row (empty list when valid)."""
        found = []
        if not self.fraction_id:
            found.append("Fraction ID is empty")
        contract = self.values.get("Contract")
        if contract is not None and contract != CONTRACT_ID:
            found.append(f"Contract is {contract!r}, expected {CONTRACT_ID!r}")
        label = self.fraction_id or "?"
        for column in MEAN_STATISTIC_COLUMNS:
            value = self.get(column)
            if value not in MEAN_STATISTICS:
                found.append(f"fraction {label}: {column!r} = {value!r} is not one of {MEAN_STATISTICS}")
        for column in CYCLE_SELECTION_COLUMNS:
            value = self.values.get(column)
            if value is not None and value not in CYCLE_SELECTIONS:
                found.append(f"fraction {label}: {column!r} = {value!r} is not one of {CYCLE_SELECTIONS}")
        for element, required in (("Pb", PB_REQUIRED_RATIOS), ("U", U_REQUIRED_RATIOS)):
            if not self.has_block(element):
                continue
            if element == "Pb" and self.values.get("Spike Type") == "2535":
                required = (*required, "202Pb/205Pb")
            for ratio in required:
                for column in (mean_column(ratio), se_column(ratio)):
                    if column not in self.values:
                        found.append(f"fraction {label}: {element} block present but {column!r} is missing")
        formula = self.values.get("U Oxide Formula")
        if self.values.get("U Oxide 18O/16O") is not None and formula is None:
            found.append(f"fraction {label}: 'U Oxide Formula' is required when 'U Oxide 18O/16O' is filled")
        if formula is not None and formula not in U_OXIDE_FORMULAS:
            found.append(f"fraction {label}: 'U Oxide Formula' = {formula!r} is not one of {U_OXIDE_FORMULAS}")
        for name, value in self.values.items():
            if name.startswith("rho ") and not -1.0 <= value <= 1.0:
                found.append(f"fraction {label}: {name} = {value!r} is outside [-1, 1]")
        return found

    # ----------------------------------------------------------------- csv
    def to_csv(self) -> dict[str, str]:
        """Cell texts of the non-empty columns (known and extra); ``Contract`` is always set."""
        cells = {name: format_value(value, COLUMN_BY_NAME[name].kind) for name, value in self.values.items()}
        cells["Contract"] = CONTRACT_ID
        cells.update(self.extra)
        return {name: text for name, text in cells.items() if text != ""}

    @classmethod
    def from_csv(cls, cells: dict[str, str], *, legacy: bool = False) -> FractionRow:
        """Build a row from cell texts (header name → text); empty cells are missing."""
        values: dict[str, Any] = {}
        extra: dict[str, str] = {}
        for name, text in cells.items():
            if text == "":
                continue
            column = COLUMN_BY_NAME.get(name)
            if column is None:
                extra[name] = text
            else:
                values[name] = parse_value(text, column.kind, column=name)
        return cls(values=values, extra=extra, legacy=legacy)


# --------------------------------------------------------------------- write
def header_for(rows: Sequence[FractionRow]) -> list[str]:
    """``Contract``, ``Fraction ID``, the used known columns in canonical order, then extras by first appearance."""
    used = set(REQUIRED_COLUMNS)
    extras: dict[str, None] = {}
    for row in rows:
        used.update(row.values)
        for name in row.extra:
            extras.setdefault(name, None)
    return [name for name in COLUMN_NAMES if name in used] + list(extras)


def csv_text(rows: Sequence[FractionRow]) -> str:
    """The CSV text :func:`write_csv` writes. Raises :class:`ContractError` for invalid rows or duplicate IDs."""
    seen: set[str | None] = set()
    problems: list[str] = []
    for row in rows:
        problems += row.problems()
        if row.fraction_id in seen:
            problems.append(f"Fraction ID {row.fraction_id!r} appears twice")
        seen.add(row.fraction_id)
    if problems:
        raise ContractError("cannot write the fractions file: " + "; ".join(problems))
    header = header_for(rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        cells = row.to_csv()
        writer.writerow([cells.get(name, "") for name in header])
    return buffer.getvalue()


def write_csv(rows: Iterable[FractionRow], path: str | os.PathLike[str]) -> Path:
    """Write rows as an ``idtims-fractions/1`` file (atomically). Returns the path."""
    text = csv_text(list(rows))
    path = Path(path)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


# ---------------------------------------------------------------------- read
def _check_contract_value(value: str, where: str) -> None:
    if value == CONTRACT_ID:
        return
    if value == "":
        raise ContractError(f"{where}: the Contract cell is empty; it must be {CONTRACT_ID!r} on every row")
    if re.fullmatch(rf"{re.escape(CONTRACT_NAME)}/\d+(?:\.\d+)*", value.strip()):
        raise ContractError(
            f"{where}: contract version {value!r} is not supported; this reader knows major version "
            f"{CONTRACT_MAJOR} ({CONTRACT_ID}). A newer application is needed to read this file."
        )
    raise ContractError(f"{where}: Contract is {value!r}, not an {CONTRACT_NAME} file")


def parse_csv_text(text: str, *, source: str = "<text>") -> list[FractionRow]:
    """Parse contract (or legacy) CSV text; see :func:`read_csv`."""
    text = text.removeprefix("﻿")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise ContractError(f"{source}: empty file") from None
    duplicates = sorted({name for name in header if header.count(name) > 1})
    if duplicates:
        raise ContractError(f"{source}: duplicate column names {duplicates}")
    legacy = "Contract" not in header
    if legacy:
        if "Fraction ID" not in header:
            if LEGACY_ID_COLUMN not in header:
                raise ContractError(f"{source}: no Contract column and no {LEGACY_ID_COLUMN!r} or 'Fraction ID' column")
            header = ["Fraction ID" if name == LEGACY_ID_COLUMN else name for name in header]
    elif "Fraction ID" not in header:
        raise ContractError(f"{source}: no 'Fraction ID' column")
    rows: list[FractionRow] = []
    seen: dict[str, int] = {}
    for line_number, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue
        where = f"{source}, line {line_number}"
        if len(cells) > len(header):
            raise ContractError(f"{where}: {len(cells)} cells but {len(header)} columns")
        record = dict(zip(header, cells + [""] * (len(header) - len(cells))))
        if not legacy:
            _check_contract_value(record["Contract"], where)
        try:
            row = FractionRow.from_csv(record, legacy=legacy)
        except ContractError as error:
            raise ContractError(f"{where}: {error}") from None
        if not row.fraction_id:
            raise ContractError(f"{where}: Fraction ID is empty")
        if row.fraction_id in seen:
            raise ContractError(f"{where}: Fraction ID {row.fraction_id!r} already used on line {seen[row.fraction_id]}")
        seen[row.fraction_id] = line_number
        rows.append(row)
    return rows


def read_csv(path: str | os.PathLike[str]) -> list[FractionRow]:
    """Read an ``idtims-fractions/1`` file or a legacy CSV (no ``Contract`` column; ``Grain ID`` → ``Fraction ID``)."""
    path = Path(path)
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ContractError(f"{path.name}: not UTF-8 text ({error})") from None
    return parse_csv_text(text, source=path.name)


# --------------------------------------------------------------------- merge
def merge_rows(sources: Sequence[tuple[str, Sequence[FractionRow]]]) -> list[FractionRow]:
    """Merge rows that share a ``Fraction ID`` across files (contract "Rows and merging").

    ``sources`` is ``[(file label, rows), ...]``. Rows are combined column by
    column; two different non-empty values for the same fraction and column
    raise :class:`MergeConflict` naming the fraction, the column and both
    files. The result keeps the order of first appearance.
    """
    merged: dict[str | None, dict[str, Any]] = {}
    for label, rows in sources:
        for row in rows:
            entry = merged.setdefault(row.fraction_id, {"values": {}, "extra": {}, "origin": {}, "legacy": True})
            values = dict(row.values)
            # A legacy block's implicit arithmetic mode conflicts with an
            # explicit geometric block too. An absent block supplies no mode.
            for element in ("Pb", "U"):
                column = f"{element} Mean Statistic"
                if row.has_block(element):
                    values.setdefault(column, row.get(column))
            for name, value in [*values.items(), *row.extra.items()]:
                target = entry["values"] if name in COLUMN_BY_NAME else entry["extra"]
                if name in target and target[name] != value:
                    raise MergeConflict(
                        f"fraction {row.fraction_id!r}, column {name!r}: {entry['origin'][name]} has {target[name]!r} "
                        f"but {label} has {value!r}"
                    )
                if name not in target:
                    target[name] = value
                    entry["origin"][name] = label
            entry["legacy"] = entry["legacy"] and row.legacy
    return [FractionRow(values=dict(e["values"]), extra=dict(e["extra"]), legacy=e["legacy"]) for e in merged.values()]


def read_and_merge(paths: Sequence[str | os.PathLike[str]]) -> list[FractionRow]:
    """Read several files and merge their rows by Fraction ID."""
    return merge_rows([(Path(path).name, read_csv(path)) for path in paths])


__all__ = [
    "COLUMNS",
    "COLUMN_BY_NAME",
    "COLUMN_NAMES",
    "CONTRACT_ID",
    "CONTRACT_MAJOR",
    "CONTRACT_NAME",
    "LEGACY_ID_COLUMN",
    "PB_OPTIONAL_INVERSES",
    "PB_RATIOS",
    "PB_REQUIRED_RATIOS",
    "RATIOS",
    "RATIO_ELEMENT",
    "REQUIRED_COLUMNS",
    "U_RATIOS",
    "U_REQUIRED_RATIOS",
    "Column",
    "ContractError",
    "FractionRow",
    "MergeConflict",
    "csv_text",
    "format_value",
    "header_for",
    "mean_column",
    "merge_rows",
    "parse_csv_text",
    "parse_value",
    "ratio_masses",
    "ratio_pairs",
    "read_and_merge",
    "read_csv",
    "rho_column",
    "se_column",
    "write_csv",
]
