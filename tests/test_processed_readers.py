"""P5 processed oracles: complete arrays/masks first, then full aggregate reports.

Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/
massSpectrometerModels/dataSourceProcessors/{triton/TritonMassSpec.java:120-170,
nu/NuMassSpec.java:47-161,neptune/NeptuneMassSpec.java:124-168};
methods/AnalysisMethod.java:94-140; expressions/userFunctions/UserFunction.java:123-145.
All 34 shipped pairs are unmodified Apache-2.0 snapshots, pinned in MANIFEST.toml.
"""

from pathlib import Path

import numpy as np
import pytest
from oracle_reports import read_cycle_report, read_full_report

from rawtims.analysis import Analysis, AnalysisSettings
from rawtims.readers import open_run, sniff
from rawtims.readers.idtims_template import SIGNATURE, read_template
from rawtims.readers.processed import tripoli_comparison_arrays
from rawtims.stats import describe

BASE = Path(__file__).parent / "fixtures/tripoli/processed"
FILES = sorted(p for p in (BASE / "data").rglob("*") if p.is_file())
JAVA = AnalysisSettings(
    stat_mode="geometric", oxide_formula="tripoli_java_00dc941", r18=0.00205
)


def oracle_path(path, folder, suffix):
    return (
        BASE
        / folder
        / path.relative_to(BASE / "data").parent
        / ("Oracle-" + path.stem + suffix)
    )


def check_cycles(path):
    run = open_run(path)
    values, included, times = tripoli_comparison_arrays(run)
    report = read_cycle_report(oracle_path(path, "cycleReports", "-report.tsv"))
    analysis = Analysis(run, JAVA)
    assert report.names[: run.n_functions] == [
        f.metadata["tripoli_name"] for f in run.functions
    ]
    np.testing.assert_array_equal(run.cycle, report.cycle)
    np.testing.assert_array_equal(times, report.time)
    # Compare every column, including all derived oxide columns from Nu U.
    complete = values
    masks = included
    if analysis.derived:
        complete = np.column_stack(
            [values, *[analysis.column(f.key) for f in analysis.derived]]
        )
        masks = np.column_stack(
            [included, *[~analysis.invalid[:, f.index] for f in analysis.derived]]
        )
    assert complete.shape == report.values.shape
    assert len(report.names) == len(analysis.functions)
    np.testing.assert_allclose(
        complete, report.values, rtol=1e-12, atol=0, equal_nan=True
    )
    np.testing.assert_array_equal(masks, ~report.discarded)
    # Native validity distinguishes vendor missing flags from X rejections.
    missing = np.asarray(run.metadata.extra["vendor_missing"])
    expected_invalid = ~np.isfinite(run.values) | missing
    ratio = np.array([f.is_ratio for f in run.functions])
    expected_invalid[:, ratio] |= run.values[:, ratio] <= 0
    np.testing.assert_array_equal(run.invalid, expected_invalid)
    np.testing.assert_allclose(
        run.values[np.isfinite(run.values)],
        values[np.isfinite(run.values)],
        rtol=0,
        atol=0,
    )
    assert Analysis(run).included.all()  # no implicit rejection
    return run, analysis, values, included


def test_every_public_pair_is_present():
    assert len(FILES) == 34
    for folder, suffix in [
        ("cycleReports", "-report.tsv"),
        ("fullReports", "-report.csv"),
    ]:
        assert set((BASE / folder).rglob("*" + suffix)) == {
            oracle_path(p, folder, suffix) for p in FILES
        }


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_complete_cycles_and_masks_before_full_report(path):
    """Citations above; singleton SD follows Tripoli BlockStatsRecord.java:72-76 (Apache DescriptiveStatistics)."""
    run, analysis, values, included = check_cycles(path)
    identity, columns = read_full_report(
        oracle_path(path, "fullReports", "-report.csv")
    )
    assert identity["Data File Name"] == path.name
    assert identity["Method Name"] == run.metadata.method
    functions = {f.metadata["tripoli_name"]: f for f in run.functions}
    assert {c.name for c in columns} == set(functions) | {
        f.name for f in analysis.derived
    }
    for column in columns:
        if column.name in functions:
            f = functions[column.name]
            v, mask = values[:, f.index], included[:, f.index]
            mode = (
                "geometric"
                if f.metadata["tripoli_ratio"] and np.all(v[mask] > 0)
                else "arithmetic"
            )
        else:
            f = analysis.function(column.name)
            v, mask, mode = (
                analysis.column(f.key),
                ~analysis.invalid[:, f.index],
                "geometric",
            )
        stats = describe(v, mask, mode=mode)
        assert stats.mean == pytest.approx(column.mean, rel=1e-9, abs=1e-18)
        if stats.n_used == 1:
            # Java supplies zero dispersion for one observation. Native Stats
            # deliberately retains NaN; no old output is changed to emulate it.
            assert np.isnan(stats.sd) and column.se == column.sd == 0
            continue
        if column.se_header == "%StdErr":
            assert stats.mode == "geometric"
            actual = [stats.se_pct_upper, stats.sd_pct_upper]
        else:
            actual = [stats.se, stats.sd]
        np.testing.assert_allclose(
            actual, [column.se, column.sd], rtol=1e-9, atol=1e-18
        )


