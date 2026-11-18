"""Synthetic acquisition/parameter/history checks; no private data or derived fixtures."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from rawtims.analysis import Analysis, replay
from rawtims.contract import csv_text, parse_csv_text
from rawtims.fractions import Fraction, fraction_row
from rawtims.model import RawFile, Run, RunMetadata
from rawtims.readers import UnsupportedFile, open_run
from rawtims.readers.common import invalid_mask
from rawtims.readers.functions import build_functions
from rawtims.readers.ionvantage_raw import (
    PB_METHOD,
    dead_time,
    decode_raw,
    rejection_mean,
)
from rawtims.reduction_params import (
    Baseline,
    BeamInterpolation,
    IntegrationRejection,
    ReductionParameters,
    as_acquired,
)
from rawtims.reprocess import (
    PB_INTENSITIES,
    change_dead_time,
    reprocess,
    reprocess_with_fallback,
)
from rawtims.session import SessionState, load_session, save_session


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


def test_canonical_parameters_are_immutable_and_hash_stable():
    gains = {"High1": 1.2, "Axial": 1}
    a = ReductionParameters(faraday_gains=gains, daly_dead_time_ns=36.3)
    b = ReductionParameters(faraday_gains={"Axial": 1.0, "High1": 1.2}, daly_dead_time_ns=36.3)
    gains["High1"] = 999
    assert a == b and a.canonical_json() == b.canonical_json()
    assert a.sha256 == hashlib.sha256(a.canonical_json().encode()).hexdigest()
    assert ReductionParameters.from_dict(json.loads(a.canonical_json())) == a
    assert replace(a, route="raw").sha256 != a.sha256
    with pytest.raises(FrozenInstanceError):
        a.route = "raw"
    with pytest.raises(TypeError):
        a.faraday_gains["Axial"] = 2


@pytest.mark.parametrize("kwargs", [{"daly_dead_time_ns": -1}, {"oxide_r18": 0.1}, {"faraday_gains": {"Axial": 0}},
                                    {"faraday_gains": {"unknown": 1}}, {"oxide_r18": float("nan")},
                                    {"route": "other"}, {"version": 2}, {"baseline": {"mode": "bogus"}},
                                    {"beam_interpolation": {"enabled": True, "history_cycles": 4}},
                                    {"integration_rejection": {"max_percent": 100}}, {"daly_dead_time_ns": True}])
def test_parameters_validate(kwargs):
    with pytest.raises((TypeError, ValueError)):
        ReductionParameters(**kwargs)


def test_deadtime_algebra_round_trip_and_saturation():
    n = np.array([1, 100, 1e5, 2e6])
    old = dead_time(n, 36.3)
    new = change_dead_time(old, 40-36.3)
    np.testing.assert_allclose(new, dead_time(n, 40), rtol=3e-16)
    np.testing.assert_allclose(change_dead_time(new, 36.3-40), old, rtol=3e-16)
    with pytest.raises(ValueError, match="saturat"):
        dead_time([1e9], 40)


@pytest.mark.parametrize("element", ["Pb", "U"])
def test_synthetic_decoder_units_baselines_and_rows(tmp_path, element):
    folder, params = synthetic_raw(tmp_path, element)
    out = decode_raw(folder, params)
    assert out.intensities.shape == ((1, 4, 6) if element == "Pb" else (2, 1, 5))
    if element == "Pb":
        np.testing.assert_allclose(out.intensities[0, :, out.collectors.index("Multiplier")], dead_time([100, 1000, 2000, 300], 10), rtol=1e-15)
    else:
        np.testing.assert_allclose(out.intensities[:, 0, out.collectors.index("Low3")], 100 * params.adc_volts_per_code, rtol=1e-15)
    offset = replace(params, baseline=Baseline("offset", {"Low3": 0.001}))
    delta = out.intensities - decode_raw(folder, offset).intensities
    np.testing.assert_allclose(delta[:, :, out.collectors.index("Low3")], 0.001, atol=1e-13)
    assert len(out.hashes) == 6


def test_unknown_method_and_corrupt_scan_rejected(tmp_path):
    folder, params = synthetic_raw(tmp_path)
    ief = next(folder.glob("*.ief"))
    ief.rename(folder / "Unknown two-sequence.ief")
    with pytest.raises(UnsupportedFile, match="Unknown two-sequence"):
        decode_raw(folder, params)
    (folder / "Unknown two-sequence.ief").rename(ief)
    (folder / "_FUNC001.DAT").write_bytes(b"broken")
    with pytest.raises(UnsupportedFile, match="scan sizes"):
        decode_raw(folder, params)


def test_rejection_pass_can_exceed_percent_threshold():
    # Three outliers out of 30 are rejected together, exceeding 5% in one pass.
    assert rejection_mean(np.r_[np.ones(27), np.full(3, 100)]) == 1
    assert rejection_mean(np.r_[np.ones(27), np.full(3, 100)], max_percent=0) == 10.9
    with pytest.raises(ValueError, match="every acquisition"):
        rejection_mean([1, 2, 3, 4], sigma=0.01)


def test_workbook_identity_change_history_and_v1_session(tmp_path):
    folder, params = synthetic_raw(tmp_path, cycles=5)
    xls = write_synthetic_workbook(folder, params)
    run = open_run(xls)
    acquired = as_acquired(run)
    original = reprocess(run, acquired)
    assert original.values.tobytes() == run.values.tobytes()
    assert original.keys == run.keys
    changed = replace(acquired, daly_dead_time_ns=40)
    analysis = Analysis(original)
    analysis.toggle_cycles([0], ["206/205 D"], False)
    mask = analysis.included.copy()
    analysis.set_reduction_parameters(changed)
    values = analysis.values.copy()
    assert not np.array_equal(values, original.values)
    assert analysis.run.provenance["approximation"]
    np.testing.assert_array_equal(analysis.included, mask)
    analysis.undo()
    assert analysis.values.tobytes() == original.values.tobytes()
    analysis.redo()
    assert analysis.values.tobytes() == values.tobytes()
    back = replay(run, analysis.history)
    assert back.values.tobytes() == values.tobytes()
    state = SessionState(fractions=[Fraction("synthetic", pb=analysis)])
    path = save_session(state, tmp_path / "test.rawtims")
    loaded, problems = load_session(path)
    assert not problems
    assert loaded.fractions[0].pb.values.tobytes() == values.tobytes()
    # Existing version-1 records with no parameter extension keep cached values.
    analysis.undo()
    path = save_session(SessionState(fractions=[Fraction("synthetic", pb=Analysis(run))]), tmp_path / "old.rawtims")
    document = json.loads(path.read_text())
    for key in ("initial_reduction_parameters", "reduction_parameters", "reduction_provenance"):
        del document["runs"][0][key]
    path.write_text(json.dumps(document))
    loaded, problems = load_session(path)
    assert not problems and loaded.fractions[0].pb.values.tobytes() == run.values.tobytes()


def test_workbook_raw_only_controls_and_fallback(tmp_path):
    folder, params = synthetic_raw(tmp_path, cycles=5)
    xls = write_synthetic_workbook(folder, params)
    acquired = as_acquired(xls)
    with pytest.raises(ValueError, match="requires route raw"):
        reprocess(xls, replace(acquired, integration_rejection=IntegrationRejection(3, 10)))
    ief = next(folder.glob("*.ief"))
    ief.rename(folder / "Unknown.ief")
    out = reprocess_with_fallback(xls, replace(acquired, route="raw"))
    assert out.reduction_parameters.route == "workbook"
    assert any("Unknown" in w and "used workbook route" in w for w in out.warnings)
    changed = reprocess_with_fallback(xls, replace(acquired, route="raw", daly_dead_time_ns=40))
    assert changed.reduction_parameters.route == "workbook"
    assert any("zero baseline" in w for w in changed.warnings)


def test_contract_parameter_columns_and_explicit_legacy_export(tmp_path):
    folder, params = synthetic_raw(tmp_path, cycles=5)
    run = open_run(write_synthetic_workbook(folder, params))
    analysis = replay(run, [{"op": "toggle_cycles", "cycles": [0], "keys": ["206/205 D"], "include": False, "changed": [[0, "206/205 D"]]}])
    fraction = Fraction("synthetic", pb=analysis)
    with pytest.raises(ValueError, match="per-ratio"):
        fraction_row(fraction, datetime.now(UTC))
    row = fraction_row(fraction, datetime.now(UTC), allow_legacy_per_ratio=True)
    assert row.get("Pb Cycle Selection") == "per_ratio"
    params = as_acquired(run)
    assert row.get("Pb Reduction Parameters") == params.canonical_json()
    assert row.get("Pb Reduction Parameters SHA256") == params.sha256
    assert parse_csv_text(csv_text([row]))[0].get("Pb Reduction Parameters") == params.canonical_json()


def test_changed_acquisition_refuses_session_replay(tmp_path):
    folder, params = synthetic_raw(tmp_path, cycles=5)
    xls = write_synthetic_workbook(folder, params)
    analysis = Analysis(open_run(xls))
    analysis.set_reduction_parameters(replace(as_acquired(analysis.run), route="raw"))
    analysis.undo()
    state = SessionState(fractions=[Fraction("synthetic", pb=analysis)])
    path = save_session(state, tmp_path / "source-check.rawtims")
    loaded, problems = load_session(path)
    assert not problems
    loaded.fractions[0].pb.redo()
    assert loaded.fractions[0].pb.run.reduction_parameters.route == "raw"
    dat = folder / "_FUNC001.DAT"
    content = bytearray(dat.read_bytes())
    content[-1] ^= 1
    dat.write_bytes(content)
    assert analysis.can_redo
    with pytest.raises(ValueError, match="SHA-256"):
        analysis.redo()
    assert analysis.can_redo  # a failed redo must not advance history
    loaded, problems = load_session(path)
    assert loaded.fractions[0].pb is None
    assert len(problems) == 1 and "SHA-256" in problems[0].message


def test_changed_oxide_r18_uses_intensities_and_updates_mapping(monkeypatch):
    names = ["265", "267", "270", "265/267", "270/265", "270/267",
             "238/235 oxide R18 0.00206", "233/235 oxide R18 0.00206", "238/233 oxide"]
    funcs = build_functions(names)
    x, y, z = np.array([1., 2., 3.]), np.array([10., 20., 30.]), np.array([5., 6., 7.])
    denom = y - 2*0.00206*x
    values = np.column_stack([x, y, z, x/y, z/x, z, z/denom, x/denom, z/x])
    params = ReductionParameters(oxide_r18=0.00206)
    run = Run("synthetic", RawFile("/tmp/synthetic-u.xls", "synthetic-u.xls", 0, "ab"*32, "ionvantage_xls"), "U",
              RunMetadata(extra={"270/267_intensity_alias": True, "acquired_reduction_parameters": params.to_dict()}),
              funcs, np.arange(1, 4), np.ones(3, dtype=int), np.arange(3), values, invalid_mask(values, funcs), params)
    monkeypatch.setattr("rawtims.readers.open_run", lambda _: run)
    changed = reprocess(run, replace(params, oxide_r18=0.003))
    np.testing.assert_allclose(changed.column(names[6]), z/(y-2*0.003*x), rtol=1e-15)
    assert changed.keys == run.keys
    assert changed.function(names[6]).metadata["oxide_r18"] == 0.003
    analysis = Analysis(run)
    analysis.set_reduction_parameters(replace(params, oxide_r18=0.003))
    assert analysis.mapping.ratios["238U/235U"].oxide_r18 == 0.003
    from rawtims.branding import APP_NAME
    assert analysis.oxide.provenance()["applied_by"] == APP_NAME
    analysis.undo()
    assert analysis.values.tobytes() == values.tobytes()


def test_partial_terminal_static_u_retains_distinct_cycle(tmp_path):
    folder, params = synthetic_raw(tmp_path, "U")
    for suffix, header, record in (("DAT", 0, 256), ("IDX", 0, 22), ("STS", 6080, 618)):
        path = folder / f"_FUNC001.{suffix}"
        content = path.read_bytes()
        path.write_bytes(content[:len(content)-7*record])
    out = decode_raw(folder, params)
    assert len(out.time) == 2
    assert any("3/10" in w for w in out.warnings)
    np.testing.assert_allclose(out.intensities[0], out.intensities[1], rtol=1e-15)
