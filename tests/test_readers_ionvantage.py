"""IonVantage .xls reader on every vendored workbook (SPEC sections 1.1, 3 and 7)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import pytest
import xlrd

from rawtims.model import FORMAT_IONVANTAGE_XLS
from rawtims.readers import open_run, sniff
from rawtims.readers._xls import open_xls
from reader_fixtures import B998, GHR1_PB_XLS, GHR1_U_XLS, NBS981_XLS, read

# path: (sample, serial, method, blocks, rows per block, method cycles per block, BI, n cycles, blocks measured, n functions, element, start, (complete, aborted))
# The three KU and BSU runs that stopped early also carry IsoWorks' "Data processing ABORTED!" message, so they are aborted too.
EXPECTED = {
    B998: ("13223M02 iz1", "14973", "Pb 205 Daly 150 ratios", 10, 16, 15, True, 96, 6, 59, "Pb", datetime(2018, 7, 3, 7, 46, 32), (False, True)),
    GHR1_PB_XLS: ("GHR1 20200827-11", "6590", "Pb-4-5-6-7-8 Daly 10-5-5-5-2 seconds", 100, 11, 10, True, 88, 8, 14, "Pb", datetime(2020, 8, 30, 18, 38, 8), (False, True)),
    GHR1_U_XLS: ("GHR1 20200827-11 U", "6591", "UO2 Static 265-7-8-0 Faraday 272 Daly 18s BL 22s OP", 100, 110, 110, False, 624, 6, 7, "U", datetime(2020, 8, 30, 19, 54, 7), (False, True)),
    NBS981_XLS: ("NBS981-500 20191208", "5563", "Pb-4-5-6-7-8 Daly 10-1-2-5-2 NoBI", 10, 15, 15, False, 150, 10, 5, "Pb", datetime(2019, 12, 9, 9, 50, 14), (True, False)),
}

FUNCTIONS = {
    GHR1_PB_XLS: ["i204", "i205", "i206", "i207", "i208", "204/205", "206/205", "207/205", "208/205", "206/207", "206/208", "206/204", "207/204", "208/204"],
    GHR1_U_XLS: ["i265", "i267", "i270", "i272", "270/267", "265/267", "272/270"],
    NBS981_XLS: ["i204", "i205", "i206", "i207", "i208"],
}


@pytest.mark.parametrize("path", sorted(EXPECTED), ids=lambda p: p.stem)
def test_header_cycles_and_functions(path):
    sample, serial, method, blocks, rows_per_block, method_cycles, bi, n_cycles, measured, n_functions, element, start, (complete, aborted) = EXPECTED[path]
    assert sniff(path).format == FORMAT_IONVANTAGE_XLS
    run = read(path)
    meta = run.metadata
    assert (meta.sample_id, meta.serial, meta.method) == (sample, serial, method)
    assert (meta.blocks, meta.cycles_per_block) == (blocks, rows_per_block)
    assert (meta.extra["cycles_per_block_method"], meta.extra["beam_interpolation"]) == (method_cycles, bi)
    assert (run.n_cycles, run.blocks_measured, run.n_functions) == (n_cycles, measured, n_functions)
    assert run.element == element
    assert meta.analysis_start == start and meta.software == "IonVantage"
    assert meta.complete is complete and meta.stopped_early is (not complete) and meta.aborted is aborted
    assert complete is (n_cycles == blocks * rows_per_block)
    assert (meta.aborted_reason is not None) is aborted
    assert run.raw.format == FORMAT_IONVANTAGE_XLS and run.raw.format_version == "4"
    assert np.array_equal(run.cycle, np.arange(1, n_cycles + 1))
    assert np.array_equal(run.block, (run.cycle - 1) // rows_per_block + 1)
    assert run.values.shape == (n_cycles, n_functions)
    assert len(set(run.keys)) == n_functions
    if path in FUNCTIONS:
        assert run.names == FUNCTIONS[path]


def test_boise_state_aborted_run():
    run = read(B998)
    meta = run.metadata
    assert run.n_cycles == 96 and meta.extra["Ratios so far"] == 96.0 and meta.extra["Total Ratios"] == 150.0
    assert run.blocks_measured == 6 and np.bincount(run.block)[1:].tolist() == [16] * 6
    assert meta.aborted is True and meta.stopped_early is True and meta.complete is False
    assert meta.extra["IsoWorks Error Message"].startswith("Data processing ABORTED")
    assert meta.aborted_reason == "CTRL IsoWorks Error Message: Data processing ABORTED!"
    assert meta.rejection == {"percent": 5.0, "sigma": 2.0}
    assert meta.extra["Job Code"] == "B0998" and meta.extra["Apply Baselines"] is True
    assert meta.analysis_start_raw == "Tuesday 3 July 2018 7:46:32"
    assert run.names[:3] == ["Pb204+Hg204 S1 int", "Tl205 S2 int", "Pb206+At206 S3 int"]
    assert run.names[-3:] == ["206/208 D", "207/204 D", "208/204 D"]
    assert run.function("206/204 D").collector == "D" and run.function("206/204 D").is_ratio
    assert run.function("204 D").kind == "intensity" and run.function("204 D").unit == "cps"
    assert not run.invalid.any() and np.isfinite(run.values).all()
    assert run.values[0, 0] == pytest.approx(38.15308294063305, rel=0, abs=0)


def test_repeated_function_names_are_kept_as_separate_columns():
    run = read(B998)
    repeated = sorted({name for name in run.names if run.names.count(name) > 1})
    assert "Daly/Faraday Gain" in repeated and "206/204 F-D" in repeated
    first, second = run.function("Daly/Faraday Gain"), run.function("Daly/Faraday Gain #2")
    assert first.index < second.index and first.metadata["source_column"] != second.metadata["source_column"]
    assert first.kind == second.kind == "other"
    # Some repeats hold the same numbers (the two gain columns), others differ (the raw ratios of two sequences).
    assert np.array_equal(run.column("Daly/Faraday Gain"), run.column("Daly/Faraday Gain #2"))
    assert not np.array_equal(run.column("Pb206+At206/Tl205 raw"), run.column("Pb206+At206/Tl205 raw #2"))
    book = open_xls(str(B998))
    sheet = book.sheet_by_name("CYCLE")
    for function in run.functions:
        column = [sheet.cell_value(16 + i, function.metadata["source_column"]) for i in range(run.n_cycles)]
        assert np.array_equal(run.values[:, function.index], column), function.key
    assert sum(key.endswith(" #2") for key in run.keys) == len(repeated)


@pytest.mark.parametrize("path", sorted(EXPECTED), ids=lambda p: p.stem)
def test_block_size_matches_the_block_sheet_totals(path):
    """With beam interpolation on, a block has Cycles per Block + 1 rows: the BLOCK sheet's Total row agrees."""
    book = open_xls(str(path))
    sheet = book.sheet_by_name("BLOCK")
    header = next(r for r in range(sheet.nrows) if sheet.cell_value(r, 2) == "Grand Results")
    total = next(r for r in range(header, sheet.nrows) if sheet.cell_value(r, 1) == "Total")
    run = read(path)
    counts = np.bincount(run.block)[1:]
    for col in range(3, 3 + len(counts)):
        block = int(sheet.cell_value(header, col))
        assert counts[block - 1] == int(sheet.cell_value(total, col)), (path.name, block)


def test_stock_xlrd_still_fails_and_the_workaround_is_not_global():
    assert xlrd.__version__ == "2.0.2"
    read(NBS981_XLS)
    with pytest.raises(AssertionError):
        xlrd.open_workbook(str(NBS981_XLS))


def test_concurrent_opens_agree_with_serial_opens():
    paths = sorted(EXPECTED) * 2
    serial = [open_run(path).values for path in paths]
    with ThreadPoolExecutor(max_workers=4) as pool:
        parallel = [run.values for run in pool.map(open_run, paths)]
    for a, b in zip(serial, parallel):
        assert np.array_equal(a, b, equal_nan=True)
