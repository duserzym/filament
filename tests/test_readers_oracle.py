"""Per-cycle values against Tripoli's own cycle reports for the same files (the strongest reader check).

Every column present in both the raw file and ``Oracle-*-report.tsv`` is
compared cycle by cycle; repeated names pair up by order of occurrence.
Columns only in the oracle (Tripoli's derived ``233/235oc`` …) are skipped.
At the time of writing every file agrees exactly (max relative difference 0).
"""

from __future__ import annotations

import numpy as np
import pytest

from oracle_reports import read_cycle_report
from reader_fixtures import NBS981_XLS, ORACLE_CYCLES, TIMSDP_FILES, read

TOLERANCE = 1e-12

PAIRS = {
    "KU_IGL/IonVantage/Oracle-NBS981-500 20191208-5563-report.tsv": (NBS981_XLS, 5),
    "KU_IGL/IsolinxVersion1/Oracle-NBS981 210325b-392-report.tsv": (TIMSDP_FILES["NBS981 210325b-392"], 18),
    "KU_IGL/IsolinxVersion2/Oracle-GHR1 230921 F08b-216-report.tsv": (TIMSDP_FILES["GHR1 230921 F08b-216"], 18),
    "KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239-report.tsv": (TIMSDP_FILES["GHR1 230921F03 U-239"], 8),
    "KU_IGL/IsolinxVersion2/Oracle-NBS981 230024a-145-report.tsv": (TIMSDP_FILES["NBS981 230024a-145"], 17),
    "Purdue/Oracle-WH205 z4 Pb-654-report.tsv": (TIMSDP_FILES["WH205 z4 Pb-654"], 11),
    "Purdue/Oracle-WH205 z41 U-655-report.tsv": (TIMSDP_FILES["WH205 z41 U-655"], 6),
    "Purdue/Oracle-WH233B z1 U-671-report.tsv": (TIMSDP_FILES["WH233B z1 U-671"], 6),
    "Purdue/Oracle-WH233B z3 Pb-678-report.tsv": (TIMSDP_FILES["WH233B z3 Pb-678"], 11),
}


def test_every_cycle_report_is_paired():
    on_disk = {p.relative_to(ORACLE_CYCLES).as_posix() for p in ORACLE_CYCLES.rglob("*.tsv")}
    assert on_disk == set(PAIRS)


@pytest.mark.parametrize("report_name", sorted(PAIRS))
def test_cycle_values_match_the_oracle(report_name):
    raw_path, expected_columns = PAIRS[report_name]
    report = read_cycle_report(ORACLE_CYCLES / report_name)
    run = read(raw_path)
    assert np.array_equal(report.cycle, run.cycle)
    assert np.array_equal(report.time, run.time)
    assert not report.discarded.any()  # the oracles were produced without rejections

    occurrences: dict[str, int] = {}
    compared, worst = 0, 0.0
    for j, name in enumerate(report.names):
        occurrences[name] = occurrences.get(name, 0) + 1
        key = name if occurrences[name] == 1 else f"{name} #{occurrences[name]}"
        if key not in run.keys:
            assert name.endswith("oc"), f"oracle column {name!r} missing from the run"
            continue
        expected, actual = report.values[:, j], run.column(key)
        assert np.array_equal(np.isnan(expected), np.isnan(actual)), key
        both = ~np.isnan(expected)
        scale = np.where(expected[both] == 0, 1.0, np.abs(expected[both]))
        relative = np.abs(actual[both] - expected[both]) / scale
        worst = max(worst, float(relative.max(initial=0.0)))
        compared += 1
    assert compared == expected_columns == run.n_functions
    print(f"{raw_path.name}: {compared} columns x {run.n_cycles} cycles, max relative difference {worst:.3g}")
    assert worst <= TOLERANCE
