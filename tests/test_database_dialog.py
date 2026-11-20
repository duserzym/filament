"""Offscreen selection/confirmation and worker behavior."""
import threading
import time

import pytest

pytest.importorskip("PySide6")
from PySide6 import QtCore
from test_upbdb import candidate, client

from rawtims.fractions import Fraction
from rawtims.upbdb import MatchResult
from rawtims_gui.database_dialog import LinkDialog
from rawtims_gui.export_panel import ExportPanel
from rawtims_gui.studio.theme import build_application


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
