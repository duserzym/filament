# Copied from UPbRPy commit 0b16f36, path GUI/theme.py, on 2026-11-14.
# Local changes:
# - build_application() takes the application and organisation names (the
#   QSettings names) from rawtims.branding instead of "UPbRPy Studio" and
#   "UPbRPy" (import added).
# The control icons it references were copied from the same commit
# (GUI/assets/icons/control-*.svg) into rawtims_gui/studio/assets/icons/.
# - Suite presentation: application accent, quiet surfaces and distinct control shapes.
# The "upbrpy.*" application property names remain compatible with the source.
from __future__ import annotations

import sys
import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from PySide6 import QtCore, QtGui, QtWidgets

import pyqtgraph as pg

from rawtims.branding import QSETTINGS_APP, QSETTINGS_ORG


@dataclass(frozen=True)
class ThemeSpec:
    name: str
    window: str
    window_alt: str
    surface: str
    surface_soft: str
    input_bg: str
    input_border: str
    text: str
    muted: str
    accent: str
    accent_soft: str
    accent_hover: str
    accent_strong: str
    success: str
    success_soft: str
    plot_background: str
    axis_text: str
    axis_line: str
    grid_alpha: float
    shadow_light: str
    shadow_dark: str
    on_accent: str
    glass: str
    glass_strong: str
    glass_border: str
    glass_edge: str
    faint: str
    danger: str
    row_hover: str
    plot_grid: str
    wallpaper: tuple[str, str, str]


THEMES: dict[str, ThemeSpec] = {
    "light": ThemeSpec(
        name="light", window="#eef2f8", window_alt="#eef2f8",
        surface="#ffffff", surface_soft="#ffffff", input_bg="#f8fafd",
        input_border="rgba(23,32,46,0.10)", text="#17202e", muted="#556172",
        accent="#a35746", accent_soft="rgba(163,87,70,0.12)",
        accent_hover="rgba(163,87,70,0.18)", accent_strong="#8b493b",
        success="#1d8a5b", success_soft="rgba(29,138,91,0.12)",
        plot_background="#ffffff", axis_text="#556172", axis_line="#e6e9ef",
        grid_alpha=0.55, shadow_light="#ffffff", shadow_dark="#1f2d50",
        on_accent="#ffffff", glass="rgba(255,255,255,0.72)",
        glass_strong="rgba(255,255,255,0.72)", glass_border="rgba(255,255,255,0.75)",
        glass_edge="rgba(23,32,46,0.08)", faint="#7d8899", danger="#c2413b",
        row_hover="rgba(163,87,70,0.07)", plot_grid="#e6e9ef",
        wallpaper=("#c9dbff", "#c7f0e6", "#f3d9f7"),
    ),
    "dark": ThemeSpec(
        name="dark", window="#0c111b", window_alt="#0c111b",
        surface="#161d2b", surface_soft="#1c2638", input_bg="#121926",
        input_border="rgba(255,255,255,0.10)", text="#e7ecf4", muted="#a3aec0",
        accent="#e6a392", accent_soft="rgba(230,163,146,0.16)",
        accent_hover="rgba(230,163,146,0.24)", accent_strong="#efbcaf",
        success="#56d364", success_soft="rgba(86,211,100,0.12)",
        plot_background="#121926", axis_text="#a3aec0", axis_line="#263043",
        grid_alpha=0.55, shadow_light="#ffffff", shadow_dark="#000000",
        on_accent="#0c111b", glass="rgba(22,29,43,0.82)",
        glass_strong="rgba(22,29,43,0.94)", glass_border="rgba(255,255,255,0.14)",
        glass_edge="rgba(0,0,0,0.40)", faint="#7a879b", danger="#ff7b72",
        row_hover="rgba(230,163,146,0.10)", plot_grid="#263043",
        wallpaper=("#1d3263", "#0f4a45", "#3d1f4a"),
    ),
}


def theme_color(value: str) -> QtGui.QColor:
    """Read a hex or CSS rgba token for use by Qt painters."""
    if value.startswith("rgba("):
        red, green, blue, alpha = map(float, value[5:-1].split(","))
        return QtGui.QColor(int(red), int(green), int(blue), round(alpha * 255))
    return QtGui.QColor(value)


