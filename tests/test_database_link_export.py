"""Confirmed snapshots in the contract and backward-compatible sessions."""
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from reader_fixtures import SYNTHETIC_PB, SYNTHETIC_U, read
from test_upbdb import candidate

from rawtims.analysis import Analysis
from rawtims.contract import (
    ContractError,
    FractionRow,
    csv_text,
    merge_rows,
    parse_csv_text,
)
from rawtims.fractions import Fraction, apply_link, database_link_warnings, fraction_row
from rawtims.session import (
    SessionError,
    SessionState,
    load_session,
    save_session,
    session_document,
)
from rawtims.upbdb import Source

STAMP = datetime(2026, 11, 20, 12, tzinfo=UTC)


def fraction():
    return Fraction("AH1-gc1 z1", pb=Analysis(read(SYNTHETIC_PB)))


def linked():
    f = fraction()
    f.database_link = candidate().confirm("https://example.com", "alice")
    return f


@pytest.mark.parametrize("initial", [None, "", "fraction_id", "raw_sample_id", "typed"])
def test_apply_link_sets_sample_only_for_blank_or_automatic_values(initial):
    f = fraction()
    values = {"fraction_id": f.fraction_id, "raw_sample_id": f.pb.run.metadata.sample_id, "typed": "My sample"}
    f.sample = values.get(initial, initial)
    link = candidate().confirm("example.com", "alice")
    apply_link(f, link)
    assert f.database_link == link
    assert f.sample == ("My sample" if initial == "typed" else "AH1-gc1")
    assert fraction_row(f, STAMP).get("Sample") == f.sample
    warnings = database_link_warnings(f)
    assert bool(warnings) == (initial == "typed")
    if warnings:
        assert warnings == ["Sample: your value 'My sample' differs from database 'AH1-gc1'; your value is kept."]


def test_apply_link_recognizes_the_u_runs_automatic_sample_id():
    f = Fraction("paired", u=Analysis(read(SYNTHETIC_U)))
    f.sample = f.u.run.metadata.sample_id
    apply_link(f, candidate().confirm("example.com", "alice"))
    assert f.sample == "AH1-gc1"


def test_single_source_contract_chemistry_and_repr():
    f = linked()
    row = fraction_row(f, STAMP)
    assert row.get("Fraction UID") == "f1" and row.get("Database Server") == "https://example.com"
    assert row.get("Database Read At") == f.database_link.database_read_at
    assert row.get("Beaker") == "K9" and row.get("Capsule Set") == "Krogh"
    assert row.get("Chemistry Batch UID") == "b1"
    assert row.get("Source Grain UID") == "g1" and row.get("Source Spot UID") == "p1"
    assert row.get("Source Mount") == "S" and row.get("Source Grain") == "G1" and row.get("Source Spot") == "S 1"
    assert row.get("Source Fragment Note") == "half"
    assert row.get("Spike") == "ET535" and row.get("Spike Solution") == "ET535/master/v3"
    assert row.to_csv()["Spike Weight (g)"] == repr(f.database_link.chemistry.spike_weight_g)
    assert row.to_csv()["Annealing Duration (h)"] == "48.0"
    assert parse_csv_text(csv_text([row]))[0].values == row.values
    assert f.beaker is None and f.spike is None  # Copies belong to the link; unlink restores the typed fields.


def test_multiple_sources_keep_aligned_empty_entries():
    f = linked()
    f.database_link = replace(f.database_link, sources=[
        Source(grain_uid="g1", spot_uid="p1", mount_name="M1", spot_label="P1"),
        Source(grain_uid="g2", grain_label="G2", is_fragment=True, fragment_note="chip"),
        Source(grain_uid="g3", mount_name="M3"),
    ])
    row = fraction_row(f, STAMP)
    expected = {"Source Grain UID": "g1; g2; g3", "Source Spot UID": "p1; ; ",
                "Source Mount": "M1; ; M3", "Source Grain": "; G2; ", "Source Spot": "P1; ; ",
                "Source Fragment Note": "; chip; "}
    for column, value in expected.items():
        assert row.get(column) == value
        assert len(row.to_csv()[column].split("; ")) == 3
    restored = parse_csv_text(csv_text([row]))[0]
    assert all(restored.get(k) == v for k, v in expected.items())


