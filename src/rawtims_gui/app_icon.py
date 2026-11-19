"""Load the curated small and large PNG representations for Qt."""

from pathlib import Path

from PySide6 import QtCore, QtGui

from rawtims import branding


def build_app_icon() -> QtGui.QIcon:
    assets = Path(__file__).resolve().parent / "assets"
    icon = QtGui.QIcon()
    for size, name in branding.GUI_ICON_FILENAMES.items():
        icon.addFile(str(assets / name), QtCore.QSize(size, size))
    return icon
