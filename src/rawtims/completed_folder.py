"""Manual snapshots of the C# -B*-C*.txt dialect, never a live watcher.

OGTripoli/source/vendors_data/IonVantageLiveDataCyclesFolder.cs:67-216.
The source has no completion marker or elapsed-time field. A user must explicitly
attest completion. Two unchanged size/mtime snapshots and read-time checks are
required; these checks cannot prove an instrument has stopped writing.
"""

from __future__ import annotations

import csv
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rawtims.history import canonical
from rawtims.model import RawFile, RunMetadata
from rawtims.readers import UnsupportedFile
from rawtims.readers.common import assemble_run, parse_instrument_datetime
from rawtims.readers.functions import build_functions

FORMAT = "rawtims completed cycle snapshot"
NAME = re.compile(r"(.+)-B([0-9]+)-C([0-9]+)\.txt$", re.IGNORECASE)
MAX_BYTES = 4 * 1024 * 1024
MAX_FILES = 100000


@dataclass(frozen=True)
class CycleSpecimen:
    prefix: str
    block: int
    cycle: int
    method: str
    date: str
    names: tuple[str, ...]
    values: tuple[float, ...]


def parse_cycle(name, data):
    """Strict positional subset fully described in C# LoadRatios, lines 75-184.

    The five uninterpreted header lines and three separators are kept as opaque
    text; only the positions consumed by the C# reader carry meaning here.
    """
    match = NAME.fullmatch(name)
    if not match or int(match[2]) < 1 or int(match[3]) < 1 or len(data) > MAX_BYTES:
        raise UnsupportedFile("unknown cycle filename or excessive file size")
    try:
        lines = data.decode("utf-8-sig").splitlines()
        rows = list(csv.reader(lines, strict=True))
        if (
            len(rows) < 12
            or "Version" not in lines[0]
            or rows[5][0] != "Method"
            or rows[6][0] != "Acquire Date"
            or rows[7][0] != "Functions"
        ):
            raise ValueError("unknown cycle header")
        if any(len(rows[i]) != 2 for i in (5, 6, 7)):
            raise ValueError("invalid cycle header width")
        count = int(rows[7][1])
        if not 1 <= count <= 4096:
            raise ValueError("invalid function count")
        if (
            parse_instrument_datetime(rows[6][1]) is None
            or ".RAW\\" not in rows[5][1].upper()
        ):
            raise ValueError("unknown acquisition date or Method path")
        names = tuple(rows[11 + i][1].strip() for i in range(count))
        if any(len(rows[11 + i]) != 2 or not names[i] for i in range(count)):
            raise ValueError("unknown function header")
        starts = [i for i, line in enumerate(lines) if line.startswith("#START")]
        if len(starts) != 1 or starts[0] < 11 + count:
            raise ValueError("missing/duplicate #START")
        values = []
        for row in rows[starts[0] + 1 : starts[0] + 1 + count]:
            if len(row) != 3 or not all(cell.strip() for cell in row):
                raise ValueError("truncated/unknown cycle data row")
            values.append(float(row[2]))
        if len(values) != count or not np.isfinite(values).all():
            raise ValueError("truncated/non-finite cycle values")
        # C# stops after count rows. Refuse unrecognized data rather than silently discard it.
        tail = [row for row in rows[starts[0] + 1 + count :] if row]
        if tail and tail != [["#END"]]:
            raise ValueError("unknown trailing cycle data")
        return CycleSpecimen(
            match[1],
            int(match[2]),
            int(match[3]),
            rows[5][1],
            rows[6][1],
            names,
            tuple(values),
        )
    except (ValueError, IndexError, UnicodeError, csv.Error) as error:
        raise UnsupportedFile(f"{name}: {error}") from None


