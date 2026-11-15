"""Render real-fixture review states in both themes at each supported fit-check size.

Run with PYTHONPATH cleared and QT_QPA_PLATFORM=offscreen; pass the screenshot
folder as the sole argument. Settings and recovery stay in the app build cache.
The 1280x800 images go directly in that folder; other sizes go in fit/.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtTest, QtWidgets

from rawtims import branding
from rawtims.analysis import Analysis, AnalysisSettings
from rawtims.readers import open_run
from rawtims_gui import main as gui
from rawtims_gui.studio.theme import build_application

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/tripoli"
B998 = FIXTURES / "ionvantage/BoiseState/B998_F11_13223M02_iz1_Pb1-14973.xls"
U239 = FIXTURES / "timsdp/KU_IGL/IsolinxVersion2/GHR1 230921F03 U-239.TIMSDP"
PAIR = [FIXTURES / "ionvantage/KU_IGL" / name for name in (
    "GHR1 20200827-11 Pb-6590.xls", "GHR1 20200827-11 U run2-6591.xls")]


def settle() -> None:
    QtTest.QTest.qWait(250)  # let the segmented-bar selection animation finish
    for _ in range(8):
        QtWidgets.QApplication.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def fit_evidence(window: gui.MainWindow) -> dict:
    """Record visible scrollbars and overflowing scroll bodies, including tables."""
    settle()
    sideways, overflow = [], []
    for area in window.findChildren(QtWidgets.QAbstractScrollArea):
        if not area.isVisibleTo(window):
            continue
        name = area.objectName() or type(area).__name__
        if area.horizontalScrollBar().isVisible():
            sideways.append(name)
        if isinstance(area, QtWidgets.QScrollArea) and area.widget() is not None and area.widget().width() > area.viewport().width():
            overflow.append(name)
    return {"horizontal_scrollbars": sideways, "overflowing_bodies": overflow,
            "size": [window.width(), window.height()]}


def main() -> None:
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = Path(os.environ.get("RAWTIMS_CACHE_DIR", Path.home() / "Library/Caches" / branding.CACHE_DIR_NAME)) / "review-capture"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["RAWTIMS_CACHE_DIR"] = str(cache)
    settings = QtCore.QSettings(str(cache / "settings.ini"), QtCore.QSettings.Format.IniFormat)
    gui.app_settings = lambda: settings
    app = build_application(["review-capture"], theme_mode="light")
    app.setQuitOnLastWindowClosed(False)
    run = open_run(B998)
    report = {"b998_all_valid": {}, "captures": {}}
    for mode in ("geometric", "arithmetic"):
        analysis = Analysis(run, AnalysisSettings(stat_mode=mode))
        report["b998_all_valid"][mode] = analysis.stats("206/204 D").to_dict()
    values = run.column("206/204 D")
    outliers = np.argsort(np.abs(values - np.median(values)))[-2:].tolist()
    report["manual_rejected_cycles"] = run.cycle[outliers].tolist()
    for theme in ("light", "dark"):
        for width, height in ((1280, 800), (1440, 900), (1024, 640)):
            settings.clear()
            window = gui.MainWindow(restore_geometry=False)
            window.resize(width, height)
            window.show()
            window.set_theme(theme)
            window.open_paths([str(B998)], synchronous=True)
            settle()

            def capture(name: str, *, width=width, height=height, theme=theme, window=window) -> None:
                folder = output if width == 1280 else output / "fit" / f"{width}x{height}"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{name}_{theme}.png"
                report["captures"][str(path.relative_to(output))] = fit_evidence(window)
                assert window.grab().save(str(path), "PNG")

            # Use the same hand-rejection gesture path as a plot click, without applying a rule.
            for row in outliers:
                plot = window.plot_wall.plot("206/204 D")
                plot._on_click(plot.point_of(row), QtCore.Qt.KeyboardModifier.NoModifier)
            window.statusBar().clearMessage()
            capture("01_review")
            while window.analysis.can_undo:
                window.undo_action.trigger()
            window.inspector_tabs.setCurrentIndex(gui.INSPECTOR_TABS.index("Rules"))
            window.preview_rule()
            window.statusBar().clearMessage()
            capture("02_rules")
            capture("06_rules_union_preview")
            if theme == "light" and width == 1280:
                proposal = window.current_proposal()
                report["b998_union_preview"] = {
                    "flagged": {k: len(v) for k, v in proposal.flagged.items()},
                    "flagged_cycles": {k: run.cycle[list(v)].astype(int).tolist() for k, v in proposal.flagged.items()},
                    "union_size": len(proposal.cycles),
                    "union_cycles": run.cycle[list(proposal.cycles)].astype(int).tolist(),
                    "before_after": proposal.before_after,
                }
            window.set_plot_mode("table")
            window.inspector_tabs.setCurrentIndex(gui.INSPECTOR_TABS.index("Stats"))
            window.preview_rule()
            window.statusBar().clearMessage()
            capture("03_table")
            window.unsaved_prompt = lambda _name: "discard"
            window.new_session()
            window.set_plot_mode("ratios")
            window.open_paths([str(U239)], synchronous=True)
            window.set_workflow_step("Correct")
            window.statusBar().clearMessage()
            capture("04_corrections")
            window.new_session()
            window.open_paths([str(p) for p in PAIR], synchronous=True)
            window.set_workflow_step("Export")
            assert window.fraction_list.states() == [("GHR1 20200827-11", "ready")]
            window.statusBar().clearMessage()
            capture("05_export")
            window.close()
            window.deleteLater()
            settle()
    (output / "fit-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
