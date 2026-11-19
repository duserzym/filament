# Vendored from UPbRPy 697e532, GUI/splitters.py; local theme import only.
"""Consistent splitter hit areas, grip lines and drag cursors for Studio."""

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims_gui.studio.theme import active_theme, theme_color


class _SplitterHandle(QtWidgets.QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._pressed = False
        self._cursor_override = False
        self.setMouseTracking(True)
        self.sync_cursor()

    def sync_cursor(self):
        shape = (QtCore.Qt.CursorShape.SplitHCursor
                 if self.orientation() == QtCore.Qt.Orientation.Horizontal
                 else QtCore.Qt.CursorShape.SplitVCursor)
        self.setCursor(shape)

    def enterEvent(self, event):
        self.sync_cursor()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.sync_cursor()
            self._pressed = True
            # Preserve any previous application override (for example busy).
            QtWidgets.QApplication.setOverrideCursor(self.cursor())
            self._cursor_override = True
            self.splitter().dragStarted.emit()
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressed and not event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._finish_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # QSplitter commits its final geometry before deferred plot work resumes.
        super().mouseReleaseEvent(event)
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._finish_drag()

    def _finish_drag(self):
        if not getattr(self, "_pressed", False):
            return
        self._pressed = False
        if self._cursor_override:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._cursor_override = False
        self.update()
        self.splitter().dragFinished.emit()

    def event(self, event):
        if event.type() in {QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.WindowDeactivate,
                            QtCore.QEvent.Type.UngrabMouse}:
            self._finish_drag()
        return super().event(event)

    def paintEvent(self, event):
        theme = active_theme()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = theme_color(theme.accent if self._pressed or self.underMouse() else theme.input_border)
        painter.setPen(QtGui.QPen(color, 2 if self._pressed or self.underMouse() else 1,
                                 QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        centre = QtCore.QPointF(self.rect().center())
        # A quiet central grip leaves the full 10 px handle available to grab.
        if self.orientation() == QtCore.Qt.Orientation.Horizontal:
            extent = min(28., max(0., (self.height() - 8) / 2))
            painter.drawLine(centre + QtCore.QPointF(0, -extent), centre + QtCore.QPointF(0, extent))
        else:
            extent = min(28., max(0., (self.width() - 8) / 2))
            painter.drawLine(centre + QtCore.QPointF(-extent, 0), centre + QtCore.QPointF(extent, 0))


class StudioSplitter(QtWidgets.QSplitter):
    """A live splitter with 10 px handles and a cursor held through release."""

    dragStarted = QtCore.Signal()
    dragFinished = QtCore.Signal()

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setHandleWidth(10)
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)

    def createHandle(self):
        return _SplitterHandle(self.orientation(), self)

    def setOrientation(self, orientation):
        super().setOrientation(orientation)
        for index in range(self.count()):
            self.handle(index).sync_cursor()


class RasterResizePreview(QtCore.QObject):
    """Adapted from UPbRPy 697e532: scale a raster during a live divider drag.

    Keep layout geometry live; postpone expensive plot paints until release.
    The preview is a sibling, so disabling plot updates does not disable it.
    """
    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot
        self.overlay = None
        plot.installEventFilter(self)

    def begin(self):
        if not self.plot.isVisible() or self.overlay is not None:
            return
        self.overlay = QtWidgets.QLabel(self.plot.parentWidget())
        self.overlay.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.setScaledContents(True)
        self.overlay.setPixmap(self.plot.grab())
        self.overlay.setGeometry(self.plot.geometry())
        self.plot.setUpdatesEnabled(False)
        self.overlay.show()
        self.overlay.raise_()

    def finish(self):
        self.plot.setUpdatesEnabled(True)
        if self.overlay is not None:
            self.overlay.hide()
            self.overlay.deleteLater()
            self.overlay = None
        self.plot.update()

    def eventFilter(self, watched, event):
        if self.overlay is not None:
            if event.type() in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Move):
                self.overlay.setGeometry(self.plot.geometry())
            elif event.type() in (QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.Destroy):
                self.finish()
        return False
