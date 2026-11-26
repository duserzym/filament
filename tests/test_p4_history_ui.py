"""P4 desktop acceptance: synthetic records, both themes and supported sizes.

No Tripoli screenshot oracle exists. C# history-selection semantics are pinned
at OGTripoli/source/forms/frmHistoryGraph.cs:408-427; GUI undo is native.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import test_p2_reports_ui as p2
from PySide6 import QtWidgets
from test_p4_history import specimens

from rawtims.contract import csv_text
from rawtims.exports import clipboard_text, cycles_csv_text
from rawtims.history import HistoryBook
from rawtims.session import load_session, save_session
from rawtims_gui.history import HistoryDialog


@pytest.fixture
def window(monkeypatch, tmp_path):
    yield from p2.window.__wrapped__(monkeypatch, tmp_path)


def test_history_undo_session_and_exports_unchanged(window, tmp_path):
    """OGTripoli/source/TripoliHistoryFolderStandards.cs:209-253;
    OGTripoli/source/forms/frmHistoryGraph.cs:408-427. Synthetic standard only.
    """
    a, fraction = window.analysis, window.current[0]
    stamp = datetime(2026, 11, 25, tzinfo=UTC)

    def outputs():
        return (
            csv_text([window.workspace.fraction_row(fraction, stamp)]),
            clipboard_text(fraction),
            cycles_csv_text(a),
            a.history,
        )

    before = outputs()
    dialog = HistoryDialog(window)
    dialog.capture("standard")
    assert len(dialog.book.records) == 1 and window.is_modified()
    dialog.records.selectRow(0)
    key = dialog.selected()
    assert key and key in dialog.details.toPlainText()
    dialog.exclude()
    assert "reason" in dialog.notice.text()
    dialog.reason.setText("Synthetic unstable standard")
    dialog.exclude()
    assert dialog.book.excluded(key)
    assert dialog.coordinates[0][2]
    dialog.undo()
    assert not dialog.book.excluded(key)
    dialog.redo()
    assert dialog.book.excluded(key)
    path = save_session(
        window.workspace.session_state(), tmp_path / "synthetic.rawtims"
    )
    state, problems = load_session(path)
    assert not problems
    assert state.calibration_history == window.workspace.calibration_history
    assert HistoryBook.from_dict(state.calibration_history).excluded(key)
    assert outputs() == before
    assert any(
        "Calibration history" in action.text()
        for action in window.diagnostics_menu.actions()
    )
    dialog.close()


def test_folder_refresh_confirmation_save_and_session(window, tmp_path, monkeypatch):
    """OGTripoli/source/vendors_data/IonVantageLiveDataCyclesFolder.cs:25,139-216.
    Explicit completion and portable snapshot are native safety boundaries.
    """
    _, files = specimens(tmp_path / "synthetic-folder")
    dialog = HistoryDialog(window)
    import rawtims.completed_folder as ingestion

    clock = [10.0]
    monkeypatch.setattr(ingestion.time, "monotonic", lambda: clock[0])
    dialog.set_folder(files[0].parent)
    assert not dialog.open_button.isEnabled()
    dialog.refresh_folder()
    assert "settling" in dialog.folder_status.text()
    clock[0] = 11.1
    dialog.refresh_folder()
    assert dialog.open_button.isEnabled()
    path = tmp_path / "synthetic-snapshot.json"
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a: QtWidgets.QMessageBox.StandardButton.No,
    )
    dialog.open_completed()
    assert not path.exists()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", lambda *a: (str(path), "")
    )
    dialog.open_completed()
    assert path.exists()
    assert len(window.workspace.analyses()) == 2
    saved = save_session(
        window.workspace.session_state(), tmp_path / "synthetic-with-folder.rawtims"
    )
    state, problems = load_session(saved)
    assert not problems and len(state.analyses()) == 2
    assert not any(a.history for a in state.analyses())
    other = tmp_path / "synthetic-other-folder"
    other.mkdir()
    dialog.set_folder(other)
    assert not dialog.open_button.isEnabled()
    dialog.refresh_folder()
    assert "empty" in dialog.folder_status.text()
    dialog.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,height", [(1280, 800), (1440, 900)])
def test_history_layout(window, tmp_path, theme, width, height):
    """Explicit lab UI acceptance, no Tripoli screenshot oracle."""
    window.set_theme(theme)
    window.resize(width, height)
    dialog = HistoryDialog(window)
    dialog.capture("standard")
    dialog.records.selectRow(0)
    dialog.show()
    folder = Path(os.environ.get("RAWTIMS_P4_SHOTS", tmp_path))
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
        assert window.width() == width and window.height() == height
        assert window.plot_wall.horizontalScrollBar().maximum() == 0
        assert dialog.minimumSizeHint().width() < width
        assert dialog.width() < width and dialog.height() < height
        assert dialog.records.horizontalScrollBar().maximum() == 0
        assert dialog.grab().save(
            str(folder / f"synthetic-p4-{theme}-{width}-tab{index}.png")
        )
    dialog.close()


def test_empty_history_and_unknown_legacy(window, tmp_path, monkeypatch):
    from rawtims_gui.workspace import Workspace

    window.workspace = Workspace()
    dialog = HistoryDialog(window)
    dialog.capture("standard")
    assert "Open a run" in dialog.notice.text()
    assert not dialog.book.records and not dialog.coordinates
    unknown = tmp_path / "synthetic.triphis"
    unknown.write_bytes(b"unknown")
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", lambda *a: (str(unknown), "")
    )
    dialog.import_legacy()
    assert "unsupported" in dialog.notice.text()
    assert not dialog.book.records
    dialog.close()
