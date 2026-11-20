"""The idtims-fractions/1 CSV: column names from the contract text, writer, reader, legacy MA1 file, merge (SPEC F15, section 4)."""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from reader_fixtures import B998, FIXTURES, TIMSDP_FILES, read

from rawtims.analysis import Analysis
from rawtims.contract import (
    COLUMN_BY_NAME,
    COLUMN_NAMES,
    CONTRACT_ID,
    PB_RATIOS,
    U_OXIDE_FORMULAS,
    U_RATIOS,
    ContractError,
    FractionRow,
    MergeConflict,
    csv_text,
    mean_column,
    merge_rows,
    parse_csv_text,
    read_and_merge,
    read_csv,
    rho_column,
    se_column,
    write_csv,
)
from rawtims.fractions import Fraction, SessionInfo, fraction_row

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DOC = ROOT / "docs" / "contract-idtims-fractions-v1.md"
MA1 = FIXTURES / "idtims_upbrpy" / "MA1_zircon_CA-ID-TIMS.csv"
EXPORTED_AT = datetime(2026, 11, 14, 15, 30, tzinfo=UTC)

# The column defaults of IDTIMS_UPbRPy load_grains (src/IDTIMS_UPbRPy/UPbR.py, app branch a37a52e),
# copied as data: this test must not import IDTIMS_UPbRPy.
LOAD_GRAINS_DEFAULTS = {
    "id": "Grain ID",
    "sample_weight": "Sample Weight (mg)",
    "spike_weight": "Spike Weight (g)",
    "spike_type": "Spike Type",
    "spike_name": "Spike",
    "collector": "Collector",
    "Pb_R45m": "204Pb/205Pb Mean", "Pb_R45m_std_rel": "204Pb/205Pb % Standard Error",
    "Pb_R46m": "204Pb/206Pb Mean", "Pb_R46m_std_rel": "204Pb/206Pb % Standard Error",
    "Pb_R64m": "206Pb/204Pb Mean", "Pb_R64m_std_rel": "206Pb/204Pb % Standard Error",
    "Pb_R65m": "206Pb/205Pb Mean", "Pb_R65m_std_rel": "206Pb/205Pb % Standard Error",
    "Pb_R67m": "206Pb/207Pb Mean", "Pb_R67m_std_rel": "206Pb/207Pb % Standard Error",
    "Pb_R75m": "207Pb/205Pb Mean", "Pb_R75m_std_rel": "207Pb/205Pb % Standard Error",
    "Pb_R76m": "207Pb/206Pb Mean", "Pb_R76m_std_rel": "207Pb/206Pb % Standard Error",
    "Pb_R85m": "208Pb/205Pb Mean", "Pb_R85m_std_rel": "208Pb/205Pb % Standard Error",
    "U_R85m": "238U/235U Mean", "U_R85m_std_rel": "238U/235U % Standard Error",
    "U_R35m": "233U/235U Mean", "U_R35m_std_rel": "233U/235U % Standard Error",
    "U_R83m": "238U/233U Mean", "U_R83m_std_rel": "238U/233U % Standard Error",
    "Pb_R25m": "202Pb/205Pb Mean", "Pb_R25m_std_rel": "202Pb/205Pb % Standard Error",
}
# load_grains derives 204/206 and 207/206 from 206/204 and 206/207 when absent; 202/205 is read for 2535 only.
DERIVED_BY_LOAD_GRAINS = {"Pb_R46m", "Pb_R46m_std_rel", "Pb_R76m", "Pb_R76m_std_rel"}
ONLY_FOR_2535 = {"Pb_R25m", "Pb_R25m_std_rel"}


def to_load_grains_header(header: list[str]) -> list[str]:
    """What a notebook user does to a contract file for load_grains' defaults: rename Fraction ID to Grain ID, nothing else."""
    return ["Grain ID" if name == "Fraction ID" else name for name in header]


def load_grains_missing(header: list[str], spike_type: str) -> list[str]:
    """Default load_grains columns absent from a header (pure function; no IDTIMS_UPbRPy import)."""
    needed = {k: v for k, v in LOAD_GRAINS_DEFAULTS.items() if k not in DERIVED_BY_LOAD_GRAINS and (spike_type == "2535" or k not in ONLY_FOR_2535)}
    return sorted(v for v in needed.values() if v not in header)


