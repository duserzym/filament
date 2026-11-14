"""IsoLinx .TIMSDP reader on every vendored file (SPEC sections 1.1, 3 and 7)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from rawtims.model import FORMAT_ISOLINX_TIMSDP
from rawtims.readers import open_run, sniff
from reader_fixtures import TIMSDP_FILES, read

# stem: (sample id, serial, method, blocks, cycles per block, n cycles, blocks measured, n functions, element, start, complete, software)
# Every file ends with #END,AnalysisCompleted, so none is aborted, although all but one stopped early.
EXPECTED = {
    "NBS981 210325b-392": ("NBS981 210325", "392", "PbNoBL-204-5-6-7-8 Daly 10-1-5-5-2.TIMSAM", 20, 10, 200, 20, 18, "Pb", datetime(2021, 4, 16, 17, 19, 34), True, "IsoLinx 1.2.31"),
    "GHR1 230921 F08b-216": ("GHR1 230921 F08", "216", "Pb 4-5-6-7-8 Daly 10-5-5-5-2 secBL5.TIMSAM", 100, 10, 99, 10, 18, "Pb", datetime(2023, 9, 26, 12, 53, 31), False, "IsoLinx 2.1.16"),
    "GHR1 230921F03 U-239": ("GHR1 230921F01 U", "239", "UO2 Static 265-7-8-0 Faraday 272 Daly 18s BL 22s OP FewPlot.TIMSAM", 100, 110, 770, 7, 8, "U", datetime(2023, 10, 5, 12, 44, 38), False, "IsoLinx 2.1.16"),
    "NBS981 230024a-145": ("NBS981 230024a", "145", "Pb NBS981 204-5-6-7-8 Daly 14-1-5-5-2 sec.TIMSAM", 100, 12, 159, 14, 17, "Pb", datetime(2023, 8, 25, 13, 18, 11), False, "IsoLinx 2.1.16"),
    "WH205 z4 Pb-654": ("WH205 z4", "654", "PbDaly_205_45678_Quick.TIMSAM", 15, 10, 70, 7, 11, "Pb", datetime(2022, 11, 28, 6, 30, 5), False, "IsoLinx 2.0.11"),
    "WH205 z41 U-655": ("WH205 z4", "655", "UO2_Faraday_265_267_268_270_272_AllFaraday.TIMSAM", 50, 15, 45, 3, 6, "U", datetime(2022, 11, 28, 7, 43, 25), False, "IsoLinx 2.0.11"),
    "WH233B z1 U-671": ("WH233B z1", "671", "UO2_Faraday_265_267_268_270_272_AllFaraday.TIMSAM", 50, 15, 75, 5, 6, "U", datetime(2022, 11, 29, 5, 47, 38), False, "IsoLinx 2.0.11"),
    "WH233B z3 Pb-678": ("WH233B z3", "678", "PbDaly_205_45678_Quick.TIMSAM", 10, 10, 20, 2, 11, "Pb", datetime(2022, 11, 29, 8, 24, 43), False, "IsoLinx 2.0.11"),
}


def _section(path: Path, name: str) -> list[str]:
    """Lines of one section, read independently of the reader."""
    lines, inside = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            inside = line.strip() == f"#{name}"
            continue
        if inside and line.strip():
            lines.append(line)
    return lines


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_header_cycles_and_functions(stem):
    path = TIMSDP_FILES[stem]
    sample, serial, method, blocks, cycles_per_block, n_cycles, measured, n_functions, element, start, complete, software = EXPECTED[stem]
    assert sniff(path).format == FORMAT_ISOLINX_TIMSDP
    run = read(path)
    meta = run.metadata
    assert (meta.sample_id, meta.serial, meta.method) == (sample, serial, method)
    assert (meta.blocks, meta.cycles_per_block) == (blocks, cycles_per_block)
    assert (run.n_cycles, run.blocks_measured, run.n_functions) == (n_cycles, measured, n_functions)
    assert run.element == element
    assert meta.analysis_start == start and meta.analysis_start.tzinfo is None
    assert meta.analysis_start_raw == meta.extra["header"]["AnalysisStart"]
    assert meta.complete is complete and meta.stopped_early is (not complete) and meta.software == software
    assert complete is (n_cycles == blocks * cycles_per_block)
    assert meta.aborted is False and meta.aborted_reason is None
    assert run.raw.format == FORMAT_ISOLINX_TIMSDP and run.raw.format_version == "1.20"
    assert run.raw.name == path.name and run.raw.size == path.stat().st_size and len(run.raw.sha256) == 64
    assert set(meta.rejection) == {"sigma", "percent"}
    assert meta.extra["end_status"] == "AnalysisCompleted"

    header = _section(path, "CYCLES")[0].split(",")
    assert run.names == [name.strip() for name in header[2:]]
    assert len(set(run.keys)) == run.n_functions
    assert run.values.shape == (n_cycles, n_functions) == run.invalid.shape
    assert np.array_equal(run.cycle, np.arange(1, n_cycles + 1))
    assert np.all(np.diff(run.time) > 0)


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_block_sizes_match_the_files_block_statistics(stem):
    """Block = (cycle − 1) // CyclesToMeasure + 1, BeamInterpCycles or not: #BLOCKS 'Total' agrees."""
    path = TIMSDP_FILES[stem]
    run = read(path)
    totals: dict[int, int] = {}
    for line in _section(path, "BLOCKS")[1:]:
        cells = [cell.strip() for cell in line.split(",")]
        totals[int(cells[0])] = max(totals.get(int(cells[0]), 0), int(cells[6]))
    counts = {int(b): int((run.block == b).sum()) for b in np.unique(run.block)}
    assert {b: counts[b] for b in totals} == totals
    # A last, incomplete block of a stopped run has no #BLOCKS statistics.
    unlisted = sorted(set(counts) - set(totals))
    assert unlisted in ([], [max(counts)]) and all(counts[b] < run.metadata.cycles_per_block for b in unlisted)


