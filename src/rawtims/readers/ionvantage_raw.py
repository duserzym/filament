"""Method-specific IonVantage acquisition decoder. Files are always read-only.

This is a verified subset of the vendor format, not a generic MassLynx reader.
All allocations are linear in scan count; memmaps bound acquisition IO, and
aggregation works a sequence at a time. Unknown structures fail explicitly.
"""
from __future__ import annotations

import configparser
import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rawtims.reduction_params import ReductionParameters

PB_METHOD = "Pb 205 Daly 150 ratios wo 208"
# Empirical bounds from KD33 z1/z2; Pb common-time rounding remains <1 ms.
# U excludes the workbook's duplicated terminal row; raw uses the actual scan.
PB_WORKBOOK_RTOL = 3e-6
U_WORKBOOK_RTOL = 1e-10
ADC_SCAN_BYTES = 256
MAX_SCANS = 10_000_000


def _unsupported(method, reason):
    from rawtims.readers import UnsupportedFile
    return UnsupportedFile(f"IonVantage method {method!r}: {reason}")


def raw_folder(path: Path) -> Path | None:
    if path.is_dir():
        return path
    base = re.sub(r"-\d+$", "", path.stem)
    candidate = path.with_name(base + ".raw")
    if candidate.is_dir():
        return candidate
    if path.parent.suffix.lower() == ".raw":
        return path.parent
    return None


def workbook_path(folder: Path) -> Path:
    paths = sorted(folder.glob("*.xls"))
    if len(paths) != 1:
        raise _unsupported(folder.name, "expected one accompanying .xls workbook for stable cycle keys")
    return paths[0]


def _ini(path):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    config.read_string("\n".join(line for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if not line.lstrip().startswith("=")))
    return {s: dict(config[s]) for s in config.sections()}


def acquisition_config(folder):
    if folder is None:
        return {}, {}
    params = folder / "_AcqParams.000"
    ipfs = sorted(folder.glob("*.ipf"))
    return (_ini(params) if params.is_file() else {}, _ini(ipfs[0]) if len(ipfs) == 1 else {})


def input_hashes(folder):
    """Hashes of numerical source files, relative to the acquisition folder."""
    result = {}
    for p in sorted(folder.iterdir()):
        if p.name in ("_FUNC001.DAT", "_FUNC001.IDX", "_FUNC001.STS", "_AcqParams.000") or p.suffix.lower() in (".exp", ".ief", ".ipf"):
            digest = hashlib.sha256()
            with p.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[p.name] = digest.hexdigest()
    return result


