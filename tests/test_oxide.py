"""UO2 oxide correction: formulas, input discovery, pass-through (SPEC F12, section 1.2)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from oracle_reports import read_cycle_report
from rawtims.analysis import Analysis
from rawtims.model import Run
from rawtims.oxide import correct, oxide_correction
from reader_fixtures import GHR1_PB_XLS, GHR1_U_XLS, ORACLE_CYCLES, SYNTHETIC_U, TIMSDP_FILES, read

U239 = TIMSDP_FILES["GHR1 230921F03 U-239"]


def test_ku_ghr1_u239_cycle_one_pins_both_forms():
    run = read(U239)
    r265, r270 = run.column("265/267")[0], run.column("270/267")[0]
    assert (r265, r270) == (0.9729083814, 2.42703538)  # the file's exact values
    _, tripoli, _ = correct(r265, r270, 0.00205, "tripoli_java_00dc941")
    r233, isobar_233_18O, r238_233 = correct(r265, r270, 0.00205)
    assert tripoli == pytest.approx(2.45143, abs=5e-6) and tripoli == pytest.approx(2.4514291718598384, rel=1e-15)
    # SPEC section 1.2 quotes 2.43675 (truncated); the value is 2.4367554.
    assert isobar_233_18O == pytest.approx(2.4367554130355327, rel=1e-15) and isobar_233_18O == pytest.approx(2.42703538 / (1 - 2 * 0.00205 * 0.9729083814), rel=1e-15)
    assert (tripoli - isobar_233_18O) / isobar_233_18O == pytest.approx(0.00602, abs=5e-5)
    assert r233 == pytest.approx(0.9768047817927107, rel=1e-15) and r238_233 == pytest.approx(isobar_233_18O / r233, rel=1e-15)


def test_tripoli_form_reproduces_every_oracle_cycle():
    report = read_cycle_report(ORACLE_CYCLES / "KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239-report.tsv")
    result = oxide_correction(read(U239), 0.00205, "tripoli_java_00dc941")
    for name in ("233/235oc", "238/235oc", "238/233oc"):
        expected = report.values[:, report.names.index(name)]
        np.testing.assert_allclose(result.values[name], expected, rtol=1e-14, atol=0)


def test_inputs_are_recorded_and_inverted_for_purdue():
    run = read(TIMSDP_FILES["WH205 z41 U-655"])
    result = oxide_correction(run)
    assert result.status == "computed" and result.formula == "isobar_233_18O" and result.r18 == 0.00205
    assert result.inputs == {"R265/267": "1 / 267/265", "R270/267": "270/267"}
    assert result.input_keys == ("267/265", "270/267")
    r265 = 1 / run.column("267/265")
    np.testing.assert_allclose(result.values["238/235oc"], run.column("270/267") / (1 - 2 * 0.00205 * r265), rtol=1e-15)
    assert result.provenance()["applied_by"] == "filament"


def _without(run: Run, key: str) -> Run:
    keep = [f for f in run.functions if f.key != key]
    functions = tuple(replace(f, index=i) for i, f in enumerate(keep))
    columns = [f.index for f in keep]
    return replace(run, functions=functions, values=run.values[:, columns], invalid=run.invalid[:, columns])


def test_270_over_265_path():
    run = read(TIMSDP_FILES["WH233B z1 U-671"])
    reduced = _without(run, "270/267")
    result = oxide_correction(reduced)
    assert result.inputs == {"R265/267": "1 / 267/265", "R270/267": "270/265 * R265/267"}
    direct = oxide_correction(run)
    # IsoLinx rounds each ratio to ~10 significant digits, so the two routes agree to that precision.
    np.testing.assert_allclose(result.values["238/235oc"], direct.values["238/235oc"], rtol=1e-8)


def test_ku_ionvantage_u_run_uses_direct_columns():
    result = oxide_correction(read(GHR1_U_XLS))
    assert result.inputs == {"R265/267": "265/267", "R270/267": "270/267"}


def test_pb_run_is_not_applicable():
    result = oxide_correction(read(GHR1_PB_XLS))
    assert result.status == "not_applicable" and result.values == {} and result.reason
    assert Analysis(read(GHR1_PB_XLS)).derived == ()


def test_behaviour_pass_through_on_synthetic_bsu_u_file():
    """Behaviour test on a SYNTHETIC file: no claim about BSU numbers."""
    run = read(SYNTHETIC_U)
    result = oxide_correction(run, r18=0.00205)
    assert result.status == "pass_through" and result.r18 == 0.00206 and result.values == {}
    assert result.pass_through_keys == ("238/235 oxide R18 0.00206", "233/235 oxide R18 0.00206", "238/233 oxide")
    assert result.provenance()["applied_by"] == "instrument file"
    analysis = Analysis(run)
    assert analysis.derived == () and analysis.keys == run.keys
    np.testing.assert_array_equal(analysis.column("238/235 oxide R18 0.00206"), run.column("238/235 oxide R18 0.00206"))


def test_bad_arguments():
    with pytest.raises(ValueError):
        correct(1.0, 2.0, formula="exponential")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        correct(1.0, 2.0, r18=0.5)
