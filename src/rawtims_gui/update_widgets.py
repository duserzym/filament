"""App settings around the unchanged shared update controls."""

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims_gui.labupdate.qt import NotesLabel, release_notes_url
from rawtims_gui.labupdate.qt import VersionChip as SharedVersionChip
from rawtims_gui.labupdate.state import button_view


class VersionChip(SharedVersionChip):
    """Open the app's update settings from the running-version chip."""

    def __init__(self, updater, parent=None):
        super().__init__(updater, parent)
        self._dialog = None

    def open_dialog(self, manual=False):
        if self._dialog is None:
            self._dialog = UpdatesDialog(self.updater, self.window())
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        if manual:
            self.updater.check(manual=True)
        return self._dialog


class UpdatesDialog(QtWidgets.QDialog):
    """Latest stable status, brief release notes and download preference."""

    def __init__(self, updater, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.setObjectName("UpdatesDialog")
        self.setWindowTitle("Update settings")
        self.resize(470, 340)
        self.setStyleSheet("QDialog#UpdatesDialog { background: palette(window); color: palette(window-text); }")
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(f"{updater.config.app_name} v{updater.version}")
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        self.status = QtWidgets.QLabel()
        self.details = QtWidgets.QLabel()
        for label in (self.status, self.details):
            label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.notes = NotesLabel()
        layout.addWidget(self.notes)
        self.notes_link = QtWidgets.QLabel('<a href="release">Release notes</a>')
        self.notes_link.linkActivated.connect(lambda _: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl(release_notes_url(updater))))
        layout.addWidget(self.notes_link)
        row = QtWidgets.QHBoxLayout()
        self.check_button = QtWidgets.QPushButton("Check now")
        self.check_button.clicked.connect(lambda: updater.check(manual=True))
        self.action = QtWidgets.QPushButton()
        self.action.clicked.connect(self._act)
        row.addWidget(self.check_button)
        row.addWidget(self.action)
        row.addStretch()
        layout.addLayout(row)
        self.auto_checkbox = QtWidgets.QCheckBox("Download updates automatically")
        self.auto_checkbox.setChecked(updater.auto_download)
        self.auto_checkbox.toggled.connect(updater.set_auto_download)
        layout.addWidget(self.auto_checkbox)
        self.last_check = QtWidgets.QLabel()
        self.last_check.setWordWrap(True)
        layout.addWidget(self.last_check)
        layout.addStretch()
        updater.stateChanged.connect(self._changed)
        self._changed(updater.state)

    def _changed(self, state):
        view = button_view(state, self.updater.version, self.updater.auto_download)
        self.status.setText(view.text)
        raw = " ".join(state.message.split())
        self.details.setText("Details: " + (raw[:119] + "…" if len(raw) > 120 else raw))
        self.details.setVisible(state.status == "error" and bool(raw))
        self.notes.setText(getattr(state.info, "notes", "") if state.status in {"available", "ready"} else "")
        self.notes.setVisible(bool(self.notes.text()))
        self.notes_link.setVisible(state.status in {"available", "ready"})
        self.check_button.setEnabled(not view.busy)
        self.action.setVisible(view.action is not None)
        self.action.setText({"download": "Download", "restart": "Restart to update", "page": "Download page"}.get(view.action, ""))
        self.auto_checkbox.blockSignals(True)
        self.auto_checkbox.setChecked(self.updater.auto_download)
        self.auto_checkbox.blockSignals(False)
        value = self.updater.prefs.value("updates/last_check", "", type=str)
        date = QtCore.QDateTime.fromString(value, QtCore.Qt.DateFormat.ISODate)
        last = date.toLocalTime().toString("HH:mm") if date.isValid() else "Never"
        self.last_check.setText(f"Last check: {last}")

    def _act(self):
        action = button_view(self.updater.state, self.updater.version, self.updater.auto_download).action
        if action == "download":
            self.updater.download()
        elif action == "restart":
            self.updater.install()
        elif action == "page":
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.updater.config.download_page))