def thermo(kind="Triton", rows=None, names="206/205\t204 D", time="15:23:28"):
    return (
        f"{kind} Analysis Data Report\nRun-Number-View\nSample ID: SYNTHETIC\n"
        f"Analysis date: 15/07/2022\nAnalysis time: {time}\nMethod Name: C:\\synthetic.met\n"
        + ("Cycle" if kind == "Triton" else "Block")
        + "\tTime\t"
        + names
        + "\n"
        + (rows or "1\t04:35:49:904\tX2\tD9\n2\t04:35:58:296\t4\t-1\n")
        + "***\tMean\n"
    )


@pytest.mark.parametrize("kind", ["Triton", "Neptune"])
def test_synthetic_flags_missing_negatives_times_and_source_retention(tmp_path, kind):
    """OGTripoli/source/vendors_data/ThermoFinniganTriton.cs:373-387: X outlier versus D missing."""
    p = tmp_path / "synthetic.unknown"
    source = thermo(kind)
    if kind == "Neptune":
        source = source.replace("04:35:49:904", "16549.904").replace(
            "04:35:58:296", "16558.296"
        )
    p.write_text(source)
    run = open_run(p)
    assert run.raw.format == kind.lower() + "_exp"
    assert run.names == ["206/205", "204 D"] and run.functions[1].collector == "D"
    assert run.metadata.analysis_start.isoformat() == "2022-07-15T15:23:28"
    np.testing.assert_allclose(run.time, [16549.904, 16558.296])
    np.testing.assert_array_equal(run.values, [[2, 9], [4, -1]])
    np.testing.assert_array_equal(run.invalid, [[False, True], [False, False]])
    np.testing.assert_array_equal(
        run.metadata.extra["vendor_rejected"], [[True, False], [False, False]]
    )
    assert run.metadata.extra["source_cells"][0] == ["X2", "D9"]
    assert run.metadata.extra["footer"] == ["***\tMean"]
    before = run.values.copy()
    comparison, included, times = tripoli_comparison_arrays(run)
    np.testing.assert_array_equal(comparison, run.values)
    assert included.all()
    np.testing.assert_array_equal(
        times, [43549904, 43558296] if kind == "Triton" else [16549.904, 16558.296]
    )
    np.testing.assert_array_equal(run.values, before)


def test_synthetic_neptune_blank_and_negative_decimal_tail(tmp_path):
    """NeptuneMassSpec.java:156-168: blank becomes 0, X/D stripped; BlockStatsRecord.java:64-84: nonpositive log mask."""
    p = tmp_path / "synthetic.exp"
    p.write_text(
        thermo(
            "Neptune", "1\t1\t\t-2\n2\t2\tX3\t4\n", names="1:229.5\t9:240.5/9:238U (7)"
        )
    )
    run = open_run(p)
    assert run.functions[1].is_ratio
    assert np.isnan(run.values[0, 0]) and run.invalid[0].all()
    values, mask, _ = tripoli_comparison_arrays(run)
    np.testing.assert_array_equal(values, [[0, -2], [3, 4]])
    np.testing.assert_array_equal(mask, [[True, False], [True, True]])
    assert run.block.tolist() == [1, 1]


def test_synthetic_nu_no_fabricated_native_time(tmp_path):
    """NuMassSpec.java:97-117 assigns row cycles/time=1; native time remains unavailable."""
    source = next((BASE / "data/NuTIMS").glob("*Pb*")).read_text().splitlines()[:12]
    source[1] = "Sample name\tSYNTHETIC"
    source[3] = "Number of measurements per block\t1"
    p = tmp_path / "synthetic.any"
    p.write_text("\n".join(source) + "\n1\t2\t3\t4\t5\t6\n2\t3\t4\t5\t6\t7\n")
    run = open_run(p)
    assert run.block.tolist() == [1, 2] and np.isnan(run.time).all()
    assert tripoli_comparison_arrays(run)[2].tolist() == [1, 1]
    assert run.functions[0].is_ratio


