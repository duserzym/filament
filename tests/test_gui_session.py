"""Session workflows, with all dialog answers injected and offscreen rendering."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6 import QtCore, QtGui, QtWidgets
from reader_fixtures import B998, TIMSDP_FILES

from rawtims.contract import read_csv
from rawtims.session import save_session, session_sha256
from rawtims_gui import main as gui
from rawtims_gui import recovery
from rawtims_gui.studio.theme import build_application
from rawtims_gui.workspace import Workspace

PB = TIMSDP_FILES["GHR1 230921 F08b-216"]
U = TIMSDP_FILES["GHR1 230921F03 U-239"]


@pytest.fixture
def windows(qt_settings_folder, monkeypatch, tmp_path):
    app = build_application(["test"], theme_mode="light")
    gui.app_settings().clear()
    monkeypatch.setenv(recovery.CACHE_ENV, str(tmp_path / "cache"))
    made = []

    def create():
        w = gui.MainWindow(restore_geometry=False)
        w.unsaved_prompt = lambda _name: "discard"
        w.resize(gui.DEFAULT_SIZE)
        w.show()
        made.append(w)
        return w

    yield create
    for w in made:
        w.unsaved_prompt = lambda _name: "discard"
        w.close()
        w.deleteLater()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    gui.app_settings().clear()


def wait_until(predicate, seconds=8):
    end = time.monotonic() + seconds
    while not predicate() and time.monotonic() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.005)
    assert predicate(), "GUI operation did not finish before its deadline"


def edit_session(w):
    w.open_paths([B998, PB, U], synchronous=True)
    assert w.rename_fraction(w.workspace.find("GHR1 230921F01"), "GHR1 230921 F08")
    b = w.workspace.find("13223M02 iz1")
    w.select_run(b, "Pb")
    assert w.preview_rule().cycles
    w.apply_preview()
    w.request_toggle("206/204 D", [3])
    w.request_toggle("206/204 D", [10])
    w.corrections_panel.choose("206Pb/207Pb", "206/207 F")
    g = w.workspace.find("GHR1 230921 F08")
    w.select_run(g, "U")
    w.set_analysis_setting("r18", 0.00206)
    p = w.corrections_panel
    p.formula.setCurrentIndex(p.formula.findData("tripoli_java_00dc941"))
    w.set_workflow_step("Export")
    for attr, value in (("sample", "GHR1"), ("beaker", "K1"), ("source_grain", "g12"),
                        ("source_spot", "s3"), ("source_mount", "M7"), ("aliquot", "A"),
                        ("sample_weight_mg", "0.0021"), ("spike_weight_g", "0.0125"),
                        ("spike_type", "535"), ("spike", "ET535"), ("collector", "D"),
                        ("timezone", "America/Chicago")):
        w.export_panel.set_field(attr, value)
    return w


def rows_without_timestamp(path):
    return [{k: v for k, v in row.values.items() if k != "Exported At"} for row in read_csv(path)]


def test_gui_round_trip_restores_masks_settings_mapping_form_and_export(windows, tmp_path):
    before = edit_session(windows())
    path = before.save_session_as(tmp_path / "review.rawtims")
    assert path and not before.is_modified() and "Edited" not in before.windowTitle()
    first_csv = before.save_contract_csv(str(tmp_path / "before.csv"))
    after = windows()
    after.open_paths([path], synchronous=True)
    assert not after.is_modified() and after.session_info() == before.session_info()
    assert after.skipped_list.count() == 0
    for a, b in zip(before.workspace.analyses(), after.workspace.analyses()):
        np.testing.assert_array_equal(a.included, b.included)
        np.testing.assert_array_equal(a.block_included, b.block_included)
        assert a.settings == b.settings and a.history == b.history
        assert before.workspace.mapping(a).ratios == after.workspace.mapping(b).ratios
        assert before.workspace.mapping_source(a) == after.workspace.mapping_source(b)
    g = after.workspace.find("GHR1 230921 F08")
    after.select_run(g, "U")
    after.set_workflow_step("Export")
    assert after.export_panel.row_cells() == before.export_panel.row_cells() | {
        "Exported At": after.export_panel.row_cells().get("Exported At", "")}
    second_csv = after.save_contract_csv(str(tmp_path / "after.csv"))
    assert rows_without_timestamp(first_csv) == rows_without_timestamp(second_csv)
    assert len(rows_without_timestamp(second_csv)) == 2
    assert all(row["Raw App Session SHA256"] == session_sha256(path) for row in rows_without_timestamp(second_csv))


def test_empty_project_statistics_setting_is_modified_and_saved(windows, tmp_path):
    w = windows()
    w.set_analysis_setting("stat_mode", "geometric")
    assert w.is_modified() and w.save_action.isEnabled()
    assert w.session_state_name() == "untitled"
    path = w.save_session_as(tmp_path / "empty-project.rawtims")
    assert not w.is_modified()
    after = windows()
    assert after.open_session(path, synchronous=True)
    assert after.corrections_panel.stat_mode.currentData() == "geometric"
    after.open_paths([B998], synchronous=True)
    assert after.analysis.settings.stat_mode == "geometric"


def test_recent_sessions_persist_are_limited_deduplicated_and_prune_missing(windows, tmp_path):
    w = windows()
    w.open_paths([B998], synchronous=True)
    paths = [w.save_session_as(tmp_path / f"review{i}.rawtims") for i in range(10)]
    assert w.recent_sessions() == [str(p) for p in reversed(paths[2:])]
    other = windows()
    assert other.recent_sessions() == w.recent_sessions()
    assert other.open_recent(str(paths[3]), synchronous=True)
    assert other.recent_sessions()[0] == str(paths[3])
    paths[3].unlink()
    other._rebuild_recent_menu()
    assert str(paths[3]) not in other.recent_sessions()
    assert not other.open_recent(str(paths[3]), synchronous=True)
    other.clear_recent()
    assert other.recent_sessions() == []


@pytest.mark.parametrize("action", ["new", "open", "close"])
@pytest.mark.parametrize("answer", ["save", "discard", "cancel"])
def test_unsaved_prompt_injected_for_replacing_and_closing(windows, tmp_path, monkeypatch, action, answer):
    w = windows()
    w.open_paths([B998], synchronous=True)
    original = w.analysis
    target = save_session(Workspace().session_state(), tmp_path / "empty.rawtims")
    saved = tmp_path / "saved.rawtims"
    asked = []
    w.unsaved_prompt = lambda name: asked.append(name) or answer
    monkeypatch.setattr(w, "save_session_as", lambda: w._write_session(saved))
    if action == "new":
        ok = w.new_session()
    elif action == "open":
        ok = w.open_session(target, synchronous=True)
    else:
        ok = w.close()
    assert asked == ["Untitled"]
    assert bool(ok) == (answer != "cancel")
    assert saved.exists() == (answer == "save")
    if answer == "cancel":
        assert w.analysis is original and w.is_modified() and w.isVisible()
    elif action != "close":
        assert w.workspace.analyses() == []


def test_cancelled_save_keeps_session_open(windows, monkeypatch):
    w = windows()
    w.open_paths([B998], synchronous=True)
    w.unsaved_prompt = lambda _: "save"
    monkeypatch.setattr(w, "save_session_as", lambda: None)
    assert not w.new_session() and w.analysis is not None


def test_session_export_columns_and_save_first(windows, tmp_path, monkeypatch):
    w = windows()
    w.open_paths([B998], synchronous=True)
    panel = w.export_panel
    assert "Raw App Session" not in panel.row_cells()
    assert "not saved" in panel.session_note.text()
    path = w.save_session_as(tmp_path / "s.rawtims")
    assert panel.row_cells()["Raw App Session"] == path.name
    assert panel.row_cells()["Raw App Session SHA256"] == session_sha256(path)
    assert not panel.session_first_button.isVisibleTo(panel)
    w.request_toggle("206/204 D", [3])
    assert "Edited" in w.windowTitle() and w.isWindowModified()
    assert "Raw App Session" not in panel.row_cells()
    assert "unsaved changes" in panel.session_note.text()
    w.undo()
    assert not w.is_modified() and panel.row_cells()["Raw App Session"] == path.name
    w.redo()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "export.csv"), ""))
    panel.session_first_button.click()
    rows = rows_without_timestamp(tmp_path / "export.csv")
    assert rows[0]["Raw App Session SHA256"] == session_sha256(path)
    assert not w.is_modified()
    path.write_text(path.read_text() + "\n")
    w._refresh_export()
    assert "Raw App Session" not in panel.row_cells()
    assert "changed or is missing" in panel.session_note.text()
    assert panel.session_first_button.isVisibleTo(panel)
    assert w.session_info(verify=True) is None


def test_problems_are_nonmodal_and_failed_open_keeps_current_session(windows, tmp_path):
    w = windows()
    w.open_paths([B998], synchronous=True)
    path = w.save_session_as(tmp_path / "s.rawtims")
    doc = json.loads(path.read_text())
    doc["runs"][0]["mask_sha256"] = "0" * 64
    path.write_text(json.dumps(doc))
    assert w.open_session(path, synchronous=True)
    assert w.workspace.analyses() == []
    assert w.skipped_list.count() == 1 and "does not replay exactly" in w.skipped_list.item(0).text()
    assert w.skipped_button.isVisible()
    doc["format_version"] = 100
    path.write_text(json.dumps(doc))
    old = w.workspace
    assert not w.open_session(path, synchronous=True)
    assert w.workspace is old and "newer version" in w.skipped_list.item(0).text()


def test_open_files_and_drop_route_sessions_by_content(windows, tmp_path, monkeypatch):
    source = windows()
    source.open_paths([B998], synchronous=True)
    path = source.save_session_as(tmp_path / "s.rawtims").rename(tmp_path / "renamed.json")
    w = windows()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileNames", lambda *a: ([str(path)], ""))
    w.choose_files()
    wait_until(lambda: not w._workers)
    assert w.session_path == path and len(w.workspace.analyses()) == 1
    other = windows()
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(path))])
    event = QtGui.QDropEvent(QtCore.QPointF(50, 50), QtCore.Qt.DropAction.CopyAction, mime,
                            QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
    other.dropEvent(event)
    wait_until(lambda: not other._workers)
    assert event.isAccepted() and other.session_path == path


def test_cli_open_session_offscreen(tmp_path, windows, monkeypatch):
    workspace = Workspace()
    workspace.open([B998])
    path = save_session(workspace.session_state(), tmp_path / "cli.rawtims")
    output = tmp_path / "cli.png"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-m", "rawtims_gui.main", "--open", str(path),
                             "--theme", "light", "--export", "png", str(output)],
                            env=env, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    from PIL import Image
    assert Image.open(output).size == (1280, 800)
    observed = []

    def inspect_window(window, output_path):
        observed.append(window)
        assert window.session_path == path
        assert window.analysis.run.raw.name == B998.name
        assert not window.is_modified()
        return True

    monkeypatch.setattr(gui, "export_window", inspect_window)
    assert gui.main(["--open", str(path), "--export", "png", str(output)]) == 0
    assert len(observed) == 1
    observed[0].deleteLater()


def test_debounced_recovery_and_nonmodal_next_launch_offer(windows, tmp_path, monkeypatch):
    w = windows()
    w._autosave_timer.setInterval(30)
    w.open_paths([B998], synchronous=True)
    path = recovery.recovery_path()
    assert not path.exists() and w._autosave_timer.isActive()
    wait_until(path.exists)
    assert path.parent == tmp_path / "cache" / "recovery"
    assert not list(tmp_path.glob("*.rawtims"))
    # Simulate the previous process having exited, without sharing its live PID.
    abandoned = recovery.recovery_path(987654321)
    path.rename(abandoned)
    monkeypatch.setattr(recovery, "_process_running", lambda pid: pid == os.getpid())
    other = windows()
    assert other.check_recovery().path == abandoned
    assert other.recovery_bar.isVisible() and "Restore" in other.recovery_label.text()
    assert other.restore_recovery()
    assert other.is_modified() and len(other.workspace.analyses()) == 1
    assert not abandoned.exists() and path.exists()
    other.save_session_as(tmp_path / "recovered.rawtims")
    assert not path.exists() and not other.recovery_bar.isVisible()
    w._autosave_timer.stop()