@pytest.fixture(scope="module")
def ghr1_row() -> FractionRow:
    fraction = Fraction(
        "GHR1 z1",
        pb=Analysis(read(TIMSDP_FILES["GHR1 230921 F08b-216"])),
        u=Analysis(read(TIMSDP_FILES["GHR1 230921F03 U-239"])),
        sample="GHR1", sample_weight_mg=0.012, spike_weight_g=0.0151, spike_type="535", spike="ET535", collector="D",
    )
    return fraction_row(fraction, EXPORTED_AT, SessionInfo("ghr1.rawtims", "ab" * 32))


@pytest.fixture(scope="module")
def b998_row() -> FractionRow:
    return fraction_row(Fraction("13223M02 iz1", pb=Analysis(read(B998)), notes='comma, and "quotes"'), EXPORTED_AT)


# ----------------------------------------------------------- contract text
def _doc_table_names() -> tuple[set[str], set[str]]:
    """Backticked column names in the first cell of the contract's tables, and the ratio names of its ratio table."""
    columns, ratios = set(), set()
    for line in CONTRACT_DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0] in ("Pb", "U"):
            continue
        if cells[0].strip("`") in (*U_OXIDE_FORMULAS, "arithmetic", "geometric"):  # value tables, not columns
            continue
        columns.update(re.findall(r"`([^`]+)`", cells[0]))
    for line in CONTRACT_DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith(("| Pb |", "| U |")):
            ratios.update(name for name in re.findall(r"`([^`]+)`", line) if "/" in name)
    return columns, ratios


def test_every_contract_table_column_is_known_and_every_known_column_is_in_the_contract():
    named, ratios = _doc_table_names()
    assert ratios == set(PB_RATIOS) | set(U_RATIOS)
    assert len(named) == 62  # 8 identity, 8 setup, 29 provenance, 17 database/chemistry
    assert named <= set(COLUMN_NAMES)
    for name in COLUMN_NAMES:  # every non-ratio column comes from a contract table
        if name.endswith((" Mean", " % Standard Error")) or name.startswith("rho "):
            continue
        assert name in named, name
    # The optional inverse orientations the contract allows a writer to add.
    for ratio in ("204Pb/206Pb", "207Pb/206Pb"):
        assert mean_column(ratio) in COLUMN_BY_NAME and ratio in CONTRACT_DOC.read_text(encoding="utf-8")
    assert rho_column("206Pb/205Pb", "207Pb/205Pb") in COLUMN_BY_NAME  # the contract's own example


def test_contract_copy_matches_the_spec_statement():
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    assert f"`{CONTRACT_ID}`" in text and "Status: **agreed**" in text


# --------------------------------------------------------------- round trip
def test_write_read_write_is_byte_identical(tmp_path, ghr1_row, b998_row):
    extra = FractionRow(values=dict(ghr1_row.values) | {"Fraction ID": "GHR1 z2"}, extra={"Lab Note": "kept, as text"})
    first = write_csv([ghr1_row, b998_row, extra], tmp_path / "a.fractions.csv")
    rows = read_csv(first)
    second = write_csv(rows, tmp_path / "b.fractions.csv")
    assert first.read_bytes() == second.read_bytes()
    assert not first.read_bytes().startswith(b"\xef\xbb\xbf") and b"\r\n" not in first.read_bytes()
    for original, back in zip([ghr1_row, b998_row, extra], rows):
        assert back.values == original.values | {"Contract": CONTRACT_ID}
        assert back.extra == original.extra and not back.legacy


def test_written_numbers_are_full_precision_repr(ghr1_row):
    text = csv_text([ghr1_row])
    header, values = list(csv.reader(io.StringIO(text)))
    cells = dict(zip(header, values))
    mean = ghr1_row.mean("206Pb/204Pb")
    assert cells[mean_column("206Pb/204Pb")] == repr(mean) and float(cells[mean_column("206Pb/204Pb")]) == mean
    assert cells["Pb Cycles Used"] == "99" and cells["Contract"] == CONTRACT_ID


def test_column_subset_is_required_plus_used_in_canonical_order(b998_row):
    header = next(csv.reader(io.StringIO(csv_text([b998_row]))))
    assert header[:2] == ["Contract", "Fraction ID"]
    assert header == [name for name in COLUMN_NAMES if name in header]
    assert not any(name.startswith(("238U", "233U", "U ")) for name in header)  # Pb-only row: no U columns
    assert "rho 206Pb/204Pb|202Pb/205Pb" not in header


def test_unknown_columns_are_preserved(tmp_path, b998_row):
    text = csv_text([b998_row])
    lines = text.splitlines()
    lines[0] += ",Operator,Zz Unknown"
    lines[1] += ",YZ,"
    path = tmp_path / "with_extra.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = read_csv(path)
    assert rows[0].extra == {"Operator": "YZ"}
    again = read_csv(write_csv(rows, tmp_path / "again.csv"))
    assert again[0].extra == {"Operator": "YZ"} and again[0].values == rows[0].values


