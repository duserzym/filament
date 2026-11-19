"""Read the bundled or checkout guide in the app, including local screenshots."""
import re
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


def guide_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'guide/user-guide.md'
    return Path(__file__).resolve().parents[2] / 'docs/user-guide.md'


def check_guide_resources():
    """Fail frozen smoke validation if the guide or any screenshot was omitted."""
    path = guide_path()
    text = path.read_text(encoding='utf-8')
    for relative in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', text):
        if not (path.parent / relative).is_file():
            raise RuntimeError(f'Missing bundled guide image: {relative}')


class GuideBrowser(QtWidgets.QTextBrowser):
    """Fit local screenshots to the viewport while retaining their aspect ratio."""
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_images()

    def fit_images(self):
        document = self.document()
        available = max(1, self.viewport().width() - 24)
        block = document.begin()
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    fmt = fragment.charFormat().toImageFormat()
                    url = document.baseUrl().resolved(QtCore.QUrl(fmt.name()))
                    image = QtGui.QImage(url.toLocalFile())
                    if not image.isNull():
                        width = min(image.width(), available)
                        fmt.setWidth(width)
                        fmt.setHeight(width * image.height() / image.width())
                        cursor = QtGui.QTextCursor(document)
                        cursor.setPosition(fragment.position())
                        cursor.movePosition(QtGui.QTextCursor.MoveOperation.NextCharacter,
                                            QtGui.QTextCursor.MoveMode.KeepAnchor)
                        cursor.setCharFormat(fmt)
                iterator += 1
            block = block.next()


def show_user_guide(parent):
    path = guide_path()
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle('User guide')
    dialog.resize(min(960, parent.width() - 48), min(760, parent.height() - 64))
    layout = QtWidgets.QVBoxLayout(dialog)
    browser = GuideBrowser()
    browser.setOpenExternalLinks(True)
    browser.document().setBaseUrl(QtCore.QUrl.fromLocalFile(str(path.parent) + '/'))
    browser.setMarkdown(path.read_text(encoding='utf-8') if path.is_file() else f'Guide unavailable: {path}')
    layout.addWidget(browser)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.close)
    layout.addWidget(buttons)
    parent.user_guide_dialog = dialog
    dialog.show()
    browser.fit_images()
    return dialog
