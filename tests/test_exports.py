"""Tripoli clipboard text and the cycles CSV (SPEC F16, F17)."""

from __future__ import annotations

import csv
import io

import numpy as np
import pytest

from oracle_reports import read_short_report
from rawtims.analysis import Analysis, AnalysisSettings
from rawtims.exports import CLIPBOARD_SEPARATOR, clipboard_entries, clipboard_text, legacy_e7, cycles_csv_text, write_cycles_csv
from rawtims.fractions import Fraction, FractionError
from rawtims.mapping import MappedRatio, propose_mapping
from reader_fixtures import B998, SYNTHETIC_PB, SYNTHETIC_U, TIMSDP_FILES, TRIPOLI, read

SHORT = TRIPOLI / "oracle" / "shortReports" / "KU_IGL" / "IsolinxVersion2"

# Header labels in the "Raw Data Input" sheet of IDTIMS_UPbRPy/BSULab_UPbR26XML.xls, column E, rows 10-46
# (read with xlrd on 2026-11-14; copied here because tests must not read other repositories). The sheet's
# row order is the order of these blocks, Pb then U.
BSU_SHEET_HEADERS_PB = [
    "206/204 D  (Mean, %StdErr)", "206/207 D  (Mean, %StdErr)", "206/205 D  (Mean, %StdErr)", "207/205 D  (Mean, %StdErr)",
    "204/205 D  (Mean, %StdErr)", "208/205 D  (Mean, %StdErr)", "202/205 D  (Mean, %StdErr)",
]
BSU_SHEET_HEADERS_U = [
    "238/235 oxide R18 0.00206  (Mean, %StdErr)", "233/235 oxide R18 0.00206  (Mean, %StdErr)", "238/233 oxide  (Mean, %StdErr)",
]


def _blocks(text: str) -> list[list[str]]:
    assert text.endswith("\r\n\r\n")
    assert "\n" not in text.replace("\r\n", "")
    return [block.split("\r\n") for block in text[:-4].split("\r\n\r\n")]


@pytest.mark.parametrize("value,expected", [
    (9235.343, "9.2353430E+003"), (0.0054346663, "5.4346663E-003"),
    (-9235.343, "-9.2353430E+003"), (-0.0054346663, "-5.4346663E-003"),
    (0, "0.0000000E+000"), (1e100, "1.0000000E+100"),
])
def test_legacy_csharp_e7(value, expected):
    assert legacy_e7(value) == expected


def test_clipboard_complete_legacy_block_and_full_precision():
    fraction = Fraction("iz1", pb=Analysis(read(B998)))
    entries = clipboard_entries(fraction, "Pb")
    expected = "".join(f"{name}  (Mean, %StdErr)\r\n{legacy_e7(mean)}\r\n{legacy_e7(pct)}\r\n\r\n"
                       for name, mean, pct in entries)
    assert clipboard_text(fraction) == expected
    for block, (_, mean, pct) in zip(_blocks(clipboard_text(fraction, full_precision=True)), entries):
        assert float(block[1]) == mean and float(block[2]) == pct


def test_b998_clipboard_headers_and_order_match_the_bsu_sheet():
    fraction = Fraction("iz1", pb=Analysis(read(B998)))
    blocks = _blocks(clipboard_text(fraction, "Pb"))
    assert [b[0] for b in blocks] == BSU_SHEET_HEADERS_PB[:6]  # B998 is a 535 run: no 202/205
    analysis = fraction.pb
    for block, key in zip(blocks, ("206/204 D", "206/207 D", "206/205 D", "207/205 D", "204/205 D", "208/205 D")):
        assert len(block) == 3
        stats = analysis.stats(key)
        assert block[1] == legacy_e7(stats.mean) and block[2] == legacy_e7(stats.se_pct)
    assert CLIPBOARD_SEPARATOR == "  "


def test_b998_faraday_clipboard_uses_the_faraday_names():
    text = clipboard_text(Fraction("iz1", pb=Analysis(read(B998)), collector="F"), "Pb")
    assert [b[0] for b in _blocks(text)] == [
        "206/204 F-D  (Mean, %StdErr)", "206/207 F  (Mean, %StdErr)", "206/205 F  (Mean, %StdErr)",
        "207/205 F  (Mean, %StdErr)", "204/205 F-D  (Mean, %StdErr)", "208/205 F  (Mean, %StdErr)",
    ]


