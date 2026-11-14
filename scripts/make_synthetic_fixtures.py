#!/usr/bin/env python3
"""Write the SYNTHETIC IonVantage-like workbooks under tests/fixtures/synthetic/ (SPEC section 0, decision 4).

They cover cases no real fixture has, until real Boise State files arrive:

* ``synthetic_BSU_U_oxide_R18.xls``: a U run whose CYCLE sheet carries the BSU
  function names ``238/235 oxide R18 0.00206``, ``233/235 oxide R18 0.00206``
  and ``238/233 oxide`` next to the raw ``270/267``, ``265/267`` and ``272/270``.
  The oxide-corrected columns are computed from the raw ones with the ET_Redux
  form (238/235 = R270/267 / (1 − 2·r18·R265/267), 233/235 = R265/267 /
  (1 − 2·r18·R265/267)), r18 = 0.00206.
* ``synthetic_ET2535_Pb_202.xls``: a BSU-style Pb run with ``202/205 D`` and
  the other ``D`` functions, beam interpolation on (16 rows per block), and a
  repeated ``Daly/Faraday Gain`` column as in the real BSU workbook.

Magnitudes follow BSU/Grenville spreadsheets (238/235 ≈ 0.40, 233/235 ≈ 1.005,
206/204 ≈ 1500, 202/205 ≈ 1.007); noise is seeded and a few outlier cycles are
planted (listed in the CTRL note). Nothing here is instrument data, and no
test that claims agreement with BSU numbers may rest on these files.

Reproducibility: the output is byte-identical on every run and platform. The
noise uses only ``random.Random(seed).random()`` (Mersenne Twister, stable for
an integer seed) and IEEE additions, multiplications and divisions (an
Irwin-Hall approximation to a normal deviate, no libm calls), and the writer
below stores no timestamps. ``tests/test_readers_synthetic.py`` regenerates the
files into a temporary folder and compares bytes.

The writer is a minimal BIFF8 (Excel 97-2003) workbook inside an OLE2 compound
file: text, number and boolean cells only, no styles. xlrd reads it; Excel may
complain about the missing formatting records. Standard library only.

    python scripts/make_synthetic_fixtures.py [--out tests/fixtures/synthetic]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import random
import struct

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "synthetic"
GENERATOR = "scripts/make_synthetic_fixtures.py"
R18 = 0.00206

Cell = str | float | int | bool
Sheet = dict[tuple[int, int], Cell]


# --------------------------------------------------------------------------- BIFF8 + OLE2 writer

def _record(rc: int, data: bytes = b"") -> bytes:
    return struct.pack("<HH", rc, len(data)) + data


def _bof(kind: int) -> bytes:
    return _record(0x0809, struct.pack("<HHHHII", 0x0600, kind, 0x0DBB, 0x07CC, 0, 0x06))


def _unicode(text: str, length_format: str) -> bytes:
    try:
        encoded, flag = text.encode("latin-1"), 0
    except UnicodeEncodeError:
        encoded, flag = text.encode("utf-16-le"), 1
    return struct.pack(length_format, len(text)) + bytes([flag]) + encoded


def _sheet_stream(cells: Sheet) -> bytes:
    rows = 1 + max(row for row, _ in cells)
    cols = 1 + max(col for _, col in cells)
    out = [_bof(0x0010), _record(0x0200, struct.pack("<IIHHH", 0, rows, 0, cols, 0))]
    for (row, col), value in sorted(cells.items()):
        if isinstance(value, bool):
            out.append(_record(0x0205, struct.pack("<HHHBB", row, col, 0, int(value), 0)))
        elif isinstance(value, (int, float)):
            out.append(_record(0x0203, struct.pack("<HHHd", row, col, 0, float(value))))
        else:
            if len(value) > 255:
                raise ValueError(f"label longer than 255 characters at {row},{col}")
            out.append(_record(0x0204, struct.pack("<HHH", row, col, 0) + _unicode(value, "<H")))
    out.append(_record(0x000A))
    return b"".join(out)


def _workbook_stream(sheets: list[tuple[str, Sheet]]) -> bytes:
    bodies = [_sheet_stream(cells) for _, cells in sheets]
    head = _bof(0x0005) + _record(0x0042, struct.pack("<H", 1200))
    bound_sizes = [4 + 6 + len(_unicode(name, "<B")) for name, _ in sheets]
    offset = len(head) + sum(bound_sizes) + 4
    bound = []
    for (name, _), body in zip(sheets, bodies):
        bound.append(_record(0x0085, struct.pack("<IBB", offset, 0, 0) + _unicode(name, "<B")))
        offset += len(body)
    return head + b"".join(bound) + _record(0x000A) + b"".join(bodies)


_FREE, _END, _FATSECT, _NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF


def _dir_entry(name: str = "", kind: int = 0, child: int = _NOSTREAM, start: int = 0, size: int = 0) -> bytes:
    encoded = (name + "\0").encode("utf-16-le") if name else b""
    return struct.pack(
        "<64sHBBIII16sIQQIII", encoded, len(encoded), kind, 1 if kind else 0, _NOSTREAM, _NOSTREAM, child, b"\0" * 16, 0, 0, 0, start, size, 0
    )


def compound_file(stream: bytes) -> bytes:
    """An OLE2 compound file (version 3, 512-byte sectors) holding one ``Workbook`` stream."""
    stream = stream + b"\0" * max(0, 4096 - len(stream))  # stay above the mini-stream cutoff
    stream_sectors = -(-len(stream) // 512)
    fat_sectors = 1
    while fat_sectors * 128 < fat_sectors + stream_sectors + 1:
        fat_sectors += 1
    if fat_sectors > 109:
        raise ValueError("workbook too large for a header-only DIFAT")
    first_stream = fat_sectors
    directory = fat_sectors + stream_sectors
    fat = [_FATSECT] * fat_sectors
    fat += [first_stream + i + 1 for i in range(stream_sectors - 1)] + [_END]
    fat += [_END]  # directory, one sector
    fat += [_FREE] * (fat_sectors * 128 - len(fat))
    header = struct.pack(
        "<8s16sHHHHH6sIIIIIIIII",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"\0" * 16, 0x003E, 0x0003, 0xFFFE, 9, 6, b"\0" * 6,
        0, fat_sectors, directory, 0, 4096, _END, 0, _END, 0,
    )
    header += struct.pack("<109I", *(list(range(fat_sectors)) + [_FREE] * (109 - fat_sectors)))
    entries = _dir_entry("Root Entry", 5, child=1, start=_END) + _dir_entry("Workbook", 2, start=first_stream, size=len(stream))
    entries += _dir_entry() * 2
    body = struct.pack(f"<{len(fat)}I", *fat) + stream + b"\0" * (stream_sectors * 512 - len(stream)) + entries
    return header + body


def write_xls(path: Path, sheets: list[tuple[str, Sheet]]) -> None:
    path.write_bytes(compound_file(_workbook_stream(sheets)))


# --------------------------------------------------------------------------- deterministic noise

class Noise:
    """Seeded noise from ``random.random()`` and IEEE arithmetic only (no libm)."""

    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def normal(self) -> float:
        total = 0.0
        for _ in range(12):
            total += self._random.random()
        return total - 6.0

    def rel(self, sigma: float) -> float:
        return 1.0 + sigma * self.normal()


# --------------------------------------------------------------------------- IonVantage-like layout

STAT_LABELS = ("Mean (After)", "Std Dev% (After)", "Std Err% (After)", "Included", "Total", "Mean", "Std Dev", "Std.Dev%", "Std Err%")


def cycle_sheet(names: list[str], rows: list[list[float]], times: list[float], cycles_per_block: int, note: str) -> Sheet:
    cells: Sheet = {(0, 0): "CYCLE Data", (0, 2): note, (1, 1): "Function:", (2, 1): "Column Index"}
    n = len(rows)
    for j, name in enumerate(names):
        col = 2 + j
        cells[(1, col)] = name
        cells[(2, col)] = j
        total = 0.0
        for row in rows:
            total += row[j]
        cells[(7, col)] = n
        cells[(8, col)] = total / n
    for i, label in enumerate(STAT_LABELS):
        cells[(3 + i, 1)] = label
    for i, label in enumerate(("Create Cycle Chart:", "Create Block Chart:", "Summarize:")):
        cells[(12 + i, 1)] = label
        for j in range(len(names)):
            cells[(12 + i, 2 + j)] = False
    cells.update({(15, 0): "Cycle", (15, 1): "Time (s)", (15, 2): "Cycle No.:", (15, 3): n, (15, 4): "Block No.:", (15, 5): (n - 1) // cycles_per_block + 1})
    for i, (row, time) in enumerate(zip(rows, times)):
        cells[(16 + i, 0)] = i + 1
        cells[(16 + i, 1)] = time
        for j, value in enumerate(row):
            cells[(16 + i, 2 + j)] = value
    return cells


def ctrl_sheet(*, sample: str, serial: int, method: str, cycles_per_block: int, blocks: int, measured: int, start: str, units: str, bi: bool, note: str) -> Sheet:
    return {
        (0, 0): "Workbook Parameters",
        (6, 0): "Workbook Version:", (6, 1): 4,
        (7, 0): "Run Terminated:", (7, 1): False, (7, 2): "Sample Name (ID):", (7, 3): sample,
        (8, 2): "Serial Number:", (8, 3): serial,
        (11, 2): "Method Name:", (11, 3): method,
        (12, 2): "Cycles per Block:", (12, 3): cycles_per_block,
        (13, 2): "Number of Blocks:", (13, 3): blocks,
        (15, 2): "Total Ratios:", (15, 3): cycles_per_block * blocks,
        (16, 2): "Ratios so far:", (16, 3): measured,
        (20, 2): "IsoWorks Error Message:",
        (21, 2): "Analysis Start Time:", (21, 3): start,
        (29, 0): "Rejection %:", (29, 1): 5,
        (30, 0): "Sigma Level:", (30, 1): 2,
        (38, 0): "Apply Baselines:", (38, 1): True,
        (40, 0): "Units - Standard:", (40, 1): units,
        (45, 0): "Beam Interpolation (BI):", (45, 1): bi,
        (58, 0): "Synthetic Note:", (58, 1): note,
        (76, 0): "Job Code:", (76, 1): "SYNTH",
    }


def _times(n: int, rows_per_block: int, step: float, gap: float, start: float) -> list[float]:
    times, now = [], start
    for i in range(n):
        if i and i % rows_per_block == 0:
            now += gap
        times.append(now)
        now += step
    return times


# --------------------------------------------------------------------------- the two files

def u_oxide_workbook() -> list[tuple[str, Sheet]]:
    seed, cycles_per_block, blocks = 20261114, 10, 12
    noise = Noise(seed)
    n = cycles_per_block * blocks
    outliers = {17: ("270/267", 1.012), 58: ("265/267", 0.990), 101: ("265/267", 1.010)}
    names = ["265 F", "267 F", "270 F", "270/267", "265/267", "272/270",
             "238/235 oxide R18 0.00206", "233/235 oxide R18 0.00206", "238/233 oxide"]
    r265_true = 1.005 / (1.0 + 2.0 * R18 * 1.005)
    r270_true = 0.40 * (1.0 - 2.0 * R18 * r265_true)
    rows, beam = [], 1.6
    for cycle in range(1, n + 1):
        beam = beam * 0.9985
        r265 = r265_true * noise.rel(0.0004)
        r270 = r270_true * noise.rel(0.0006)
        r272 = 2.0 * R18 * noise.rel(0.02)
        if cycle in outliers:
            name, factor = outliers[cycle]
            if name == "270/267":
                r270 = r270 * factor
            else:
                r265 = r265 * factor
        i267 = beam * noise.rel(0.001)
        oc233 = r265 / (1.0 - 2.0 * R18 * r265)
        oc238 = r270 / (1.0 - 2.0 * R18 * r265)
        rows.append([r265 * i267, i267, r270 * i267, r270, r265, r272, oc238, oc233, oc238 / oc233])
    note = (f"SYNTHETIC test fixture from {GENERATOR} (seed {seed}); not instrument data. "
            f"Planted outliers: cycle 17 270/267 x1.012, cycle 58 265/267 x0.990, cycle 101 265/267 x1.010.")
    times = _times(n, cycles_per_block, 4.2, 95.0, 48.5)
    return [
        ("CYCLE", cycle_sheet(names, rows, times, cycles_per_block, "SYNTHETIC test data, not instrument output")),
        ("CTRL", ctrl_sheet(sample="SYNTHETIC BSU z1 U", serial=90001, method="SYNTHETIC U static oxide R18 0.00206",
                            cycles_per_block=cycles_per_block, blocks=blocks, measured=n,
                            start="Friday 14 November 2025 9:05:07", units="Volts", bi=False, note=note)),
    ]


def pb_202_workbook() -> list[tuple[str, Sheet]]:
    seed, cycles_per_block, blocks = 20261115, 15, 10
    rows_per_block = cycles_per_block + 1  # beam interpolation adds one row per block
    noise = Noise(seed)
    n = rows_per_block * blocks
    names = ["206/204 D", "206/207 D", "206/205 D", "207/205 D", "204/205 D", "208/205 D", "202/205 D",
             "202 D", "204 D", "205 D", "206 D", "207 D", "208 D", "Daly/Faraday Gain",
             "206/208 D", "207/204 D", "208/204 D", "Daly/Faraday Gain"]
    rows, beam = [], 6.0e4
    for cycle in range(1, n + 1):
        beam = beam * (1.012 if cycle <= 40 else 0.996)
        i205 = beam * noise.rel(0.002)
        i202 = 1.007 * i205 * noise.rel(0.0012)
        i206 = 0.62 * i205 * noise.rel(0.0012)
        i204 = i206 / 1500.0 * noise.rel(0.012)
        i207 = 0.0755 * i206 * noise.rel(0.0015)
        i208 = 0.118 * i206 * noise.rel(0.0015)
        if cycle == 23:
            i204 = i204 * 1.30
        elif cycle == 77:
            i202 = i202 * 1.010
        elif cycle == 140:
            i207 = i207 * 1.020
        gain = 0.9235 * noise.rel(0.001)
        rows.append([
            i206 / i204, i206 / i207, i206 / i205, i207 / i205, i204 / i205, i208 / i205, i202 / i205,
            i202, i204, i205, i206, i207, i208, gain,
            i206 / i208, i207 / i204, i208 / i204, gain * noise.rel(0.0005),
        ])
    note = (f"SYNTHETIC test fixture from {GENERATOR} (seed {seed}); not instrument data. "
            f"Planted outliers: cycle 23 204 x1.30, cycle 77 202 x1.010, cycle 140 207 x1.020.")
    times = _times(n, rows_per_block, 40.5, 300.0, 210.0)
    return [
        ("CYCLE", cycle_sheet(names, rows, times, rows_per_block, "SYNTHETIC test data, not instrument output")),
        ("CTRL", ctrl_sheet(sample="SYNTHETIC ET2535 z1 Pb", serial=90002, method="SYNTHETIC Pb 202-205 Daly 150 ratios",
                            cycles_per_block=cycles_per_block, blocks=blocks, measured=n,
                            start="Thursday 13 November 2025 7:46:32", units="CPS", bi=True, note=note)),
    ]


FILES = {
    "synthetic_BSU_U_oxide_R18.xls": u_oxide_workbook,
    "synthetic_ET2535_Pb_202.xls": pb_202_workbook,
}


def write_all(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, build in FILES.items():
        path = out / name
        write_xls(path, build())
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default: tests/fixtures/synthetic)")
    args = parser.parse_args(argv)
    for path in write_all(args.out):
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