@pytest.mark.parametrize(
    "bad",
    [
        lambda s: s.replace("Triton Analysis Data Report", "Triton data"),
        lambda s: s.replace("Cycle\tTime", "Cycle\tOther"),
        lambda s: s.replace("X2", "not a number"),
        lambda s: s.replace("2\t04:", "1\t04:"),
    ],
)
def test_synthetic_malformed_vendor_reports_fail(tmp_path, bad):
    p = tmp_path / "synthetic.exp"
    p.write_text(bad(thermo()))
    with pytest.raises(ValueError):
        open_run(p)


@pytest.mark.parametrize(
    "cpb,blocks,padded", [(2, [1, 1, 2, 2], 1), (0, [1, 1, 1], 0), (10, [1, 1, 1], 0)]
)
def test_template_scalar_layout_and_padding(tmp_path, cpb, blocks, padded):
    """OGTripoli/source/vendors_data/IDTIMS_ImportedCSVDataFile.cs:126-174,195-213,286-328: template, blocks, zero clamp/padding."""
    p = tmp_path / "synthetic.csv"
    p.write_text(
        f"{SIGNATURE},,\nDate:,Jan/02/2010\nSample:,SYNTHETIC\nFraction:,z1\ncycles/blk:,{cpb}\n"
        "START DATA,,\ncycle #,206/205,204/205\n1,2,1\n2,4,2\n3,-2,3\n"
    )
    run = open_run(p)
    assert run.raw.format == "idtims_template_csv"
    assert run.metadata.analysis_start.isoformat() == "2010-01-02T00:00:00"
    assert run.metadata.extra["fraction_id"] == "z1"
    from rawtims.fractions import pair_analyses

    assert pair_analyses([Analysis(run)]).fractions[0].fraction_id == "z1"
    assert run.metadata.extra["padded_cycles"] == padded
    assert run.block.tolist() == blocks
    np.testing.assert_array_equal(run.values[:3], [[2, 1], [4, 2], [0, 3]])
    assert run.invalid[2, 0]
    assert Analysis(run).stats("206/205").mean == 3


def test_committed_template_is_an_empty_layout_oracle():
    """OGTripoli/docs/ID_TIMS_DataImportTemplate.csv:1-17; importer TestFileValidity:81-88."""
    p = BASE / "ID_TIMS_DataImportTemplate.csv"
    assert sniff(p).format == "idtims_template_csv"
    with pytest.raises(ValueError, match="Empty import template"):
        read_template(p)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("cycles/blk:,2", "cycles/blk:,-1"),
        lambda s: s.replace("1,2,3", "1,broken,3"),
        lambda s: s.replace("1,2,3", "1,2"),
        lambda s: s.replace("cycle #,206/205,204/205", "cycle #,,204/205"),
    ],
)
def test_malformed_template_does_not_shift_columns(tmp_path, change):
    p = tmp_path / "synthetic.csv"
    p.write_text(
        change(
            f"{SIGNATURE}\ncycles/blk:,2\nSTART DATA\ncycle #,206/205,204/205\n1,2,3\n"
        )
    )
    with pytest.raises(ValueError):
        open_run(p)


@pytest.mark.parametrize(
    "relative",
    [
        "NuTIMS/FC1 E U (Individual Answers_554).txt",
        "TritonTIMS/ETH/21341_ R9_z2_U_STAT.exp",
        "NeptuneMCICPMS/MK-113z1.exp",
    ],
)
def test_processed_pb_u_session_reopens_identically(tmp_path, relative):
    """New paths retain the established session replay contract and per-function vendor flags."""
    from rawtims.session import load_session, save_session
    from rawtims_gui.workspace import Workspace

    w = Workspace()
    result = w.open([BASE / "data" / relative])
    assert len(result.added) == 1 and not result.skipped
    original = result.added[0]
    original.toggle_block(1, False)
    target = save_session(w.session_state(), tmp_path / "synthetic.json")
    state, problems = load_session(target)
    assert not problems
    reopened = next(a for f in state.fractions for a in (f.pb, f.u) if a is not None)
    np.testing.assert_array_equal(reopened.values, original.values)
    np.testing.assert_array_equal(reopened.invalid, original.invalid)
    np.testing.assert_array_equal(reopened.effective, original.effective)
    assert reopened.run.metadata.extra == original.run.metadata.extra


def test_nu_intensity_unit_and_thermo_equation_caption_are_preserved():
    """NuMassSpec.java:72-81; TritonMassSpec.java:79-83 retain source captions, not evaluated equations."""
    nu = open_run(BASE / "data/NuTIMS/FC1 E U (Individual Answers_554).txt")
    assert nu.function("270 (V)").unit == "V"
    triton = open_run(BASE / "data/TritonTIMS/ETH/21341_ R9_z2_U_STAT.exp")
    name = "238/235 oc = (R3/R2)/((1/R2)-(2*R18))"
    assert triton.function(name).name == name
    assert triton.metadata.extra["unmeasured_cycles"] == [
        str(i) for i in range(318, 401)
    ]
