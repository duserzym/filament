"""Offscreen selection/confirmation and worker behavior."""
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("PySide6")
from PySide6 import QtCore, QtGui
from test_upbdb import candidate, client

from rawtims.fractions import Fraction
from rawtims.upbdb import MatchResult
from rawtims_gui.database_dialog import LinkDialog
from rawtims_gui.export_panel import ExportPanel
from rawtims_gui.studio.theme import THEMES, active_theme, build_application


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_candidate_details_readable_steps_overrides_outcomes_and_theme(tmp_path, mode):
    app = build_application(["test"], theme_mode=mode)
    c, _ = client(tmp_path)
    choice = candidate()
    choice.batch["steps"] += [
        {"id": code, "ordinal": n, "method_code": code, "parameters": {}}
        for n, code in enumerate(("SP-TIMS-LEACH", "SP-TIMS-WASH", "SP-TIMS-DISS", "SP-TIMS-CHLOR",
                                  "SP-TIMS-COL", "SP-TIMS-LOAD"), 5)
    ] + [{"id": "custom", "ordinal": 11, "method_code": "CUSTOM", "method_name": "Lab preparation"},
         {"id": "unknown", "ordinal": 12, "method_code": "UNKNOWN"}]
    dialog = LinkDialog(c, "AH1-gc1 z1")
    dialog.show_result(MatchResult([choice]))
    dialog.table.selectRow(0)
    dialog.show()
    app.processEvents()
    text = dialog.summary.toPlainText()
    assert text.startswith("AH1-gc1 z1\nK9 · Krogh · 2026-11-14 · spiked")
    assert "Sources\nS · S 1 · G1 — half" in text
    assert "1. Anneal (this capsule) — 900 °C, 48 h" in text
    assert "2. Chemical abrasion (this capsule) — 190 °C, 10 h, 29 M HF ⚠ dissolved in ca" in text
    assert "3. Spike (this capsule) — ET535/master/v3, 1.23457e-05 g" in text
    for number, name in enumerate(("Leach", "Wash", "Dissolution", "Chloride conversion",
                                   "Column chemistry", "Load", "Lab preparation", "UNKNOWN"), 4):
        assert f"{number}. {name}" in text
    assert "HCl" not in text  # The skipped batch wash is also omitted from export.
    assert "SP-TIMS-" not in text
    header = dialog.summary.document().find("AH1-gc1 z1").charFormat()
    assert header.fontWeight() >= QtGui.QFont.Weight.Bold
    assert dialog.summary.document().find("half").charFormat().fontItalic()
    outcome = dialog.summary.document().find("⚠ dissolved in ca").charFormat()
    assert outcome.foreground().color().name() == active_theme().danger
    assert dialog.summary.document().find("Sources").charFormat().foreground().color().name() == active_theme().muted
    assert dialog.summary.isReadOnly()
    assert dialog.summary.horizontalScrollBar().maximum() == 0
    assert dialog.table.viewport().height() >= 4 * dialog.table.verticalHeader().defaultSectionSize()
    assert dialog.width() <= 900 and dialog.height() <= 640
    if mode == "dark":
        html = dialog.summary.toHtml()
        assert THEMES["light"].text not in html and THEMES["light"].muted not in html
        assert active_theme().text in html
    dialog.close()
    app.processEvents()


def test_candidate_details_empty_sections_local_read_time_uid_copy_and_cache(tmp_path, monkeypatch):
    app = build_application(["test"], theme_mode="light")
    c, _ = client(tmp_path)
    choice = candidate()
    choice.fraction.update(id="01234567-89ab-cdef-0123-456789abcdef", sources=[])
    choice.batch = {}
    choice.chemistry_message = "No chemistry access (403)."
    choice.read_at = "2026-11-20T15:49:27.837970+00:00"
    read_at = datetime.fromisoformat(choice.read_at)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (read_at + timedelta(minutes=3)).astimezone(tz or UTC)

    monkeypatch.setattr("rawtims.upbdb.datetime", Clock)
    dialog = LinkDialog(c, "AH1-gc1 z1")
    dialog.show_result(MatchResult([choice], offline=True, fetched_at=choice.read_at))
    dialog.table.selectRow(0)
    text = dialog.summary.toPlainText()
    assert "No LA source (sample-only fraction)" in text
    assert "No spike recorded yet" in text and "No chemistry steps recorded" in text
    assert f"Read {read_at.astimezone():%Y-%m-%d %H:%M} (3 minutes ago) · from offline cache" in text
    assert "No chemistry access (403)." in text
    assert "Fraction UID: 01234567" in text and choice.fraction["id"] not in text
    uid = dialog.summary.document().find("01234567")
    assert uid.charFormat().toolTip() == choice.fraction["id"]
    dialog.summary.anchorClicked.emit(QtCore.QUrl("copy-uid"))
    assert app.clipboard().text() == choice.fraction["id"]
    dialog.close()
    app.processEvents()


def test_candidate_details_escape_database_text_and_leave_equal_override_unmarked(tmp_path):
    app = build_application(["test"], theme_mode="light")
    c, _ = client(tmp_path)
    choice = candidate()
    choice.sample["name"] = "Sample <test> & more"
    choice.batch["fraction_step_records"][0]["parameters"]["duration_h"] = 60
    choice.fraction["sources"][0]["fragment_note"] = "<img src='not-an-image'>"
    dialog = LinkDialog(c, "AH1-gc1 z1")
    dialog.show_result(MatchResult([choice]))
    dialog.table.selectRow(0)
    text = dialog.summary.toPlainText()
    assert text.startswith("Sample <test> & more z1")
    assert "1. Anneal — 900 °C, 60 h" in text
    assert "<img src='not-an-image'>" in text and "<img " not in dialog.summary.toHtml()
    dialog.close()
    app.processEvents()


