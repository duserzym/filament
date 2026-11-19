"""Invented acquisition and cached workbook for portable GUI/build checks.

Shared with the reprocessing tests. No instrument measurements are copied.
The workbook is intentionally a different magnitude than the raw acquisition;
use the workbook route for its dead-time demonstration, not raw parity.
"""
import importlib.util
import struct
from pathlib import Path

import numpy as np

from rawtims.model import RawFile, Run, RunMetadata
from rawtims.readers.common import invalid_mask
from rawtims.readers.functions import build_functions
from rawtims.readers.ionvantage_raw import PB_METHOD
from rawtims.reduction_params import BeamInterpolation, ReductionParameters
from rawtims.reprocess import PB_INTENSITIES


def synthetic_raw(tmp_path, element="Pb", cycles=3):
    """One block with constant signals plus noise on one Daly acquisition."""
    folder = tmp_path / "SYNTHETIC.raw"
    folder.mkdir()
    pb = element == "Pb"
    method = PB_METHOD if pb else "SYNTHETIC U static"
    masses = [203.5, 204.5, 204, 205, 206, 207] if pb else [269.5, 270.5, 270]
    text = "\n".join(f"SET_MAGNET,{m},1000\nINTEGRATE,10000,1000,TRUE,TRUE" for m in masses)
    (folder / (method + ".ief")).write_text(text)
    (folder / (method + ".exp")).write_text(f"Event File Name,{method}.ief\n")
    mapping = {"Low3": 1, "Low2": 2, "Axial": 3, "High1": 4, "High2": 5, "Multiplier": 10}
    (folder / "_AcqParams.000").write_text("[CollectorMapping]\n" + "\n".join(f"{c}={i}" for c, i in mapping.items()))
    peak = np.repeat([204, 205, 206, 207], [10, 5, 5, 5]) if pb else np.repeat(270, 10)
    mass = np.r_[np.repeat(masses[0], 30), np.repeat(masses[1], 30), np.tile(peak, cycles if pb else 2)]
    n = len(mass)
    a = np.zeros((n, 32, 2), dtype="<f4")
    a[:, :, 0] = 8388608
    a[:, :, 1] = np.arange(n)[:, None]
    for c, channel in mapping.items():
        if c != "Multiplier":
            a[60:, channel, 0] += channel * 100
    a[:, 10, 0] = 0
    if pb:
        a[60:, 10, 0] = np.tile(np.repeat([100, 1000, 2000, 300], [10, 5, 5, 5]), cycles)
    a.tofile(folder / "_FUNC001.DAT")
    idx = bytearray(n*22)
    for i in range(n):
        struct.pack_into("<II", idx, i*22, i*256, 0x18000020)
        struct.pack_into("<f", idx, i*22+12, i/60)
    (folder / "_FUNC001.IDX").write_bytes(idx)
    sts = bytearray(6080+n*618)
    struct.pack_into("<HHH", sts, 32, 77, 3, 38)
    sts[38:47] = b"Set Mass\0"
    for i, m in enumerate(mass):
        struct.pack_into("<f", sts, 6080+i*618+38, m)
        struct.pack_into("<HH", sts, 6080+i*618+58, 1, 0)
    (folder / "_FUNC001.STS").write_bytes(sts)
    params = ReductionParameters(daly_dead_time_ns=10, faraday_gains={c: 1 for c in mapping if c != "Multiplier"},
                                 faraday_resistors_ohm={c: 1e12 for c in mapping if c != "Multiplier"},
                                 beam_interpolation=BeamInterpolation(pb), oxide_r18=0.002, route="raw")
    return folder, params


def write_synthetic_workbook(folder, params):
    # Reuse the existing deterministic, stdlib-only BIFF writer.
    path = Path(__file__).resolve().parents[1] / "scripts" / "make_synthetic_fixtures.py"
    spec = importlib.util.spec_from_file_location("synthetic_writer", path)
    writer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(writer)
    names = list(PB_INTENSITIES) + ["Faraday-Daly Gain", "206/204 D", "206/207 D", "206/205 D", "207/205 D", "204/205 D", "208/205 D", "206/208 F H1", "206/208 F H2", "206/208 F average", "208 F (H1)"]
    # Three rows are intentionally invented; no instrument content is copied.
    columns = np.ones((3, len(names)))
    for j, name in enumerate(names):
        if name in PB_INTENSITIES:
            seq, collector = PB_INTENSITIES[name]
            columns[:, j] = (seq+1)*1000 + np.arange(3)*10 if collector == "Multiplier" else 5000 + np.arange(3)*20
    functions = build_functions(names)
    run = Run("synthetic", RawFile("", "", 0, "", "ionvantage_xls"), "Pb", RunMetadata(), functions,
              np.arange(1, 4), np.ones(3), np.arange(3), columns, invalid_mask(columns, functions))
    from rawtims.reprocess import _functions
    _functions(run, columns, params)
    cycle = {(0, 0): "CYCLE Data", (12, 1): "Function:", (15, 0): "Cycle", (15, 1): "Time (s)"}
    for j, name in enumerate(names, 2):
        cycle[12, j] = name
        for row in range(3):
            cycle[16+row, 0], cycle[16+row, 1], cycle[16+row, j] = row+1, float(row), float(columns[row, j-2])
    ctrl = {(0, 0): "Method Name:", (0, 1): PB_METHOD, (1, 0): "Cycles per Block:", (1, 1): 3,
            (2, 0): "Number of Blocks:", (2, 1): 1}
    tuning = {(3, 0): "Collector:"}
    for col, (collector, gain) in enumerate(params.faraday_gains.items(), 1):
        tuning[3, col], tuning[6, col], tuning[8, col] = collector, gain, 1e12
    col = len(params.faraday_gains)+1
    tuning[3, col], tuning[6, col], tuning[8, col], tuning[9, col] = "Multiplier", 1, 1e12, params.daly_dead_time_ns
    xls = folder / "SYNTHETIC-1.xls"
    writer.write_xls(xls, [("CYCLE", cycle), ("CTRL", ctrl), ("TUNING", tuning)])
    return xls

