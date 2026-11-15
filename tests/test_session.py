"""Session save and restore without Qt (SPEC F18, section 3 "Session")."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

import numpy as np
import pytest
from reader_fixtures import B998, TIMSDP_FILES

from rawtims.branding import SESSION_FORMAT, SESSION_FORMAT_VERSION
from rawtims.fractions import SessionInfo
from rawtims.readers import sniff
from rawtims.session import (
    SessionError,
    load_session,
    looks_like_session,
    save_session,
    session_document,
    session_sha256,
)
from rawtims_gui.workspace import Workspace

GHR1_PB = TIMSDP_FILES["GHR1 230921 F08b-216"]
GHR1_U = TIMSDP_FILES["GHR1 230921F03 U-239"]
EXPORTED_AT = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def _edited_workspace(paths=(B998, GHR1_PB, GHR1_U)) -> Workspace:
    """B998 and the KU GHR1 pair, GHR1 merged by renaming, a Chauvenet rule, two manual toggles,
    r18 and formula changed on U, export-form fields and a mapping edit."""
    workspace = Workspace()
    workspace.open(list(paths))
    ok, _message, ghr1 = workspace.rename(workspace.find("GHR1 230921F01"), "GHR1 230921 F08")
    assert ok and ghr1.pb is not None and ghr1.u is not None
    b998 = workspace.find("13223M02 iz1").pb
    proposal = b998.propose_chauvenet(mapping=workspace.mapping(b998))
    assert proposal.cycles
    b998.apply_rule(proposal)
    b998.toggle_cycles([3], None, False)
    b998.toggle_cycles([10], ["206/204 D"], False)
    ghr1.u.set_setting("r18", 0.00206)
    ghr1.u.set_setting("oxide_formula", "tripoli_java_00dc941")
    ghr1.beaker, ghr1.source_grain, ghr1.sample_weight_mg = "K1", "g12", 0.0021
    ghr1.spike_type, ghr1.spike, ghr1.timezone, ghr1.collector = "535", "ET535", "America/Chicago", "D"
    chosen = {ratio: mapped.to_dict() for ratio, mapped in workspace.mapping(b998).ratios.items()}
    chosen["206Pb/207Pb"] = {"function": "206/207 F", "inverted": False}
    workspace.set_mapping(b998, chosen)
    return workspace


def _restored(path) -> tuple[Workspace, list]:
    state, problems = load_session(path)
    workspace = Workspace()
    problems += workspace.restore(state)
    return workspace, problems


def _copy_fixtures(folder, *paths):
    folder.mkdir(parents=True, exist_ok=True)
    return [shutil.copy2(path, folder / path.name) for path in paths]


def test_round_trip_restores_masks_settings_mappings_fields_and_rows(tmp_path):
    workspace = _edited_workspace()
    path = save_session(workspace.session_state(), tmp_path / "review")
    assert path.name == "review.rawtims"
    restored, problems = _restored(path)
    assert problems == []
    assert [f.fraction_id for f in restored.fractions] == [f.fraction_id for f in workspace.fractions]
    for before, after in zip(workspace.analyses(), restored.analyses()):
        assert after.run.run_id == before.run.run_id and after.run.raw.sha256 == before.run.raw.sha256
        assert np.array_equal(after.included, before.included)
        assert np.array_equal(after.block_included, before.block_included)
        assert after.settings == before.settings and after.history == before.history
        assert restored.mapping_source(after) == workspace.mapping_source(before)
        assert restored.mapping(after).ratios == workspace.mapping(before).ratios
    b998 = restored.find("13223M02 iz1").pb
    assert restored.mapping_source(b998) == "edited" and restored.mapping(b998).ratios["206Pb/207Pb"].key == "206/207 F"
    ghr1 = restored.find("GHR1 230921 F08")
    assert (ghr1.beaker, ghr1.source_grain, ghr1.sample_weight_mg, ghr1.spike_type, ghr1.spike, ghr1.timezone, ghr1.collector) == (
        "K1", "g12", 0.0021, "535", "ET535", "America/Chicago", "D")
    assert ghr1.u.settings.r18 == 0.00206 and ghr1.u.settings.oxide_formula == "tripoli_java_00dc941"
    info = SessionInfo(path.name, session_sha256(path))
    rows_before, left_before = workspace.export_rows(EXPORTED_AT, session_info=info)
    rows_after, left_after = restored.export_rows(EXPORTED_AT, session_info=info)
    assert left_before == left_after
    assert [r.values for r in rows_after] == [r.values for r in rows_before] and len(rows_after) == 2
    assert rows_after[0].values["Raw App Session"] == "review.rawtims"
    assert rows_after[0].values["Raw App Session SHA256"] == session_sha256(path)
    # Saving the restored workspace writes the same document (saved_at aside).
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    assert session_document(restored.session_state(), path, saved_at=stamp) == session_document(workspace.session_state(), path, saved_at=stamp)


def test_saved_json_holds_no_per_cycle_values(tmp_path):
    workspace = _edited_workspace()
    path = save_session(workspace.session_state(), tmp_path / "s.rawtims")
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["format"] == SESSION_FORMAT and document["format_version"] == SESSION_FORMAT_VERSION
    assert document["saved_at"].endswith("+00:00")
    assert path.stat().st_size < 40_000

    def walk(node):
        if isinstance(node, dict):
            assert "values" not in node and "cycles" not in node.get("raw", {})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            # No array of numbers as long as a run (cycle values); cycle indices only appear inside histories.
            assert not (len(node) >= 90 and all(isinstance(x, float) for x in node))
            for value in node:
                walk(value)

    walk(document)
    run = document["runs"][0]
    assert set(run["raw"]) == {"name", "relative", "absolute", "size", "sha256", "format", "format_version"}
    assert run["raw"]["relative"].endswith(B998.name)


def test_missing_and_changed_files_are_problems_and_the_runs_are_not_opened(tmp_path):
    data = tmp_path / "data"
    b998, pb, u = _copy_fixtures(data, B998, GHR1_PB, GHR1_U)
    workspace = _edited_workspace((b998, pb, u))
    path = save_session(workspace.session_state(), tmp_path / "s.rawtims")
    saved = json.loads(path.read_text(encoding="utf-8"))
    b998.unlink()
    with open(u, "ab") as stream:
        stream.write(b"\n")  # one more byte: the SHA-256 differs
    restored, problems = _restored(path)
    kinds = {(p.fraction_id, p.element): p.kind for p in problems}
    assert kinds == {("13223M02 iz1", "Pb"): "missing", ("GHR1 230921 F08", "U"): "changed"}
    assert all("the run is not opened" in p.message for p in problems)
    b998_fraction, ghr1 = restored.find("13223M02 iz1"), restored.find("GHR1 230921 F08")
    assert b998_fraction.pb is None and ghr1.u is None and ghr1.pb is not None
    assert ghr1.beaker == "K1"  # the fraction and its fields survive
    # Neither fraction is exported (exporting only the Pb block would silently change GHR1).
    rows, left_out = restored.export_rows(EXPORTED_AT)
    assert rows == [] and {fid for fid, _ in left_out} == {"13223M02 iz1", "GHR1 230921 F08"}
    assert restored.fraction_status(ghr1)[0] == "attention"
    # A run opened later does not take the slot of a missing one; a merge into it is refused.
    ok, message, _holder = restored.rename(b998_fraction, "GHR1 230921 F08")
    assert not ok and "could not open" in message
    # Saving again writes the missing records back unchanged.
    again = save_session(restored.session_state(), tmp_path / "again.rawtims")
    resaved = json.loads(again.read_text(encoding="utf-8"))
    assert resaved["runs"] == saved["runs"] and resaved["fractions"] == saved["fractions"]


def test_replay_mismatch_is_a_problem_and_nothing_changes_silently(tmp_path):
    workspace = _edited_workspace()
    path = save_session(workspace.session_state(), tmp_path / "s.rawtims")
    document = json.loads(path.read_text(encoding="utf-8"))
    b998 = next(r for r in document["runs"] if r["raw"]["name"] == B998.name)
    toggle = next(op for op in b998["history"] if op["op"] == "toggle_cycles")
    toggle["changed"] = toggle["changed"][:-1]  # the recorded flags no longer match what replay changes
    path.write_text(json.dumps(document), encoding="utf-8")
    restored, problems = _restored(path)
    assert [(p.kind, p.fraction_id, p.element) for p in problems] == [("replay", "13223M02 iz1", "Pb")]
    assert "does not replay exactly" in problems[0].message
    assert restored.find("13223M02 iz1").pb is None and len(restored.analyses()) == 2

    # A tampered mask digest is caught too.
    document = json.loads(save_session(workspace.session_state(), tmp_path / "t.rawtims").read_text(encoding="utf-8"))
    document["runs"][0]["mask_sha256"] = "0" * 64
    (tmp_path / "t.rawtims").write_text(json.dumps(document), encoding="utf-8")
    _restored_t, problems = _restored(tmp_path / "t.rawtims")
    assert [p.kind for p in problems] == ["replay"]


@pytest.mark.parametrize(("change", "message"), [
    ({"format": "UPbRPy reduction project"}, "is not a session file"),
    ({"format_version": SESSION_FORMAT_VERSION + 1}, "saved by a newer version"),
    ({"format_version": "1"}, "is not a version number"),
])
def test_unknown_format_or_newer_version_is_rejected(tmp_path, change, message):
    document = session_document(Workspace().session_state(), None)
    document.update(change)
    path = tmp_path / "x.rawtims"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SessionError, match=message):
        load_session(path)


def test_not_json_is_rejected(tmp_path):
    path = tmp_path / "x.rawtims"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(SessionError, match="not a readable JSON file"):
        load_session(path)
    assert not looks_like_session(path)


def test_relative_paths_resolve_after_moving_session_and_raw_files_together(tmp_path):
    first = tmp_path / "first"
    files = _copy_fixtures(first / "data", B998, GHR1_PB, GHR1_U)
    workspace = _edited_workspace(files)
    save_session(workspace.session_state(), first / "s.rawtims")
    moved = shutil.move(str(first), str(tmp_path / "second"))
    restored, problems = _restored(f"{moved}/s.rawtims")
    assert problems == [] and len(restored.analyses()) == 3
    assert all(a.run.raw.path.startswith(moved) for a in restored.analyses())
    rows, _ = restored.export_rows(EXPORTED_AT)
    expected, _ = workspace.export_rows(EXPORTED_AT)
    assert [r.values for r in rows] == [r.values for r in expected]


def test_a_same_named_file_next_to_the_session_is_found(tmp_path):
    files = _copy_fixtures(tmp_path / "elsewhere", B998)
    workspace = Workspace()
    workspace.open(files)
    (tmp_path / "a").mkdir()
    save_session(workspace.session_state(), tmp_path / "a" / "s.rawtims")
    shutil.move(str(files[0]), str(tmp_path / "a" / B998.name))
    restored, problems = _restored(tmp_path / "a" / "s.rawtims")
    assert problems == [] and restored.analyses()[0].run.raw.path == str(tmp_path / "a" / B998.name)


def test_session_files_are_recognised_by_content(tmp_path):
    path = save_session(Workspace().session_state(), tmp_path / "s.rawtims")
    assert looks_like_session(path)
    renamed = path.rename(tmp_path / "s.txt")
    assert looks_like_session(renamed)
    assert "saved session" in sniff(renamed).reason  # a folder import names it instead of a parse error
    assert not looks_like_session(B998)


def test_absolute_path_is_used_when_relative_file_is_gone(tmp_path):
    workspace = Workspace()
    workspace.open([B998])
    path = save_session(workspace.session_state(), tmp_path / "s.rawtims")
    document = json.loads(path.read_text())
    document["runs"][0]["raw"]["relative"] = "missing/data.xls"
    path.write_text(json.dumps(document))
    restored, problems = _restored(path)
    assert not problems and restored.analyses()[0].run.raw.path == str(B998)


def test_content_detection_does_not_depend_on_key_order_or_a_short_header(tmp_path):
    document = session_document(Workspace().session_state(), None)
    document = {"comment": "x" * 5000, **document}
    path = tmp_path / "large-header.json"
    path.write_text(json.dumps(document))
    assert looks_like_session(path)


def test_failed_atomic_replace_leaves_the_previous_session_intact(tmp_path, monkeypatch):
    from rawtims import session

    state = Workspace().session_state()
    path = save_session(state, tmp_path / "s.rawtims")
    before = path.read_bytes()

    def fail_replace(*args):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(session.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        save_session(state, path)
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s.rawtims"]


@pytest.mark.parametrize("key,value", [("runs", {}), ("fractions", {}),
                                        ("runs", [{"element": "Pb"}])])
def test_malformed_session_structure_has_a_clear_error(tmp_path, key, value):
    document = session_document(Workspace().session_state(), None)
    document[key] = value
    path = tmp_path / "bad.rawtims"
    path.write_text(json.dumps(document))
    with pytest.raises(SessionError, match="must be a list|without a run_id"):
        load_session(path)


def test_changed_relative_file_is_not_silently_bypassed_by_absolute_copy(tmp_path):
    workspace = Workspace()
    workspace.open([B998])
    path = save_session(workspace.session_state(), tmp_path / "s.rawtims")
    document = json.loads(path.read_text())
    relative = tmp_path / "data.xls"
    relative.write_bytes(b"a changed raw file")
    document["runs"][0]["raw"]["relative"] = relative.name
    path.write_text(json.dumps(document))
    restored, problems = _restored(path)
    assert [p.kind for p in problems] == ["changed"]
    assert problems[0].path == str(relative)
    assert restored.analyses() == []


def test_undone_operations_are_restored_and_can_be_redone(tmp_path):
    workspace = _edited_workspace()
    analysis = workspace.find("GHR1 230921 F08").u
    analysis.toggle_cycles([5], None, False)
    included = analysis.included.copy()
    analysis.undo()
    analysis.undo()  # Undo the oxide formula too; replay must restore settings at the cursor.
    path = save_session(workspace.session_state(), tmp_path / "s.rawtims")
    restored, problems = _restored(path)
    assert not problems
    after = restored.find("GHR1 230921 F08").u
    assert after.settings == analysis.settings
    assert after.history == analysis.history
    assert after.redo_history == analysis.redo_history and after.can_redo
    np.testing.assert_array_equal(after.included, analysis.included)
    after.redo()
    after.redo()
    np.testing.assert_array_equal(after.included, included)
    assert after.settings.oxide_formula == "tripoli_java_00dc941"
    assert not after.can_redo


def test_a_mismatch_in_undone_history_is_also_reported(tmp_path):
    workspace = _edited_workspace()
    analysis = workspace.analyses()[0]
    analysis.toggle_cycles([5], None, False)
    analysis.undo()
    path = save_session(workspace.session_state(), tmp_path / "s.rawtims")
    document = json.loads(path.read_text())
    document["runs"][0]["redo_history"][0]["changed"] = []
    path.write_text(json.dumps(document))
    restored, problems = _restored(path)
    assert [p.kind for p in problems] == ["replay"]
    assert restored.find("13223M02 iz1").pb is None
