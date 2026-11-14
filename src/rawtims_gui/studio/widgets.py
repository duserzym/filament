# Copied from UPbRPy commit 0b16f36, path GUI/widgets.py, on 2026-11-14.
# Only _WorkflowRailDelegate (source lines 173-195) is copied, unchanged; the
# other widgets (SegmentedBar, ChipButton, ...) follow when a step needs them.
# Local changes:
# - imports: only what this class needs; the theme import points at the
#   vendored rawtims_gui.studio.theme instead of GUI.theme.
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims_gui.studio.theme import active_theme, theme_color


class _WorkflowRailDelegate(QtWidgets.QStyledItemDelegate):
    """Keep stage icons and number badges readable in the compact rail."""

    def paint(self, painter, option, index):
        if not self.parent().property("compactRail"):
            return super().paint(painter, option, index)
        theme = active_theme()
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(1, 1, -1, -1)
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        if selected or option.state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(theme_color(theme.accent_soft if selected else theme.row_hover))
            painter.drawRoundedRect(QtCore.QRectF(rect), 9, 9)
        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        icon.paint(painter, QtCore.QRect(rect.left()+5, rect.center().y()-10, 20, 20))
        font = option.font
        font.setPixelSize(9)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(theme.accent if selected else theme.muted))
        painter.drawText(rect.adjusted(27, 0, -2, 0), QtCore.Qt.AlignmentFlag.AlignCenter, str(index.row()+1))
        painter.restore()