def test_dialog_requires_explicit_row_selection(tmp_path):
    app = build_application(["test"], theme_mode="light")
    c, _fake = client(tmp_path)
    fraction = Fraction("AH1-gc1 z1", sample="AH1-gc1 z1")
    dialog = LinkDialog(c, fraction.fraction_id, fraction=fraction)
    assert not dialog.link_button.isEnabled()
    dialog.show_result(MatchResult([candidate()]))
    assert not dialog.link_button.isEnabled() and not dialog.table.selectionModel().selectedRows()
    dialog.table.selectRow(0)
    app.processEvents()
    assert dialog.link_button.isEnabled()
    assert "ET535/master/v3" in dialog.summary.toPlainText()
    assert dialog.link is None
    assert fraction.database_link is None and fraction.sample == "AH1-gc1 z1"
    dialog.confirm()
    assert dialog.link.fraction_uid == "f1" and dialog.link.confirmed_by == "alice"
    assert dialog.match_result.candidates[0].read_at == dialog.link.database_read_at
    assert fraction.database_link == dialog.link and fraction.sample == "AH1-gc1"
    dialog.deleteLater()


@pytest.mark.parametrize("second_project", ["P2", "P1"])
def test_same_named_candidates_show_project_code_and_sample_uuid_tail(tmp_path, second_project):
    app = build_application(["test"], theme_mode="light")
    c, _fake = client(tmp_path)
    choices = [candidate(), candidate()]
    for choice, project, tail in zip(choices, ("P1", second_project), ("12345678", "87654321")):
        choice.sample.update(name="KG5", id="00000000-0000-0000-0000-0000" + tail, project={"code": project})
    dialog = LinkDialog(c, "KG5 z1")
    dialog.show_result(MatchResult(choices))
    assert dialog.table.item(0, 0).text() == "KG5 / P1 [12345678]"
    assert dialog.table.item(1, 0).text() == f"KG5 / {second_project} [87654321]"
    assert choices[0].sample["id"] in dialog.table.item(0, 0).toolTip()
    dialog.close()
    app.processEvents()


def test_dialog_zero_results_refusal_and_edits_invalidate(tmp_path):
    app = build_application(["test"], theme_mode="light")
    c, _fake = client(tmp_path)
    dialog = LinkDialog(c, "unparsed")
    assert not dialog.sample.text() and not dialog.name.text()
    dialog.show_result(MatchResult(reason="no_fraction"))
    assert "No active fraction" in dialog.message.text()
    assert not dialog.link_button.isVisible() and not dialog.link_button.isEnabled()
    dialog.show_result(MatchResult([candidate()]))
    dialog.table.selectRow(0)
    assert dialog.link_button.isEnabled()
    dialog.sample.setText("different")
    assert not dialog.link_button.isEnabled() and dialog.table.rowCount() == 0
    assert dialog.maximumWidth() <= 900 and dialog.maximumHeight() <= 640
    dialog.close()
    app.processEvents()


def test_lookup_runs_off_gui_thread_and_can_cancel(tmp_path):
    app = build_application(["test"], theme_mode="light")
    c, fake = client(tmp_path)
    gui_thread = threading.get_ident()
    called = []
    def transport(*args):
        called.append(threading.get_ident())
        return fake(*args)
    c.transport = transport
    dialog = LinkDialog(c, "AH1-gc1 z1")
    dialog.lookup()
    end = time.monotonic() + 5
    while dialog.busy and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    assert not dialog.busy and len(dialog.match_result.candidates) == 1
    assert called and all(t != gui_thread for t in called)
    dialog.reject()
    assert dialog.cancelled.is_set() and dialog.link is None
    app.processEvents()


def test_export_panel_link_display_warning_and_unlink(tmp_path):
    app = build_application(["test"], theme_mode="light")
    panel = ExportPanel()
    f = Fraction("AH1-gc1 z1", beaker="mine", database_link=candidate().confirm("example.com", "alice"))
    panel.fraction = f
    panel._refresh_database()
    assert "Linked: AH1-gc1 z1" in panel.database_detail.text()
    assert "your value is kept" in panel.database_detail.text()
    edits = []
    panel.fieldEdited.connect(lambda attribute, value: edits.append((attribute, value)))
    panel.database_unlink.click()
    assert edits == [("database_link", None)]
    panel.close()
    app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_cancel_during_http_does_not_publish_candidates(tmp_path):
    app = build_application(["test"], theme_mode="light")
    c, fake = client(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def transport(*args):
        entered.set()
        assert release.wait(5)
        return fake(*args)
    c.transport = transport
    dialog = LinkDialog(c, "AH1-gc1 z1")
    dialog.lookup()
    assert entered.wait(2)
    dialog.reject()
    assert dialog.cancelled.is_set() and dialog.link is None
    release.set()
    end = time.monotonic() + 5
    while dialog.busy and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    assert not dialog.busy and not dialog.match_result.candidates
    assert not c.cache["lookups"]
