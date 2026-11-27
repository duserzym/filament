"""Qt workers, update scheduling and palette-based compact update controls."""

import atexit
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import shutil
import urllib.parse
import weakref

from PySide6 import QtCore, QtGui, QtWidgets

from . import install, tls
from .manifest import Release, NoUpdateForPlatform, compare_versions, fetch_manifest
from .minisign import parse_public_key
from .state import STATES, UpdateState, button_view, transition

_RUNNING = set()


def _wait_for_threads():
    for thread in tuple(_RUNNING):
        thread.requestInterruption()
        thread.wait()


atexit.register(_wait_for_threads)


class _Worker(QtCore.QThread):
    result = QtCore.Signal(object)

    def __init__(self, operation, updater):
        super().__init__(updater)
        self.operation = operation
        self.config, self.version = updater.config, updater.version
        self.opener, self.runner = updater._opener, updater._runner
        self.info, self.path, self.root = updater.state.info, updater.state.path, updater.root

    def run(self):
        try:
            if self.operation == "check":
                try:
                    release = fetch_manifest(self.config, self.opener)
                except NoUpdateForPlatform as exc:
                    self.result.emit(("unsupported", str(exc)))
                    return
                self.result.emit(("found", release) if compare_versions(release.version, self.version) > 0 else ("no_update",))
            elif self.operation == "download":
                path = install.download_archive(self.info, self.config, self.opener,
                    progress=lambda n, total: self.result.emit(("progress", n, total)),
                    cancelled=self.isInterruptionRequested)
                self.result.emit(("downloaded", path))
            elif self.operation == "install":
                script = install.prepare_install(self.path, self.root, self.info, self.config, self.runner)
                self.result.emit(("installed", script))
        except Exception as exc:
            self.result.emit(("failed", exc))


