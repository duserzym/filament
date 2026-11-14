"""Desktop entry point: an empty main window in the vendored Studio theme.

Phase 1 step 1 (docs/SPEC.md section 8): the window has the final layout
with placeholders only: the workflow rail on the left, the plot area in the
centre and the inspector on the right.

Command line (the executable name is branding.EXECUTABLE_NAME; the pip
console script is set in pyproject.toml)::

    <app> [--theme light|dark|system]
    <app> --export png PATH     # render the window offscreen and exit
    <app> --version
    <app> --verify ...          # not available yet: exits 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    # Run as a script (PyInstaller's entry point): make `src/` importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims import branding
from rawtims_gui.studio.theme import NeumorphicFrame, WallpaperWidget, build_application, paint_wallpaper
from rawtims_gui.studio.widgets import _WorkflowRailDelegate

WORKFLOW_STEPS = ("Import", "Review", "Correct", "Export")
INSPECTOR_TABS = ("Stats", "Rules", "Corrections", "Export")
DEFAULT_SIZE = QtCore.QSize(1280, 800)
MINIMUM_SIZE = QtCore.QSize(1024, 640)
GEOMETRY_KEY = "window/geometry"
THEME_KEY = "theme_mode"
THEME_MODES = ("light", "dark", "system")


def app_settings() -> QtCore.QSettings:
    """Per-viewer preferences (the user scope of QSettings)."""
    return QtCore.QSettings(branding.QSETTINGS_ORG, branding.QSETTINGS_APP)


def fitted_window_size(available: QtCore.QSize) -> QtCore.QSize:
    """1280 x 800, reduced to the available screen area, never below the minimum."""
    return QtCore.QSize(
        max(MINIMUM_SIZE.width(), min(DEFAULT_SIZE.width(), available.width())),
        max(MINIMUM_SIZE.height(), min(DEFAULT_SIZE.height(), available.height())),
    )


def _section_title(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def _placeholder(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("SecondaryText")
    label.setWordWrap(True)
    label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    return label


class MainWindow(QtWidgets.QMainWindow):
    """The single main window: rail, centre and inspector placeholders."""

    def __init__(self, *, restore_geometry: bool = True) -> None:
        super().__init__()
        self.settings = app_settings()
        self.setWindowTitle(branding.DISPLAY_NAME)
        self.setMinimumSize(MINIMUM_SIZE)
        # Paint one wallpaper behind the central area and the status bar.
        self.setProperty("wallpaperRoot", True)

        central = WallpaperWidget()
        layout = QtWidgets.QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(4)
        layout.addWidget(self._build_rail())
        layout.addWidget(self._build_centre(), 1)
        layout.addWidget(self._build_inspector())
        self.setCentralWidget(central)

        self.version_label = QtWidgets.QLabel(branding.RAW_APP_LABEL)
        self.version_label.setObjectName("VersionLabel")
        self.statusBar().addPermanentWidget(self.version_label)
        self.statusBar().showMessage("No runs open")

        saved = self.settings.value(GEOMETRY_KEY) if restore_geometry else None
        if not (isinstance(saved, QtCore.QByteArray) and self.restoreGeometry(saved)):
            self.resize(self.default_window_size())
            self.centre_on_screen()

    # ------------------------------------------------------------ layout
    def _build_rail(self) -> QtWidgets.QWidget:
        frame = NeumorphicFrame()
        frame.setObjectName("RailPanel")
        frame.setFixedWidth(200)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 14)
        brand = QtWidgets.QLabel(branding.DISPLAY_NAME)
        brand.setObjectName("RailBrand")
        layout.addWidget(brand)
        layout.addWidget(_section_title("Workflow"))
        self.workflow_step_list = QtWidgets.QListWidget()
        self.workflow_step_list.setItemDelegate(_WorkflowRailDelegate(self.workflow_step_list))
        self.workflow_step_list.setObjectName("WorkflowStepRail")
        self.workflow_step_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.workflow_step_list.setSpacing(1)
        for index, name in enumerate(WORKFLOW_STEPS, start=1):
            self.workflow_step_list.addItem(f"{index}  {name}")
        self.workflow_step_list.setCurrentRow(0)
        self.workflow_step_list.setFixedHeight(self.workflow_step_list.sizeHintForRow(0) * len(WORKFLOW_STEPS) + 16)
        layout.addWidget(self.workflow_step_list)
        layout.addWidget(_section_title("Fractions"))
        layout.addWidget(_placeholder("Fractions appear here after import."))
        layout.addStretch(1)
        return frame

    def _build_centre(self) -> QtWidgets.QWidget:
        frame = NeumorphicFrame()
        frame.setObjectName("CentrePanel")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        title = QtWidgets.QLabel("No runs open")
        title.setObjectName("HeroTitle")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(_placeholder(
            "IsotopX IonVantage workbooks (.xls) and IsoLinx files (.TIMSDP) will open here; "
            "reading them comes in a later step."
        ))
        layout.addStretch(1)
        return frame

    def _build_inspector(self) -> QtWidgets.QWidget:
        frame = NeumorphicFrame()
        frame.setObjectName("InspectorPanel")
        frame.setFixedWidth(340)
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(_section_title("Inspector"))
        self.inspector_tabs = QtWidgets.QTabWidget()
        self.inspector_tabs.setDocumentMode(True)
        self.inspector_tabs.setElideMode(QtCore.Qt.TextElideMode.ElideRight)
        self.inspector_tabs.setUsesScrollButtons(False)
        for name in INSPECTOR_TABS:
            self.inspector_tabs.addTab(_placeholder("Nothing to show yet."), name)
        layout.addWidget(self.inspector_tabs, 1)
        return frame

    # ---------------------------------------------------------- geometry
    def default_window_size(self) -> QtCore.QSize:
        """The opening size for this window's screen (see fitted_window_size)."""
        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return QtCore.QSize(DEFAULT_SIZE)
        return fitted_window_size(screen.availableGeometry().size())

    def centre_on_screen(self) -> None:
        screen = self.screen() or QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def persist_geometry(self) -> None:
        self.settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        self.settings.sync()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt API
        paint_wallpaper(self)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 - Qt API
        self.persist_geometry()
        super().closeEvent(event)


