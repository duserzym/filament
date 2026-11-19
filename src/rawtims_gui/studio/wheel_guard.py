# Vendored from UPbRPy commit 428b57f, GUI/wheel_guard.py. No upstream imports.
"""Keep wheel gestures for scrolling rather than editing form values."""

from PySide6 import QtCore, QtGui, QtWidgets


class WheelGuard(QtCore.QObject):
    """Block wheel edits, forwarding gestures to the nearest scroll area."""

    def eventFilter(self, watched, event):
        if not isinstance(watched, QtWidgets.QWidget):
            return False
        guarded = (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QSlider)
        if event.type() == QtCore.QEvent.Type.Polish and isinstance(watched, guarded):
            watched.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        if event.type() != QtCore.QEvent.Type.Wheel:
            return False
        widget = watched
        while widget is not None:
            # A combo popup owns an item view. Its list must retain wheel scrolling.
            if isinstance(widget, QtWidgets.QAbstractItemView):
                return False
            if isinstance(widget, guarded):
                break
            widget = widget.parentWidget()
        if widget is None:
            return False
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QtWidgets.QAbstractScrollArea):
                viewport = parent.viewport()
                forwarded = QtGui.QWheelEvent(
                    QtCore.QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                    event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                    event.buttons(), event.modifiers(), event.phase(), event.inverted(),
                    event.source(), event.pointingDevice(),
                )
                QtWidgets.QApplication.sendEvent(viewport, forwarded)
                break
            parent = parent.parentWidget()
        event.accept()
        return True


def install_wheel_guard(app: QtWidgets.QApplication) -> WheelGuard:
    """Install one guard per application, including windows built by tests."""
    guard = getattr(app, "_studio_wheel_guard", None)
    if guard is None:
        guard = WheelGuard(app)
        app.installEventFilter(guard)
        app._studio_wheel_guard = guard
    return guard