class Updater(QtCore.QObject):
    """One updater per app; injected I/O, root and previews support offline testing."""

    stateChanged = QtCore.Signal(object)
    whatsNew = QtCore.Signal(str, str)

    def __init__(self, config, version: str, parent=None, *, opener=None, runner=None,
                 preview=None, settings=None, root=None):
        super().__init__(parent or QtCore.QCoreApplication.instance())
        self.config, self.version = config, version
        self.root = Path(root) if root is not None else install.install_root()
        self._opener, self._runner = opener or config.opener or tls.urlopen, runner or install.detached_runner
        self._prefs = settings if settings is not None else QtCore.QSettings(config.settings_org, config.settings_app)
        self._prefs.setValue("updates/channel", "stable")
        self._whats_new = None
        self._state = UpdateState(app_name=config.app_name, host=urllib.parse.urlsplit(config.feed_url).hostname or "github.com")
        self._jobs = []
        self._downloads = set()
        self._closing = self._started = False
        self._reason = ""
        self._preview = preview
        self._initial_timer = QtCore.QTimer(self)
        self._initial_timer.setSingleShot(True)
        self._initial_timer.setInterval(8000)
        self._initial_timer.timeout.connect(self.check)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(6 * 60 * 60 * 1000)
        self._timer.timeout.connect(self.check)
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(600)
        self._preview_timer.timeout.connect(self._preview_checked)
        if preview is not None:
            if preview not in STATES:
                raise ValueError(f"Unknown update preview: {preview}")
            info = Release("2.0.0", "Release notes", None, config.download_page, "")
            self._state = replace(self._state, status=preview, info=info if preview in {"available", "downloading", "ready", "installing", "unsupported"} else None,
                                  progress=43, total=100, message="Network error" if preview == "error" else "Preview" if preview == "unsupported" else "")
        self._preview_state = self._state
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def state(self):
        return self._state

    @property
    def prefs(self):
        return self._prefs

    @property
    def auto_download(self):
        return self.prefs.value("updates/auto_download", True, type=bool)

    def set_auto_download(self, enabled):
        """Persist the preference and download an already available update."""
        self.prefs.setValue("updates/auto_download", bool(enabled))
        self.stateChanged.emit(self.state)
        if enabled:
            self.download()

    def _emit(self, event):
        self._state = transition(self.state, event)
        self.stateChanged.emit(self.state)

    def _support_reason(self):
        if not self.config.pubkey.strip():
            return "not_configured", "no public key configured"
        try:
            parse_public_key(self.config.pubkey)
        except ValueError as exc:
            return "not_configured", str(exc)
        if not install.can_replace(self.root):
            return "not_writable", "Installation folder is not writable or this is a source checkout"
        return "", ""

    def current_notes(self):
        """Return bundled notes, matching pending notes, or a version fallback."""
        text = self.config.release_notes(self.version) if self.config.release_notes else None
        if not text and str(self.prefs.value("updates/pending_version", "")).removeprefix("v") == self.version.removeprefix("v"):
            text = self.prefs.value("updates/pending_notes", "", type=str)
        return text or f"Updated to v{self.version.removeprefix('v')}."

    def show_whats_new(self):
        """Reopen the running version's notes without changing first-run settings."""
        self.whatsNew.emit(self.version, self.current_notes())

    def start(self):
        """Record the running version and announce an upgrade once per settings store."""
        if self._started or self._preview is not None or self._closing:
            return
        previous = self.prefs.value("updates/last_seen_version", "", type=str)
        try:
            newer = bool(previous and compare_versions(self.version, previous) > 0)
        except ValueError:
            newer = False
        if newer:
            self._whats_new = (self.version, self.current_notes())
            # Startup precedes widget creation in some hosts; deliver after it.
            QtCore.QTimer.singleShot(0, lambda: self.whatsNew.emit(*self._whats_new))
        self.prefs.setValue("updates/last_seen_version", self.version)
        self._start_scheduler()

    def start_scheduler(self):
        """Compatibility entry point for start()."""
        self.start()

    def _start_scheduler(self):
        """Discard the backup and schedule supported checks."""
        if self._started or self._preview is not None or self._closing:
            return
        self._started = True
        kind, reason = self._support_reason()
        if reason:
            self._emit(("unsupported", reason, kind))
            return
        try:
            install.cleanup_previous(self.root)
        except OSError:
            pass
        self._initial_timer.start()
        self._timer.start()

    @QtCore.Slot()
    def check(self, manual=False):
        """Request a background check; manual checks also work in source checkouts."""
        if self._closing or self._jobs:
            return
        if self._preview is not None:
            if manual:
                self._emit(("check_started", True))
                self._preview_timer.start()
            return
        kind, self._reason = self._support_reason()
        if self._reason and not manual:
            self._emit(("unsupported", self._reason, kind))
            return
        before = self.state
        self._emit(("check_started", manual))
        if self.state is not before:
            self._work("check")

    def _preview_checked(self):
        self._state = replace(self._preview_state, status="none" if self._preview == "idle" else self._preview, manual=True)
        self.stateChanged.emit(self.state)

    @QtCore.Slot()
    def download(self):
        """Download and verify the selected archive without blocking the interface."""
        if self._closing or self._jobs or self._preview is not None or self.state.status != "available":
            return
        kind, reason = self._support_reason()
        if reason:
            self._emit(("unsupported", reason, kind))
            return
        self._emit("download_started")
        self._work("download")

    @QtCore.Slot()
    def install(self):
        """Stage the verified update and quit only once its helper has launched."""
        if self._closing or self._jobs or self._preview is not None or self.state.status != "ready":
            return
        kind, reason = self._support_reason()
        if reason:
            self._emit(("unsupported", reason, kind))
            return
        self.prefs.setValue("updates/pending_version", self.state.info.version)
        self.prefs.setValue("updates/pending_notes", self.state.info.notes)
        self.prefs.sync()
        self._emit("install_started")
        self._work("install")

    def _work(self, operation):
        worker = _Worker(operation, self)
        self._jobs.append(worker)
        _RUNNING.add(worker)
        worker.result.connect(self._result)
        worker.finished.connect(self._finished)
        worker.start()

    @QtCore.Slot(object)
    def _result(self, event):
        if event[0] == "downloaded":
            self._downloads.add(Path(event[1]).parent)
        if self._closing:
            return
        if event[0] == "installed":
            QtCore.QCoreApplication.quit()
            return
        was_checking = self.state.status == "checking"
        self._state = transition(self.state, event)
        if was_checking and event[0] in {"found", "no_update", "failed", "unsupported"}:
            self.prefs.setValue("updates/last_check", datetime.now(timezone.utc).isoformat())
            self.prefs.setValue("updates/last_result", button_view(self.state, self.version).text)
            if self._reason and event[0] != "failed":
                kind, reason = self._support_reason()
                self._state = transition(self.state, ("unsupported", reason, kind))
        self.stateChanged.emit(self.state)

    @QtCore.Slot()
    def _finished(self):
        worker = self.sender()
        worker.wait()
        self._jobs.remove(worker)
        _RUNNING.discard(worker)
        worker.deleteLater()
        if not self._closing and self.state.status == "available" and self.auto_download:
            self.download()

    @QtCore.Slot()
    def shutdown(self):
        """Stop timers, interrupt downloads and join workers before Qt destruction."""
        self._closing = True
        for timer in (self._initial_timer, self._timer, self._preview_timer):
            timer.stop()
        for worker in self._jobs:
            worker.requestInterruption()
        for worker in self._jobs:
            worker.wait()
            _RUNNING.discard(worker)
        # A worker may have completed during wait; consume its queued result first.
        QtCore.QCoreApplication.sendPostedEvents(self, QtCore.QEvent.Type.MetaCall)
        for folder in self._downloads:
            shutil.rmtree(folder, ignore_errors=True)
        self._downloads.clear()