def test_collectors_formulas_and_repeated_names():
    purdue = read(TIMSDP_FILES["WH205 z4 Pb-654"])
    collectors = purdue.metadata.extra["collectors"]
    assert [row["Name"] for row in collectors] == ["PM", "L5", "L4", "L3", "L2", "Ax", "H1", "H2", "H3", "H4"]
    assert collectors[0] == {"Name": "PM", "Type": "PM", "Resistor": "1e+11", "Gain": "1.000000000", "Efficiency": "1.000000000", "DT": "29.9000"}
    r45 = purdue.function("R45")
    assert r45.metadata["function_id"] == "Srr_1" and r45.metadata["formula"] == "Intensity(1,_RPM)/Intensity(2,_RPM)"
    assert r45.kind == "other"  # IsoLinx shorthand without masses; Tripoli also treats it as a user function
    assert purdue.function("i205Pb").unit == "cps"
    assert purdue.metadata.extra["samplelist"]["Operator"] == "RBI"
    assert purdue.metadata.extra["header"]["BeamInterpCycles"] == "True"

    ku = read(TIMSDP_FILES["NBS981 230024a-145"])
    assert ku.names.count("208/206 F/F S1") == 2
    first, second = ku.function("208/206 F/F S1"), ku.function("208/206 F/F S1 #2")
    assert (first.index, second.index) == (9, 15)
    assert (first.metadata["function_id"], second.metadata["function_id"]) == ("Srr_5", "UF_4")
    assert np.array_equal(ku.column("208/206 F/F S1"), ku.column("208/206 F/F S1 #2"))  # UF_4 = Srr_5 in the file
    assert ku.function("alpha 204/206").kind == "other"

    u = read(TIMSDP_FILES["WH205 z41 U-655"])
    assert u.function("265UO2_V").unit == "V"


def test_invalid_mask_flags_non_positive_ratios_only():
    run = read(TIMSDP_FILES["NBS981 210325b-392"])
    ratio = run.function("205/206")
    assert ratio.is_ratio and np.all(run.invalid[:, ratio.index] == ~(run.column("205/206") > 0))
    assert run.invalid[:, ratio.index].sum() > 100
    intensity = run.function("205Pb")
    assert intensity.kind == "intensity" and (run.column("205Pb") <= 0).any()
    assert not run.invalid[:, intensity.index].any()


def _variant(tmp_path: Path, source: Path, name: str, transform) -> Path:
    target = tmp_path / name
    target.write_bytes(transform(source.read_bytes()))
    return target


def test_duplicated_cycles_marker_crlf_and_extension_are_tolerated(tmp_path):
    source = TIMSDP_FILES["WH205 z41 U-655"]
    original = open_run(source)
    variants = [
        _variant(tmp_path, source, "dup_before.TIMSDP", lambda b: b.replace(b"#CYCLES\n", b"#CYCLES\n#CYCLES\n")),
        _variant(tmp_path, source, "dup_after.TIMSDP", lambda b: b.replace(b"\n1,57.001", b"\n#CYCLES\n1,57.001")),
        _variant(tmp_path, source, "crlf.TIMSDP", lambda b: b.replace(b"\n", b"\r\n")),
        _variant(tmp_path, source, "renamed.txt", lambda b: b),
    ]
    for path in variants:
        run = open_run(path)
        assert run.names == original.names, path.name
        assert np.array_equal(run.values, original.values, equal_nan=True), path.name
        assert np.array_equal(run.cycle, original.cycle), path.name


def test_raw_integration_file_without_cycles_is_unsupported(tmp_path):
    text = TIMSDP_FILES["WH233B z3 Pb-678"].read_text(encoding="utf-8")
    head = text.split("#CYCLES")[0] + "#ONPEAK\nID,Block,Cycle\n#END,AnalysisCompleted\n"
    path = tmp_path / "raw.TIMSDP"
    path.write_text(head, encoding="utf-8")
    result = sniff(path)
    assert result.format is None and "#CYCLES" in result.reason
