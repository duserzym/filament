"""P6 read-only desktop acceptance; no Tripoli screenshot oracle exists."""

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import test_p2_reports_ui as p2
from PySide6 import QtWidgets
from test_p6_methods import XML, display_run

from rawtims.contract import csv_text
from rawtims.exports import clipboard_text, cycles_csv_text
from rawtims.physical_units import IntensityUnit
from rawtims_gui.method_inspector import MethodInspector


@pytest.fixture
def window(monkeypatch, tmp_path):
    yield from p2.window.__wrapped__(monkeypatch, tmp_path)


def test_read_only_import_refusal_and_outputs(window, tmp_path):
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:200-322 / TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:261-270 (TripoliCore/.../methods).
    Synthetic source-schema import only; no hardware or vendor method validation claimed.
    """
    a, fraction = window.analysis, window.current[0]
    stamp = datetime(2026, 11, 26, tzinfo=UTC)

    def outputs():
        return (
            csv_text([window.workspace.fraction_row(fraction, stamp)]),
            clipboard_text(fraction),
            cycles_csv_text(a),
            a.history,
        )

    before = outputs()
    original_values = a.run.values.copy()
    dialog = MethodInspector(window)
    dialog.import_xml(XML)
    assert dialog.method and dialog.baselines.rowCount() == 4
    assert dialog.sequences.rowCount() == 3
    assert "differs" in dialog.method_notice.text()
    assert "CreatedBy: SYNTHETIC" in dialog.fields.toPlainText()
    for table in (
        dialog.baselines,
        dialog.sequences,
        dialog.instruments,
        dialog.detectors,
        dialog.species,
    ):
        assert (
            table.editTriggers()
            == QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
    invalid = tmp_path / "synthetic-unknown.xml"
    invalid.write_bytes(XML.read_bytes().replace(b"</HEADER>", b"<UNKNOWN/></HEADER>"))
    previous = dialog.method
    dialog.import_xml(invalid)
    assert dialog.method is previous
    assert "Import refused" in dialog.method_notice.text()
    assert not dialog.unit.isEnabled() and "unavailable" in dialog.unit_notice.text()
    dialog.element.setCurrentText("U")
    assert dialog.species.rowCount() > 1
    assert outputs() == before
    np.testing.assert_array_equal(a.run.values, original_values)
    assert any(
        "instrument references" in action.text()
        for action in window.diagnostics_menu.actions()
    )
    dialog.close()


def test_synthetic_verified_intensity_display(window, monkeypatch):
    """TripoliCore/src/main/java/org/cirdles/tripoli/constants/TripoliConstants.java:155-173 and TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/SpeciesIntensityAnalysisPlot.java:219-245.
    New display uses an existing synthetic provenance-bearing Run without reprocessing.
    """
    exceptions = []
    monkeypatch.setattr(sys, "excepthook", lambda *args: exceptions.append(args))
    dialog = MethodInspector(window)
    dialog.run = display_run()
    dialog.function.clear()
    dialog.function.addItem("SYNTHETIC 265", "265")
    before = dialog.run.values.copy()
    dialog.refresh_units()
    assert dialog.unit.isEnabled()
    assert dialog.unit.count() - 1 == len(IntensityUnit)
    for unit, factor in (
        (IntensityUnit.AMPS, 1e-11),
        (
            IntensityUnit.COUNTS,
            1 / (1e11 * dialog.run.reduction_parameters.electron_charge_c),
        ),
        (IntensityUnit.VOLTS, 1.0),
    ):
        dialog.unit.setCurrentIndex(dialog.unit.findData(unit))
        QtWidgets.QApplication.processEvents()
        assert not exceptions
        assert dialog.plot.getAxis("left").labelText == unit.value
        assert dialog.displayed_values is not None
        np.testing.assert_allclose(
            dialog.displayed_values, dialog.run.column("265") * factor, equal_nan=True
        )
    np.testing.assert_array_equal(dialog.run.values, before)
    dialog.unit.setCurrentIndex(0)
    np.testing.assert_array_equal(dialog.displayed_values, dialog.run.column("265"))
    dialog.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,height", [(1280, 800), (1440, 900)])
def test_p6_layout_all_reference_tabs(window, theme, width, height, tmp_path):
    """No upstream screenshot oracle: explicit lab-layout acceptance in both themes/sizes."""
    window.set_theme(theme)
    window.resize(width, height)
    dialog = MethodInspector(window)
    dialog.import_xml(XML)
    dialog.show()
    folder = Path(os.environ.get("RAWTIMS_P6_SHOTS", tmp_path))
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(index)
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
        assert dialog.width() < width and dialog.height() < height
        assert dialog.minimumSizeHint().width() < width
        assert window.width() == width and window.height() == height
        assert window.plot_wall.horizontalScrollBar().maximum() == 0
        for table in (
            dialog.baselines,
            dialog.sequences,
            dialog.instruments,
            dialog.detectors,
            dialog.species,
        ):
            if table.isVisible():
                assert table.horizontalScrollBar().maximum() == 0
        assert dialog.grab().save(
            str(folder / f"synthetic-p6-{theme}-{width}-tab{index}.png")
        )
    dialog.tabs.setCurrentIndex(0)
    for index in range(dialog.method_tabs.count()):
        dialog.method_tabs.setCurrentIndex(index)
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
        assert dialog.grab().save(
            str(folder / f"synthetic-p6-{theme}-{width}-method{index}.png")
        )
    assert window.grab().save(str(folder / f"synthetic-p6-window-{theme}-{width}.png"))
    dialog.close()


def test_empty_work_product(window):
    window.current = None
    dialog = MethodInspector(window)
    assert not dialog.unit.isEnabled() and "No intensity" in dialog.unit_notice.text()
    dialog.import_xml(XML)
    assert dialog.method is not None
    dialog.close()
