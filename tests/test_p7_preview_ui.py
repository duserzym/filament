"""P7 session-only preview and synthetic desktop acceptance in both lab themes."""

import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import test_p2_reports_ui as p2
from PySide6 import QtWidgets
from reader_fixtures import SYNTHETIC_PB
from test_p7_preview import components, synthetic_xml

from rawtims.contract import csv_text
from rawtims.exports import clipboard_text, cycles_csv_text
from rawtims.session import SessionError, load_session, save_session
from rawtims_gui.fractionation_preview import PRESENTATION_KEY, FractionationPreview


@pytest.fixture
def window(monkeypatch, tmp_path):
    yield from p2.window.__wrapped__(monkeypatch, tmp_path)


def populate(dialog, tmp_path):
    path = tmp_path / "synthetic-tracer.xml"
    path.write_bytes(synthetic_xml())
    dialog.import_xml(path)
    for (value, sigma), estimate in zip(
        dialog.components, components().__dict__.values()
    ):
        value.setText(str(estimate.value))
        sigma.setText(str(estimate.sigma))


def test_preview_batch_undo_roundtrip_and_all_export_boundaries(window, tmp_path):
    """OGTripoli/source/TripoliWorkProduct.cs:1074,2332; forms/fmrMainTripoli.cs:7216.
    D1 extension preserves originals instead of overwriting correction results.
    """
    a = window.analysis
    window.workspace.open([SYNTHETIC_PB])
    stamp = datetime(2026, 11, 26, tzinfo=UTC)

    def outputs():
        return (
            csv_text(
                [
                    window.workspace.fraction_row(f, stamp)
                    for f in window.workspace.fractions
                ]
            ),
            [clipboard_text(f) for f in window.workspace.fractions],
            [cycles_csv_text(run) for run in window.workspace.analyses()],
            [copy.deepcopy(run.history) for run in window.workspace.analyses()],
        )

    before = outputs()
    original = a.run.values.copy()
    dialog = FractionationPreview(window)
    populate(dialog, tmp_path)
    dialog.create_current()
    assert len(dialog.book.visible()) == 1, dialog.notice.text()
    frozen = copy.deepcopy(dialog.book.data["records"][0])
    assert (
        frozen["data"]["reduction_parameters_sha256"]
        == a.run.reduction_parameters.sha256
    )
    assert dialog.table.rowCount() == 4
    assert "absolute 1σ" in dialog.report.toPlainText()
    dialog.create_batch()
    assert len(dialog.book.data["records"]) == 3
    assert dialog.book.data["records"][0] == frozen
    dialog.undo()
    assert len(dialog.book.visible()) == 2
    dialog.redo()
    assert len(dialog.book.visible()) == 3
    # Active selection may change; applied XML/result stays frozen.
    dialog.tracers.setCurrentIndex(0)
    dialog.create_current()
    assert dialog.book.data["records"][0] == frozen
    assert dialog.book.data["records"][3]["data"]["result"]["values"][0] == 0
    assert outputs() == before
    np.testing.assert_array_equal(a.run.values, original)
    # A later review edit makes a distinct revision, never a live mutation of the old one.
    a.toggle_cycles([0], a.keys, False)
    edited_outputs = outputs()
    dialog.create_current()
    assert dialog.book.data["records"][0] == frozen
    assert (
        dialog.book.data["records"][-1]["data"]["mask_sha256"]
        != frozen["data"]["mask_sha256"]
    )
    assert outputs() == edited_outputs
    a.undo()
    assert outputs() == before
    path = tmp_path / "synthetic-preview-session.json"
    path = save_session(window.workspace.session_state(), path)
    state, problems = load_session(path)
    assert not problems
    assert state.presentation[PRESENTATION_KEY] == dialog.book.to_dict()
    window.workspace.restore(state)
    window.select_run(next(f for f in window.workspace.fractions if f.u), "U")
    reopened = FractionationPreview(window)
    assert reopened.book.to_dict() == dialog.book.to_dict()
    assert outputs() == before
    reopened.close()
    dialog.close()


def test_tampered_preview_in_session_fails_validation(window, tmp_path):
    """Derived revisions are inert but hash-checked on native save/reopen."""
    dialog = FractionationPreview(window)
    dialog.create_current()  # explicit identity/no-tracer record
    path = save_session(
        window.workspace.session_state(), tmp_path / "synthetic-preview"
    )
    document = json.loads(path.read_text())
    document["presentation"][PRESENTATION_KEY]["records"][0]["data"]["result"][
        "values"
    ][0] = 9
    path.write_text(json.dumps(document))
    with pytest.raises(SessionError, match="preview.*hash"):
        load_session(path)
    dialog.close()


def test_failed_preview_does_not_replace_previous_and_requires_u_components(
    window, tmp_path
):
    """OGTripoli/source/TripoliWorkProduct.cs:1124-1142 requires U components."""
    dialog = FractionationPreview(window)
    path = tmp_path / "synthetic.xml"
    path.write_bytes(synthetic_xml())
    dialog.import_xml(path)
    dialog.create_current()
    assert not dialog.book.data["records"]
    assert "Enter blank_pg" in dialog.report.toPlainText()
    assert "refused" in dialog.notice.text()
    assert window.analysis.history == []
    assert any(
        "Fractionation preview" in a.text() for a in window.diagnostics_menu.actions()
    )
    dialog.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,height", [(1280, 800), (1440, 900)])
def test_p7_preview_layout(window, tmp_path, theme, width, height):
    """No Tripoli screenshot oracle; explicit lab-layout acceptance follows P6 pattern."""
    window.set_theme(theme)
    window.resize(width, height)
    dialog = FractionationPreview(window)
    populate(dialog, tmp_path)
    dialog.create_current()
    dialog.show()
    folder = Path(os.environ.get("RAWTIMS_P7_SHOTS", tmp_path))
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
        assert dialog.width() < width and dialog.height() < height
        assert dialog.minimumSizeHint().width() < width
        assert dialog.minimumSizeHint().height() < height
        assert window.width() == width and window.height() == height
        assert window.plot_wall.horizontalScrollBar().maximum() == 0
        if dialog.table.isVisible():
            assert dialog.table.horizontalScrollBar().maximum() == 0
        assert dialog.grab().save(
            str(folder / f"synthetic-p7-{theme}-{width}-tab{index}.png")
        )
    dialog.close()


def test_empty_session_preview(window):
    window.current = None
    window.workspace.fractions.clear()
    dialog = FractionationPreview(window)
    dialog.create_batch()
    dialog.create_current()
    assert dialog.table.rowCount() == 0
    assert "Created 0" in dialog.notice.text()
    dialog.close()