def test_bom_is_tolerated(tmp_path, b998_row):
    path = tmp_path / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbf" + csv_text([b998_row]).encode())
    assert read_csv(path)[0].values == read_csv(write_csv([b998_row], tmp_path / "plain.csv"))[0].values


@pytest.mark.parametrize("value,message", [
    ("idtims-fractions/2", "not supported; this reader knows major version 1"),
    ("idtims-fractions/10", "not supported"),
    ("something-else/1", "not an idtims-fractions file"),
    ("", "Contract cell is empty"),
])
def test_unknown_major_version_and_bad_contract_values_are_rejected(value, message):
    text = f"Contract,Fraction ID\n{value},z1\n"
    with pytest.raises(ContractError, match=message):
        parse_csv_text(text, source="x.csv")


def test_reader_rejects_duplicate_ids_columns_and_bad_numbers():
    with pytest.raises(ContractError, match="already used"):
        parse_csv_text(f"Contract,Fraction ID\n{CONTRACT_ID},z1\n{CONTRACT_ID},z1\n")
    with pytest.raises(ContractError, match="duplicate column"):
        parse_csv_text("Contract,Fraction ID,Fraction ID\n")
    with pytest.raises(ContractError, match="not a number"):
        parse_csv_text(f"Contract,Fraction ID,206Pb/204Pb Mean\n{CONTRACT_ID},z1,abc\n")
    with pytest.raises(ContractError, match="Fraction ID"):
        parse_csv_text("Sample\nx\n")


def test_writer_refuses_incomplete_blocks_and_2535_without_202(b998_row):
    partial = FractionRow(values={k: v for k, v in b998_row.values.items() if not k.startswith("208Pb/205Pb")})
    with pytest.raises(ContractError, match="208Pb/205Pb Mean"):
        csv_text([partial])
    spiked = FractionRow(values=b998_row.values | {"Spike Type": "2535"})
    with pytest.raises(ContractError, match="202Pb/205Pb Mean"):
        csv_text([spiked])
    with pytest.raises(ContractError, match="appears twice"):
        csv_text([b998_row, b998_row])
    with pytest.raises(ContractError, match="unknown column"):
        FractionRow(values={"Fraction ID": "z", "Mystery": 1.0})


# ------------------------------------------------------------------- legacy
def test_legacy_ma1_reads_all_rows_without_loss():
    with MA1.open(encoding="utf-8-sig", newline="") as handle:
        table = list(csv.reader(handle))
    header, body = table[0], table[1:]
    assert header[0] == "Grain ID" and "Contract" not in header
    rows = read_csv(MA1)
    assert len(rows) == len(body) == 12
    for row, cells in zip(rows, body):
        assert row.legacy and not row.extra
        for name, text in zip(header, cells):
            column = "Fraction ID" if name == "Grain ID" else name
            value = row.get(column)
            if COLUMN_BY_NAME[column].kind == "float":
                assert value == float(text), (row.fraction_id, column)
            else:
                assert value == text, (row.fraction_id, column)
                if column == "Spike Type":
                    assert float(value) == float(text)
        assert set(row.values) == {"Fraction ID" if n == "Grain ID" else n for n in header}


def test_legacy_ma1_round_trips_through_the_contract(tmp_path):
    rows = read_csv(MA1)
    written = write_csv(rows, tmp_path / "ma1.fractions.csv")
    back = read_csv(written)
    assert [r.values for r in back] == [r.values | {"Contract": CONTRACT_ID} for r in rows]
    assert write_csv(back, tmp_path / "again.csv").read_bytes() == written.read_bytes()


def test_contract_file_converts_to_load_grains_defaults_by_renaming_fraction_id_only(ghr1_row):
    header = next(csv.reader(io.StringIO(csv_text([ghr1_row]))))
    converted = to_load_grains_header(header)
    assert "Grain ID" in converted and "Fraction ID" not in converted
    assert load_grains_missing(converted, "535") == []
    assert load_grains_missing(converted, "2535") == ["202Pb/205Pb % Standard Error", "202Pb/205Pb Mean"]
    # And the legacy layout itself, as load_grains reads it today.
    ma1_header = next(csv.reader(MA1.open(encoding="utf-8-sig", newline="")))
    assert load_grains_missing(ma1_header, "535") == []


