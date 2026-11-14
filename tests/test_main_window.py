"""The empty main window: size rules, placeholders, theme and geometry (SPEC section 5)."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6 import QtGui, QtWidgets  # noqa: E402

from rawtims import branding  # noqa: E402
from rawtims_gui import main as gui_main  # noqa: E402
from rawtims_gui.studio.theme import active_theme, build_application  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app():
    return build_application(["test"], theme_mode="light")


@pytest.fixture
def window(app, qt_settings_folder):
    gui_main.app_settings().clear()
    window = gui_main.MainWindow(restore_geometry=False)
    yield window
    window.deleteLater()


def test_window_layout_and_size_rules(window):
    assert window.windowTitle() == branding.DISPLAY_NAME
    assert window.minimumSize() == QtCore.QSize(1024, 640)
    window.resize(gui_main.DEFAULT_SIZE)
    window.show()
    QtWidgets.QApplication.processEvents()
    assert window.size() == QtCore.QSize(1280, 800)
    rail = [window.workflow_step_list.item(i).text() for i in range(window.workflow_step_list.count())]
    assert [text.split(maxsplit=1)[1] for text in rail] == ["Import", "Review", "Correct", "Export"]
    tabs = [window.inspector_tabs.tabText(i) for i in range(window.inspector_tabs.count())]
    assert tabs == ["Stats", "Rules", "Corrections", "Export"]
    assert window.version_label.text() == branding.RAW_APP_LABEL
    assert active_theme().name == "light"


@pytest.mark.parametrize(("available", "expected"), [
    ((1440, 875), (1280, 800)),
    ((1280, 775), (1280, 775)),
    ((800, 600), (1024, 640)),
])
def test_opening_size_fits_the_screen(available, expected):
    assert gui_main.fitted_window_size(QtCore.QSize(*available)) == QtCore.QSize(*expected)


def test_geometry_is_saved_per_viewer_and_restored(app, qt_settings_folder):
    settings = gui_main.app_settings()
    settings.clear()
    first = gui_main.MainWindow()
    # The offscreen screen is 800 x 800, so restoreGeometry clamps the width to the
    # 1024 minimum; the height (700, not the default 800) shows the restore.
    first.resize(1024, 700)
    first.show()
    QtWidgets.QApplication.processEvents()
    first.close()
    assert isinstance(settings.value(gui_main.GEOMETRY_KEY), QtCore.QByteArray)
    assert Path(settings.fileName()).is_relative_to(qt_settings_folder)
    second = gui_main.MainWindow()
    assert second.size() == QtCore.QSize(1024, 700)
    first.deleteLater()
    second.deleteLater()


def test_dark_theme_applies(app):
    build_application(["test"], theme_mode="dark")
    try:
        assert active_theme().name == "dark"
    finally:
        build_application(["test"], theme_mode="light")


def _run_cli(*arguments, tmp_path):
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run([sys.executable, "-m", "rawtims_gui.main", *arguments], capture_output=True, text=True,
                          env=env, cwd=tmp_path, timeout=120)


def test_export_png_writes_a_full_size_screenshot(tmp_path):
    output = tmp_path / "empty.png"
    result = _run_cli("--theme", "light", "--export", "png", str(output), tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert output.stat().st_size > 10_000
    assert QtGui.QImage(str(output)).size() == QtCore.QSize(1280, 800)


def test_version_and_verify_stub(tmp_path):
    version = _run_cli("--version", tmp_path=tmp_path)
    assert version.returncode == 0 and version.stdout.strip() == branding.RAW_APP_LABEL
    verify = _run_cli("--verify", "x.xls", tmp_path=tmp_path)
    assert verify.returncode == 2
    assert "not available yet" in verify.stderr
    bad = _run_cli("--export", "jpg", str(tmp_path / "x.jpg"), tmp_path=tmp_path)
    assert bad.returncode == 2
