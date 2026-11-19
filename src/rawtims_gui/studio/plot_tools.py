"""Floating plot tools, adapted from UPbRPy f05b970 (GUI/main_window.py).

Drag only a ghost; move the real tools once at release. Geometry events never
reposition the real tools during dragging. Clamp and snap within eight pixels.
"""
from PySide6 import QtCore, QtWidgets


def snap(point, size, area):
    def axis(value, low, high):
        high = max(low, high)
        value = min(high, max(low, value))
        stop = min((low, high), key=lambda p: abs(p-value))
        return stop if abs(stop-value) <= 8 else value
    return QtCore.QPoint(axis(point.x(), area.left(), area.right()+1-size.width()),
                        axis(point.y(), area.top(), area.bottom()+1-size.height()))


class PlotTools(QtWidgets.QFrame):
    modeChanged = QtCore.Signal(str)
    resetRequested = QtCore.Signal()
    moved = QtCore.Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('FloatingPlotTools')
        self.setStyleSheet('#FloatingPlotTools { background: palette(base); border: 1px solid #aab4c4; border-radius: 6px; } QToolButton { padding: 2px 5px; font-size: 11px; }')
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(3, 2, 3, 2)
        row.setSpacing(1)
        self.grip = QtWidgets.QLabel('⠿')
        self.grip.setToolTip('Drag the plot tools; double-click to reset their place')
        self.grip.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        self.grip.installEventFilter(self)
        row.addWidget(self.grip)
        self.buttons = {}
        group = QtWidgets.QButtonGroup(self)
        for mode, text in (('review','Review'),('pan','Pan'),('zoom','Zoom')):
            button = QtWidgets.QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setChecked(mode=='review')
            group.addButton(button)
            button.clicked.connect(lambda checked, m=mode:self.modeChanged.emit(m))
            row.addWidget(button)
            self.buttons[mode]=button
        reset = QtWidgets.QToolButton()
        reset.setText('Reset')
        reset.clicked.connect(self.resetRequested)
        row.addWidget(reset)
        self.adjustSize()
        self.drag = None
        self.ghost = None
        self._has_place = False
        parent.installEventFilter(self)
        self.place()

    def area(self):
        return self.parentWidget().rect().adjusted(6,6,-6,-6)

    def place(self):
        if self.drag is not None:
            return
        point = self.pos() if self._has_place else QtCore.QPoint(self.area().right()+1-self.width(), self.area().top())
        self.move(snap(point,self.size(),self.area()))
        self.raise_()

    def finish(self):
        if self.drag is None:
            return
        target = self.drag[2]
        self.drag = None
        if target is not None:
            self.ghost.hide()
            self.move(target)
            self._has_place = True
            QtWidgets.QApplication.restoreOverrideCursor()
            self.moved.emit(target)

    def eventFilter(self, watched, event):
        kind=event.type()
        if watched is self.parentWidget() and kind == QtCore.QEvent.Type.Resize:
            self.place()
        if watched is not self.grip:
            return False
        if kind in (QtCore.QEvent.Type.Hide, QtCore.QEvent.Type.WindowDeactivate, QtCore.QEvent.Type.UngrabMouse):
            self.finish()
        if kind == QtCore.QEvent.Type.MouseButtonPress and event.button()==QtCore.Qt.MouseButton.LeftButton:
            self.finish()
            self.drag=(event.globalPosition().toPoint(), self.pos(), None)
            return True
        if kind == QtCore.QEvent.Type.MouseMove and self.drag is not None:
            if not event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                self.finish()
                return True
            start, origin, target = self.drag
            delta = event.globalPosition().toPoint()-start
            if target is None:
                if delta.manhattanLength() < QtWidgets.QApplication.startDragDistance():
                    return True
                if self.ghost is None:
                    self.ghost=QtWidgets.QLabel(self.window(),QtCore.Qt.WindowType.ToolTip|QtCore.Qt.WindowType.FramelessWindowHint)
                    for attribute in (QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating,
                                      QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                        self.ghost.setAttribute(attribute)
                self.ghost.setPixmap(self.grab())
                self.ghost.setFixedSize(self.size())
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            target=snap(origin+delta,self.size(),self.area())
            self.drag=(start,origin,target)
            self.ghost.move(self.parentWidget().mapToGlobal(target))
            self.ghost.show()
            return True
        if kind == QtCore.QEvent.Type.MouseButtonRelease and self.drag is not None:
            self.finish()
            return True
        if kind == QtCore.QEvent.Type.MouseButtonDblClick:
            self.finish()
            self._has_place=False
            self.place()
            return True
        return False

    def hideEvent(self,event):
        self.finish()
        super().hideEvent(event)