def paint_wallpaper(widget: QtWidgets.QWidget) -> None:
    """Paint the suite's quiet window canvas behind the scientific plots."""
    painter = QtGui.QPainter(widget)
    painter.fillRect(widget.rect(), QtGui.QColor(active_theme().window))


class WallpaperWidget(QtWidgets.QWidget):
    """A transparent central surface over a window's shared wallpaper."""

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if not self.window().property("wallpaperRoot"):
            paint_wallpaper(self)


class _PopupCorners(QtCore.QObject):
    """Clip Qt popup windows to their rounded surface, including native edges."""

    def eventFilter(self, watched, event):
        if event.type() not in (QtCore.QEvent.Type.Polish, QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Resize):
            return False
        if not isinstance(watched, QtWidgets.QWidget):
            return False
        popup = isinstance(watched, QtWidgets.QMenu) or watched.windowType() in (
            QtCore.Qt.WindowType.Popup, QtCore.Qt.WindowType.ToolTip,
        )
        dialog = isinstance(watched, QtWidgets.QDialog)
        if event.type() == QtCore.QEvent.Type.Polish and popup:
            watched.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
            watched.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint, True)
        if event.type() in (QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Resize) and (popup or dialog):
            path = QtGui.QPainterPath()
            radius = 16 if dialog else 12
            path.addRoundedRect(QtCore.QRectF(watched.rect()), radius, radius)
            watched.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))
        return False


