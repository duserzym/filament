"""Opt-in, Qt-free cross-run evidence. No calibration is applied from this book.

C# schema references: GainsFile.cs:157-278 (dated collector cycles),
StandardsFile.cs:164-201 (block means), TripoliHistoryFolderStandards.cs:124-143
(folder/history/settings), frmHistoryGraph.cs:408-427 (history selections).
Records are content-addressed immutable JSON snapshots; exclusions are separate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from rawtims.stats import describe

FORMAT = "rawtims calibration history"
VERSION = 1


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def finite(value):
    return float(value) if math.isfinite(value) else None


@dataclass(frozen=True)
class HistoryRecord:
    """Payload text prevents mutation through nested arrays or dictionaries."""

    payload: str

    def __post_init__(self):
        data = json.loads(self.payload)
        if set(data) != {
            "kind",
            "date",
            "label",
            "source",
            "calibration",
            "review",
            "series",
            "derivation",
        }:
            raise ValueError("unknown history record fields")
        if data["kind"] not in ("gains", "standard") or not isinstance(
            data["label"], str
        ):
            raise ValueError("unknown history kind/label")
        if data["date"] is not None:
            date = datetime.fromisoformat(data["date"])
            if date.tzinfo is not None:
                raise ValueError(
                    "history uses recorded instrument wall times; timezone mixing is unsupported"
                )
        if (
            not isinstance(data["source"], dict)
            or not isinstance(data["source"].get("sha256"), str)
            or not re.fullmatch("[0-9a-f]{64}", data["source"]["sha256"])
        ):
            raise ValueError("history requires source SHA-256")
        if not all(
            isinstance(data[k], dict) for k in ("calibration", "review")
        ) or not isinstance(data["derivation"], str):
            raise ValueError("invalid history provenance")
        if not isinstance(data["series"], list) or not data["series"]:
            raise ValueError("history series must be a nonempty list")
        keys = set()
        for series in data["series"]:
            if (
                set(series) != {"key", "unit", "mean", "se", "n", "block_means"}
                or not isinstance(series["key"], str)
                or series["key"] in keys
            ):
                raise ValueError("unknown/duplicate history series")
            keys.add(series["key"])
            if type(series["n"]) is not int or series["n"] < 0:
                raise ValueError("invalid history count")
            for number in (series["mean"], series["se"], *series["block_means"]):
                if number is not None and (
                    type(number) not in (int, float) or not math.isfinite(number)
                ):
                    raise ValueError("non-finite history value")
        object.__setattr__(self, "payload", canonical(data))

    @property
    def key(self):
        return hashlib.sha256(self.payload.encode()).hexdigest()

    @property
    def data(self):
        return json.loads(self.payload)


def record(kind, date, label, source, calibration, review, series, derivation):
    return HistoryRecord(
        canonical(
            {
                "kind": kind,
                "date": date,
                "label": label,
                "source": source,
                "calibration": calibration,
                "review": review,
                "series": series,
                "derivation": derivation,
            }
        )
    )


def summary(key, values, unit=None, block_means=()):
    stat = describe(values)
    return {
        "key": key,
        "unit": unit,
        "mean": finite(stat.mean),
        "se": finite(stat.se),
        "n": stat.n_used,
        "block_means": [finite(v) for v in block_means],
    }


def capture(analysis, kind):
    """Snapshot an explicitly selected open run; never infer that a sample is a standard.

    Standards retain current accepted-cycle block means (arithmetic), then their
    equal-block mean/SE. This is a labeled diagnostic, distinct from cycle export.
    """
    if kind not in ("gains", "standard"):
        raise ValueError("choose gains or standard")
    run = analysis.run
    params = run.reduction_parameters
    calibration = {
        "parameters": params.to_dict(),
        "sha256": params.sha256,
        "acquired": analysis.initial_reduction_parameters.to_dict(),
        "provenance": run.provenance,
    }
    series = []
    if kind == "gains":
        for collector, value in sorted(
            analysis.initial_reduction_parameters.faraday_gains.items()
        ):
            series.append(summary("As-acquired " + collector, [value]))
        for function in run.functions:
            if "gain" in function.name.casefold():
                values = run.column(function.key)
                series.append(
                    summary(function.key, values[np.isfinite(values)], function.unit)
                )
    else:
        for function in analysis.functions:
            if function.is_ratio:
                means = [
                    describe(
                        analysis.column(function.key)[run.block == block],
                        analysis.included_for(function.key)[run.block == block],
                    ).mean
                    for block in analysis.blocks
                ]
                series.append(summary(function.key, means, function.unit, means))
    if not series:
        raise ValueError(
            "This run has no recorded gains"
            if kind == "gains"
            else "This run has no ratio functions"
        )
    return record(
        kind,
        run.metadata.analysis_start.isoformat()
        if run.metadata.analysis_start
        else None,
        run.metadata.sample_id or run.raw.name,
        {
            "path": run.raw.path,
            "sha256": run.raw.sha256,
            "format": run.raw.format,
            "version": run.raw.format_version,
            "method": run.metadata.method,
        },
        calibration,
        {
            "settings": analysis.settings.to_dict(),
            "history": analysis.history,
            "included": analysis.included.tolist(),
            "blocks": analysis.block_included.tolist(),
        },
        series,
        "rawtims history/1; accepted-cycle arithmetic block means, equal-block summary"
        if kind == "standard"
        else "rawtims history/1; as-acquired gains and unfiltered acquired gain columns",
    )


class HistoryBook:
    def __init__(self):
        self._records = {}
        self._events = []
        self.applied = 0

    @property
    def records(self):
        return tuple(
            sorted(
                self._records.values(),
                key=lambda r: (r.data["date"] is None, r.data["date"] or "", r.key),
            )
        )

    def add(self, entry):
        if not isinstance(entry, HistoryRecord):
            raise TypeError("expected immutable history record")
        if entry.key in self._records:
            return False
        self._records[entry.key] = entry
        return True

    def excluded(self, key):
        if key not in self._records:
            raise ValueError("unknown history record")
        value = False
        for event in self._events[: self.applied]:
            if event["key"] == key:
                value = event["after"]
        return value

    def exclude(self, key, excluded, reason):
        if (
            type(excluded) is not bool
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError("history exclusions require a reason")
        before = self.excluded(key)
        if before == excluded:
            return False
        self._events[self.applied :] = [
            {"key": key, "before": before, "after": excluded, "reason": reason.strip()}
        ]
        self.applied += 1
        return True

    def undo(self):
        if self.applied:
            self.applied -= 1
            return True
        return False

    def redo(self):
        if self.applied < len(self._events):
            self.applied += 1
            return True
        return False

    def to_dict(self):
        return json.loads(
            canonical(
                {
                    "format": FORMAT,
                    "version": VERSION,
                    "records": [{"key": r.key, "data": r.data} for r in self.records],
                    "events": self._events,
                    "applied": self.applied,
                }
            )
        )

    @classmethod
    def from_dict(cls, data):
        book = cls()
        if data == {}:
            return book
        if not isinstance(data, dict):
            raise TypeError("history must be an object")
        if (
            set(data) != {"format", "version", "records", "events", "applied"}
            or data["format"] != FORMAT
            or type(data["version"]) is not int
            or data["version"] != VERSION
        ):
            raise ValueError("unknown history schema/version")
        if not isinstance(data["records"], list) or not isinstance(
            data["events"], list
        ):
            raise TypeError("history records/events must be lists")
        for entry in data["records"]:
            if not isinstance(entry, dict):
                raise TypeError("invalid history record")
            item = HistoryRecord(canonical(entry["data"]))
            if (
                set(entry) != {"key", "data"}
                or entry["key"] != item.key
                or not book.add(item)
            ):
                raise ValueError("history record hash mismatch/duplicate")
        for event in data["events"]:
            if (
                not isinstance(event, dict)
                or set(event) != {"key", "before", "after", "reason"}
                or type(event["before"]) is not bool
                or event["before"] != book.excluded(event["key"])
            ):
                raise ValueError("history exclusion replay mismatch")
            if not book.exclude(event["key"], event["after"], event["reason"]):
                raise ValueError("empty history event")
        if type(data["applied"]) is not int or not 0 <= data["applied"] <= len(
            book._events
        ):
            raise ValueError("invalid history cursor")
        book.applied = data["applied"]
        return book
