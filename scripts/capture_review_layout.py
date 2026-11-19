"""Capture the review wall and Focus offscreen, keeping all artifacts in scratch.

Example: QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/capture_review_layout.py
$TMPDIR/review-layout --open /read-only/run-Pb.xls /read-only/run-U.xls
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6 import QtCore, QtTest, QtWidgets

from rawtims_gui import main as gui
from rawtims_gui.studio.theme import build_application

SIZES = ((1512, 982), (1440, 900), (1280, 800), (1024, 640))


def settle():
    for _ in range(8):
        QtWidgets.QApplication.processEvents()
    QtTest.QTest.qWait(80)


def capture(window, output):
    image = window.grab().toImage().scaled(window.size())
    if not image.save(str(output)):
        raise OSError(f'Could not save {output}')
    wall = window.plot_wall
    viewport = QtCore.QRect(QtCore.QPoint(), wall.viewport().size())
    # Count only the visible part of scrolled plots, never offscreen cards.
    canvas_area = 0
    for plot in wall.plots:
        rect = QtCore.QRect(plot.mapTo(wall.viewport(), QtCore.QPoint()), plot.size())
        visible = rect.intersected(viewport)
        canvas_area += visible.width() * visible.height()
    area = window.width() * window.height()
    return {'window': [window.width(), window.height()],
            'plot_panel': [viewport.width(), viewport.height()],
            'plot_panel_share': round(viewport.width() * viewport.height() / area, 4),
            'visible_canvas_share': round(canvas_area / area, 4),
            'columns': wall.column_count(),
            'scroll_max': wall.verticalScrollBar().maximum()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--open', nargs='+', required=True, metavar='PATH')
    parser.add_argument('--label', default='after')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = output / '.capture-cache'
    cache.mkdir(exist_ok=True)
    os.environ['RAWTIMS_CACHE_DIR'] = str(cache)
    settings = QtCore.QSettings(str(cache / 'viewer.ini'), QtCore.QSettings.Format.IniFormat)
    settings.clear()
    gui.app_settings = lambda: settings
    app = build_application([], theme_mode='light')
    app.setQuitOnLastWindowClosed(False)
    window = gui.MainWindow(restore_geometry=False)
    report = {}
    try:
        window.open_paths(args.open, synchronous=True)
        for width, height in SIZES:
            window.resize(width, height)
            window.show()
            for focus in (False, True):
                window.review_shell.set_focus(focus)
                settle()
                name = f'{args.label}-{"focus-" if focus else ""}{width}x{height}.png'
                report[name] = capture(window, output / name)
            window.review_shell.set_focus(False)
        (output / f'{args.label}-geometry.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
    finally:
        window.unsaved_prompt = lambda _name: 'discard'
        window.close()
        window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    main()
