"""Responsive toolbar, vendored from UPbRPy 780498c / 17c970a, GUI/widgets.py.

Controls move into content-sized overflow submenus; actions and widget state
remain the same objects at every width. No upstream imports.
"""
from PySide6 import QtCore, QtWidgets


class ReviewToolbar(QtWidgets.QWidget):
    """Move secondary control groups into menus when the row is too narrow."""

    def __init__(self):
        super().__init__()
        self.setObjectName("ReviewToolbar")
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
        self.row = QtWidgets.QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.entries = []
        self._order = []
        self.overflow = QtWidgets.QToolButton()
        self.overflow.setText("⋯")
        self.overflow.setFixedHeight(26)
        self.overflow.setToolTip("More plot controls")
        self.overflow.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QtWidgets.QMenu(self.overflow)
        self.overflow.setMenu(self.menu)
        self._style_button(self.overflow)
        self.row.addWidget(self.overflow)
        self.overflow.hide()
        self._busy = False
        self._divider_width = 0

    @staticmethod
    def _style_button(button):
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        if not button.accessibleName():
            button.setAccessibleName(button.toolTip() or button.text())
        button.setProperty("hasToolbarMenu", button.menu() is not None)
        button.setStyleSheet(
            "QToolButton { padding: 2px 3px; min-width: 0px; min-height: 0px; } "
            "QToolButton[hasToolbarMenu=\"true\"] { padding-right: 14px; } "
            "QToolButton::menu-indicator { subcontrol-origin: padding; "
            "subcontrol-position: right center; right: 3px; width: 7px; }")

    def add_separator(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        line.setFixedWidth(1)
        self.row.insertWidget(self.row.count()-1, line)
        self._order.append(line)
        self._divider_width += 1 + self.row.spacing()

    def add_control(self, widget, title, priority=0):
        if isinstance(widget, QtWidgets.QComboBox):
            widget.setStyleSheet("padding: 2px 6px; min-height: 0px;")
            widget.setFixedHeight(26)
        popup = self.menu.addMenu(title)
        content = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(content)
        box.setContentsMargins(6, 6, 6, 6)
        action = QtWidgets.QWidgetAction(popup)
        action.setDefaultWidget(content)
        popup.addAction(action)
        popup.menuAction().setVisible(False)
        for button in ([widget] if isinstance(widget, QtWidgets.QToolButton) else
                       widget.findChildren(QtWidgets.QToolButton)):
            self._style_button(button)
            button.setFixedHeight(26)
        self.row.insertWidget(self.row.count()-1, widget)
        self._order.append(widget)
        self.entries.append((widget, popup, content, priority))
        widget.installEventFilter(self)

    def add_stretch(self):
        self.row.insertStretch(self.row.count()-1, 1)
        self._order.append(None)

    def eventFilter(self, watched, event):
        if (not self._busy and event.type() in (QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Hide,
                                                   QtCore.QEvent.Type.LayoutRequest)):
            QtCore.QTimer.singleShot(0, self, self.reflow)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def showEvent(self, event):
        super().showEvent(event)
        self.reflow()

    def minimumSizeHint(self):
        return QtCore.QSize(50, self.sizeHint().height())

    def reflow(self):
        if self._busy:
            return
        self._busy = True
        try:
            for w, menu, box, _ in self.entries:
                if w.property("toolbarAvailable") is False:
                    menu.menuAction().setVisible(False)
            active = [(w, menu, box, priority) for w, menu, box, priority in self.entries
                      if w.property("toolbarAvailable") is not False
                      and (not w.isHidden() or menu.menuAction().isVisible())]
            widths = {w: w.sizeHint().expandedTo(w.minimumSizeHint()).expandedTo(w.minimumSize())
                      .boundedTo(w.maximumSize()).width() + self.row.spacing() for w, *_ in active}
            total = sum(widths.values()) + self._divider_width - self.row.spacing()
            if getattr(self, 'always_overflow', False):
                total += self.overflow.sizeHint().width() + self.row.spacing()
            folded = set()
            if total > self.width():
                total += self.overflow.sizeHint().width() + self.row.spacing()
                for w, menu, box, priority in sorted(active, key=lambda item: -item[3]):
                    if total <= self.width():
                        break
                    folded.add(w)
                    total -= widths[w]
            for w, menu, box, _ in active:
                if w in folded:
                    if w.parentWidget() is not box:
                        self.row.removeWidget(w)
                        box.layout().addWidget(w)
                    w.show()
                    menu.menuAction().setVisible(True)
                else:
                    if w.parentWidget() is box:
                        box.layout().removeWidget(w)
                        w.setParent(self)
                    menu.menuAction().setVisible(False)
                    w.show()
            desired = [item for item in self._order if item is None or item.parentWidget() is self]
            desired.append(self.overflow)
            current = [self.row.itemAt(i).widget() for i in range(self.row.count())]
            if current != desired:
                while self.row.count():
                    self.row.takeAt(0)
                for item in desired:
                    if item is None:
                        self.row.addStretch(1)
                    else:
                        self.row.addWidget(item)
            self.overflow.setVisible(bool(folded) or getattr(self, 'always_overflow', False))
        finally:
            self._busy = False

