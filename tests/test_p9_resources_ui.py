"""P9 synthetic workspace isolation and lab-layout acceptance."""

import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import test_p2_reports_ui as p2
from PySide6 import QtCore, QtWidgets

from rawtims.contract import csv_text
from rawtims.educational import demo_catalog
from rawtims.exports import clipboard_text, cycles_csv_text
from rawtims.reference_data import element_nuclides
from rawtims_gui.plot_palette import plot_palette
from rawtims_gui.resources import EducationalSession, PeriodicTable, show_resource


@pytest.fixture
def window(monkeypatch, tmp_path):
    yield from p2.window.__wrapped__(monkeypatch, tmp_path)


def test_periodic_selection_read_only(window):
    """TripoliApp/src/main/java/org/cirdles/tripoli/gui/PeriodicTableController.java:120-131;
    synthetic work product, upstream isotope selection semantics (no screenshot oracle).
    """
    dialog = PeriodicTable(window)
    for symbol in ("Pb", "U", "Og", "n"):
        if symbol in dialog.buttons:
            dialog.buttons[symbol].click()
        else:
            dialog.select(symbol)
        assert dialog.element.currentData() == symbol
        assert dialog.species.rowCount() == len(element_nuclides(symbol))
        assert (
            dialog.species.editTriggers()
            == QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
    dialog.select("Pb")
    texts = [dialog.species.item(i, 3).text() for i in range(dialog.species.rowCount())]
    assert "stable" in texts and "unavailable" in texts
    dialog.close()


def test_demo_menu_and_independent_read_only_sessions(window, tmp_path):
    """TripoliApp/src/main/java/org/cirdles/tripoli/gui/TripoliGUIController.java:748-762;
    TripoliApp/src/main/resources/org/cirdles/tripoli/gui/TripoliGUI.fxml:103-106.
    Filament deliberately exposes only isolated educational subsets of hidden demos.
    """
    a, fraction = window.analysis, window.current[0]
    stamp = datetime(2026, 11, 26, tzinfo=UTC)

    def outputs():
        return (
            csv_text([window.workspace.fraction_row(fraction, stamp)]),
            clipboard_text(fraction),
            cycles_csv_text(a),
            repr(a.history),
            repr(a.settings),
            repr(window.workspace.presentation),
            window.settings.allKeys(),
        )

    before = outputs()
    values = a.run.values.copy()
    workspace = window.workspace
    assert len(window.resources_menu.actions()) == 2
    menu = window.resources_menu.actions()[1].menu()
    assert len(menu.actions()) == 4
    for action in menu.actions():
        action.trigger()
    QtWidgets.QApplication.processEvents()
    dialogs = window.findChildren(EducationalSession)
    assert len(dialogs) == 4
    other = show_resource(window, "two-isotope-1")
    first = next(d for d in dialogs if d.session.key == "two-isotope-1")
    assert first.session is not other.session
    assert not np.shares_memory(
        first.session.observations.observed, other.session.observations.observed
    )
    for dialog in [*dialogs, other]:
        assert not hasattr(dialog, "workspace")
        assert (
            dialog.table.editTriggers()
            == QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        assert dialog.details.isReadOnly()
        assert not dialog.plot.getPlotItem().menuEnabled()
        if dialog.session.scan is None:
            for index in range(dialog.channel.count()):
                dialog.channel.setCurrentIndex(index)
            dialog.basis.setCurrentText("cubic")
        dialog.close()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    assert window.workspace is workspace and window.analysis is a
    assert outputs() == before
    np.testing.assert_array_equal(a.run.values, values)


def test_open_demo_tracks_theme_and_empty_work_product(window):
    window.current = None
    dialog = show_resource(window, "two-isotope-1")
    before = dialog.session.initialization.evaluation.model.copy()
    for theme in ("dark", "light"):
        window.set_theme(theme)
        QtWidgets.QApplication.processEvents()
        assert (
            dialog.plot.backgroundBrush().color().name().upper()
            == plot_palette().background.upper()
        )
        np.testing.assert_array_equal(
            dialog.session.initialization.evaluation.model, before
        )
    dialog.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,height", [(1280, 800), (1440, 900)])
def test_resource_and_demo_layouts(window, theme, width, height, tmp_path):
    """No upstream screenshot oracle; synthetic work product in both lab themes/sizes."""
    window.set_theme(theme)
    window.resize(width, height)
    folder = Path(os.environ.get("RAWTIMS_P9_SHOTS", tmp_path))
    folder.mkdir(parents=True, exist_ok=True)
    dialogs = [PeriodicTable(window)] + [
        EducationalSession(key, window) for key in demo_catalog()
    ]
    for index, dialog in enumerate(dialogs):
        dialog.show()
        tabs = range(dialog.tabs.count()) if hasattr(dialog, "tabs") else [None]
        for tab in tabs:
            if tab is not None:
                dialog.tabs.setCurrentIndex(tab)
            for _ in range(3):
                QtWidgets.QApplication.processEvents()
            assert dialog.width() < width and dialog.height() < height
            assert dialog.minimumSizeHint().width() < width
            assert window.width() == width and window.height() == height
            table = (
                dialog.species if isinstance(dialog, PeriodicTable) else dialog.table
            )
            if table.isVisible():
                assert table.horizontalScrollBar().maximum() == 0
            assert dialog.grab().save(
                str(folder / f"p9-{theme}-{width}-{index}-{tab}.png")
            )
        if isinstance(dialog, PeriodicTable):
            assert len(dialog.buttons) == 118
            for button in dialog.buttons.values():
                assert button.width() >= 24 and button.height() >= 26
        dialog.close()
    assert window.plot_wall.horizontalScrollBar().maximum() == 0
