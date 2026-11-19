"""Guide resource routing and image constraints, including the frozen layout."""
import re
import sys

from PIL import Image

from rawtims_gui import user_guide


def test_checkout_guide_images_are_small_and_plot_first():
    guide = user_guide.guide_path()
    assert guide.is_file()
    user_guide.check_guide_resources()
    for relative in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', guide.read_text()):
        path = guide.parent / relative
        assert path.stat().st_size <= 250_000
        with Image.open(path) as image:
            assert image.size == (1440, 900)
    assert 'guide/review-wall.png' in guide.read_text()


def test_frozen_guide_uses_bundle_and_rejects_missing_image(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    path = tmp_path / 'guide/user-guide.md'
    path.parent.mkdir()
    path.write_text('![Example](guide/example.png)')
    assert user_guide.guide_path() == path
    with pytest.raises(RuntimeError, match='Missing bundled guide image'):
        user_guide.check_guide_resources()


def test_guide_dialog_and_images_fit_small_window(qt_settings_folder):
    from PySide6 import QtCore, QtWidgets

    from rawtims_gui.studio.theme import build_application
    build_application(['guide-test'], theme_mode='light')
    parent = QtWidgets.QWidget()
    parent.resize(1024, 640)
    dialog = user_guide.show_user_guide(parent)
    try:
        for _ in range(4):
            QtWidgets.QApplication.processEvents()
        assert dialog.width() < parent.width()
        assert dialog.height() < parent.height()
        browser = dialog.findChild(user_guide.GuideBrowser)
        browser.fit_images()
        block = browser.document().begin()
        count = 0
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    assert fragment.charFormat().toImageFormat().width() <= browser.viewport().width()
                    count += 1
                it += 1
            block = block.next()
        assert count >= 10
    finally:
        dialog.close()
        parent.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
