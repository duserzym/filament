"""Updater surfaces cover content in both host themes, using synthetic previews."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims_gui.labupdate.config import UpdateConfig
from rawtims_gui.labupdate.qt import CheckUpdatesButton, Updater
from rawtims_gui.studio.theme import apply_theme


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("status", ["none", "available", "ready"])
@pytest.mark.parametrize("card", ["popover", "whats_new_card"])
def test_update_popup_opaque(theme, status, card, tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / "updates.ini"), QtCore.QSettings.Format.IniFormat)
    config = UpdateConfig("Synthetic app", "example/synthetic", "", settings_org="test", settings_app="test")
    updater = Updater(config, "1.0.0", preview=status, settings=settings, root=tmp_path)
    button = CheckUpdatesButton(updater)
    try:
        # Change the theme after creation as well: popups must follow live palette updates.
        apply_theme(app, "dark" if theme == "light" else "light")
        apply_theme(app, theme)
        popup = getattr(button, card)
        popup.resize(370, 240)
        popup.ensurePolished()
        image = QtGui.QImage(popup.size(), QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("magenta"))
        popup.render(image)
        colour = image.pixelColor(5, popup.height() // 2)
        assert colour.alpha() == 255
        assert colour.name() == ("#ffffff" if theme == "light" else "#161d2b")
        assert popup.windowType() == QtCore.Qt.WindowType.Popup
        assert popup.windowOpacity() == 1.0
    finally:
        updater.shutdown()
        button.close()
        button.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        apply_theme(app, "light")


@pytest.mark.parametrize("card", ["popover", "whats_new_card"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_update_popup_normalises_palette_alpha(card, theme, tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    settings = QtCore.QSettings(str(tmp_path / "updates.ini"), QtCore.QSettings.Format.IniFormat)
    config = UpdateConfig("Synthetic app", "example/synthetic", "", settings_org="test", settings_app="test")
    updater = Updater(config, "1.0.0", preview="available", settings=settings, root=tmp_path)
    button = CheckUpdatesButton(updater)
    try:
        apply_theme(app, theme)
        popup = getattr(button, card)
        palette = popup.palette()
        colour = QtGui.QColor("#ffffff" if theme == "light" else "#161d2b")
        colour.setAlpha(80)
        palette.setColor(QtGui.QPalette.ColorRole.Button, colour)
        popup.setPalette(palette)
        popup.resize(370, 240)
        popup.ensurePolished()
        image = QtGui.QImage(popup.size(), QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("magenta"))
        popup.render(image)
        pixel = image.pixelColor(5, popup.height() // 2)
        assert pixel.alpha() == 255
        assert pixel.name() == ("#ffffff" if theme == "light" else "#161d2b")
    finally:
        updater.shutdown()
        button.close()
        button.deleteLater()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        apply_theme(app, "light")