def export_window(window: QtWidgets.QMainWindow, output_path: str) -> bool:
    """Render the window (offscreen works) to a PNG; return whether it saved."""
    window.show()
    for _ in range(4):
        QtWidgets.QApplication.processEvents()
    return window.grab().save(output_path, "PNG")


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=branding.EXECUTABLE_NAME, description=f"{branding.DISPLAY_NAME}: raw ID-TIMS data review")
    parser.add_argument("--theme", choices=THEME_MODES, help="Theme for this launch (default: the saved choice, else light)")
    parser.add_argument("--export", nargs=2, metavar=("FORMAT", "PATH"), help="Render the window to PATH and exit; FORMAT must be png")
    parser.add_argument("--version", action="version", version=branding.RAW_APP_LABEL)
    parser.add_argument("--verify", nargs="*", metavar="ARG", help="Not available yet (comes with the readers)")
    args = parser.parse_args(argv)
    if args.verify is not None:
        parser.exit(2, f"{branding.EXECUTABLE_NAME}: --verify is not available yet; it arrives with the readers in a later step.\n")
    if args.export is not None and args.export[0].lower() != "png":
        parser.error(f"--export supports only png, not {args.export[0]!r}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    settings = app_settings()
    theme_mode = args.theme or str(settings.value(THEME_KEY, "light", type=str) or "light")
    if theme_mode not in THEME_MODES:
        theme_mode = "light"
    app = build_application([sys.argv[0]], theme_mode=theme_mode)
    app.setApplicationDisplayName(branding.DISPLAY_NAME)

    if args.export is not None:
        # Scripted export: always 1280 x 800 (the offscreen screen is smaller),
        # nothing read from or written to the saved geometry.
        window = MainWindow(restore_geometry=False)
        window.resize(DEFAULT_SIZE)
        output = Path(args.export[1]).expanduser()
        if not export_window(window, str(output)):
            print(f"Could not write {output}", file=sys.stderr)
            return 1
        return 0

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