def test_synthetic_files_give_the_sheet_headers_for_202_and_u():
    """Format only (synthetic files carry BSU-style names); no claim about BSU numbers."""
    pb = clipboard_text(Fraction("s", pb=Analysis(read(SYNTHETIC_PB)), spike_type="2535"), "Pb")
    assert [b[0] for b in _blocks(pb)] == BSU_SHEET_HEADERS_PB
    u = clipboard_text(Fraction("s", u=Analysis(read(SYNTHETIC_U))), "U")
    assert [b[0] for b in _blocks(u)] == BSU_SHEET_HEADERS_U


def test_whole_fraction_clipboard_is_pb_then_u():
    fraction = Fraction("GHR1", pb=Analysis(read(TIMSDP_FILES["GHR1 230921 F08b-216"])), u=Analysis(read(TIMSDP_FILES["GHR1 230921F03 U-239"])))
    names = [b[0].removesuffix("  (Mean, %StdErr)") for b in _blocks(clipboard_text(fraction))]
    assert names == ["206/204", "206/207", "206/205", "207/205", "204/205", "208/205", "238/235oc", "233/235oc", "238/233oc"]


def test_single_space_separator_reproduces_the_tripoli_short_report(tmp_path):
    fraction = Fraction("GHR1", pb=Analysis(read(TIMSDP_FILES["GHR1 230921 F08b-216"]), AnalysisSettings(stat_mode="geometric")))
    path = tmp_path / "clip.txt"
    path.write_text(clipboard_text(fraction, "Pb", separator=" ", full_precision=True), encoding="utf-8")
    ours = read_short_report(path)
    oracle = {name: (mean, pct) for name, mean, pct in read_short_report(SHORT / "Oracle-GHR1 230921 F08b-216.txt")}
    assert len(ours) == 6
    for name, mean, pct in ours:
        assert mean == pytest.approx(oracle[name][0], rel=1e-9) and pct == pytest.approx(oracle[name][1], rel=1e-9)


def test_inverted_clipboard_names_say_so():
    analysis = Analysis(read(TIMSDP_FILES["NBS981 230024a-145"]), AnalysisSettings(stat_mode="geometric"))
    fraction = Fraction("NBS", pb=analysis)
    with pytest.raises(FractionError, match="lacks contract ratios"):
        clipboard_entries(fraction, "Pb")
    mapping = propose_mapping(analysis)
    assert mapping.ratios["206Pb/204Pb"].inverted
    # Fill the missing ratios with any function of the right shape for this format check only.
    for ratio in ("207Pb/205Pb", "204Pb/205Pb", "208Pb/205Pb"):
        mapping.ratios[ratio] = MappedRatio(ratio=ratio, key="208/206 Daly", name="208/206 Daly")
    entries = clipboard_entries(Fraction("NBS", pb=analysis, pb_mapping=mapping), "Pb")
    assert entries[0][0] == "1/(204/206 Daly)"
    assert entries[0][1] * analysis.stats("204/206 Daly").mean == pytest.approx(1.0, abs=1e-14)


def test_cycles_csv_layout_values_and_flags(tmp_path):
    analysis = Analysis(read(TIMSDP_FILES["GHR1 230921F03 U-239"]))
    analysis.toggle_cycles([0, 5], ["270/267"], include=False)
    analysis.toggle_block(3, include=False)
    keys = ["270/267", "265/267", "238/235oc"]
    text = cycles_csv_text(analysis, keys)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["Block", "Cycle", "Time (s)", "270/267", "270/267 included", "265/267", "265/267 included", "238/235oc", "238/235oc included"]
    body = rows[1:]
    assert len(body) == analysis.n_cycles
    values = np.array([[float(r[3]), float(r[5]), float(r[7])] for r in body])
    assert np.array_equal(values, analysis.values[:, [analysis.index(k) for k in keys]])
    flags = np.array([[r[4] == "1", r[6] == "1", r[8] == "1"] for r in body])
    assert np.array_equal(flags, analysis.effective[:, [analysis.index(k) for k in keys]])
    assert body[0][4] == "0" and body[0][6] == "1"
    assert all(r[4] == r[6] == "0" for r in body if r[0] == "3")
    assert [int(r[1]) for r in body] == analysis.run.cycle.tolist() and [int(r[0]) for r in body] == analysis.run.block.tolist()
    every = cycles_csv_text(analysis)
    assert next(csv.reader(io.StringIO(every)))[3::2] == analysis.keys
    path = write_cycles_csv(analysis, tmp_path / "cycles.csv", keys)
    assert path.read_text(encoding="utf-8") == text and "\r" not in text


def test_cycles_csv_empty_cell_for_missing_values():
    analysis = Analysis(read(B998))
    text = cycles_csv_text(analysis, ["206/204 D"])
    assert all(len(row) == 5 for row in csv.reader(io.StringIO(text)))
