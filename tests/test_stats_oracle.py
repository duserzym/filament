"""filament's statistics against Tripoli's own expected outputs for the same raw files (SPEC F11, F12).

Tripoli made its ``Oracle-*`` reports with every cycle included, geometric
statistics for ratios and arithmetic statistics for everything else, and its
current oxide formula with 18O/16O = 0.00205. An analysis opened with
default settings includes every valid cycle, so its numbers must match.

Two documented differences:

* **Ratios with values ≤ 0.** Tripoli (``UserFunction.testRatioStatus``, its
  issue #214) then treats the whole ratio as a plain function: arithmetic
  statistics over every value, the non-positive ones included. filament keeps
  its rule that values ≤ 0 in a ratio column are invalid and never enter
  statistics (SPEC section 3). For those columns the test checks both: that
  filament excludes them by default, and that filament's arithmetic
  statistics over the same values Tripoli used reproduce Tripoli's numbers.
* **Oxide columns** (``*oc``). With ``oxide_formula="tripoli_java_00dc941"`` they
  match Tripoli; with the default ET_Redux form 233/235oc is the same (both
  forms share it) and 238/235oc and 238/233oc differ.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from oracle_reports import read_full_report, read_short_report
from rawtims.analysis import Analysis, AnalysisSettings
from rawtims.stats import describe
from reader_fixtures import NBS981_XLS, TIMSDP_FILES, TRIPOLI, read

SHORT = TRIPOLI / "oracle" / "shortReports"
FULL = TRIPOLI / "oracle" / "fullReports"
TOLERANCE = 1e-9

# short report path (relative to SHORT): (raw file, number of functions in the report)
SHORT_PAIRS = {
    "KU_IGL/IonVantage/Oracle-NBS981-500 20191208-5563.txt": (NBS981_XLS, 5),
    "KU_IGL/IsolinxVersion1/Oracle-NBS981 210325b-392.txt": (TIMSDP_FILES["NBS981 210325b-392"], 18),
    "KU_IGL/IsolinxVersion2/Oracle-GHR1 230921 F08b-216.txt": (TIMSDP_FILES["GHR1 230921 F08b-216"], 18),
    "KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239.txt": (TIMSDP_FILES["GHR1 230921F03 U-239"], 11),
    "KU_IGL/IsolinxVersion2/Oracle-NBS981 230024a-145.txt": (TIMSDP_FILES["NBS981 230024a-145"], 17),
    "Purdue/Oracle-WH205 z4 Pb-654.txt": (TIMSDP_FILES["WH205 z4 Pb-654"], 11),
    "Purdue/Oracle-WH205 z41 U-655.txt": (TIMSDP_FILES["WH205 z41 U-655"], 6),
    "Purdue/Oracle-WH233B z1 U-671.txt": (TIMSDP_FILES["WH233B z1 U-671"], 6),
    "Purdue/Oracle-WH233B z3 Pb-678.txt": (TIMSDP_FILES["WH233B z3 Pb-678"], 11),
}
# Ratio columns in which Tripoli found values <= 0 and switched to arithmetic statistics.
NONPOSITIVE = {("NBS981 210325b-392", "205/206"), ("NBS981 230024a-145", "205/206 Daly")}
TRIPOLI_OXIDE = AnalysisSettings(oxide_formula="tripoli_java_00dc941", r18=0.00205)


def _rel(actual: float, expected: float) -> float:
    return abs(actual - expected) / abs(expected) if expected else abs(actual)


def _keyed(names):
    seen: dict[str, int] = {}
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        yield name if seen[name] == 1 else f"{name} #{seen[name]}"


def _tripoli_view(analysis: Analysis, key: str):
    """Stats as Tripoli computed them for this column: filament's own, or arithmetic over all finite values."""
    stem = analysis.run.raw.name.rsplit(".", 1)[0]
    if (stem, key) in NONPOSITIVE:
        values = analysis.column(key)
        return describe(values, np.isfinite(values), mode="arithmetic")
    return analysis.stats(key)


def test_every_short_report_is_paired():
    assert {p.relative_to(SHORT).as_posix() for p in SHORT.rglob("*.txt")} == set(SHORT_PAIRS)