def test_user_values_never_overwritten_and_differences_reported():
    f = linked()
    f.beaker, f.spike, f.spike_weight_g = "B1", "OTHER", 0.02
    f.source_mount, f.source_grain, f.source_spot = "mine", "g", "p"
    row = fraction_row(f, STAMP)
    assert row.get("Beaker") == "B1" and row.get("Spike") == "OTHER" and row.get("Spike Weight (g)") == 0.02
    assert row.get("Source Mount") == "mine" and row.get("Source Grain") == "g" and row.get("Source Spot") == "p"
    warnings = database_link_warnings(f)
    assert len(warnings) == 6 and all("your value is kept" in w for w in warnings)


def test_unlinked_csv_byte_identical_to_pre_database_writer():
    # SHA256 generated with the original fractions.py and contract.py writer at
    # the task's starting revision, using this fixed fixture and export time.
    text = csv_text([fraction_row(fraction(), STAMP)])
    assert hashlib.sha256(text.encode()).hexdigest() == "23909997d37f755dc9e003425f03a513be2d63351d983e47ebbf78ec16be3207"
    assert "Fraction UID" not in text and "Database Server" not in text


def test_session_link_roundtrip_versions_and_unknown_link_format(tmp_path):
    f = linked()
    state = SessionState(fractions=[f])
    path = save_session(state, tmp_path / "linked.rawtims")
    record = json.loads(path.read_text())
    assert record["format_version"] == 2
    assert record["fractions"][0]["database_link"]["format"] == "filament database link"
    restored, problems = load_session(path)
    assert not problems and restored.fractions[0].database_link == f.database_link
    assert session_document(restored, path, saved_at=STAMP) == session_document(state, path, saved_at=STAMP)
    record["fractions"][0]["database_link"]["format_version"] = 999
    path.write_text(json.dumps(record))
    with pytest.raises(SessionError, match="database link format or format_version"):
        load_session(path)
    f.database_link = None
    record = session_document(state, path)
    assert record["format_version"] == 1 and "database_link" not in record["fractions"][0]
    path.write_text(json.dumps(record))
    assert load_session(path)[0].fractions[0].database_link is None


def test_session_no_runs_link_is_still_preserved(tmp_path):
    f = Fraction("AH1-gc1 z1", database_link=candidate().confirm("example.com", "alice"))
    path = save_session(SessionState(fractions=[f]), tmp_path / "empty.rawtims")
    assert load_session(path)[0].fractions[0].database_link == f.database_link


def test_latest_read_time_merges_and_mixed_servers_refused():
    a = FractionRow({"Contract": "idtims-fractions/1", "Fraction ID": "x", "Database Server": "https://x", "Database Read At": "2026-11-20T11:00:00+00:00"})
    b = FractionRow({**a.values, "Database Read At": "2026-11-20T10:00:00-02:00"})
    assert merge_rows([("a", [a]), ("b", [b])])[0].get("Database Read At") == b.get("Database Read At")
    b.values["Database Server"] = "https://y"
    with pytest.raises(ContractError, match="more than one Database Server"):
        merge_rows([("a", [a]), ("b", [b])])


def test_pairing_merge_preserves_links_and_refuses_conflicting_links():
    from rawtims_gui.workspace import Workspace
    workspace = Workspace()
    a, b = Fraction("a", database_link=candidate().confirm("example.com", "alice")), Fraction("b")
    workspace.fractions = [a, b]
    ok, _message, merged = workspace.rename(a, "b")
    assert ok and merged.database_link == a.database_link
    c = Fraction("c", database_link=replace(a.database_link, fraction_uid="different"))
    workspace.fractions.append(c)
    ok, message, _ = workspace.rename(c, "b")
    assert not ok and "different database links" in message
    assert c in workspace.fractions