class NeumorphicFrame(QtWidgets.QFrame):
    """Paint a quiet suite panel; retain the existing content geometry."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("neumorphic", True)
        self.setContentsMargins(7, 7, 7, 7)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        theme = active_theme()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        body = QtCore.QRectF(self.rect()).adjusted(7, 7, -7, -7)
        if body.width() <= 0 or body.height() <= 0:
            return
        painter.setBrush(theme_color(theme.surface if self.property("floatingPanel") else theme.glass))
        painter.setPen(QtGui.QPen(theme_color(theme.input_border), 1))
        painter.drawRoundedRect(body, 10, 10)



class NeumorphicStyle(QtWidgets.QProxyStyle):
    """Use crisp chevrons for arrow buttons created internally by Qt."""

    def __init__(self) -> None:
        super().__init__("Fusion")

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QtWidgets.QStyle.PrimitiveElement.PE_IndicatorTabClose:
            painter.save()
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            rect = QtCore.QRectF(option.rect).adjusted(1, 1, -1, -1)
            if option.state & QtWidgets.QStyle.StateFlag.State_MouseOver:
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(theme_color(active_theme().accent_soft))
                painter.drawEllipse(rect)
            painter.setPen(QtGui.QPen(QtGui.QColor(active_theme().muted), 1.4,
                                     QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
            center = rect.center()
            painter.drawLine(center + QtCore.QPointF(-2.5, -2.5), center + QtCore.QPointF(2.5, 2.5))
            painter.drawLine(center + QtCore.QPointF(-2.5, 2.5), center + QtCore.QPointF(2.5, -2.5))
            painter.restore()
            return
        if element == QtWidgets.QStyle.PrimitiveElement.PE_PanelItemViewRow and isinstance(widget, QtWidgets.QTreeView):
            return
        arrows = {
            QtWidgets.QStyle.PrimitiveElement.PE_IndicatorArrowDown: ((-3, -1.5), (0, 1.5), (3, -1.5)),
            QtWidgets.QStyle.PrimitiveElement.PE_IndicatorArrowUp: ((-3, 1.5), (0, -1.5), (3, 1.5)),
            QtWidgets.QStyle.PrimitiveElement.PE_IndicatorArrowLeft: ((1.5, -3), (-1.5, 0), (1.5, 3)),
            QtWidgets.QStyle.PrimitiveElement.PE_IndicatorArrowRight: ((-1.5, -3), (1.5, 0), (-1.5, 3)),
        }
        if element not in arrows:
            return super().drawPrimitive(element, option, painter, widget)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        color = QtGui.QColor(active_theme().muted)
        if not option.state & QtWidgets.QStyle.StateFlag.State_Enabled:
            color.setAlphaF(0.35)
        painter.setPen(QtGui.QPen(color, 1.8, QtCore.Qt.PenStyle.SolidLine,
                                 QtCore.Qt.PenCapStyle.RoundCap, QtCore.Qt.PenJoinStyle.RoundJoin))
        center = QtCore.QRectF(option.rect).center()
        path = QtGui.QPainterPath()
        for index, (x, y) in enumerate(arrows[element]):
            point = center + QtCore.QPointF(x, y)
            path.moveTo(point) if index == 0 else path.lineTo(point)
        painter.drawPath(path)
        painter.restore()


def build_application(argv: list[str] | None = None, theme_mode: str = "light") -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv or sys.argv)
    app.setApplicationName(QSETTINGS_APP)
    app.setOrganizationName(QSETTINGS_ORG)
    app.setStyle(NeumorphicStyle())
    app.setFont(_pick_font(app))
    pg.setConfigOptions(antialias=True)
    if not hasattr(app, "_popup_corners"):
        app._popup_corners = _PopupCorners(app)
        app.installEventFilter(app._popup_corners)
    apply_theme(app, theme_mode)
    return app


def resolve_theme_name(app: QtWidgets.QApplication, theme_mode: str) -> str:
    if theme_mode == "system":
        return system_theme_name(app)
    return theme_mode if theme_mode in THEMES else "light"


def system_theme_name(app: QtWidgets.QApplication) -> str:
    try:
        color_scheme = app.styleHints().colorScheme()
    except AttributeError:
        return "light"
    return "dark" if color_scheme == QtCore.Qt.ColorScheme.Dark else "light"


def active_theme(app: QtWidgets.QApplication | None = None) -> ThemeSpec:
    resolved_name = "light"
    application = app or QtWidgets.QApplication.instance()
    if application is not None:
        resolved_name = str(application.property("upbrpy.resolved_theme") or resolved_name)
    return THEMES.get(resolved_name, THEMES["light"])


def apply_theme(app: QtWidgets.QApplication, theme_mode: str) -> ThemeSpec:
    import gc

    resolved_name = resolve_theme_name(app, theme_mode)
    theme = THEMES[resolved_name]
    palette = _build_palette(theme)
    sheet = _stylesheet(theme)
    # Avoid redundant repolishing and cyclic collection while Qt visits widgets.
    # See docs/notes/stylesheet_segfault_2026-11-06.md for the crash hypothesis.
    if app.palette() != palette:
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            app.setPalette(palette)
        finally:
            if was_enabled:
                gc.enable()
    if app.styleSheet() != sheet:
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            app.setStyleSheet(sheet)
        finally:
            if was_enabled:
                gc.enable()
    app.setProperty("upbrpy.theme_mode", theme_mode)
    app.setProperty("upbrpy.resolved_theme", resolved_name)
    for widget in app.topLevelWidgets():
        widget.update()
        for frame in widget.findChildren(NeumorphicFrame):
            frame.update()
    return theme


def _pick_font(app: QtWidgets.QApplication) -> QtGui.QFont:
    for family in [".AppleSystemUIFont", "SF Pro Text", "Segoe UI", "Helvetica Neue", "Arial"]:
        if family in QtGui.QFontDatabase.families():
            font = QtGui.QFont(family)
            font.setPointSizeF(10.5)
            return font
    font = app.font()
    font.setPointSizeF(10.5)
    return font


def _build_palette(theme: ThemeSpec) -> QtGui.QPalette:
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(theme.window))
    palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(theme.input_bg))
    palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor(theme.surface_soft))
    palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(theme.text))
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(theme.text))
    palette.setColor(QtGui.QPalette.ColorRole.Link, QtGui.QColor(theme.accent))
    palette.setColor(QtGui.QPalette.ColorRole.LinkVisited, QtGui.QColor(theme.accent))
    palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(theme.text))
    palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(theme.surface))
    palette.setColor(QtGui.QPalette.ColorRole.Highlight, theme_color(theme.accent_soft))
    palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(theme.accent))
    return palette


def _stylesheet(theme: ThemeSpec) -> str:
    icons = (Path(__file__).parent / "assets" / "icons").as_posix()

    def icon(name: str) -> str:
        return f'url("{icons}/control-{name}-{theme.name}.svg")'

    return f"""
    QWidget {{ color: {theme.text}; }}
    QMainWindow, QTabWidget::pane, QStackedWidget, QLabel {{ background: transparent; border: none; }}
    QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QMenuBar, QStatusBar {{ background: {theme.glass}; border: none; border-radius: 10px; padding: 2px 6px; }}
    QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 8px; }}
    QMenuBar::item:selected {{ background: {theme.accent_soft}; }}
    QStatusBar::item {{ border: none; }}
    QDialog, QMessageBox {{ background: {theme.surface}; border-radius: 16px; }}
    QMenu, QToolTip {{ background: {theme.surface}; color: {theme.text}; border: 1px solid {theme.input_border}; border-radius: 12px; padding: 6px; }}
    QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 8px; }}
    QMenu::item:selected {{ background: {theme.accent_soft}; color: {theme.accent}; }}
    QMenu::separator {{ height: 1px; background: {theme.input_border}; margin: 5px 10px; }}
    QMenu::right-arrow {{ image: {icon("right")}; width: 12px; height: 12px; }}
    QToolTip {{ padding: 7px 10px; }}
    QFrame[neumorphic="true"] {{ background: transparent; border: none; }}
    #WorkflowHintCard, #WorkflowActionsCard, #SelectorCard, #WorkflowCard,
    #PlotControlBar, #StageSegmentBar, #ChannelsCard {{
        background: {theme.glass}; border: 1px solid {theme.glass_border}; border-radius: 16px;
    }}
    #WorkflowActionsInline {{ background: transparent; border: none; }}
    #HeroTitle {{ font-size: 19px; font-weight: 700; }}
    #RailBrand {{ font-size: 18px; font-weight: 700; }}
    #Brand {{ font-size: 24px; font-weight: 700; }}
    #SectionTitle, #MetricLabel, #DetailLabel, #IsotopeElemLabel, #IsotopeSectionLabel {{ color: {theme.muted}; font-size: 10px; font-weight: 600; }}
    #IsotopeSectionLabel {{ font-size: 9px; }}
    #IsotopeSectionLine {{ background: {theme.input_border}; }}
    #MetricValue {{ font-size: 22px; font-weight: 700; }}
    #WorkflowLabel, #WorkflowContextTitle {{ font-size: 12px; font-weight: 600; }}
    #ControlBarDivider {{ background: {theme.input_border}; border: none; }}
    #SecondaryText, #PanelBody, #ControlBarLabel {{ color: {theme.muted}; font-size: 11px; }}
    #InspectorHint, #WorkflowStatusCompact {{ color: {theme.muted}; font-size: 9px; }}
    #Pill, #StatusPill {{ padding: 4px 10px; border-radius: 10px; background: {theme.input_bg}; color: {theme.muted}; }}
    #StatusPill {{ background: {theme.success_soft}; color: {theme.success}; }}
    QPushButton, QToolButton {{
        background: {theme.glass_strong}; border: 1px solid {theme.input_border};
        border-radius: 7px; padding: 7px 11px; font-weight: 600;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {theme.row_hover}; border-color: {theme.accent}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {theme.accent_soft}; }}
    QPushButton[accent="true"] {{ background: {theme.accent}; color: {theme.on_accent}; border-color: {theme.accent}; }}
    QPushButton[accent="true"]:hover {{ background: {theme.accent_strong}; }}
    QPushButton[tertiary="true"] {{ background: transparent; border-color: transparent; }}
    QPushButton[tertiary="true"]:hover {{ background: {theme.row_hover}; }}
    QToolButton[modeToggle="true"] {{ border: none; background: transparent; padding: 5px 6px; border-radius: 9px; font-size: 11px; }}
    QToolButton[modeToggle="true"]:hover {{ background: {theme.row_hover}; }}
    QToolButton:checked, QToolButton[modeToggle="true"]:checked {{ background: {theme.accent_soft}; color: {theme.accent}; }}

    QToolButton[compactToggle="true"] {{ padding: 1px; }}
    QToolButton::menu-indicator {{ image: {icon("down")}; width: 10px; height: 10px; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {theme.faint}; background: {theme.glass}; border-color: {theme.input_border}; }}
    QToolButton[segmentChild="true"], QToolButton[segmentChild="true"]:checked, QToolButton[segmentChild="true"]:disabled {{ background: transparent; border: none; padding: 5px 4px; }}
    QPushButton:focus, QToolButton:focus {{ border: 1px solid {theme.accent}; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar {{ background: transparent; border-bottom: 1px solid {theme.input_border}; }}
    QTabBar::tab {{ background: transparent; color: {theme.muted}; border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 7px 8px; margin: 0; }}
    QTabBar::tab:selected {{ background: transparent; border-bottom: 2px solid {theme.accent}; color: {theme.accent}; font-weight: 600; }}
    QTabBar::tab:hover {{ background: {theme.row_hover}; }}
    QTabBar::close-button {{ width: 18px; height: 18px; border-radius: 9px; background: transparent; }}
    QTabBar QToolButton {{ padding: 2px; border-radius: 8px; background: {theme.surface}; }}
    QTabBar QToolButton::left-arrow {{ image: {icon("left")}; width: 12px; height: 12px; }}
    QTabBar QToolButton::right-arrow {{ image: {icon("right")}; width: 12px; height: 12px; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QTextBrowser {{
        background: {theme.glass_strong}; border: 1px solid {theme.input_border};
        border-radius: 7px; padding: 6px 9px; selection-background-color: {theme.accent_soft}; selection-color: {theme.accent};
    }}
    QComboBox {{ combobox-popup: 0; padding-right: 28px; min-height: 22px; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: 26px; min-height: 22px; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {theme.accent}; }}
    QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {theme.faint}; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; border: none; width: 24px; background: transparent; }}
    QComboBox::down-arrow {{ image: {icon("down")}; width: 14px; height: 14px; }}
    QComboBox::down-arrow:disabled {{ image: {icon("down-disabled")}; }}
    QComboBoxPrivateContainer {{ background: transparent; border: none; }}
    QComboBox QAbstractItemView {{ background: {theme.surface}; border: 1px solid {theme.input_border}; border-radius: 12px; padding: 6px; outline: none; selection-background-color: {theme.accent_soft}; selection-color: {theme.accent}; }}
    QComboBox QAbstractItemView::item {{ padding: 7px 10px; min-height: 20px; border-radius: 8px; }}
    QComboBox QAbstractItemView::item:selected {{ background: {theme.accent_soft}; color: {theme.accent}; }}
    QListView, QTreeView, QTableView {{ background: {theme.glass_strong}; border: 1px solid {theme.input_border}; border-radius: 12px; padding: 4px; outline: none; alternate-background-color: {theme.row_hover}; gridline-color: {theme.input_border}; }}
    QListView::item, QTreeView::item {{ border: none; padding: 4px; border-radius: 8px; }}
    QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {{ background: {theme.row_hover}; }}
    QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {{ background: {theme.accent_soft}; color: {theme.accent}; }}
    QTreeView::branch, QTreeView::branch:selected, QTreeView::branch:hover {{ background: transparent; border-image: none; }}
    QTreeView::branch:has-children:closed {{ image: {icon("right")}; }}
    QTreeView::branch:has-children:open {{ image: {icon("down")}; }}
    #WorkflowStepRail {{ background: transparent; border: none; padding: 0; font-size: 12px; font-weight: 600; }}
    #WorkflowStepRail::item {{ padding: 2px 4px; margin: 1px 0; border-radius: 9px; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: {theme.surface}; color: {theme.muted}; border: none; border-bottom: 1px solid {theme.input_border}; padding: 6px; }}
    QHeaderView::up-arrow {{ image: {icon("up")}; width: 12px; height: 12px; }}
    QHeaderView::down-arrow {{ image: {icon("down")}; width: 12px; height: 12px; }}
    QTableCornerButton::section {{ background: {theme.surface}; border: none; border-top-left-radius: 10px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 24px; margin: 2px 2px 0 0; border: none; border-radius: 6px; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; margin: 0 2px 2px 0; border: none; border-radius: 6px; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {theme.accent_soft}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: {icon("up")}; width: 12px; height: 12px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: {icon("down")}; width: 12px; height: 12px; }}
    QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {{ image: {icon("up-disabled")}; }}
    QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {{ image: {icon("down-disabled")}; }}
    QCheckBox, QRadioButton {{ spacing: 7px; padding: 2px 0; background: transparent; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {theme.input_border}; border-radius: 5px; background: {theme.glass_strong}; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:checked {{ image: {icon("check")}; background: {theme.accent}; border-color: {theme.accent}; }}
    QCheckBox::indicator:indeterminate {{ image: {icon("minus")}; background: {theme.accent}; }}
    QRadioButton::indicator:checked {{ image: {icon("dot")}; border-color: {theme.accent}; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {theme.accent}; }}
    QAbstractItemView::indicator, QListView::indicator, QTreeView::indicator, QTableView::indicator {{ width: 16px; height: 16px; border: 1px solid {theme.input_border}; border-radius: 5px; background: {theme.glass_strong}; }}
    QAbstractItemView::indicator:unchecked, QListView::indicator:unchecked, QTreeView::indicator:unchecked, QTableView::indicator:unchecked {{ image: none; background: {theme.glass_strong}; }}
    QAbstractItemView::indicator:checked, QListView::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked {{ image: {icon("check")}; background: {theme.accent}; border-color: {theme.accent}; }}
    QAbstractItemView::indicator:indeterminate, QListView::indicator:indeterminate, QTreeView::indicator:indeterminate, QTableView::indicator:indeterminate {{ image: {icon("minus")}; background: {theme.accent}; border-color: {theme.accent}; }}
    QAbstractItemView::indicator:hover, QListView::indicator:hover, QTreeView::indicator:hover, QTableView::indicator:hover {{ border-color: {theme.accent}; }}
    QAbstractItemView::indicator:disabled, QListView::indicator:disabled, QTreeView::indicator:disabled, QTableView::indicator:disabled {{ border-color: {theme.muted}; }}
    QAbstractItemView::indicator:unchecked:disabled, QListView::indicator:unchecked:disabled, QTreeView::indicator:unchecked:disabled, QTableView::indicator:unchecked:disabled {{ background: {theme.surface_soft}; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color: {theme.faint}; }}
    QSlider::groove:horizontal {{ height: 5px; border-radius: 2px; background: {theme.input_border}; }}
    QSlider::sub-page:horizontal {{ background: {theme.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ width: 16px; margin: -6px 0; border-radius: 8px; background: {theme.surface}; border: 1px solid {theme.accent}; }}
    QSlider::groove:vertical {{ width: 5px; border-radius: 2px; background: {theme.input_border}; }}
    QSlider::handle:vertical {{ height: 16px; margin: 0 -6px; border-radius: 8px; background: {theme.surface}; border: 1px solid {theme.accent}; }}
    QProgressBar {{ background: {theme.input_border}; border: none; border-radius: 2px; text-align: center; min-height: 4px; }}
    QProgressBar::chunk {{ background: {theme.accent}; border-radius: 2px; }}
    QGroupBox {{ background: {theme.glass}; border: 1px solid {theme.input_border}; border-radius: 16px; margin-top: 16px; padding: 12px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {theme.muted}; }}
    QSplitter::handle {{ background: transparent; border: none; border-radius: 3px; }}
    QSplitter::handle:hover {{ background: {theme.accent_soft}; }}
    #StageSegmentBar {{ background: {theme.input_bg}; border: 1px solid {theme.input_border}; border-radius: 7px; }}
    QToolButton[segmentChild="true"]:checked {{ color: {theme.accent}; }}
    #SaveContract {{ background: {theme.accent}; color: {theme.on_accent}; border-color: {theme.accent}; }}
    #SaveContract:hover {{ background: {theme.accent_strong}; }}
    #SaveContract:disabled {{ background: {theme.surface_soft}; color: {theme.faint}; border-color: {theme.input_border}; }}
    #FloatingPlotTools {{ background: {theme.surface}; border: 1px solid {theme.input_border}; border-radius: 7px; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 1px; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 1px 4px; }}
    QScrollBar::handle {{ background: {theme.accent_hover}; border: none; border-radius: 3px; }}
    QScrollBar::handle:vertical {{ min-height: 28px; }}
    QScrollBar::handle:horizontal {{ min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {theme.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ background: transparent; border: none; width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """
