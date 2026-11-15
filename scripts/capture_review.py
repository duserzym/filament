"""Render real-fixture review states in both themes at each supported fit-check size.

Run with PYTHONPATH cleared and QT_QPA_PLATFORM=offscreen; pass the screenshot
folder as the positional argument. Settings and recovery stay under that folder.
The 1280x800 images go directly in that folder; other sizes go in fit/.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

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
    QtTest.QTest.qWait(250)  # settle geometry and any mouse-driven panel motion
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


def save_overview(output: Path, width: int, height: int, theme: str) -> None:
    """Refresh the existing visual QA sheets from this capture's six states."""
    source = output if width == 1280 else output / "fit" / f"{width}x{height}"
    names = ("01_review", "02_rules", "03_table", "04_corrections", "05_export", "06_rules_union_preview")
    tile_width = 640
    tile_height = round(height * tile_width / width)
    sheet = QtGui.QImage(tile_width * 3, (tile_height + 24) * 2, QtGui.QImage.Format.Format_RGB32)
    sheet.fill(QtGui.QColor("#e8ecf2"))
    painter = QtGui.QPainter(sheet)
    for index, name in enumerate(names):
        x, y = index % 3 * tile_width, index // 3 * (tile_height + 24)
        painter.setPen(QtGui.QColor("#142130"))
        painter.drawText(x + 8, y + 17, f"{width}×{height} · {theme} · {name}")
        picture = QtGui.QImage(str(source / f"{name}_{theme}.png"))
        assert not picture.isNull()
        painter.drawImage(QtCore.QRect(x, y + 24, tile_width, tile_height), picture)
    painter.end()
    (output / "fit").mkdir(exist_ok=True)
    assert sheet.save(str(output / "fit" / f"overview_{width}x{height}_{theme}.png"), "PNG")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument("--round-shots", type=Path, help="Also write the UI-round review, collapsed and maximised captures")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = output / ".capture-cache"
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
    outliers = [int(np.flatnonzero(run.cycle == cycle)[0]) for cycle in (23, 24)]
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
            if args.round_shots and (width == 1280 or theme == "light"):
                args.round_shots.mkdir(parents=True, exist_ok=True)
                name = f"after_review_{width}_{theme}.png"
                assert window.grab().save(str(args.round_shots / name), "PNG")
                if width == 1280 and theme == "light":
                    window.review_shell.inspector.set_collapsed(True, animate=False)
                    settle()
                    assert window.plot_wall.verticalScrollBar().maximum() == 0
                    assert window.grab().save(str(args.round_shots / "after_review_collapsed_1280_light.png"), "PNG")
                    window.review_shell.inspector.set_collapsed(False, animate=False)
                    window.plot_wall.cards[0].max_button.click()
                    settle()
                    assert window.grab().save(str(args.round_shots / "after_maximised_card_1280_light.png"), "PNG")
                    window.review_shell.restore_all()
                    settle()
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
            save_overview(output, width, height, theme)
            window.close()
            window.deleteLater()
            settle()
    (output / "fit-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