class CompletedFolder:
    """Folder-bound observations; selecting another folder creates a fresh instance."""

    def __init__(self, path, settle_seconds=1.0):
        self.path = Path(path).resolve()
        if not np.isfinite(settle_seconds) or settle_seconds <= 0:
            raise ValueError("settle interval must be positive")
        self.settle_seconds = settle_seconds
        self._seen = {}
        self._ready = None
        self.notice = "Refresh twice after the files settle."

    def _listing(self):
        if not self.path.is_dir():
            raise UnsupportedFile("cycle folder is missing")
        result = {}
        for path in sorted(self.path.iterdir()):
            if NAME.fullmatch(path.name):
                if path.is_symlink() or not path.is_file():
                    raise UnsupportedFile("cycle entries must be regular local files")
                stat = path.stat()
                if stat.st_size > MAX_BYTES:
                    raise UnsupportedFile("cycle file size limit exceeded")
                result[path.name] = (stat.st_size, stat.st_mtime_ns)
        if not result or len(result) > MAX_FILES:
            raise UnsupportedFile("empty or excessive cycle folder")
        return result

    def refresh(self, *, now=None):
        now = time.monotonic() if now is None else now
        self._ready = None
        try:
            listing = self._listing()
            pending = []
            observations = {}
            for name, signature in listing.items():
                previous = self._seen.get(name)
                since = previous[1] if previous and previous[0] == signature else now
                observations[name] = (signature, since)
                if now - since < self.settle_seconds:
                    pending.append(name)
            self._seen = observations
            if pending:
                self.notice = f"{len(pending)} file(s) settling; Refresh again after {self.settle_seconds:g} s."
                return False
            specimens, manifest = [], []
            for name, signature in listing.items():
                data = (self.path / name).read_bytes()
                stat = (self.path / name).stat()
                if (
                    len(data) != signature[0]
                    or (stat.st_size, stat.st_mtime_ns) != signature
                ):
                    raise UnsupportedFile(
                        "folder changed during Refresh; retry after settling"
                    )
                specimens.append(parse_cycle(name, data))
                manifest.append(
                    {
                        "name": name,
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            if self._listing() != listing:
                raise UnsupportedFile(
                    "folder changed during Refresh; retry after settling"
                )
            first = specimens[0]
            identity = (first.prefix, first.method, first.date, first.names)
            by_cycle = {}
            duplicates = 0
            for specimen in specimens:
                if (
                    specimen.prefix.casefold(),
                    specimen.method,
                    specimen.date,
                    specimen.names,
                ) != (identity[0].casefold(), *identity[1:]):
                    raise UnsupportedFile("mixed acquisitions or function headers")
                key = specimen.block, specimen.cycle
                if key in by_cycle:
                    if specimen.values != by_cycle[key].values:
                        raise UnsupportedFile("conflicting duplicate cycle")
                    duplicates += 1
                by_cycle[key] = specimen
            ordered = sorted(by_cycle)
            cpb = (
                max(c for b, c in ordered if b == 1)
                if any(b == 1 for b, c in ordered)
                else 0
            )
            if (
                cpb == 0
                or len(ordered) % cpb
                or any(
                    key != (index // cpb + 1, index % cpb + 1)
                    for index, key in enumerate(ordered)
                )
            ):
                raise UnsupportedFile(
                    "missing cycle or incomplete block; completed rectangular folders only"
                )
            self._ready = {
                "format": FORMAT,
                "version": 1,
                "method": first.method,
                "date": first.date,
                "names": list(first.names),
                "cycles_per_block": cpb,
                "values": [list(by_cycle[key].values) for key in ordered],
                "manifest": manifest,
                "folder": str(self.path),
                "attested_complete": True,
            }
            self._signature = listing
            self.notice = f"{len(ordered)} cycles ready · {duplicates} identical duplicates ignored. Confirm acquisition is complete before opening."
            return True
        except (OSError, UnsupportedFile) as error:
            self.notice = str(error)
            return False

    def snapshot_bytes(self, *, completed=False):
        if completed is not True:
            raise UnsupportedFile(
                "explicit completed-acquisition confirmation required"
            )
        if self._ready is None or self._listing() != self._signature:
            self._ready = None
            raise UnsupportedFile("Refresh a settled folder first")
        # Validate content again, even if a writer restored size/mtime.
        for entry in self._ready["manifest"]:
            if (
                hashlib.sha256((self.path / entry["name"]).read_bytes()).hexdigest()
                != entry["sha256"]
            ):
                self._ready = None
                raise UnsupportedFile("cycle content changed; Refresh again")
        if self._listing() != self._signature:
            self._ready = None
            raise UnsupportedFile("folder changed while opening; Refresh again")
        return (canonical(self._ready) + "\n").encode()


def read_snapshot(path, data):
    """Portable immutable acquisition snapshot; ordinary run dispatch reads only this schema."""
    import json

    try:
        item = json.loads(data)
        if (
            set(item)
            != {
                "format",
                "version",
                "method",
                "date",
                "names",
                "cycles_per_block",
                "values",
                "manifest",
                "folder",
                "attested_complete",
            }
            or item["format"] != FORMAT
            or type(item["version"]) is not int
            or item["version"] != 1
            or item["attested_complete"] is not True
        ):
            raise ValueError("unknown completed snapshot schema")
        cpb = item["cycles_per_block"]
        if type(cpb) is not int or cpb < 1:
            raise ValueError("invalid block length")
        date = parse_instrument_datetime(item["date"])
        if (
            date is None
            or not isinstance(item["method"], str)
            or ".RAW\\" not in item["method"].upper()
        ):
            raise ValueError("invalid snapshot date/method")
        names = item["names"]
        if (
            not isinstance(names, list)
            or not 1 <= len(names) <= 4096
            or not all(isinstance(n, str) and n.strip() for n in names)
        ):
            raise ValueError("invalid snapshot functions")
        values = np.asarray(item["values"], dtype=float)
        if (
            values.ndim != 2
            or values.shape[1] != len(names)
            or not 1 <= len(values) <= MAX_FILES
            or len(values) % cpb
            or not np.isfinite(values).all()
        ):
            raise ValueError("invalid snapshot cycles")
        if not item["manifest"] or any(
            set(e) != {"name", "size", "sha256"}
            or not NAME.fullmatch(e["name"])
            or type(e["size"]) is not int
            or e["size"] < 0
            or not re.fullmatch("[0-9a-f]{64}", e["sha256"])
            for e in item["manifest"]
        ):
            raise ValueError("invalid snapshot manifest")
        functions = build_functions(names)
        # The Method field is an acquisition path, not a method name. Preserve it verbatim.
        acquisition = re.split(r"\.RAW\\", item["method"], flags=re.IGNORECASE)[-1]
        metadata = RunMetadata(
            sample_id=acquisition,
            analysis_start=date,
            analysis_start_raw=item["date"],
            cycles_per_block=cpb,
            blocks=len(values) // cpb,
            complete=None,
            stopped_early=None,
            extra={"cycle_folder": item},
        )
        run = assemble_run(
            RawFile.describe(path, data, FORMAT, "1"),
            metadata,
            functions,
            np.arange(1, len(values) + 1),
            np.full(len(values), np.nan),
            values,
        )
        run.warnings = (
            "User-attested completed folder; no instrument completion flag or elapsed times in this dialect.",
        )
        return run
    except (ValueError, TypeError, KeyError) as error:
        raise UnsupportedFile(f"invalid completed cycle snapshot: {error}") from None
