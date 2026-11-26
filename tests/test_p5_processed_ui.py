"""Synthetic-only P5 acceptance in both themes at the two supported window sizes."""

import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets
from test_processed_readers import thermo

from rawtims_gui import main as gui
from rawtims_gui.studio.theme import build_application


def settle():
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("size", [(1280, 800), (1440, 900)])
def test_non_pb_u_review_without_contract_mapping(
    qt_settings_folder, monkeypatch, tmp_path, theme, size
):
    """TritonMassSpec.java:45-170 accepts other isotope systems; F71 is independent of /1 export."""
    build_application(["p5-ui"], theme_mode=theme)
    settings = QtCore.QSettings(
        str(tmp_path / "ui.ini"), QtCore.QSettings.Format.IniFormat
    )
    monkeypatch.setattr(gui, "app_settings", lambda: settings)
    p = tmp_path / "synthetic-cr.exp"
    p.write_text(thermo(names="53Cr/52Cr (1)\t53Cr", rows="1\t1\tX2\t-1\n2\t2\t4\t2\n"))
    w = gui.MainWindow(restore_geometry=False)
    w.resize(*size)
    w.show()
    try:
        w.open_paths([str(p)], synchronous=True)
        settle()
        assert not w.workspace.fractions and not w.skipped
        assert "1 independent run review" in w.import_summary.text()
        assert len(w._processed_reviews) == 1
        d = w._processed_reviews[0]
        d.resize(size[0] - 100, size[1] - 100)
        settle()
        a = d.analysis
        assert a.run.element is None and a.mapping is None and a.included.all()
        assert len(d.wall.plots) == 1
        assert d.table.cycle_model.rowCount() == 2
        assert d.table.cycle_model.columnCount() == 6
        for widget in [
            d.functions,
            d.mode,
            d.vendor,
            d.undo_button,
            d.tabs,
            d.statistics,
            d.save_button,
        ]:
            assert widget.isVisibleTo(d)
            rect = QtCore.QRect(widget.mapTo(d, QtCore.QPoint()), widget.size())
            assert d.rect().contains(rect), (widget, rect, d.rect())
        before = a.effective.copy()
        d.use_vendor_flags()
        assert not a.effective[0, 0] and a.effective[0, 1]
        d.undo()
        np.testing.assert_array_equal(a.effective, before)
        d.toggle(a.keys[0], [1])
        assert not a.effective[1, 0]
        d.undo()
        np.testing.assert_array_equal(a.effective, before)
        d.mode.setCurrentIndex(1)
        assert a.stats(a.keys[0]).mean == pytest.approx(np.sqrt(8))
        for i in range(3):
            d.tabs.setCurrentIndex(i)
            settle()
            assert d.tabs.currentWidget().isVisibleTo(d)
        target = tmp_path / "synthetic-reviewed.csv"
        assert d.save(path=target) == target
        assert "53Cr/52Cr (1)" in target.read_text()
        assert "X2" in d.source.toPlainText()
        w.open_paths([str(p)], synchronous=True)
        settle()
        assert len(w._processed_reviews) == 1
        assert len(w.skipped) == 1 and "already open" in w.skipped[0][1]
        d.close()
        settle()
    finally:
        w.unsaved_prompt = lambda _: "discard"
        w.close()
        w.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete
        )