def rejection_mean(values, sigma=2.0, max_percent=5.0):
    """Reject all >sigma sample-SD outliers per pass, while prior loss <max%."""
    a = np.asarray(values, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    keep = np.ones(a.shape, dtype=bool)
    active = np.full(a.shape[1], max_percent > 0, dtype=bool)
    while active.any():
        count = keep.sum(axis=0)
        mean = np.sum(a, axis=0, where=keep) / count
        delta = a - mean
        sd = np.sqrt(np.sum(delta * delta, axis=0, where=keep) / np.maximum(count - 1, 1))
        candidate = keep & (np.abs(delta) <= sigma * sd)
        changed = np.any(candidate != keep, axis=0) & active
        if np.any(active & ~candidate.any(axis=0)):
            raise ValueError("integration rejection would reject every acquisition in a collector")
        keep[:, changed] = candidate[:, changed]
        active = changed & ((len(a) - keep.sum(axis=0)) / len(a) < max_percent / 100)
    return np.sum(a, axis=0, where=keep) / keep.sum(axis=0)


def dead_time(values, tau_ns):
    a = np.asarray(values, dtype=np.float64)
    factor = 1 - a * tau_ns * 1e-9
    if np.any(factor <= 0):
        raise ValueError("Daly dead time saturates an acquisition (1 - cps*tau <= 0)")
    return a / factor


@dataclass
class DecodedAcquisition:
    method: str
    element: str
    # n_rows × n_sequences × n_collectors, baseline-subtracted output units.
    intensities: np.ndarray
    baselines: np.ndarray
    collectors: tuple[str, ...]
    time: np.ndarray
    block: np.ndarray
    hashes: dict[str, str]
    warnings: tuple[str, ...] = ()


def decode_raw(folder, params: ReductionParameters) -> DecodedAcquisition:
    folder = Path(folder)
    iefs = sorted(folder.glob("*.ief"))
    method = iefs[0].stem if len(iefs) == 1 else folder.name
    if len(iefs) != 1:
        raise _unsupported(method, "missing or ambiguous .ief")
    text = iefs[0].read_text(errors="replace")
    masses = [float(v) for v in re.findall(r"^SET_MAGNET,([\d.]+)", text, re.MULTILINE)]
    if method == PB_METHOD and masses[:6] == [203.5, 204.5, 204, 205, 206, 207]:
        element, baseline_masses, sequences, counts = "Pb", (203.5, 204.5), (204, 205, 206, 207), (10, 5, 5, 5)
    elif masses[:3] == [269.5, 270.5, 270] and set(masses) == {269.5, 270.5, 270}:
        element, baseline_masses, sequences, counts = "U", (269.5, 270.5), (270,), (10,)
    else:
        raise _unsupported(method, "only four-sequence Pb Daly and static U Faraday are decoded")
    # The validated acquisition duration is 1 second. Refuse an unverified normalization.
    durations = re.findall(r"^INTEGRATE,\d+,([\d.]+)", text, re.MULTILINE)
    if not durations or any(float(v) != 1000 for v in durations):
        raise _unsupported(method, "only 1000 ms acquisitions are validated")
    dat, idx, sts = (folder / f"_FUNC001.{ext}" for ext in ("DAT", "IDX", "STS"))
    size = dat.stat().st_size
    n = size // ADC_SCAN_BYTES
    if size % ADC_SCAN_BYTES or not 0 < n <= MAX_SCANS or idx.stat().st_size != n * 22:
        raise _unsupported(method, "invalid DAT/IDX scan sizes")
    a = np.memmap(dat, mode="r", dtype="<f4", shape=(n, 32, 2))
    index = np.memmap(idx, mode="r", dtype=np.dtype({"names": ["offset", "flags"], "formats": ["<u4", "<u4"], "offsets": [0, 4], "itemsize": 22}), shape=(n,))
    if np.any(index["offset"] != np.arange(n, dtype=np.uint64) * ADC_SCAN_BYTES) or np.any((index["flags"] & 0xffff) != 32):
        raise _unsupported(method, "unsupported indexed scan layout")
    # STS header: 32-byte prefix + 48-byte field descriptors. Read descriptors
    # rather than assuming Set Mass remains at record offset 38.
    with sts.open("rb") as stream:
        prefix = stream.read(32)
        if len(prefix) != 32:
            raise _unsupported(method, "truncated STS header")
        # Verified descriptor count is contained in the verified 32-byte prefix.
        # Find header/record sizes via the descriptor table and file length.
        header = stream.read(126 * 48)
    if len(header) != 126 * 48 or sts.stat().st_size != 6080 + n * 618:
        raise _unsupported(method, "unsupported STS record layout")
    # The format subset pins descriptor positions/types as well as sizes.
    # Descriptor offset is a uint16 at byte 4; see docs/raw-reduction.md.
    descriptors = [header[i:i+48] for i in range(0, len(header), 48)]
    mass_descriptor = next((d for d in descriptors if b"Set Mass\x00" in d), None)
    if mass_descriptor is None:
        raise _unsupported(method, "STS has no Set Mass descriptor")
    mass_offset = struct.unpack_from("<H", mass_descriptor, 4)[0]
    if mass_offset != 38:
        raise _unsupported(method, f"unsupported Set Mass offset {mass_offset}")
    status = np.memmap(sts, mode="r", offset=6080, dtype=np.dtype({"names": ["mass", "event", "acq"], "formats": ["<f4", "<u2", "<u2"], "offsets": [38, 58, 60], "itemsize": 618}), shape=(n,))
    if np.any(status["event"] != 1) or np.any(status["acq"] != 0):
        raise _unsupported(method, "unvalidated event/acquisition types")
    config, _ipf = acquisition_config(folder)
    mapping = config.get("CollectorMapping", {})
    collectors = tuple(c for c in params.faraday_gains if int(mapping.get(c, -1)) > 0)
    if element == "Pb":
        collectors += ("Multiplier",)
    required = ("High1", "High2", "Axial", "Multiplier") if element == "Pb" else ("Low3", "Low2", "Axial")
    if not set(required) <= set(collectors):
        raise _unsupported(method, "missing collector mapping/gains")
    channels = [int(mapping[c]) for c in collectors]
    if any(c < 0 or c >= 18 for c in channels) or len(set(channels)) != len(channels):
        raise _unsupported(method, "invalid acquisition collector channels")
    values = a[:, channels, 0].astype(np.float64)
    if not np.isfinite(values).all():
        raise _unsupported(method, "nonfinite acquisition intensity")
    for j, c in enumerate(collectors):
        if c == "Multiplier":
            if params.daly_dead_time_ns is None:
                raise ValueError("raw Pb requires daly_dead_time_ns")
            values[:, j] = (dead_time(values[:, j], params.daly_dead_time_ns) if params.correct_dead_time else values[:, j]) * params.multiplier_gain
        else:
            gain = params.faraday_gains[c] if params.apply_faraday_gains else 1.0
            values[:, j] = (values[:, j] - params.adc_zero) * params.adc_volts_per_code * gain
            if element == "Pb":
                if c not in params.faraday_resistors_ohm:
                    raise ValueError(f"raw Pb requires faraday_resistors_ohm.{c}")
                values[:, j] /= params.faraday_resistors_ohm[c] * params.electron_charge_c
    mass = status["mass"].astype(float)
    # Tuning adds a small mass offset, up to 0.034 in the validated runs.
    b1 = np.abs(mass - baseline_masses[0]) < 0.2
    starts = np.flatnonzero(b1 & ~np.r_[False, b1[:-1]])
    if not len(starts) or starts[0] != 0:
        raise _unsupported(method, "missing leading block baselines")
    stops = np.r_[starts[1:], n]
    output, baselines, times, blocks = [], [], [], []
    warnings = []
    rejection = params.integration_rejection
    def avg(x):
        return rejection_mean(x, rejection.sigma, rejection.max_percent)
    for block_no, (start, stop) in enumerate(zip(starts, stops), 1):
        pos = int(start)
        mass_offset = mass[pos] - baseline_masses[0]
        if stop == n and stop-start <= 60 and np.all(np.minimum(np.abs(mass[start:stop] - baseline_masses[0] - mass_offset),
                                                                              np.abs(mass[start:stop] - baseline_masses[1] - mass_offset)) < 0.05):
            warnings.append("incomplete terminal baseline-only block ignored; it has no exported cycle rows")
            break
        baseline_values = []
        for expected in baseline_masses:
            end = pos
            while end < stop and abs(mass[end] - expected - mass_offset) < 0.05:
                end += 1
            if end - pos != 30:
                raise _unsupported(method, "expected two 30-scan baselines per block")
            baseline_values.append(avg(values[pos:end]))
            pos = end
        baseline = np.mean(baseline_values, axis=0) if params.apply_baselines else np.zeros(len(collectors))
        yy, tt = [], []
        while pos + sum(counts) <= stop:
            cy, ct = [], []
            for expected, count in zip(sequences, counts):
                if not np.all(np.abs(mass[pos:pos+count] - expected - mass_offset) < 0.05):
                    raise _unsupported(method, "unexpected peak-hop sequence")
                cy.append(avg(values[pos:pos+count]))
                ct.append(a[pos:pos+count, 0, 1].astype(float).mean())
                pos += count
            yy.append(cy)
            tt.append(ct)
        if element == "U" and stop == n and pos < stop and np.all(np.abs(mass[pos:stop] - sequences[0] - mass_offset) < 0.05):
            warnings.append(f"partial terminal U integration: {stop-pos}/10 acquisitions; reduced the acquired scans")
            yy.append([avg(values[pos:stop])])
            tt.append([a[pos:stop, 0, 1].astype(float).mean()])
            pos = stop
        if pos != stop:
            raise _unsupported(method, "incomplete terminal integration; row correspondence unverified")
        yy, tt = np.asarray(yy), np.asarray(tt)
        # Pb always drops the first two precycles to preserve saved row keys,
        # including when BI is disabled or its history is shortened.
        for k in range(2 if element == "Pb" else 0, len(yy)):
            t0 = (tt[k-2, 0] + tt[k, -1]) / 2 if element == "Pb" else tt[k, 0]
            y = yy[k]
            if params.beam_interpolation.enabled:
                h = params.beam_interpolation.history_cycles
                if element != "Pb":
                    raise _unsupported(method, "BI is not supported for static U")
                t, v = tt[k-h+1:k+1], yy[k-h+1:k+1]
                tm, vm = t.mean(axis=0), v.mean(axis=0)
                slope = ((t-tm)[:, :, None] * (v-vm)).sum(axis=0) / (((t-tm)**2).sum(axis=0)[:, None])
                y = vm + slope * (t0-tm)[:, None]
            y = y - baseline
            if params.baseline.mode == "offset":
                y -= np.array([params.baseline.offsets.get(c, 0) for c in collectors])
            output.append(y)
            baselines.append(baseline)
            times.append(t0)
            blocks.append(block_no)
    return DecodedAcquisition(method, element, np.asarray(output), np.asarray(baselines), collectors,
                              np.asarray(times), np.asarray(blocks), input_hashes(folder), tuple(warnings))
