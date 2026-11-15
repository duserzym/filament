"""Capture the Tripoli palette and wall fit using real B998 data, offscreen.

Pass the output directory. All settings/recovery files stay beneath it.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtTest, QtWidgets

from rawtims_gui import main as gui
from rawtims_gui.studio.theme import build_application

ROOT = Path(__file__).resolve().parents[1]
B998 = ROOT / 'tests/fixtures/tripoli/ionvantage/BoiseState/B998_F11_13223M02_iz1_Pb1-14973.xls'


def settle():
    QtTest.QTest.qWait(150)
    for _ in range(8):
        QtWidgets.QApplication.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = output / '.capture-cache'
    cache.mkdir(exist_ok=True)
    os.environ['RAWTIMS_CACHE_DIR'] = str(cache)
    settings = QtCore.QSettings(str(cache / 'settings.ini'), QtCore.QSettings.Format.IniFormat)
    gui.app_settings = lambda: settings
    app = build_application(['plot-colours-capture'], theme_mode='light')
    app.setQuitOnLastWindowClosed(False)
    report = {}
    for layout, theme in [('wall', 'light'), ('wall', 'dark'), ('classic', 'light')]:
        settings.clear()
        window = gui.MainWindow(restore_geometry=False, layout=layout)
        window.resize(1280, 800)
        window.show()
        window.set_theme(theme)
        window.open_paths([str(B998)], synchronous=True)
        analysis = window.analysis
        rejected = np.flatnonzero(np.isin(analysis.run.cycle, [22, 23, 24])).tolist()
        window.request_toggle('206/204 D', rejected)
        row = int(np.flatnonzero(analysis.run.block == 4)[0])
        window.request_block_toggle('206/204 D', row)
        window.statusBar().clearMessage()
        settle()

        def save(name):
            settle()
            picture = window.grab()
            assert picture.size() / picture.devicePixelRatio() == window.size()
            # Normalize Retina captures to the requested logical dimensions.
            picture = picture.toImage().scaled(window.size(), QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                                               QtCore.Qt.TransformationMode.SmoothTransformation)
            assert picture.save(str(output / name))
            wall = window.plot_wall
            report[name] = {'window': [window.width(), window.height()],
                            'viewport': [wall.viewport().width(), wall.viewport().height()],
                            'columns': wall.column_count(), 'scroll_max': wall.verticalScrollBar().maximum(),
                            'cards': [[c.x(), c.y(), c.width(), c.height()] for c in getattr(wall, 'cards', [])]}

        save(f'{layout}_{theme}.png')
        if layout == 'wall':
            card = window.plot_wall.cards[0]
            image = card.grab().toImage()
            image = image.scaled(card.size() * 2, QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                                 QtCore.Qt.TransformationMode.SmoothTransformation)
            assert image.save(str(output / f'card_zoom_{theme}.png'))
        if layout == 'wall' and theme == 'light':
            window.review_shell.inspector.set_collapsed(True, animate=False)
            save('wall_collapsed_1280_light.png')
            assert window.plot_wall.verticalScrollBar().maximum() == 0
            source = window.plot_wall.plots[0]
            point = source.view_box.mapViewToScene(QtCore.QPointF(23, source.point_of(22).y()))
            # Exercise the same scene event delivered by a physical hover.
            source.scene().sigMouseMoved.emit(point)
            assert all(p.hover_guide.isVisible() and p.hover_guide.value() == 23 for p in window.plot_wall.plots)
            save('wall_hover_guide_light.png')
            window.plot_wall.set_hover_cycle(None)
            window.resize(1024, 640)
            save('wall_collapsed_1024_light.png')
        window.unsaved_prompt = lambda _name: 'discard'
        window.close()
        window.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    (output / 'fit-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