def release_notes_url(updater):
    """Return the selected release's public notes page."""
    version = getattr(updater.state.info, "version", updater.version).removeprefix("v")
    return f"https://github.com/{updater.config.repo}/releases/tag/v{version}"


class NotesLabel(QtWidgets.QLabel):
    """Plain notes rendered in at most four wrapped lines, ending in an ellipsis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setFixedHeight(self.fontMetrics().lineSpacing() * 4)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.ColorRole.WindowText))
        lines = []
        for paragraph in self.text().splitlines():
            layout = QtGui.QTextLayout(paragraph or " ", self.font())
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(max(1, self.width()))
                lines.append(paragraph[line.textStart():line.textStart() + line.textLength()])
            layout.endLayout()
        metrics = self.fontMetrics()
        for index, line in enumerate(lines[:4]):
            if index == 3 and len(lines) > 4:
                line = metrics.elidedText(line + "…", QtCore.Qt.TextElideMode.ElideRight, self.width())
            painter.drawText(0, metrics.ascent() + index * metrics.lineSpacing(), line)


class WhatsNewCard(QtWidgets.QFrame):
    """Dismissible, palette-based running-version notes anchored near a check button."""

    def __init__(self, button):
        super().__init__(button, QtCore.Qt.WindowType.Popup)
        self.button = button
        if not hasattr(button.updater, "_note_buttons"):
            button.updater._note_buttons = weakref.WeakSet()
        button.updater._note_buttons.add(button)
        self.setObjectName("WhatsNewCard")
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QtGui.QPalette.ColorRole.Button)
        self.setAutoFillBackground(True)
        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.heading = QtWidgets.QLabel()
        row.addWidget(self.heading)
        close = QtWidgets.QToolButton()
        close.setText("✕")
        close.setAccessibleName("Close what’s new")
        close.clicked.connect(self.hide)
        row.addWidget(close)
        layout.addLayout(row)
        self.notes = QtWidgets.QLabel()
        self.notes.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)
        button.updater.whatsNew.connect(self.show_notes)

    @QtCore.Slot(str, str)
    def show_notes(self, version, text):
        buttons = []
        for button in self.button.updater._note_buttons:
            try:
                if button.isVisible():
                    buttons.append(button)
            except RuntimeError:
                # Qt may have deleted a tab before Python collects its wrapper.
                continue
        active = QtWidgets.QApplication.activeWindow()
        candidates = [button for button in buttons if button.window() is active] or buttons
        if not candidates or self.button is not candidates[0]:
            return
        self.heading.setText(f"What's new in v{version.removeprefix('v')}")
        self.notes.setText(text)
        bounds = self.button.screen().availableGeometry()
        self.setFixedWidth(min(390, bounds.width() - 20))
        margins = self.layout().contentsMargins()
        notes_width = self.width() - margins.left() - margins.right() - 2 * self.frameWidth()
        self.notes.setFixedHeight(self.notes.heightForWidth(max(1, notes_width)))
        self.adjustSize()
        point = self.button.mapToGlobal(QtCore.QPoint(self.button.width(), 0))
        self.move(max(bounds.left(), min(point.x() - self.width(), bounds.right() - self.width() + 1)),
                  max(bounds.top(), min(point.y() - self.height() - 6, bounds.bottom() - self.height() + 1)))
        self.show()
        self.setFocus()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        # Hosts supply their opaque panel colour through the Button palette role.
        # Normalise alpha here so inherited glass palettes cannot reveal content.
        surface = self.palette().color(QtGui.QPalette.ColorRole.Button)
        surface.setAlpha(255)
        painter.fillRect(self.rect(), surface)
        painter.end()
        super().paintEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


class UpdatePopover(QtWidgets.QFrame):
    """A screen-clamped popover with release notes, actions and raw diagnostics."""

    def __init__(self, button, open_settings=None):
        super().__init__(button, QtCore.Qt.WindowType.Popup)
        self.button, self.updater = button, button.updater
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QtGui.QPalette.ColorRole.Button)
        self.setAutoFillBackground(True)
        self.setFixedWidth(370)
        self.setStyleSheet("""
            QPushButton { background-color: palette(button); color: palette(button-text);
                border: 1px solid palette(mid); border-radius: 4px; padding: 4px 8px; }
            QPushButton:hover { background-color: palette(midlight); }
            QPushButton:disabled { color: palette(mid); }
        """)
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = QtWidgets.QLabel(self.updater.config.app_name)
        self.heading.setWordWrap(True)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.details = QtWidgets.QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setMaximumHeight(70)
        self.notes = NotesLabel()
        for widget in (self.heading, self.status, self.details, self.notes):
            layout.addWidget(widget)
        self.notes_link = QtWidgets.QLabel('<a href="release">Release notes</a>')
        self.notes_link.linkActivated.connect(lambda _: QtGui.QDesktopServices.openUrl(
            QtCore.QUrl(release_notes_url(self.updater))))
        layout.addWidget(self.notes_link)
        self.whats_new_link = QtWidgets.QLabel("<a href=\"new\">What's new</a>")
        self.whats_new_link.linkActivated.connect(lambda _: self._show_whats_new())
        layout.addWidget(self.whats_new_link)
        row = QtWidgets.QHBoxLayout()
        self.check_button = QtWidgets.QPushButton("Check now")
        self.check_button.clicked.connect(lambda: self.updater.check(manual=True))
        self.action = QtWidgets.QPushButton()
        self.action.clicked.connect(self._act)
        row.addWidget(self.check_button)
        row.addWidget(self.action)
        layout.addLayout(row)
        self.auto = QtWidgets.QCheckBox("Download updates automatically")
        self.auto.setChecked(self.updater.auto_download)
        self.auto.toggled.connect(self.updater.set_auto_download)
        layout.addWidget(self.auto)
        if open_settings is not None:
            settings = QtWidgets.QPushButton("Update settings")
            settings.clicked.connect(open_settings)
            layout.addWidget(settings)
        self.updater.stateChanged.connect(self._changed)
        button.installEventFilter(self)
        self._changed(self.updater.state)

    def _changed(self, state):
        view = button_view(state, self.updater.version, self.updater.auto_download)
        self.status.setText(view.text)
        raw = " ".join(state.message.split())
        self.details.setText("Details: " + (raw[:119] + "…" if len(raw) > 120 else raw))
        self.details.setToolTip(state.message)
        self.details.setVisible(state.status == "error" and bool(state.message))
        self.notes.setText(getattr(state.info, "notes", "") if state.status in {"available", "ready"} else "")
        self.notes.setVisible(bool(self.notes.text()))
        self.notes_link.setVisible(state.status in {"available", "ready"})
        self.action.setVisible(view.action is not None)
        self.action.setText({"download": "Download", "restart": "Restart to update", "page": "Download page"}.get(view.action, ""))
        self.check_button.setEnabled(not view.busy)
        if self.isVisible():
            self.adjustSize()
            self.reanchor()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        # Hosts supply their opaque panel colour through the Button palette role.
        # Normalise alpha here so inherited glass palettes cannot reveal content.
        surface = self.palette().color(QtGui.QPalette.ColorRole.Button)
        surface.setAlpha(255)
        painter.fillRect(self.rect(), surface)
        painter.end()
        super().paintEvent(event)

    def _show_whats_new(self):
        self.hide()
        self.updater.show_whats_new()

    def _act(self):
        action = button_view(self.updater.state, self.updater.version, self.updater.auto_download).action
        if action == "download":
            self.updater.download()
        elif action == "restart":
            self.updater.install()
        elif action == "page":
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.updater.config.download_page))

    def reanchor(self):
        rect = self.button.screen().availableGeometry()
        point = self.button.mapToGlobal(QtCore.QPoint(0, 0))
        x = max(rect.left(), min(point.x() + self.button.width() - self.width(), rect.right() - self.width() + 1))
        y = point.y() - self.height() - 6
        if y < rect.top():
            y = point.y() + self.button.height() + 6
        y = max(rect.top(), min(y, rect.bottom() - self.height() + 1))
        self.move(x, y)

    def showEvent(self, event):
        self.button.window().installEventFilter(self)
        self.adjustSize()
        self.reanchor()
        super().showEvent(event)

    def hideEvent(self, event):
        self.button.window().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if self.isVisible() and event.type() in {QtCore.QEvent.Type.Move, QtCore.QEvent.Type.Resize}:
            self.reanchor()
        if watched is self.button.window() and event.type() in {QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.Close}:
            self.hide()
        return super().eventFilter(watched, event)


class CheckUpdatesButton(QtWidgets.QToolButton):
    """Always-visible painted circular arrows with a badge and busy rotation."""

    def __init__(self, updater, open_settings=None, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.setObjectName("CheckUpdatesButton")
        self.setIconSize(QtCore.QSize(16, 16))
        self.setAccessibleName("Check for updates")
        self.setAutoRaise(True)
        self.setFixedSize(21, 21)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._angle = 0
        self._rotation_timer = QtCore.QTimer(self)
        self._rotation_timer.setInterval(40)
        self._rotation_timer.timeout.connect(self._rotate)
        self.whats_new_card = WhatsNewCard(self)
        self.popover = UpdatePopover(self, open_settings)
        self.installEventFilter(self)
        self.clicked.connect(self._toggle)
        updater.stateChanged.connect(self._changed)
        self._changed(updater.state)

    def _toggle(self):
        if self.popover.isVisible():
            self.popover.hide()
        else:
            if self.updater.state.status in {"idle", "none", "error", "unsupported"}:
                self.updater.check(manual=True)
            self.popover.show()

    def _rotate(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def _changed(self, state):
        view = button_view(state, self.updater.version, self.updater.auto_download)
        self.setProperty("badge", view.badge)
        self.setProperty("busy", view.busy)
        self.setToolTip(f"Check for updates · v{self.updater.version} · {view.text}")
        if view.busy and self.isVisible() and self.style().styleHint(QtWidgets.QStyle.StyleHint.SH_Widget_Animate, None, self):
            self._rotation_timer.start()
        else:
            self._rotation_timer.stop()
            self._angle = 0
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._changed(self.updater.state)

    def hideEvent(self, event):
        self._rotation_timer.stop()
        self.popover.hide()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if watched is self and event.type() == QtCore.QEvent.Type.StyleChange:
            self._changed(self.updater.state)
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.save()
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._angle)
        painter.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.ColorRole.ButtonText), 1.6,
                                  QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        for rotation in (0, 180):
            painter.save()
            painter.rotate(rotation)
            painter.drawArc(QtCore.QRectF(-6, -6, 12, 12), 20 * 16, 140 * 16)
            painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(-7, -5), QtCore.QPointF(-5.6, -2), QtCore.QPointF(-2.5, -3.5)]))
            painter.restore()
        painter.restore()
        if self.property("badge"):
            painter.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.ColorRole.Window), 1.2))
            painter.setBrush(self.palette().brush(QtGui.QPalette.ColorRole.Highlight))
            painter.drawEllipse(QtCore.QPointF(self.width() - 4, 4), 3, 3)


class VersionChip(QtWidgets.QToolButton):
    """An anchored version control sharing the updater's popover and badge."""

    def __init__(self, updater, parent=None):
        super().__init__(parent)
        self.updater, self._canvas = updater, None
        self.setObjectName("VersionChip")
        self.setAutoRaise(True)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Application version and updates")
        self.setStyleSheet("""
            QToolButton { background-color: palette(button); color: palette(button-text);
                border: 1px solid palette(mid); border-radius: 12px; padding: 4px 10px; }
            QToolButton:hover { background-color: palette(midlight); }
        """)
        self.popover = UpdatePopover(self)
        self.clicked.connect(self.open_dialog)
        updater.stateChanged.connect(self._changed)
        self._changed(updater.state)

    def _changed(self, state):
        view = button_view(state, self.updater.version)
        self.setProperty("badge", view.badge)
        self.setText(f"v{self.updater.version.removeprefix('v')}")
        self.setToolTip(view.text)
        self._position()

    def anchor_to(self, parent_widget):
        """Keep the chip ten pixels inside a resizable canvas."""
        if self._canvas is not None:
            self._canvas.removeEventFilter(self)
            if isinstance(self._canvas, QtWidgets.QStackedWidget):
                self._canvas.currentChanged.disconnect(self._position)
        self._canvas = parent_widget
        self.setParent(parent_widget)
        parent_widget.installEventFilter(self)
        if isinstance(parent_widget, QtWidgets.QStackedWidget):
            parent_widget.currentChanged.connect(self._position)
        self._position()
        self.show()

    def _position(self, *_args):
        self.adjustSize()
        if self._canvas is not None:
            self.move(max(0, self._canvas.width() - self.width() - 10), max(0, self._canvas.height() - self.height() - 10))
            self.raise_()

    def eventFilter(self, watched, event):
        if watched is self._canvas and event.type() in {QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Show, QtCore.QEvent.Type.LayoutRequest}:
            self._position()
        return super().eventFilter(watched, event)

    def open_dialog(self, manual=False):
        """Show update details; a manual Help-menu invocation also checks now."""
        if manual:
            self.updater.check(manual=True)
        self.popover.show()
        return self.popover