# -------------------------------------------------------------------- merge
def test_merge_pb_and_u_rows_from_two_files(tmp_path, ghr1_row):
    pb_only = FractionRow(values={k: v for k, v in ghr1_row.values.items() if not k.startswith(("238U", "233U", "U ", "rho 238U", "rho 233U"))})
    u_only = FractionRow(values={k: v for k, v in ghr1_row.values.items() if k in ("Contract", "Fraction ID", "Exported At") or k.startswith(("238U", "233U", "U ", "rho 238U", "rho 233U"))})
    a = write_csv([pb_only], tmp_path / "pb.csv")
    b = write_csv([u_only], tmp_path / "u.csv")
    merged = read_and_merge([a, b])
    assert len(merged) == 1
    assert merged[0].values == ghr1_row.values


def test_merge_conflict_names_fraction_column_and_both_files(ghr1_row):
    other = FractionRow(values=ghr1_row.values | {"206Pb/204Pb Mean": 1.0})
    with pytest.raises(MergeConflict) as info:
        merge_rows([("first.csv", [ghr1_row]), ("second.csv", [other])])
    message = str(info.value)
    for part in ("'GHR1 z1'", "'206Pb/204Pb Mean'", "first.csv", "second.csv"):
        assert part in message
    same = merge_rows([("first.csv", [ghr1_row]), ("second.csv", [FractionRow(values=dict(ghr1_row.values))])])
    assert same[0].values == ghr1_row.values


def test_se_columns_are_percent_names():
    assert se_column("238U/235U") == "238U/235U % Standard Error"


def test_u_oxide_formula_required_with_r18_and_from_the_allowed_values():
    row = FractionRow.from_csv({"Contract": CONTRACT_ID, "Fraction ID": "z1", "U Oxide 18O/16O": "0.00206"})
    assert any("'U Oxide Formula' is required" in p for p in row.problems())
    row.values["U Oxide Formula"] = "made_up"
    assert any("is not one of" in p for p in row.problems())
    for value in U_OXIDE_FORMULAS:
        row.values["U Oxide Formula"] = value
        assert not any("U Oxide Formula" in p for p in row.problems())


@pytest.mark.parametrize("element", ["Pb", "U"])
@pytest.mark.parametrize("mode", ["arithmetic", "geometric"])
def test_mean_statistic_columns_round_trip(tmp_path, ghr1_row, element, mode):
    column = f"{element} Mean Statistic"
    assert COLUMN_BY_NAME[column].kind == "text" and COLUMN_BY_NAME[column].group == "provenance"
    row = FractionRow(values=ghr1_row.values | {column: mode})
    back = read_csv(write_csv([row], tmp_path / "stats.csv"))[0]
    assert back.get(column) == mode and back.values == row.values


@pytest.mark.parametrize("element", ["Pb", "U"])
def test_bad_mean_statistic_is_a_problem(element):
    column = f"{element} Mean Statistic"
    row = FractionRow(values={"Fraction ID": "z1", column: "median"})
    assert any(column in p and "median" in p and "is not one of" in p for p in row.problems())


@pytest.mark.parametrize("element", ["Pb", "U"])
@pytest.mark.parametrize("implicit_arithmetic", [False, True])
def test_merge_refuses_mixed_mean_statistics(ghr1_row, element, implicit_arithmetic):
    column = f"{element} Mean Statistic"
    arithmetic = dict(ghr1_row.values)
    if implicit_arithmetic:
        arithmetic.pop(column)
    other = FractionRow(values=ghr1_row.values | {column: "geometric"})
    with pytest.raises(MergeConflict) as info:
        merge_rows([("legacy.csv", [FractionRow(values=arithmetic)]), ("geometric.csv", [other])])
    assert all(part in str(info.value) for part in (column, "GHR1 z1", "legacy.csv", "geometric.csv"))


@pytest.mark.parametrize("prefix", ["Grain ID\nz1\n", f"Contract,Fraction ID\n{CONTRACT_ID},z1\n"])
def test_missing_mean_statistic_reads_as_arithmetic(prefix):
    row = parse_csv_text(prefix)[0]
    assert row.get("Pb Mean Statistic") == row.get("U Mean Statistic") == "arithmetic"
    # Absence remains lossless on re-export.
    assert "Mean Statistic" not in csv_text([row])


def test_clarification_10_contract_hash_and_sibling_copy():
    import hashlib
    expected = "691f5f410862508ebe94220b74aa43a38b16ab617e6d515263d551cbbab50205"
    assert hashlib.sha256(CONTRACT_DOC.read_bytes()).hexdigest() == expected
    sibling = ROOT.parent / "IDTIMS_UPbRPy" / "docs" / CONTRACT_DOC.name
    if sibling.is_file():
        assert CONTRACT_DOC.read_bytes() == sibling.read_bytes()