@pytest.mark.parametrize("report_name", sorted(SHORT_PAIRS))
def test_mean_and_percent_se_match_the_short_report(report_name):
    raw_path, n_expected = SHORT_PAIRS[report_name]
    entries = read_short_report(SHORT / report_name)
    run = read(raw_path)
    analysis = Analysis(run, TRIPOLI_OXIDE)
    assert analysis.history == [] and analysis.effective.sum() == (~analysis.invalid).sum()
    worst_mean = worst_pct = 0.0
    keys = list(_keyed(name for name, _, _ in entries))
    for key, (_, mean, pct) in zip(keys, entries):
        stats = _tripoli_view(analysis, key)
        assert stats.n_used == run.n_cycles, key  # every cycle, as Tripoli used
        worst_mean = max(worst_mean, _rel(stats.mean, mean))
        worst_pct = max(worst_pct, _rel(stats.se_pct, pct))
    assert len(keys) == n_expected
    print(f"{report_name}: {len(keys)} functions, max rel diff mean {worst_mean:.2g}, %SE {worst_pct:.2g}")
    assert worst_mean <= TOLERANCE and worst_pct <= TOLERANCE


@pytest.mark.parametrize("stem,key", sorted(NONPOSITIVE))
def test_filament_excludes_nonpositive_ratio_values_where_tripoli_goes_arithmetic(stem, key):
    analysis = Analysis(read(TIMSDP_FILES[stem]))
    function = analysis.function(key)
    assert function.is_ratio and analysis.invalid[:, function.index].any()
    stats = analysis.stats(key)
    assert stats.mode == "geometric" and stats.n_used == analysis.n_cycles - int(analysis.invalid[:, function.index].sum())
    assert stats.mean > 0


def test_ku_ghr1_u239_oxide_columns_tripoli_form_matches_isobar_233_18O_differs():
    report = {name: (mean, pct) for name, mean, pct in read_short_report(SHORT / "KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239.txt")}
    run = read(TIMSDP_FILES["GHR1 230921F03 U-239"])
    tripoli = Analysis(run, TRIPOLI_OXIDE)
    isobar_233_18O = Analysis(run)
    assert isobar_233_18O.settings.oxide_formula == "isobar_233_18O" and isobar_233_18O.settings.r18 == 0.00205
    for name in ("233/235oc", "238/235oc", "238/233oc"):
        mean, pct = report[name]
        assert _rel(tripoli.stats(name).mean, mean) <= TOLERANCE and _rel(tripoli.stats(name).se_pct, pct) <= TOLERANCE
    assert isobar_233_18O.stats("233/235oc").mean == tripoli.stats("233/235oc").mean  # identical formula in both forms
    for name in ("238/235oc", "238/233oc"):
        assert _rel(isobar_233_18O.stats(name).mean, report[name][0]) > 5e-3  # about 0.6 % apart
    assert isobar_233_18O.stats("238/235oc").mean == pytest.approx(2.43849557, rel=1e-8)
    assert tripoli.stats("238/235oc").mean == pytest.approx(2.45317502478215, rel=1e-12)


@pytest.mark.parametrize("report_path", sorted(FULL.rglob("*.csv")), ids=lambda p: p.stem)
def test_full_report_mean_se_and_sd(report_path):
    """Full reports: mean, then upper-side %SE and %SD (e^x − 1) for ratios, absolute SE and SD otherwise."""
    stem = report_path.name.removeprefix("Oracle-").removesuffix("-report.csv")
    run = read(TIMSDP_FILES[stem])
    analysis = Analysis(run, TRIPOLI_OXIDE)
    identity, columns = read_full_report(report_path)
    assert list(identity) == ["Analysis Name", "Analyst", "Lab Name", "Sample Name", "Sample Description", "Fraction", "Data File Name", "Method Name"]
    assert identity["Data File Name"] == run.raw.name and identity["Analysis Name"] == stem
    worst = 0.0
    for key, column in zip(_keyed(c.name for c in columns), columns):
        stats = _tripoli_view(analysis, key)
        assert _rel(stats.mean, column.mean) <= TOLERANCE, key
        if column.se_header == "%StdErr" and stats.mode == "geometric":
            assert column.sd_header == "%StdDev"
            pairs = ((stats.se_pct_upper, column.se), (stats.sd_pct_upper, column.sd))
        else:
            pairs = ((stats.se, column.se), (stats.sd, column.sd))
        for actual, expected in pairs:
            worst = max(worst, _rel(actual, expected))
    print(f"{report_path.name}: {len(columns)} functions, max rel diff SE/SD {worst:.2g}")
    assert worst <= TOLERANCE


def test_smaller_side_percent_is_the_lower_side():
    stats = describe(np.exp([0.0, 0.1, 0.2, 0.3]), mode="geometric")
    plus = (math.exp(stats.center + stats.se) - stats.mean) / stats.mean * 100
    minus = (stats.mean - math.exp(stats.center - stats.se)) / stats.mean * 100
    assert stats.se_pct == pytest.approx(min(plus, minus), rel=1e-14) == pytest.approx(minus, rel=1e-14)
    assert stats.se_pct_upper == pytest.approx(plus, rel=1e-14)
