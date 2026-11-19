"""Capture the plot-first user guide and audit every panel offscreen.

Run: env -u PYTHONPATH .venv/bin/python scripts/capture_guide.py
Private Drive inputs are read-only. Only screenshots and derived geometry enter
this checkout. Fixtures substitute when Drive is absent; KD33 shots are skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = '1'
from PIL import Image
from PySide6 import QtCore, QtTest, QtWidgets

from rawtims.parity import drive_path
from rawtims_gui import main as gui
from rawtims_gui.studio.theme import build_application
from rawtims_gui.walkthrough import availability

ROOT = Path(__file__).resolve().parents[1]
SIZES = ((1512, 982), (1440, 900), (1280, 800), (1024, 640))


def settle(window):
    # Wait for acquisition probes and animations before recording geometry.
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
        QtTest.QTest.qWait(15)
    QtCore.QThreadPool.globalInstance().waitForDone(10000)
    QtWidgets.QApplication.processEvents()
    window._autosave_timer.stop()


def screenshot(window, path):
    settle(window)
    window.statusBar().clearMessage()
    window.grab().save(str(path), 'PNG')
    with Image.open(path) as original:
        # Deterministic indexed PNG, 1440×900 pixels; preserves readable text.
        image = original.convert('RGB').quantize(colors=128, method=Image.Quantize.MEDIANCUT)
        image.save(path, optimize=True)
    if path.stat().st_size > 250_000:
        raise RuntimeError(f'Guide image exceeds 250 KB: {path}')
    return {'pixels': [window.width(), window.height()], 'bytes': path.stat().st_size}


def show_panel(window, name):
    window.review_shell.set_focus(False)
    window.set_plot_mode('ratios')
    window.set_workflow_step('Review')
    if name in ('Mapping', 'Reduction', 'Run info'):
        window.show_correction_page(name)
    elif name in ('Stats', 'Rules', 'Export'):
        window.inspector_tabs.setCurrentIndex(gui.INSPECTOR_TABS.index(name))
    elif name in ('intensities', 'table'):
        window.set_plot_mode(name)
    elif name == 'Import':
        window.set_workflow_step('Import')
    elif name == 'Focus':
        window.review_shell.set_focus(True)


def panel_geometry(window, panel):
    """Check real widths, not offscreen-screen geometry or scrolled vertical content."""
    problems = []
    scrolls = []
    for scroll in window.inspector_panel.findChildren(QtWidgets.QScrollArea):
        if not scroll.isVisible():
            continue
        content, viewport = scroll.widget(), scroll.viewport()
        scrolls.append({'page': content.objectName(), 'content_width': content.width(),
                        'viewport_width': viewport.width(), 'scroll_y': scroll.verticalScrollBar().maximum()})
        if content.width() > viewport.width():
            problems.append(f'{content.objectName()} wider than viewport: {content.width()} > {viewport.width()}')
        # Check leaf controls against their content's horizontal bounds. Vertical
        # overflow is intentional and reachable through the scroll bar.
        for child in content.findChildren(QtWidgets.QWidget):
            if not child.isVisible() or not isinstance(child, (QtWidgets.QAbstractButton, QtWidgets.QLineEdit, QtWidgets.QComboBox, QtWidgets.QLabel)):
                continue
            rect = QtCore.QRect(child.mapTo(content, QtCore.QPoint()), child.size())
            if rect.left() < 0 or rect.right() >= content.width():
                problems.append(f'{child.objectName() or type(child).__name__} outside content horizontally')
    return {'window': [window.width(), window.height()], 'panel': panel, 'scrolls': scrolls, 'problems': problems}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/guide')
    parser.add_argument('--examples-folder', type=Path, default=drive_path())
    parser.add_argument('--fit-output', type=Path, default=Path(tempfile.gettempdir()) / 'guide-fit')
    parser.add_argument('--fixtures-only', action='store_true')
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    args.fit_output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='guide-capture-') as scratch:
        os.environ['RAWTIMS_CACHE_DIR'] = scratch
        settings = QtCore.QSettings(str(Path(scratch) / 'viewer.ini'), QtCore.QSettings.Format.IniFormat)
        gui.app_settings = lambda: settings
        app = build_application([], theme_mode='light')
        app.setQuitOnLastWindowClosed(False)
        window = gui.MainWindow(restore_geometry=False)
        window.unsaved_prompt = lambda _: 'discard'
        window.resize(1440, 900)
        window.show()  # QT_QPA_PLATFORM is forced offscreen above.
        shots, fit = {}, []
        private = not args.fixtures_only and not availability(args.examples_folder)
        try:
            if private:
                window.walkthrough.start(folder=args.examples_folder, step=1, synchronous=True)
                window.walkthrough.bar.hide()
                # Ordinary guide tasks use the shared-cycle export selection.
                for analysis in window.workspace.analyses():
                    analysis.use_union_of_rejections()
                window._after_edit()
            else:
                print('Skipping KD33 walkthrough shots: examples unavailable or --fixtures-only.')
                fixtures = ROOT / 'tests/fixtures/tripoli/timsdp/KU_IGL/IsolinxVersion2'
                window.open_paths([str(fixtures / 'GHR1 230921 F08b-216.TIMSDP'),
                                   str(fixtures / 'GHR1 230921F03 U-239.TIMSDP')], synchronous=True)
            def take(name):
                window.resize(1440, 900)
                shots[name] = screenshot(window, args.output / f'{name}.png')
            show_panel(window, 'Import')
            take('open-run')
            show_panel(window, 'Stats')
            take('review-wall')
            # Show a real rejection through the public analysis operation.
            window.analysis.toggle_cycles([50, 51], window.mapping.function_keys, False)
            window._after_edit()
            take('reject-cycles')
            show_panel(window, 'Run info')
            take('run-info')
            pb_fraction = window.workspace.fractions[0]
            u_fraction = next((f for f in window.workspace.fractions if f.u is not None), None)
            if u_fraction:
                window.select_run(u_fraction, 'U')
                show_panel(window, 'Run info')
                take('run-warnings')
                window.select_run(pb_fraction, 'Pb')
            show_panel(window, 'Rules')
            for rule, name in [('legacy_two_sigma', 'rules-2sigma'), ('legacy_chauvenet', 'rules-chauvenet')]:
                window.rules_panel.set_rule(rule)
                window.preview_rule()
                take(name)
                window.discard_preview()
            window.preview_rule()
            window.apply_preview()
            take('rules-applied')
            show_panel(window, 'Reduction')
            take('reduction-parameters')
            show_panel(window, 'Export')
            take('export-send')
            scroll = window.export_panel.findChild(QtWidgets.QScrollArea)
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            take('send-command')
            if private:
                for step in range(1, 6):
                    window.walkthrough.start(folder=args.examples_folder, step=step, synchronous=True)
                    if step == 3:
                        window.reduction_panel.form_toggle.setChecked(False)
                    take(f'walkthrough-{step}')
                    for size in SIZES:
                        window.resize(*size)
                        settle(window)
                        record = panel_geometry(window, f'Walkthrough {step}')
                        if record['window'] != list(size):
                            record['problems'].append(f'Window grew beyond requested {size}')
                        bar = window.walkthrough.bar
                        for button in bar.findChildren(QtWidgets.QAbstractButton):
                            if button.isVisible() and not bar.rect().contains(QtCore.QRect(button.mapTo(bar, QtCore.QPoint()), button.size())):
                                record['problems'].append(f'Walkthrough button clipped: {button.text()}')
                        fit.append(record)
                        window.grab().save(str(args.fit_output / f'{size[0]}x{size[1]}-Walkthrough-{step}.png'))
                window.walkthrough.bar.hide()
            for element in ('Pb', 'U'):
                fraction = next((f for f in window.workspace.fractions if getattr(f, element.lower()) is not None), None)
                if fraction is None:
                    continue
                window.select_run(fraction, element)
                for size in SIZES:
                    window.resize(*size)
                    for panel in ('Import', 'Stats', 'Rules', 'Mapping', 'Reduction', 'Run info', 'Export', 'intensities', 'table', 'Focus'):
                        show_panel(window, panel)
                        if panel == 'Reduction':
                            window.reduction_panel.form_toggle.setChecked(True)
                        settle(window)
                        record = panel_geometry(window, panel)
                        record['element'] = element
                        if record['window'] != list(size):
                            record['problems'].append(f'Window grew beyond requested {size}')
                        fit.append(record)
                        window.grab().save(str(args.fit_output / f'{element}-{size[0]}x{size[1]}-{panel.replace(" ", "-")}.png'))
            from rawtims_gui.user_guide import GuideBrowser, show_user_guide
            for size in SIZES:
                window.resize(*size)
                dialog = show_user_guide(window)
                settle(window)
                browser = dialog.findChild(GuideBrowser)
                browser.fit_images()
                problems = []
                if dialog.width() > size[0] or dialog.height() > size[1]:
                    problems.append('Guide exceeds parent window')
                if browser.horizontalScrollBar().maximum():
                    problems.append('Guide requires horizontal scrolling')
                fit.append({'window': list(size), 'panel': 'User guide',
                            'dialog': [dialog.width(), dialog.height()], 'problems': problems})
                dialog.grab().save(str(args.fit_output / f'{size[0]}x{size[1]}-User-guide.png'))
                dialog.close()
            report = {'source': 'KD33 z1' if private else 'public fixtures', 'screenshots': shots, 'fit': fit}
            (args.output / 'capture-report.json').write_text(json.dumps(report, indent=2) + '\n')
            problems = [f'{r["window"]} {r["panel"]}: {p}' for r in fit for p in r['problems']]
            print(f'{len(shots)} guide screenshots; {len(fit)} panel/size checks. Fit images: {args.fit_output}')
            if problems:
                print('\n'.join(problems))
                return 1
            return 0
        finally:
            QtCore.QThreadPool.globalInstance().waitForDone(10000)
            window.close()
            window.deleteLater()
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


if __name__ == '__main__':
    raise SystemExit(main())
