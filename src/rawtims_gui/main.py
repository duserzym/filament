"""Desktop entry point and main window (SPEC section 5, Phase 1 steps 5-7: GUI steps A and B, sessions).

The window has the workflow rail and the fraction list on the left, the
review area in the centre (mode bar Ratios | Intensities | Table, the cycle
plot wall or the cycle table) and the inspector on the right: Stats, Rules
(preview, apply, history), Corrections (oxide correction and mapping) and
Export (fraction fields, contract preview, CSV, clipboard and cycles).

Every rejection and setting goes through :class:`rawtims.analysis.Analysis`
operations, so statistics, plots and table update at once and Undo/Redo walk
the history. Nothing is rejected automatically (SPEC section 0, decision 3):
a rule is previewed first and applied only on request.

Sessions (SPEC F18, :mod:`rawtims.session`): File > New Session, Open
Session…, Open Recent (per viewer, at most 8), Save (⌘S) and Save As… (⇧⌘S).
Open Files… and drag and drop route by content, so a session file opens as a
session. The title shows the session name and "Edited" while there are
unsaved changes (the state is compared with what the file holds, so undoing
back to the saved state is clean again). Closing, New Session and opening
another session ask Save / Don't Save / Cancel first. Exported rows carry
``Raw App Session`` only while the session is saved and unchanged. While
there are unsaved changes a recovery copy is written to the app cache
(:mod:`rawtims_gui.recovery`); one left by a crash is offered on the next
launch in a bar above the review area, without a modal dialog.

Command line (the executable name is branding.EXECUTABLE_NAME; the pip
console script is set in pyproject.toml)::

    <app> [--theme light|dark|system] [--open PATH ...]   # PATH: run files, folders or one session
    <app> --export png PATH [--open PATH ...]   # render the window offscreen and exit
    <app> --verify PATH ... --verification-output OUT.csv   # headless contract CSV, no window
    <app> --version
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    # Run as a script (PyInstaller's entry point): make `src/` importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims import branding
from rawtims.analysis import Analysis
from rawtims.contract import ContractError, write_csv
from rawtims.exports import CLIPBOARD_SEPARATOR, clipboard_text, write_cycles_csv
from rawtims import session as session_io
from rawtims.fractions import Fraction, FractionError, SessionInfo
from rawtims.mapping import ElementMapping, MappingError, MethodMapping
from rawtims.rules import RuleProposal
from rawtims_gui import recovery
from rawtims_gui.corrections_panel import CorrectionsPanel
from rawtims_gui.cycle_table import CycleTable
from rawtims_gui.export_panel import ExportPanel
from rawtims_gui.fraction_list import FractionList
from rawtims_gui.inspector import StatsPanel
from rawtims_gui.plots import PlotState, PlotWall
from rawtims_gui.rules_panel import RulesPanel, SHARED_SELECTION_TOOLTIP
from rawtims_gui.studio.theme import NeumorphicFrame, WallpaperWidget, apply_theme, build_application, paint_wallpaper
from rawtims_gui.studio.widgets import ElidedLabel, SegmentButton, SegmentedBar, _WorkflowRailDelegate, elide_tab_titles, scrolling_page
from rawtims_gui.studio.workers import FunctionWorker
from rawtims_gui.verify import run_verify
from rawtims_gui.workspace import Workspace, describe_path, read_paths

WORKFLOW_STEPS = ("Import", "Review", "Correct", "Export")
ACTIVE_STEPS = WORKFLOW_STEPS
INSPECTOR_TABS = ("Stats", "Rules", "Corrections", "Export")
STEP_TABS = {"Correct": "Corrections", "Export": "Export"}
REMEMBERED_KEY = "mappings/remembered"
EXPORT_DIR_KEY = "export/folder"
PLOT_MODES = {"ratios": "Ratios", "intensities": "Intensities", "table": "Table"}
DEFAULT_SIZE = QtCore.QSize(1280, 800)
MINIMUM_SIZE = QtCore.QSize(1024, 640)
GEOMETRY_KEY = "window/geometry"
THEME_KEY = "theme_mode"
FIT_ALL_KEY = "plots/fit_all_points"
THEME_MODES = ("light", "dark", "system")
DEFAULT_INTENSITIES = 6
RUN_FILTER = (f"Run files and sessions (*.xls *.XLS *.TIMSDP *.timsdp *{branding.SESSION_EXTENSION});;"
              f"Sessions (*{branding.SESSION_EXTENSION});;All files (*)")
SESSION_FILTER = f"Sessions (*{branding.SESSION_EXTENSION})"
RECENT_KEY = "sessions/recent"
MAX_RECENT = 8
AUTOSAVE_MS = 1500
UNTITLED = "Untitled"
LEGEND = "● used  ○ excluded  × invalid  — mean, bands 2SE · 1σ · 2σ   Click or drag: toggle · ⌘-click, ⇧-drag: select · B: block"
LEGEND_TIP = ("Filled: used. Hollow red: excluded by hand or by block. Grey cross: invalid value (never used).\n"
              "Red edge triangles: excluded points outside the range; hover for the true value, click to toggle.\n"
              "Line: mean of the used cycles; bands from dark to light: 2SE, 1σ, 2σ.\n"
              "Click a point to toggle that cycle; drag a box to toggle the cycles inside.\n"
              "⌘-click (Ctrl-click) adds a point to the selection; ⇧-drag selects a box.\n"
              "Delete or Backspace rejects the selection; B toggles its block; right-click for the block menu.\n"
              "Group ratios always share selection. SYNCH controls free functions only. ⌘ + wheel zooms a plot.\n"
              "Amber square: a cycle the previewed rule would reject (Rules tab).")


def app_settings() -> QtCore.QSettings:
    """Per-viewer preferences (the user scope of QSettings)."""
    return QtCore.QSettings(branding.QSETTINGS_ORG, branding.QSETTINGS_APP)


def load_remembered(settings: QtCore.QSettings) -> dict[str, MethodMapping]:
    """Mappings remembered per method name (one JSON value; unreadable entries are skipped)."""
    text = settings.value(REMEMBERED_KEY, "", type=str) or ""
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    remembered: dict[str, MethodMapping] = {}
    for method, entry in (data.items() if isinstance(data, dict) else []):
        try:
            remembered[str(method)] = MethodMapping.from_dict(entry)
        except (KeyError, TypeError, ValueError):
            continue
    return remembered


def store_remembered(settings: QtCore.QSettings, remembered: dict[str, MethodMapping]) -> None:
    if remembered:
        settings.setValue(REMEMBERED_KEY, json.dumps({method: m.to_dict() for method, m in remembered.items()}, sort_keys=True))
    else:
        settings.remove(REMEMBERED_KEY)
    settings.sync()


def fitted_window_size(available: QtCore.QSize) -> QtCore.QSize:
    """1280 x 800, reduced to the available screen area, never below the minimum."""
    return QtCore.QSize(
        max(MINIMUM_SIZE.width(), min(DEFAULT_SIZE.width(), available.width())),
        max(MINIMUM_SIZE.height(), min(DEFAULT_SIZE.height(), available.height())),
    )


def fitted_page(page: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
    """An inspector page that scrolls vertically and never sideways (UX rule 7)."""
    scroll = scrolling_page(page)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.viewport().setAutoFillBackground(False)
    page.setObjectName(page.objectName() or "InspectorPage")
    page.setStyleSheet(f"#{page.objectName()} {{ background: transparent; }}")
    return scroll


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


def _divider() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.Shape.VLine)
    line.setObjectName("ControlBarDivider")
    return line


def _tool(action: QtGui.QAction, text: str) -> QtWidgets.QToolButton:
    """A compact tool button for an action; ``text`` is its short label (the menus keep the full one)."""
    action.setIconText(text)
    button = QtWidgets.QToolButton()
    button.setDefaultAction(action)
    button.setProperty("modeToggle", True)
    button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
    return button


def default_intensities(analysis: Analysis) -> list[str]:
    """Up to six intensity functions: the Daly singles when the file has them, else the first ones."""
    intensities = [f for f in analysis.functions if f.kind == "intensity"]
    daly = [f for f in intensities if f.collector == "D"]
    return [f.key for f in (daly or intensities)[:DEFAULT_INTENSITIES]]


class FittedStatusBar(QtWidgets.QStatusBar):
    """Keep transient messages readable with an ellipsis and the full text on hover."""

    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.message_label = ElidedLabel("")
        self.addWidget(self.message_label, 1)
        self._message = ""
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clearMessage)

    def showMessage(self, message: str, timeout: int = 0) -> None:
        self._timer.stop()
        self._message = message
        self.message_label.setText(message)
        self.message_label.setToolTip(message)
        self.messageChanged.emit(message)
        if timeout > 0:
            self._timer.start(timeout)

    def currentMessage(self) -> str:
        return self._message

    def clearMessage(self) -> None:
        self.showMessage("")


class MainWindow(QtWidgets.QMainWindow):
    """The single main window."""

    importFinished = QtCore.Signal(object)  # rawtims_gui.workspace.ImportResult

    def __init__(self, *, restore_geometry: bool = True) -> None:
        super().__init__()
        self.settings = app_settings()
        self.workspace = Workspace(load_remembered(self.settings))
        self.current: tuple[Fraction, str] | None = None
        self.preview: tuple[Analysis, RuleProposal] | None = None
        self.selection: set[int] = set()
        self.focus_key: str | None = None
        self.last_row: int | None = None
        self.plot_mode = "ratios"
        self.plot_kind = "ratios"  # the plotted set (ratios or intensities) the table and picker follow
        self.log_ratio = False
        self.fit_all_points = self.settings.value(FIT_ALL_KEY, False, type=bool)
        self.skipped: list[tuple[str, str]] = []
        self._plotted: dict[int, dict[str, list[str]]] = {}
        self._workers: set[FunctionWorker] = set()
        # The saved session: its path, the fingerprint of what it holds and its SHA-256 (None: never saved).
        self.session_path: Path | None = None
        self._saved_fingerprint: str | None = None
        self._session_sha: str | None = None
        self._pending_recovery: recovery.Recovery | None = None
        # Seam for the unsaved-changes question: returns "save", "discard" or "cancel".
        self.unsaved_prompt = self._ask_unsaved
        self._autosave_timer = QtCore.QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(AUTOSAVE_MS)
        self._autosave_timer.timeout.connect(self.write_recovery)
        self.setWindowTitle(branding.DISPLAY_NAME)
        self.setMinimumSize(MINIMUM_SIZE)
        self.setAcceptDrops(True)
        # Paint one wallpaper behind the central area and the status bar.
        self.setProperty("wallpaperRoot", True)

        self._build_actions()
        self._build_menus()
        central = WallpaperWidget()
        layout = QtWidgets.QHBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(4)
        layout.addWidget(self._build_rail())
        layout.addWidget(self._build_centre(), 1)
        layout.addWidget(self._build_inspector())
        self.setCentralWidget(central)
        self._build_status_bar()
        self._sync_controls()
        self._update_titles()

        saved = self.settings.value(GEOMETRY_KEY) if restore_geometry else None
        if not (isinstance(saved, QtCore.QByteArray) and self.restoreGeometry(saved)):
            self.resize(self.default_window_size())
            self.centre_on_screen()
        try:
            QtWidgets.QApplication.instance().styleHints().colorSchemeChanged.connect(self._system_scheme_changed)
        except AttributeError:
            pass

    # ----------------------------------------------------------- actions
    def _action(self, text: str, slot, shortcut=None, *, checkable: bool = False, tip: str | None = None) -> QtGui.QAction:
        action = QtGui.QAction(text, self)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                action.setShortcuts([QtGui.QKeySequence(s) for s in shortcut])
            else:
                action.setShortcut(QtGui.QKeySequence(shortcut))
        action.setCheckable(checkable)
        if tip:
            action.setStatusTip(tip)
            action.setToolTip(tip)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        self.new_session_action = self._action("New Session", self.new_session, QtGui.QKeySequence.StandardKey.New,
                                                tip="Close the open fractions and start an empty session")
        self.open_session_action = self._action("Open Session…", self.choose_session, tip="Open a saved session")
        self.save_action = self._action("Save", self.save_session, QtGui.QKeySequence.StandardKey.Save,
                                        tip="Save the session (⌘S)")
        self.save_as_action = self._action("Save As…", lambda: self.save_session_as(), QtGui.QKeySequence.StandardKey.SaveAs,
                                           tip="Save the session under a new name (⇧⌘S)")
        self.open_files_action = self._action("Open Files…", self.choose_files, QtGui.QKeySequence.StandardKey.Open)
        self.open_folder_action = self._action("Open Folder…", self.choose_folder, "Ctrl+Shift+O")
        self.quit_action = self._action("Quit", self.close, QtGui.QKeySequence.StandardKey.Quit)
        self.undo_action = self._action("Undo", self.undo, QtGui.QKeySequence.StandardKey.Undo, tip="Undo the last edit")
        self.redo_action = self._action("Redo", self.redo, QtGui.QKeySequence.StandardKey.Redo, tip="Redo the edit undone last")
        self.reject_action = self._action(
            "Reject Selected Cycles", self.reject_selection,
            [QtGui.QKeySequence.StandardKey.Delete, QtCore.Qt.Key.Key_Backspace],
            tip="Exclude the selected cycles (Delete or Backspace)")
        self.block_action = self._action("Toggle Block", self.toggle_selection_block, "B",
                                         tip="Include or exclude the block of the selected or last clicked cycle (B)")
        self.clear_selection_action = self._action("Clear Selection", self.clear_selection, "Escape")
        self.reset_analysis_action = self._action("Reset Analysis…", lambda: self.reset_analysis(confirm=True),
                                                  tip="Include every cycle and block of this run again (undoable)")
        self.synch_action = self._action("SYNCH", self.set_synch, checkable=True,
                                         tip="On: a rejection applies to every function mapped to the contract. "
                                             "Off: only to the function clicked.")
        self.log_action = self._action("Log Ratios", self.set_log_ratio, "Ctrl+L", checkable=True, tip="Plot ln(ratio) instead of the ratio (Ctrl+L)")
        self.fit_all_action = self._action("Fit all points", self.set_fit_all_points, checkable=True,
                                           tip="Fit every point, including excluded cycles. Off: fit accepted, valid cycles.")
        self.fit_all_action.setChecked(self.fit_all_points)
        self.mode_actions: dict[str, QtGui.QAction] = {}
        for number, (mode, label) in enumerate(PLOT_MODES.items(), start=1):
            self.mode_actions[mode] = self._action(label, lambda _c=False, m=mode: self.set_plot_mode(m), f"Ctrl+{number}")
        self.theme_group = QtGui.QActionGroup(self)
        self.theme_actions: dict[str, QtGui.QAction] = {}
        for mode in THEME_MODES:
            action = self._action(mode.capitalize(), lambda _c=False, m=mode: self.set_theme(m), checkable=True)
            self.theme_group.addAction(action)
            self.theme_actions[mode] = action
        self.reset_layout_action = self._action("Reset Layout", self.reset_layout, tip="Window back to 1280 × 800, centred")

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        file_menu.addActions([self.new_session_action, self.open_session_action])
        self.recent_menu = file_menu.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self._rebuild_recent_menu()
        file_menu.addSeparator()
        file_menu.addActions([self.open_files_action, self.open_folder_action])
        file_menu.addSeparator()
        file_menu.addActions([self.save_action, self.save_as_action])
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        edit = bar.addMenu("Edit")
        edit.addActions([self.undo_action, self.redo_action])
        edit.addSeparator()
        edit.addActions([self.reject_action, self.block_action, self.clear_selection_action])
        edit.addSeparator()
        edit.addAction(self.reset_analysis_action)
        view = bar.addMenu("View")
        view.addActions(list(self.mode_actions.values()))
        view.addSeparator()
        view.addActions([self.log_action, self.synch_action, self.fit_all_action])
        view.addSeparator()
        theme_menu = view.addMenu("Theme")
        theme_menu.addActions(list(self.theme_actions.values()))
        mode = str(QtWidgets.QApplication.instance().property("upbrpy.theme_mode") or "light")
        self.theme_actions.get(mode, self.theme_actions["light"]).setChecked(True)
        view.addAction(self.reset_layout_action)

    # ------------------------------------------------------------ layout
    def _build_rail(self) -> QtWidgets.QWidget:
        frame = NeumorphicFrame()
        frame.setObjectName("RailPanel")
        frame.setFixedWidth(224)
        self.rail_panel = frame
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(6)
        brand = QtWidgets.QLabel(branding.DISPLAY_NAME)
        brand.setObjectName("RailBrand")
        layout.addWidget(brand)
        layout.addWidget(_section_title("Workflow"))
        self.workflow_step_list = QtWidgets.QListWidget()
        self.workflow_step_list.setItemDelegate(_WorkflowRailDelegate(self.workflow_step_list))
        self.workflow_step_list.setObjectName("WorkflowStepRail")
        self.workflow_step_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.workflow_step_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.workflow_step_list.setSpacing(1)
        for index, name in enumerate(WORKFLOW_STEPS, start=1):
            item = QtWidgets.QListWidgetItem(f"{index}  {name}")
            item.setToolTip({
                "Import": "Open run files and folders",
                "Review": "Cycles, hand rejection and rules",
                "Correct": "Oxide correction and the mapping to the contract (Corrections tab)",
                "Export": "Fraction fields, contract CSV, Tripoli clipboard, cycles CSV (Export tab)",
            }[name])
            self.workflow_step_list.addItem(item)
        self.workflow_step_list.setCurrentRow(0)
        self.workflow_step_list.setFixedHeight(self.workflow_step_list.sizeHintForRow(0) * len(WORKFLOW_STEPS) + 16)
        self.workflow_step_list.currentRowChanged.connect(self._workflow_step_changed)
        layout.addWidget(self.workflow_step_list)
        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(4)
        self.open_files_button = QtWidgets.QPushButton("Open…")
        self.open_files_button.setToolTip("Open run files (.xls, .TIMSDP)")
        self.open_files_button.clicked.connect(self.choose_files)
        self.open_folder_button = QtWidgets.QPushButton("Folder…")
        self.open_folder_button.setToolTip("Open every run file in a folder")
        self.open_folder_button.clicked.connect(self.choose_folder)
        buttons.addWidget(self.open_files_button, 1)
        buttons.addWidget(self.open_folder_button, 1)
        layout.addLayout(buttons)
        layout.addSpacing(4)
        layout.addWidget(_section_title("Fractions"))
        self.fraction_list = FractionList()
        self.fraction_list.runSelected.connect(self.select_run)
        self.fraction_list.renameRequested.connect(self.rename_fraction)
        layout.addWidget(self.fraction_list, 1)
        return frame

    def _build_centre(self) -> QtWidgets.QWidget:
        frame = NeumorphicFrame()
        frame.setObjectName("CentrePanel")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(self._build_recovery_bar())
        self.legacy_bar = QtWidgets.QFrame()
        legacy_layout = QtWidgets.QVBoxLayout(self.legacy_bar)
        legacy_layout.setContentsMargins(6, 4, 6, 4)
        self.legacy_notice = QtWidgets.QLabel()
        self.legacy_notice.setWordWrap(True)
        self.legacy_notice.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        legacy_layout.addWidget(self.legacy_notice)
        self.legacy_union_button = QtWidgets.QPushButton("Use the union of rejections")
        self.legacy_union_button.clicked.connect(self.use_union_of_rejections)
        legacy_layout.addWidget(self.legacy_union_button)
        self.legacy_bar.hide()
        layout.addWidget(self.legacy_bar)
        self.centre_stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.centre_stack)
        self.import_page = self._build_import_page()
        self.review_page = self._build_review_page()
        self.centre_stack.addWidget(self.import_page)
        self.centre_stack.addWidget(self.review_page)
        return frame

    def _build_recovery_bar(self) -> QtWidgets.QWidget:
        """A non-modal offer to restore unsaved work left by a crash (hidden until there is some)."""
        bar = QtWidgets.QFrame()
        bar.setObjectName("RecoveryBar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 6, 6)
        row.setSpacing(6)
        self.recovery_label = QtWidgets.QLabel("")
        self.recovery_label.setWordWrap(True)
        row.addWidget(self.recovery_label, 1)
        self.recovery_restore_button = QtWidgets.QPushButton("Restore")
        self.recovery_restore_button.clicked.connect(lambda: self.restore_recovery())
        self.recovery_discard_button = QtWidgets.QPushButton("Discard")
        self.recovery_discard_button.clicked.connect(self.discard_recovery)
        row.addWidget(self.recovery_restore_button)
        row.addWidget(self.recovery_discard_button)
        bar.setVisible(False)
        self.recovery_bar = bar
        return bar

    def _build_import_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addStretch(1)
        title = QtWidgets.QLabel("Open run files")
        title.setObjectName("HeroTitle")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(_placeholder(
            "Drop IsotopX IonVantage workbooks (.xls), IsoLinx files (.TIMSDP) or folders anywhere on this window, "
            "or use the buttons below. The Pb and U runs of a fraction are paired by sample ID."
        ))
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        for text, slot in (("Open files…", self.choose_files), ("Open folder…", self.choose_folder)):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.import_summary = _placeholder("")
        self.import_summary.setVisible(False)
        layout.addWidget(self.import_summary)
        layout.addStretch(1)
        return page

    def _build_review_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)
        self.mode_bar = SegmentedBar()
        self.mode_bar.setObjectName("StageSegmentBar")
        mode_row = QtWidgets.QHBoxLayout(self.mode_bar)
        mode_row.setContentsMargins(4, 4, 4, 4)
        mode_row.setSpacing(1)
        self.mode_buttons: dict[str, SegmentButton] = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for mode, label in PLOT_MODES.items():
            button = SegmentButton()
            button.setText(label)
            shortcut = self.mode_actions[mode].shortcut().toString(QtGui.QKeySequence.SequenceFormat.NativeText)
            button.setToolTip(f"{label} ({shortcut})")
            button.setCheckable(True)
            button.setProperty("modeToggle", True)
            button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setMinimumHeight(28)
            button.setMinimumWidth(78)
            button.clicked.connect(lambda _checked=False, m=mode: self.set_plot_mode(m))
            group.addButton(button)
            self.mode_buttons[mode] = button
            mode_row.addWidget(button)
            self.mode_bar.add_segment(button)
        self.mode_buttons["ratios"].setChecked(True)
        top.addWidget(self.mode_bar)
        self.run_title = ElidedLabel("")
        self.run_title.setObjectName("WorkflowContextTitle")
        top.addWidget(self.run_title, 1)
        layout.addLayout(top)

        bar = QtWidgets.QFrame()
        bar.setObjectName("PlotControlBar")
        self.plot_control_bar = bar
        controls = QtWidgets.QHBoxLayout(bar)
        controls.setContentsMargins(6, 3, 6, 3)
        controls.setSpacing(3)
        self.function_button = QtWidgets.QToolButton()
        self.function_button.setText("Functions")
        self.function_button.setToolTip("Choose the functions to plot")
        self.function_button.setProperty("modeToggle", True)
        self.function_button.setStyleSheet("QToolButton { padding-right: 16px; }")
        self.function_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.function_menu = QtWidgets.QMenu(self.function_button)
        self.function_list = QtWidgets.QListWidget()
        self.function_list.setObjectName("FunctionPicker")
        self.function_list.setMinimumWidth(280)
        self.function_list.setFixedHeight(300)
        self.function_list.itemChanged.connect(self._function_checked)
        picker = QtWidgets.QWidgetAction(self.function_menu)
        picker.setDefaultWidget(self.function_list)
        self.function_menu.addAction(picker)
        self.function_menu.addSeparator()
        self.function_menu.addAction("Contract ratios only", self.plot_contract_ratios)
        self.function_button.setMenu(self.function_menu)
        controls.addWidget(self.function_button)
        controls.addWidget(_divider())
        self.log_button = _tool(self.log_action, "Log")
        self.synch_button = _tool(self.synch_action, "SYNCH")
        controls.addWidget(self.log_button)
        controls.addWidget(self.synch_button)
        self.why_link = QtWidgets.QLabel('<a href="shared">Why?</a>')
        self.why_link.linkActivated.connect(lambda _url: self.show_shared_selection_help())
        controls.addWidget(self.why_link)
        self.fit_all_button = _tool(self.fit_all_action, "Fit all points")
        controls.addWidget(self.fit_all_button)
        controls.addWidget(_divider())
        self.undo_button = _tool(self.undo_action, "Undo")
        self.redo_button = _tool(self.redo_action, "Redo")
        controls.addWidget(self.undo_button)
        controls.addWidget(self.redo_button)
        controls.addStretch(1)
        self.reset_button = _tool(self.reset_analysis_action, "Reset…")
        controls.addWidget(self.reset_button)
        layout.addWidget(bar)

        self.view_stack = QtWidgets.QStackedWidget()
        self.plot_wall = PlotWall()
        self.plot_wall.toggleRequested.connect(self.request_toggle)
        self.plot_wall.selectRequested.connect(self.request_select)
        self.plot_wall.blockToggleRequested.connect(self.request_block_toggle)
        self.plot_wall.focused.connect(self._set_focus_key)
        self.cycle_table = CycleTable()
        self.cycle_table.rowsSelected.connect(self._table_selection)
        self.cycle_table.cycle_model.includeToggled.connect(self._table_include)
        self.view_stack.addWidget(self.plot_wall)
        self.view_stack.addWidget(self.cycle_table)
        layout.addWidget(self.view_stack, 1)
        self.table_navigation = QtWidgets.QWidget()
        navigation = QtWidgets.QHBoxLayout(self.table_navigation)
        navigation.setContentsMargins(0, 0, 0, 0)
        self.table_columns_label = QtWidgets.QLabel()
        self.table_columns_label.setObjectName("SecondaryText")
        navigation.addWidget(self.table_columns_label, 1)
        self.table_previous = QtWidgets.QPushButton("Previous")
        self.table_next = QtWidgets.QPushButton("Next")
        for button, direction in ((self.table_previous, -1), (self.table_next, 1)):
            button.setToolTip("Show the next or previous group of function columns")
            button.clicked.connect(lambda _checked=False, d=direction: self.cycle_table.change_column_page(d))
            navigation.addWidget(button)
        self.cycle_table.columnPageChanged.connect(self._update_table_navigation)
        layout.addWidget(self.table_navigation)
        self.table_navigation.setVisible(False)
        self.legend = ElidedLabel(LEGEND)
        self.legend.setObjectName("SecondaryText")
        self.legend.setToolTip(LEGEND_TIP)
        # A fixed line height: the label never shares rows with the last plot's axis.
        self.legend.setFixedHeight(self.legend.fontMetrics().height() + 6)
        self.legend.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.legend)
        return page

    def _update_table_navigation(self) -> None:
        first, end, total = self.cycle_table.visible_function_range
        self.table_columns_label.setText(f"Functions {first + 1}–{end} of {total}" if total else "No functions")
        self.table_previous.setEnabled(first > 0)
        self.table_next.setEnabled(end < total)

    def _build_inspector(self) -> QtWidgets.QWidget:
        frame = NeumorphicFrame()
        frame.setObjectName("InspectorPanel")
        frame.setFixedWidth(320)
        self.inspector_panel = frame
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.addWidget(_section_title("Inspector"))
        self.inspector_tabs = QtWidgets.QTabWidget()
        self.inspector_tabs.setDocumentMode(True)
        self.inspector_tabs.tabBar().setStyleSheet("QTabBar::tab { padding: 7px 6px; margin: 3px 1px; }")
        self.stats_panel = StatsPanel()
        self.stats_panel.blockToggleRequested.connect(self.toggle_block)
        self.inspector_tabs.addTab(self.stats_panel, "Stats")
        self.rules_panel = RulesPanel()
        self.rules_panel.previewRequested.connect(self.preview_rule)
        self.rules_panel.applyRequested.connect(self.apply_preview)
        self.rules_panel.discardRequested.connect(self.discard_preview)
        self.rules_panel.parametersEdited.connect(self.discard_preview)
        self.rules_panel.synchToggled.connect(self.set_synch)
        self.rules_panel.whyRequested.connect(self.show_shared_selection_help)
        self.rules_panel.setObjectName("RulesPage")
        self.inspector_tabs.addTab(fitted_page(self.rules_panel), "Rules")
        self.corrections_panel = CorrectionsPanel()
        self.corrections_panel.settingRequested.connect(self.set_analysis_setting)
        self.corrections_panel.mappingEdited.connect(self.edit_mapping)
        self.corrections_panel.collectorChanged.connect(self.set_collector)
        self.corrections_panel.rememberRequested.connect(self.remember_mapping)
        self.corrections_panel.forgetRequested.connect(self.forget_mapping)
        self.corrections_panel.revertRequested.connect(self.revert_mapping)
        self.corrections_panel.setObjectName("CorrectionsPage")
        self.inspector_tabs.addTab(fitted_page(self.corrections_panel), "Corrections")
        self.export_panel = ExportPanel()
        self.export_panel.fieldEdited.connect(self.set_fraction_field)
        self.export_panel.compareLegacyRequested.connect(self.compare_legacy)
        self.export_panel.saveContractRequested.connect(lambda: self.save_contract_csv())
        self.export_panel.copyClipboardRequested.connect(lambda: self.copy_clipboard())
        self.export_panel.saveCyclesRequested.connect(lambda: self.save_cycles_csv())
        self.export_panel.saveSessionFirstRequested.connect(lambda: self.save_session_then_export())
        self.inspector_tabs.addTab(self.export_panel, "Export")
        elide_tab_titles(self.inspector_tabs)
        self.inspector_tabs.currentChanged.connect(self._inspector_tab_changed)
        layout.addWidget(self.inspector_tabs, 1)
        return frame

    def _build_status_bar(self) -> None:
        self.setStatusBar(FittedStatusBar(self))
        status = self.statusBar()
        self.run_label = QtWidgets.QLabel("")
        self.run_label.setObjectName("StatusRun")
        self.cycles_label = QtWidgets.QLabel("")
        self.cycles_label.setToolTip("Cycles used in every contract-mapped function / cycles in the run")
        self.history_label = QtWidgets.QLabel("")
        self.history_label.setToolTip("Edits applied to this run (Undo and Redo walk them)")
        self.skipped_button = QtWidgets.QToolButton()
        self.skipped_button.setObjectName("SkippedButton")
        self.skipped_button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.skipped_menu = QtWidgets.QMenu(self.skipped_button)
        self.skipped_list = QtWidgets.QListWidget()
        self.skipped_list.setObjectName("SkippedList")
        self.skipped_list.setMinimumWidth(420)
        self.skipped_list.setWordWrap(True)
        skipped_action = QtWidgets.QWidgetAction(self.skipped_menu)
        skipped_action.setDefaultWidget(self.skipped_list)
        self.skipped_menu.addAction(skipped_action)
        self.skipped_button.setMenu(self.skipped_menu)
        self.skipped_button.setVisible(False)
        self.version_label = QtWidgets.QLabel(branding.RAW_APP_LABEL)
        self.version_label.setObjectName("VersionLabel")
        for label in (self.run_label, self.cycles_label, self.history_label, self.version_label):
            label.setContentsMargins(10, 0, 4, 0)
        status.addPermanentWidget(self.run_label)
        status.addPermanentWidget(self.cycles_label)
        status.addPermanentWidget(self.history_label)
        status.addPermanentWidget(self.skipped_button)
        status.addPermanentWidget(self.version_label)
        status.showMessage("No runs open")

    # ------------------------------------------------------------ import
    def choose_files(self) -> None:
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Open run files", "", RUN_FILTER)
        if paths:
            self.open_paths(paths)

    def choose_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Open a folder of run files")
        if folder:
            self.open_paths([folder])

    def open_paths(self, paths: Sequence[str], *, synchronous: bool = False) -> None:
        """Read files and folders on the shared thread pool (or here, for scripted use) and add them.

        A session file among them (recognised by content) opens as the session
        first; the other paths are then added to it.
        """
        paths = [str(path) for path in paths]
        if not paths:
            return
        sessions = [path for path in paths if Path(path).is_file() and session_io.looks_like_session(path)]
        if sessions:
            others = [path for path in paths if path not in sessions]
            extra = [(path, "only one session opens at a time; open it on its own") for path in sessions[1:]]
            self.open_session(sessions[0], synchronous=synchronous, then_open=others, extra_problems=extra)
            return
        if synchronous:
            self._import_finished(read_paths(paths))
            return
        self.statusBar().showMessage(f"Reading {len(paths)} item{'s' if len(paths) != 1 else ''}…")
        worker = FunctionWorker(lambda: read_paths(paths))
        worker.signals.succeeded.connect(self._import_finished)
        worker.signals.failed.connect(lambda message, _trace: self.statusBar().showMessage(f"Could not open the files: {message}"))
        worker.signals.finished.connect(lambda w=worker: self._workers.discard(w))
        self._workers.add(worker)
        QtCore.QThreadPool.globalInstance().start(worker)

    def _import_finished(self, payload) -> None:
        analyses, skipped = payload
        result = self.workspace.add(analyses, skipped)
        self.skipped = result.skipped
        self._show_skipped(result.skipped)
        if self.current is None and result.added:
            first = result.added[0]
            self.fraction_list.set_fractions(self.workspace.fractions, None)
            self.select_run(self.workspace.fraction_of(first), first.run.element)
        else:
            self.fraction_list.set_fractions(self.workspace.fractions, self.current)
            self._refresh_export()
            self._update_titles()
        runs, fractions = len(result.added), len(result.fractions)
        message = f"Opened {runs} run{'s' if runs != 1 else ''} in {fractions} fraction{'s' if fractions != 1 else ''}"
        if result.skipped:
            count = len(result.skipped)
            message += f"; {count} file{'s' if count != 1 else ''} skipped (list in the status bar)"
        if not runs and not result.skipped:
            message = "No run files found"
        self.statusBar().showMessage(message, 8000)
        self.import_summary.setText(message)
        self.import_summary.setVisible(True)
        self.importFinished.emit(result)

    def _show_skipped(self, skipped: list[tuple[str, str]], *, noun: str = "skipped") -> None:
        """The non-modal list in the status bar: files skipped by an import, or problems of a session."""
        self.skipped_list.clear()
        for path, reason in skipped:
            item = QtWidgets.QListWidgetItem(f"{describe_path(path)}: {reason}" if noun == "skipped" else reason)
            item.setToolTip(path)
            self.skipped_list.addItem(item)
        count = len(skipped)
        self.skipped_list.setFixedHeight(min(280, 28 * max(1, count) + 12))
        if noun == "skipped":
            self.skipped_button.setText(f"{count} skipped")
            self.skipped_button.setToolTip("Files that were not opened, and why")
        else:
            self.skipped_button.setText(f"{count} problem{'s' if count != 1 else ''}")
            self.skipped_button.setToolTip("What the session could not restore as saved, and why")
        self.skipped_button.setVisible(bool(count))

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802 - Qt API
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.open_paths(paths)

    # --------------------------------------------------------- fractions
    @property
    def analysis(self) -> Analysis | None:
        if self.current is None:
            return None
        fraction, element = self.current
        return fraction.pb if element == "Pb" else fraction.u

    @property
    def mapping(self) -> ElementMapping | None:
        analysis = self.analysis
        return self.workspace.mapping(analysis) if analysis is not None else None

    def select_run(self, fraction: Fraction, element: str) -> None:
        analysis = fraction.pb if element == "Pb" else fraction.u
        if analysis is None:
            return
        self.current = (fraction, element)
        self.selection = set()
        self.last_row = None
        if id(analysis) not in self._plotted:
            mapping = self.workspace.mapping(analysis)
            ratios = list(mapping.function_keys) if mapping is not None and mapping.function_keys else analysis.ratio_keys[:6]
            self._plotted[id(analysis)] = {"ratios": ratios, "intensities": default_intensities(analysis)}
        self.focus_key = (self.plotted_keys() or [None])[0]
        self.fraction_list.set_current(self.current)
        self.centre_stack.setCurrentWidget(self.review_page)
        if WORKFLOW_STEPS[self.workflow_step_list.currentRow()] == "Import":
            self.workflow_step_list.blockSignals(True)
            self.workflow_step_list.setCurrentRow(WORKFLOW_STEPS.index("Review"))
            self.workflow_step_list.blockSignals(False)
        self._rebuild_view()

    def rename_fraction(self, fraction: Fraction, new_id: str) -> bool:
        ok, message, holder = self.workspace.rename(fraction, new_id)
        if ok and self.current is not None and self.current[0] is fraction:
            self.current = (holder, self.current[1])
        self.fraction_list.set_fractions(self.workspace.fractions, self.current)
        if message:
            self.statusBar().showMessage(message, 8000)
        self._after_edit()
        return ok

    def _workflow_step_changed(self, row: int) -> None:
        step = WORKFLOW_STEPS[row]
        if step == "Import" or self.analysis is None:
            self.centre_stack.setCurrentWidget(self.import_page)
        else:
            self.centre_stack.setCurrentWidget(self.review_page)
        if step in STEP_TABS:
            self.inspector_tabs.blockSignals(True)
            self.inspector_tabs.setCurrentIndex(INSPECTOR_TABS.index(STEP_TABS[step]))
            self.inspector_tabs.blockSignals(False)

    def set_workflow_step(self, step: str) -> None:
        self.workflow_step_list.setCurrentRow(WORKFLOW_STEPS.index(step))

    def _inspector_tab_changed(self, index: int) -> None:
        """The rail follows the inspector: Corrections is the Correct step, Export the Export step."""
        if self.analysis is None:
            return
        tab = INSPECTOR_TABS[index]
        step = {"Corrections": "Correct", "Export": "Export"}.get(tab, "Review")
        self.workflow_step_list.blockSignals(True)
        self.workflow_step_list.setCurrentRow(WORKFLOW_STEPS.index(step))
        self.workflow_step_list.blockSignals(False)
        self.centre_stack.setCurrentWidget(self.review_page)

    # ------------------------------------------------------- plot / view
    def plotted_keys(self, kind: str | None = None) -> list[str]:
        analysis = self.analysis
        if analysis is None:
            return []
        return list(self._plotted[id(analysis)][kind or self.plot_kind])

    def _state(self) -> PlotState | None:
        analysis = self.analysis
        if analysis is None:
            return None
        return PlotState(analysis, self.mapping, self.log_ratio, frozenset(self.selection), self.preview_rows(), self.fit_all_points)

    def current_proposal(self) -> RuleProposal | None:
        if self.preview is None or self.preview[0] is not self.analysis:
            return None
        return self.preview[1]

    def preview_rows(self) -> dict[str, frozenset[int]]:
        """Function key → rows the previewed rule would exclude there (synced: the union in every function)."""
        proposal = self.current_proposal()
        analysis = self.analysis
        if proposal is None or analysis is None:
            return {}
        return {key: frozenset(rows) for key, rows in analysis.rule_targets(proposal).items() if rows}

    def _rebuild_view(self) -> None:
        """New run, mode or function set: rebuild the plots and the table."""
        state = self._state()
        keys = self.plotted_keys()
        self.plot_wall.set_plots(keys if self.plot_mode != "table" else [], state)
        mapping = self.mapping
        self.cycle_table.cycle_model.set_analysis(self.analysis, keys, mapping.function_keys if mapping is not None else [])
        if self.selection:
            self.cycle_table.select_rows(sorted(self.selection))
        self._fill_function_picker()
        self._after_edit()

    def _after_edit(self, *, rebuild: bool = False, keep_preview: bool = False) -> None:
        """Everything that shows the analysis follows its current flags. Any edit drops a rule preview."""
        if not keep_preview:
            self.preview = None
        state = self._state()
        if state is not None and self.plot_mode != "table":
            self.plot_wall.refresh(state, rebuild=rebuild)
        self.cycle_table.cycle_model.set_preview(self.preview_rows())
        self.stats_panel.update_stats(self.analysis, self.mapping, self.stats_keys())
        self.rules_panel.update_panel(self.analysis, self.current_proposal())
        self._refresh_corrections()
        self._refresh_export()
        self._sync_controls()
        self._update_titles()
        self._refresh_legacy_notice()

    def _refresh_legacy_notice(self) -> None:
        analysis = self.analysis
        pending = analysis is not None and (analysis.legacy_pending or not analysis.group_consistent())
        self.legacy_bar.setVisible(pending)
        if pending:
            lines = ["per-ratio selection (legacy) — contract export blocked. Differing rejections by ratio:"]
            for key, cycles in analysis.group_differences().items():
                lines.append(f"{key}: {', '.join(map(str, cycles)) or 'none'}")
            self.legacy_notice.setText("\n".join(lines))

    def use_union_of_rejections(self) -> dict | None:
        if self.analysis is None:
            return None
        op = self.analysis.use_union_of_rejections()
        self._after_edit()
        return op

    def _refresh_corrections(self) -> None:
        analysis = self.analysis
        fraction = self.current[0] if self.current is not None else None
        if analysis is None:
            self.corrections_panel.update_panel(None, None, None, "proposed", False)
            self.corrections_panel.set_project_statistics(self.workspace.stat_mode, bool(self.workspace.statistics_problem()))
            return
        method = analysis.run.metadata.method
        self.corrections_panel.update_panel(
            analysis, fraction, self.mapping, self.workspace.mapping_source(analysis),
            bool(method) and method in self.workspace.remembered)
        self.corrections_panel.set_project_statistics(self.workspace.stat_mode, bool(self.workspace.statistics_problem()))

    def fraction_reports(self) -> list[tuple[Fraction, str, list[str], Any, str | None]]:
        """(fraction, state, reasons, row or None, error or None) for every open fraction."""
        now = datetime.now().astimezone()
        info = self.session_info(verify=True)
        reports = []
        for fraction in self.workspace.fractions:
            state, reasons, row, error = self.workspace.fraction_report(fraction, now, info)
            reports.append((fraction, state, reasons, row, error))
        return reports

    def _refresh_export(self) -> None:
        reports = self.fraction_reports()
        self.fraction_list.set_states({id(f): (state, reasons) for f, state, reasons, _row, _error in reports})
        fraction = self.current[0] if self.current is not None else None
        row = error = None
        for f, _state, _reasons, f_row, f_error in reports:
            if f is fraction:
                row, error = f_row, f_error
        self.export_panel.update_panel(fraction, [(f, state, reasons) for f, state, reasons, _r, _e in reports], row, error,
                                       self.current[1] if self.current is not None else None)
        self.export_panel.set_session_state(self.session_state_name(), self.session_name())
        self.export_panel.set_project_statistics(self.workspace.stat_mode, self.workspace.statistics_problem())

    def stats_keys(self) -> list[str]:
        keys = self.plotted_keys("ratios")
        if self.plot_kind == "intensities":
            keys += self.plotted_keys("intensities")
        return keys

    def _update_titles(self) -> None:
        modified = self._session_changed()
        analysis = self.analysis
        base = self._window_title(modified)
        if analysis is None or self.current is None:
            self.setWindowTitle(base)
            self.setWindowModified(modified)
            self.run_title.setText("")
            self.run_label.setText("No run selected")
            self.cycles_label.setText("")
            self.history_label.setText("")
            return
        fraction, element = self.current
        self.setWindowTitle(f"{base} — {fraction.fraction_id} {element}")
        self.setWindowModified(modified)
        self.run_title.setText(f"{fraction.fraction_id} · {element} · {analysis.run.raw.name}"
                               + (" · per-ratio selection (legacy)" if analysis.legacy_pending else ""))
        run_text = f"{analysis.run.raw.name} ({element})"
        self.run_label.setText(self.run_label.fontMetrics().elidedText(run_text, QtCore.Qt.TextElideMode.ElideMiddle, 300))
        self.run_label.setToolTip(analysis.run.raw.path)
        used, total = self.cycles_used()
        self.cycles_label.setText(f"Cycles {used}/{total}")
        self.history_label.setText(f"History {len(analysis.history)}" + (" · redo available" if analysis.can_redo else ""))

    def cycles_used(self) -> tuple[int, int]:
        """(cycles used in every mapped function, cycles in the run) for the current run."""
        analysis = self.analysis
        if analysis is None:
            return 0, 0
        mapping = self.mapping
        keys = (mapping.function_keys if mapping is not None else []) or self.plotted_keys("ratios")
        if not keys:
            return analysis.n_cycles, analysis.n_cycles
        columns = [analysis.index(key) for key in keys]
        return int(analysis.effective[:, columns].all(axis=1).sum()), analysis.n_cycles

    def _sync_controls(self) -> None:
        analysis = self.analysis
        has_run = analysis is not None
        self.undo_action.setEnabled(has_run and analysis.can_undo)
        self.redo_action.setEnabled(has_run and analysis.can_redo)
        for action in (self.reject_action, self.block_action, self.reset_analysis_action, self.synch_action,
                       self.log_action, self.fit_all_action, *self.mode_actions.values()):
            action.setEnabled(has_run)
        self.function_button.setEnabled(has_run)
        self.synch_action.blockSignals(True)
        locked = has_run and (self.focus_key in analysis.group_keys or
                              (self.plot_mode == "table" and bool(analysis.group_keys)))
        self.synch_action.setChecked(True if locked else analysis.settings.synced if has_run else True)
        self.synch_action.setEnabled(has_run and not locked)
        self.synch_action.setToolTip(SHARED_SELECTION_TOOLTIP if locked else "SYNCH applies to free functions only")
        self.synch_button.setText("SYNCH · locked" if locked else "SYNCH")
        self.why_link.setVisible(bool(locked))
        self.synch_action.blockSignals(False)
        self.log_action.blockSignals(True)
        self.log_action.setChecked(self.log_ratio)
        self.log_action.blockSignals(False)
        self.log_button.setVisible(self.plot_kind == "ratios")

    def set_plot_mode(self, mode: str) -> None:
        if mode not in PLOT_MODES:
            raise ValueError(mode)
        self.plot_mode = mode
        if mode != "table":
            self.plot_kind = mode
            if self.focus_key not in self.plotted_keys():
                self.focus_key = (self.plotted_keys() or [None])[0]
        self.mode_buttons[mode].setChecked(True)
        self.mode_bar.select_checked()
        self.view_stack.setCurrentWidget(self.cycle_table if mode == "table" else self.plot_wall)
        self.table_navigation.setVisible(mode == "table")
        self._rebuild_view()

    def set_log_ratio(self, checked: bool) -> None:
        self.log_ratio = bool(checked)
        state = self._state()
        if state is not None:
            self.plot_wall.refresh(state, rebuild=True)
        self._sync_controls()

    def set_fit_all_points(self, checked: bool) -> None:
        self.fit_all_points = bool(checked)
        self.fit_all_action.setChecked(self.fit_all_points)
        self.settings.setValue(FIT_ALL_KEY, self.fit_all_points)
        state = self._state()
        if state is not None:
            self.plot_wall.refresh(state)

    def _fill_function_picker(self) -> None:
        self.function_list.blockSignals(True)
        self.function_list.clear()
        analysis = self.analysis
        if analysis is not None:
            plotted = set(self.plotted_keys())
            mapped = set(self.mapping.function_keys) if self.mapping is not None else set()
            for function in analysis.functions:
                if (function.kind == "intensity") != (self.plot_kind == "intensities"):
                    continue
                item = QtWidgets.QListWidgetItem(function.key + ("  (contract)" if function.key in mapped else ""))
                item.setData(QtCore.Qt.ItemDataRole.UserRole, function.key)
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Checked if function.key in plotted else QtCore.Qt.CheckState.Unchecked)
                self.function_list.addItem(item)
        self.function_list.blockSignals(False)
        self.function_button.setText(f"Functions ({len(self.plotted_keys())})")

    def _function_checked(self, _item: QtWidgets.QListWidgetItem) -> None:
        keys = [self.function_list.item(row).data(QtCore.Qt.ItemDataRole.UserRole)
                for row in range(self.function_list.count())
                if self.function_list.item(row).checkState() == QtCore.Qt.CheckState.Checked]
        self.set_plotted(keys)

    def set_plotted(self, keys: Sequence[str], kind: str | None = None) -> None:
        """Set the functions plotted in Ratios or Intensities mode (plotted ones keep their place; new ones follow in file order)."""
        analysis = self.analysis
        if analysis is None:
            return
        kind = kind or self.plot_kind
        wanted = set(keys)
        order = [key for key in self._plotted[id(analysis)][kind] if key in wanted]
        order += [f.key for f in analysis.functions if f.key in wanted and f.key not in order]
        self._plotted[id(analysis)][kind] = order
        if self.focus_key not in order:
            self.focus_key = (order or [None])[0]
        self._rebuild_view()

    def plot_contract_ratios(self) -> None:
        mapping = self.mapping
        if mapping is not None and mapping.function_keys:
            self.set_plotted(mapping.function_keys, "ratios")

    # --------------------------------------------------------- rejection
    def _set_focus_key(self, key: str) -> None:
        self.focus_key = key
        self._sync_controls()

    def edit_keys(self, key: str | None) -> list[str] | None:
        """Group edits always expand; SYNCH controls only free functions."""
        analysis = self.analysis
        assert analysis is not None
        key = key or self.focus_key
        if key in analysis.group_keys:
            return analysis.group_keys
        if not analysis.settings.synced:
            return [key] if key else []
        return [k for k in analysis.keys if k not in analysis.group_keys]

    def request_toggle(self, key: str, rows: list[int]) -> dict | None:
        """A click or box on a plot: exclude the cycles when any is included in that function, else include them."""
        analysis = self.analysis
        if analysis is None or not rows:
            return None
        self.focus_key = key
        include = not bool(analysis.included[rows, analysis.index(key)].any())
        op = analysis.toggle_cycles(rows, self.edit_keys(key), include)
        self.last_row = int(rows[-1])
        self._after_edit()
        count = len(op["cycles"])
        scope = "all group ratios" if key in analysis.group_keys else "free functions" if analysis.settings.synced else key
        self.statusBar().showMessage(f"{'Included' if include else 'Excluded'} {count} cycle{'s' if count != 1 else ''} in {scope}", 5000)
        return op

    def request_select(self, key: str, rows: list[int], additive: bool) -> None:
        self.focus_key = key
        if additive and len(rows) == 1:
            self.selection ^= set(rows)
        elif additive:
            self.selection |= set(rows)
        else:
            self.selection = set(rows)
        if rows:
            self.last_row = int(rows[-1])
        self._show_selection()

    def _show_selection(self) -> None:
        self.plot_wall.set_selection(frozenset(self.selection))
        self.cycle_table.select_rows(sorted(self.selection))

    def _table_selection(self, rows: list[int]) -> None:
        self.selection = set(rows)
        if rows:
            self.last_row = rows[-1]
        self.plot_wall.set_selection(frozenset(self.selection))

    def _table_include(self, row: int, include: bool) -> None:
        analysis = self.analysis
        if analysis is None:
            return
        analysis.toggle_cycles([row], self.edit_keys(self.focus_key), include)
        self.last_row = row
        self._after_edit()

    def clear_selection(self) -> None:
        self.selection = set()
        self._show_selection()

    def reject_selection(self) -> dict | None:
        analysis = self.analysis
        if analysis is None:
            return None
        if not self.selection:
            self.statusBar().showMessage("Select cycles first: ⌘-click points, ⇧-drag a box or pick rows in the table", 5000)
            return None
        op = analysis.toggle_cycles(sorted(self.selection), self.edit_keys(self.focus_key), False)
        self._after_edit()
        count = len(op["cycles"])
        self.statusBar().showMessage(f"Excluded {count} selected cycle{'s' if count != 1 else ''}", 5000)
        return op

    def toggle_block(self, block: int) -> dict | None:
        analysis = self.analysis
        if analysis is None:
            return None
        op = analysis.toggle_block(block)
        self._after_edit()
        self.statusBar().showMessage(f"Block {block} {'included' if op['include'] else 'excluded'}", 5000)
        return op

    def request_block_toggle(self, key: str, row: int) -> None:
        analysis = self.analysis
        if analysis is not None:
            self.focus_key = key
            self.last_row = int(row)
            self.toggle_block(int(analysis.run.block[row]))

    def toggle_selection_block(self) -> None:
        analysis = self.analysis
        if analysis is None:
            return
        rows = sorted(self.selection) or ([self.last_row] if self.last_row is not None else [])
        if not rows:
            self.statusBar().showMessage("Select or click a cycle in the block first", 5000)
            return
        for block in sorted({int(analysis.run.block[row]) for row in rows}):
            self.toggle_block(block)

    def show_shared_selection_help(self) -> None:
        path = Path(__file__).resolve().parents[2] / "docs" / "shared-cycle-selection.md"
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Why one cycle selection?")
        dialog.resize(820, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        browser = QtWidgets.QTextBrowser()
        browser.setMarkdown(path.read_text(encoding="utf-8") if path.is_file() else
                            "All contract-mapped ratios of a run share one accepted-cycle mask.\n\n" + SHARED_SELECTION_TOOLTIP)
        layout.addWidget(browser)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def set_synch(self, checked: bool) -> None:
        analysis = self.analysis
        if analysis is None:
            return
        if self.focus_key in analysis.group_keys or (self.plot_mode == "table" and analysis.group_keys):
            self._sync_controls()
            return
        if analysis.settings.synced != bool(checked):
            analysis.set_setting("synced", bool(checked))
            self.statusBar().showMessage("SYNCH on: rejections apply to free functions" if checked
                                         else "SYNCH off: rejections apply only to the free function clicked", 5000)
        self._after_edit()

    def undo(self) -> None:
        analysis = self.analysis
        if analysis is not None:
            old_mapping = self.mapping
            op = analysis.undo()
            if op is not None:
                if op["op"] == "set_mapping":
                    self._replot_mapping(analysis, old_mapping)
                else:
                    self._after_edit()

    def redo(self) -> None:
        analysis = self.analysis
        if analysis is not None:
            old_mapping = self.mapping
            op = analysis.redo()
            if op is not None:
                if op["op"] == "set_mapping":
                    self._replot_mapping(analysis, old_mapping)
                else:
                    self._after_edit()

    def reset_analysis(self, *, confirm: bool = True) -> bool:
        analysis = self.analysis
        if analysis is None:
            return False
        if confirm:
            answer = QtWidgets.QMessageBox.question(
                self, "Reset analysis",
                f"Include every cycle and block of {analysis.run.raw.name} again? You can undo this.",
                QtWidgets.QMessageBox.StandardButton.Reset | QtWidgets.QMessageBox.StandardButton.Cancel,
                QtWidgets.QMessageBox.StandardButton.Cancel)
            if answer != QtWidgets.QMessageBox.StandardButton.Reset:
                return False
        analysis.reset()
        self._after_edit()
        self.statusBar().showMessage("Analysis reset: every cycle included (Undo brings the rejections back)", 6000)
        return True

    # ------------------------------------------------------------- rules
    def preview_rule(self) -> RuleProposal | None:
        """Commit the rule parameters (undoable settings), then show what the rule would reject. The mask is not changed."""
        analysis = self.analysis
        if analysis is None:
            return None
        params = self.rules_panel.parameters()
        rule = params["rule"]
        names = ("chauvenet_probability", "chauvenet_min_n") if rule == "chauvenet" else ("k_sigma", "k_sigma_max_iterations")
        for name in names:
            if getattr(analysis.settings, name) != params[name]:
                analysis.set_setting(name, params[name])
        mapping = self.mapping
        keys: list[str] | None = None
        if params["function_set"] == "one":
            keys = [params["ratio_key"]] if params["ratio_key"] else None
        elif params["function_set"] == "plotted" or mapping is None or not mapping.function_keys:
            keys = list(self.plotted_keys()) or None
        propose = analysis.propose_chauvenet if rule == "chauvenet" else analysis.propose_k_sigma
        try:
            proposal = propose(keys, mapping=mapping if mapping is not None and mapping.function_keys else None, scope=params["scope"])
        except ValueError as error:
            self.statusBar().showMessage(f"Cannot preview the rule: {error}", 8000)
            return None
        self.preview = (analysis, proposal)
        self._after_edit(keep_preview=True)
        count = len(proposal.cycles)
        self.statusBar().showMessage(
            f"Preview: {proposal.describe()}. Nothing changed yet; Apply excludes them." if count else
            f"Preview: {proposal.describe()}. Nothing would be rejected.", 8000)
        return proposal

    def apply_preview(self) -> dict | None:
        """Apply exactly the previewed proposal (recorded in the history; Undo reverts it)."""
        analysis = self.analysis
        proposal = self.current_proposal()
        if analysis is None or proposal is None:
            return None
        op = analysis.apply_rule(proposal)
        self.preview = None
        self._after_edit()
        self.statusBar().showMessage(f"Applied {proposal.describe()} (Undo reverts it)", 8000)
        return op

    def discard_preview(self) -> None:
        if self.preview is None:
            return
        self.preview = None
        self._after_edit()

    # ------------------------------------------------------- corrections
    def set_analysis_setting(self, name: str, value: Any) -> dict | None:
        """Change a run setting through its history; statistics applies to the project."""
        if name == "stat_mode":
            try:
                self.workspace.set_stat_mode(value)
            except ValueError as error:
                self.statusBar().showMessage(f"Not changed: {error}", 8000)
                return None
            self._after_edit()
            self.statusBar().showMessage(f"Statistics for this project set to {value}", 6000)
            return None
        analysis = self.analysis
        if analysis is None:
            return None
        if getattr(analysis.settings, name) == value:
            self._after_edit(keep_preview=True)
            return None
        try:
            op = analysis.set_setting(name, value)
        except (KeyError, ValueError) as error:
            self.statusBar().showMessage(f"Not changed: {error}", 8000)
            self._after_edit(keep_preview=True)
            return None
        self._after_edit()
        self.statusBar().showMessage(f"{name.replace('_', ' ')} set to {value} (Undo reverts it)", 6000)
        return op

    def _replot_mapping(self, analysis: Analysis, old: ElementMapping | None) -> None:
        """After a mapping change: the new mapped functions are plotted; other plotted ratios stay."""
        new = self.workspace.mapping(analysis)
        plotted = self._plotted.get(id(analysis))
        if plotted is not None and new is not None:
            old_keys = set(old.function_keys) if old is not None else set()
            extras = [key for key in plotted["ratios"] if key not in old_keys and key not in new.function_keys]
            plotted["ratios"] = [*new.function_keys, *extras] or plotted["ratios"]
        self._rebuild_view()

    def edit_mapping(self, choice: dict[str, dict | None]) -> ElementMapping | None:
        analysis = self.analysis
        if analysis is None:
            return None
        old = self.mapping
        try:
            mapping = self.workspace.set_mapping(analysis, choice)
        except (MappingError, ValueError) as error:
            self.statusBar().showMessage(f"Mapping not changed: {error}", 8000)
            return None
        self._replot_mapping(analysis, old)
        self.statusBar().showMessage("Mapping edited for this run", 5000)
        return mapping

    def set_collector(self, collector: str | None) -> None:
        """The fraction's Collector: a contract field that also steers the Pb mapping proposal."""
        if self.current is None:
            return
        fraction = self.current[0]
        if collector == fraction.collector:
            return
        fraction.collector = collector
        pb = fraction.pb
        if pb is not None:
            old = self.workspace.mapping(pb)
            self.workspace.clear_mapping_edit(pb)
            if self.analysis is pb:
                self._replot_mapping(pb, old)
                return
        self._after_edit(keep_preview=True)

    def remember_mapping(self) -> MethodMapping | None:
        analysis = self.analysis
        if analysis is None:
            return None
        try:
            remembered = self.workspace.remember(analysis)
        except MappingError as error:
            self.statusBar().showMessage(f"Not remembered: {error}", 8000)
            return None
        store_remembered(self.settings, self.workspace.remembered)
        self._after_edit(keep_preview=True)
        self.statusBar().showMessage(f"Mapping remembered for method “{remembered.method}”", 6000)
        return remembered

    def forget_mapping(self) -> bool:
        analysis = self.analysis
        if analysis is None or not analysis.run.metadata.method:
            return False
        forgotten = self.workspace.forget(analysis.run.metadata.method)
        store_remembered(self.settings, self.workspace.remembered)
        self._after_edit(keep_preview=True)
        if forgotten:
            self.statusBar().showMessage(f"Forgot the mapping of method “{analysis.run.metadata.method}”", 6000)
        return forgotten

    def revert_mapping(self) -> None:
        analysis = self.analysis
        if analysis is not None:
            old = self.mapping
            self.workspace.clear_mapping_edit(analysis)
            self._replot_mapping(analysis, old)

    # ------------------------------------------------------------ export
    def set_fraction_field(self, attribute: str, value: Any) -> None:
        if self.current is None:
            return
        if attribute == "collector":
            self.set_collector(value)
            return
        setattr(self.current[0], attribute, value)
        self._after_edit(keep_preview=True)

    def compare_legacy(self):
        from rawtims_gui.legacy_comparison import LegacyComparisonDialog
        if self.analysis is None or self.mapping is None:
            return None
        dialog = LegacyComparisonDialog(self.analysis, self.mapping, self)
        dialog.show()
        return dialog

    def _export_folder(self) -> str:
        folder = self.settings.value(EXPORT_DIR_KEY, "", type=str) or ""
        return folder if folder and Path(folder).is_dir() else str(Path.home())

    def save_contract_csv(self, path: str | None = None) -> Path | None:
        """Write every exportable fraction to an idtims-fractions/1 file (atomic). Asks for the path when none is given."""
        info = self.session_info(verify=True)
        rows, left_out = self.workspace.export_rows(datetime.now().astimezone(), session_info=info)
        if not rows:
            reasons = "; ".join(f"{fid}: {reason}" for fid, reason in left_out) or "no fractions open"
            self.statusBar().showMessage(f"Nothing to export ({reasons})", 10000)
            return None
        if path is None:
            default = str(Path(self._export_folder()) / f"{date.today().isoformat()}.fractions.csv")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save contract CSV", default, "Fractions CSV (*.fractions.csv *.csv)")
            if not path:
                return None
        try:
            written = write_csv(rows, path)
        except (OSError, ContractError) as error:
            self.statusBar().showMessage(f"Could not save: {error}", 10000)
            return None
        self.settings.setValue(EXPORT_DIR_KEY, str(written.parent))
        message = f"Saved {len(rows)} fraction{'s' if len(rows) != 1 else ''} to {written.name}"
        if left_out:
            message += f"; left out: {', '.join(fid for fid, _ in left_out)} (see the Export tab)"
        if info is None:
            message += f"; Raw App Session left empty ({self.session_unlinked_reason()})"
        self.statusBar().showMessage(message, 10000)
        return written

    def save_session_then_export(self, contract_path: str | None = None) -> Path | None:
        """"Save session first": save the session (asking for a name if it has none), then save the contract CSV."""
        if self.save_session() is None or self.is_modified():
            return None
        return self.save_contract_csv(contract_path)

    def copy_clipboard(self) -> str | None:
        """Copy the current fraction as Tripoli clipboard blocks (Pb then U)."""
        problem = self.workspace.statistics_problem()
        if problem:
            self.statusBar().showMessage(f"Nothing copied: {problem}", 10000)
            return None
        if self.current is None:
            return None
        fraction = self.current[0]
        self.workspace.sync_mappings(fraction)
        separator = self.export_panel.separator.currentData() or CLIPBOARD_SEPARATOR
        try:
            text = clipboard_text(fraction, separator=separator, full_precision=self.export_panel.full_precision.isChecked())
        except FractionError as error:
            self.statusBar().showMessage(f"Nothing copied: {error}", 10000)
            return None
        QtWidgets.QApplication.clipboard().setText(text)
        blocks = text.count("(Mean, %StdErr)")
        self.statusBar().showMessage(f"Copied {blocks} ratio block{'s' if blocks != 1 else ''} of {fraction.fraction_id}", 6000)
        return text

    def save_cycles_csv(self, path: str | None = None) -> Path | None:
        problem = self.workspace.statistics_problem()
        if problem:
            self.statusBar().showMessage(f"Nothing to export: {problem}", 10000)
            return None
        analysis = self.analysis
        if analysis is None:
            return None
        if path is None:
            stem = Path(analysis.run.raw.name).stem
            default = str(Path(self._export_folder()) / f"{stem}.cycles.csv")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save cycles CSV", default, "CSV (*.csv)")
            if not path:
                return None
        try:
            written = write_cycles_csv(analysis, path)
        except OSError as error:
            self.statusBar().showMessage(f"Could not save: {error}", 10000)
            return None
        self.settings.setValue(EXPORT_DIR_KEY, str(written.parent))
        self.statusBar().showMessage(f"Saved the cycles of {analysis.run.raw.name} to {written.name}", 8000)
        return written

    # ----------------------------------------------------------- session
    def session_name(self) -> str:
        return self.session_path.name if self.session_path is not None else UNTITLED

    def is_modified(self) -> bool:
        """Unsaved changes: an untitled session with something open, or a state other than the saved file holds."""
        if self.session_path is None:
            return bool(self.workspace.fractions or self.workspace.missing or self.workspace.stat_mode != "arithmetic")
        if self._saved_fingerprint is None:
            return True
        return session_io.session_fingerprint(self.workspace.session_state(), self.session_path) != self._saved_fingerprint

    def session_state_name(self) -> str:
        """``empty``, ``untitled``, ``modified`` or ``saved`` (for the Export tab)."""
        if self.session_path is None:
            return "untitled" if self.is_modified() else "empty"
        if self.is_modified():
            return "modified"
        return "saved" if self.session_info(verify=True) is not None else "unlinked"

    def session_info(self, *, verify: bool = False) -> SessionInfo | None:
        """The session the rows point to, only while it is saved and unchanged. ``verify`` re-hashes the file."""
        if self.session_path is None or self._session_sha is None or self.is_modified():
            return None
        if verify:
            try:
                if session_io.session_sha256(self.session_path) != self._session_sha:
                    return None
            except OSError:
                return None
        return SessionInfo(self.session_path.name, self._session_sha)

    def session_unlinked_reason(self) -> str:
        state = self.session_state_name()
        if state == "untitled":
            return "the session is not saved"
        if state == "modified":
            return "the session has unsaved changes"
        return "the session file changed or is missing on disk"

    def _window_title(self, modified: bool) -> str:
        if self.session_path is None and not modified:
            return branding.DISPLAY_NAME
        return f"{self.session_name()}[*]{' — Edited' if modified else ''} — {branding.DISPLAY_NAME}"

    def _session_changed(self) -> bool:
        """After any change: (re)start the debounced recovery copy, or drop it when nothing is unsaved."""
        modified = self.is_modified()
        if modified:
            self._autosave_timer.start()
        else:
            self._autosave_timer.stop()
            recovery.discard()
        self.save_action.setEnabled(bool(modified or self.workspace.fractions or self.workspace.missing or self.session_path))
        return modified

    def _ask_unsaved(self, name: str) -> str:
        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Unsaved session")
        dialog.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        dialog.setText(f"Save changes to “{name}”?")
        dialog.setInformativeText("Your changes will be lost if you don't save them.")
        buttons = QtWidgets.QMessageBox.StandardButton
        dialog.setStandardButtons(buttons.Save | buttons.Discard | buttons.Cancel)
        dialog.setDefaultButton(buttons.Save)
        dialog.setEscapeButton(buttons.Cancel)
        dialog.button(buttons.Discard).setText("Don't Save")
        choice = dialog.exec()
        return {buttons.Save: "save", buttons.Discard: "discard"}.get(buttons(choice), "cancel")

    def maybe_save(self, reason: str = "") -> bool:
        """Before closing or replacing the session: True to go on (saved or discarded), False to stay."""
        del reason
        if not self.is_modified():
            return True
        answer = self.unsaved_prompt(self.session_name())
        if answer == "save":
            return self.save_session() is not None and not self.is_modified()
        if answer == "discard":
            self._autosave_timer.stop()
            recovery.discard()
            return True
        return False

    def _install_workspace(self, workspace: Workspace, path: Path | None, fingerprint: str | None) -> None:
        """Replace what is open (new or loaded session) and show its first run."""
        self.workspace = workspace
        self.current = None
        self.preview = None
        self.selection = set()
        self.focus_key = None
        self.last_row = None
        self._plotted = {}
        self.session_path = path
        self._saved_fingerprint = fingerprint
        self._session_sha = None
        if path is not None and fingerprint is not None:
            try:
                self._session_sha = session_io.session_sha256(path)
            except OSError:
                self._session_sha = None
        self.fraction_list.set_fractions(workspace.fractions, None)
        analyses = workspace.analyses()
        if analyses:
            first = analyses[0]
            self.select_run(workspace.fraction_of(first), first.run.element)
        else:
            self._rebuild_view()
            self.set_workflow_step("Import")
            self.centre_stack.setCurrentWidget(self.import_page)

    def new_session(self) -> bool:
        if not self.maybe_save("new"):
            return False
        workspace = Workspace(self.workspace.remembered)
        self._install_workspace(workspace, None, None)
        self.skipped_button.setVisible(False)
        self.import_summary.setVisible(False)
        self.statusBar().showMessage("New session", 5000)
        return True

    def choose_session(self) -> None:
        folder = str(self.session_path.parent) if self.session_path is not None else self._export_folder()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open session", folder, SESSION_FILTER + ";;All files (*)")
        if path:
            self.open_session(path)

    @staticmethod
    def _read_session(path: Path) -> tuple:
        """Load on a worker thread: ``("ok", state, problems)`` or ``("error", message)``."""
        try:
            state, problems = session_io.load_session(path)
        except (session_io.SessionError, OSError) as error:
            return ("error", str(error))
        return ("ok", state, problems)

    def open_session(self, path: str | Path, *, synchronous: bool = False, then_open: Sequence[str] = (),
                     extra_problems: Sequence[tuple[str, str]] = ()) -> bool:
        """Open a saved session in place of what is open (asks to save unsaved changes first)."""
        if not self.maybe_save("open"):
            return False
        path = Path(path).expanduser().resolve(strict=False)
        then_open, extra_problems = list(then_open), list(extra_problems)

        def finished(payload) -> bool:
            ok = self._session_read(path, payload, extra_problems)
            if ok and then_open:
                self.open_paths(then_open, synchronous=synchronous)
            return ok

        if synchronous:
            return finished(self._read_session(path))
        self.statusBar().showMessage(f"Opening session {path.name}…")
        worker = FunctionWorker(lambda: self._read_session(path))
        worker.signals.succeeded.connect(finished)
        worker.signals.failed.connect(lambda message, _trace: self.statusBar().showMessage(f"Could not open the session: {message}"))
        worker.signals.finished.connect(lambda w=worker: self._workers.discard(w))
        self._workers.add(worker)
        QtCore.QThreadPool.globalInstance().start(worker)
        return True

    def _session_read(self, path: Path, payload: tuple, extra_problems: Sequence[tuple[str, str]] = (),
                      recovered: recovery.Recovery | None = None) -> bool:
        if payload[0] == "error":
            message = payload[1]
            self._show_skipped([(str(path), message), *extra_problems], noun="problems")
            self.statusBar().showMessage(f"Could not open the session: {message}", 12000)
            if recovered is None and not path.exists():
                self._forget_recent(path)
            return False
        _ok, state, problems = payload
        workspace = Workspace(self.workspace.remembered)
        problems = [*problems, *workspace.restore(state)]
        if recovered is None:
            target, fingerprint = path, session_io.session_fingerprint(workspace.session_state(), path)
        else:
            original = Path(recovered.session_path) if recovered.session_path else None
            target = original if original is not None and original.parent.is_dir() else None
            fingerprint = None  # restored work is unsaved until the user saves it
        self._install_workspace(workspace, target, fingerprint)
        if recovered is None:
            self._remember_recent(path)
        items = [(p.path or "", p.message) for p in problems] + list(extra_problems)
        if items:
            self._show_skipped(items, noun="problems")
        else:
            self.skipped_button.setVisible(False)
        runs = len(workspace.analyses())
        what = "Restored unsaved work" if recovered is not None else f"Opened session {path.name}"
        message = f"{what}: {runs} run{'s' if runs != 1 else ''} in {len(workspace.fractions)} fraction{'s' if len(workspace.fractions) != 1 else ''}"
        if items:
            message += f"; {len(items)} problem{'s' if len(items) != 1 else ''} (list in the status bar)"
        self.statusBar().showMessage(message, 12000)
        self.import_summary.setText(message)
        self.import_summary.setVisible(True)
        self._update_titles()
        self._refresh_export()
        return True

    def save_session(self) -> Path | None:
        """Save to the session's file, or ask for one when it has none (⌘S)."""
        if self.session_path is None:
            return self.save_session_as()
        return self._write_session(self.session_path)

    def save_session_as(self, path: str | Path | None = None) -> Path | None:
        """Save under a new name (⇧⌘S); asks for the path when none is given."""
        if path is None:
            folder = self.session_path.parent if self.session_path is not None else Path(self._export_folder())
            name = self.session_path.name if self.session_path is not None else f"{date.today().isoformat()}{branding.SESSION_EXTENSION}"
            chosen, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save session", str(folder / name), SESSION_FILTER)
            if not chosen:
                return None
            path = chosen
        return self._write_session(Path(path))

    def _write_session(self, path: Path) -> Path | None:
        state = self.workspace.session_state()
        try:
            written = session_io.save_session(state, path).resolve(strict=False)
            sha = session_io.session_sha256(written)
        except (OSError, ValueError) as error:
            self.statusBar().showMessage(f"Could not save the session: {error}", 12000)
            return None
        self.session_path = written
        self._saved_fingerprint = session_io.session_fingerprint(state, written)
        self._session_sha = sha
        self._autosave_timer.stop()
        recovery.discard()
        self._remember_recent(written)
        self._update_titles()
        self._refresh_export()
        self.statusBar().showMessage(f"Saved session {written.name}", 6000)
        return written

    # ------------------------------------------------------ recent files
    def recent_sessions(self) -> list[str]:
        text = self.settings.value(RECENT_KEY, "", type=str) or ""
        try:
            data = json.loads(text) if text else []
        except ValueError:
            return []
        paths = list(dict.fromkeys(item for item in data if isinstance(item, str) and Path(item).is_file()))[:MAX_RECENT] if isinstance(data, list) else []
        if paths != data:
            self.settings.setValue(RECENT_KEY, json.dumps(paths))
        return paths

    def _store_recent(self, paths: list[str]) -> None:
        if paths:
            self.settings.setValue(RECENT_KEY, json.dumps(paths[:MAX_RECENT]))
        else:
            self.settings.remove(RECENT_KEY)
        self._rebuild_recent_menu()

    def _remember_recent(self, path: str | Path) -> None:
        path = str(Path(path).resolve(strict=False))
        self._store_recent([path, *(p for p in self.recent_sessions() if p != path)])

    def _forget_recent(self, path: str | Path) -> None:
        path = str(Path(path).resolve(strict=False))
        self._store_recent([p for p in self.recent_sessions() if p != path])

    def clear_recent(self) -> None:
        self._store_recent([])

    def remove_missing_recent(self) -> None:
        self._store_recent([p for p in self.recent_sessions() if Path(p).is_file()])

    def _rebuild_recent_menu(self) -> None:
        menu = self.recent_menu
        menu.clear()
        recent = self.recent_sessions()
        for path in recent:
            exists = Path(path).is_file()
            action = menu.addAction(Path(path).name.replace("&", "&&"))
            action.setData(path)
            action.setEnabled(exists)
            action.setToolTip(path if exists else f"Missing: {path}")
            action.setStatusTip(path if exists else f"Missing: {path}")
            action.triggered.connect(lambda _checked=False, p=path: self.open_recent(p))
        if not recent:
            menu.addAction("No recent sessions").setEnabled(False)
        menu.addSeparator()
        missing = any(not Path(p).is_file() for p in recent)
        remove = menu.addAction("Remove Missing", self.remove_missing_recent)
        remove.setEnabled(missing)
        menu.addAction("Clear Menu", self.clear_recent).setEnabled(bool(recent))

    def open_recent(self, path: str, *, synchronous: bool = False) -> bool:
        if not Path(path).is_file():
            self._forget_recent(path)
            self.statusBar().showMessage(f"{Path(path).name} is no longer there; removed from Open Recent", 8000)
            return False
        return self.open_session(path, synchronous=synchronous)

    # --------------------------------------------------------- recovery
    def write_recovery(self) -> Path | None:
        """Write the recovery copy now (the debounce timer calls this). Nothing is written without unsaved changes."""
        if not self.is_modified():
            return None
        try:
            return recovery.write_recovery(self.workspace.session_state(), self.session_path)
        except (OSError, ValueError) as error:
            self.statusBar().showMessage(f"Recovery copy not written: {error}", 8000)
            return None

    def check_recovery(self) -> recovery.Recovery | None:
        """Offer the newest recovery copy left by a crash, in the bar above the review area (non-modal)."""
        found = recovery.pending()
        self._pending_recovery = found[0] if found else None
        item = self._pending_recovery
        if item is None:
            self.recovery_bar.setVisible(False)
            return None
        when = item.saved_at.astimezone().strftime("%d %b %H:%M") if item.saved_at is not None else "an earlier run"
        self.recovery_label.setText(f"Unsaved work in “{item.session_name}” from {when} was kept when the app last "
                                    "closed unexpectedly. Restore it?")
        self.recovery_label.setToolTip(str(item.path))
        theme_accent = self.palette().color(QtGui.QPalette.ColorRole.Highlight).name()
        self.recovery_bar.setStyleSheet(f"#RecoveryBar {{ border: 1px solid {theme_accent}; border-radius: 8px; }}")
        self.recovery_bar.setVisible(True)
        return item

    def restore_recovery(self) -> bool:
        item = self._pending_recovery
        if item is None or not self.maybe_save("restore"):
            return False
        ok = self._session_read(item.path, self._read_session(item.path), recovered=item)
        if ok:
            recovery.discard(item.path)
            self.write_recovery()
        self.check_recovery()
        return ok

    def discard_recovery(self) -> None:
        if self._pending_recovery is not None:
            recovery.discard(self._pending_recovery.path)
        self.check_recovery()

    # ------------------------------------------------------------- theme
    def set_theme(self, mode: str) -> None:
        if mode not in THEME_MODES:
            return
        self.settings.setValue(THEME_KEY, mode)
        self.theme_actions[mode].setChecked(True)
        apply_theme(QtWidgets.QApplication.instance(), mode)
        self.refresh_theme()

    def _system_scheme_changed(self, *_args) -> None:
        app = QtWidgets.QApplication.instance()
        if str(app.property("upbrpy.theme_mode")) == "system":
            apply_theme(app, "system")
            self.refresh_theme()

    def refresh_theme(self) -> None:
        self.plot_wall.apply_theme()
        self.cycle_table.apply_theme()
        self.fraction_list.set_current(self.current)
        self.stats_panel.update_stats(self.analysis, self.mapping, self.stats_keys())
        self._refresh_corrections()
        self._refresh_export()
        self.update()

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

    def reset_layout(self) -> None:
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        self.resize(self.default_window_size())
        self.centre_on_screen()
        self.settings.remove(GEOMETRY_KEY)
        if self.analysis is not None:
            self.set_plot_mode("ratios")

    def persist_geometry(self) -> None:
        self.settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        self.settings.sync()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        narrow = self.width() < 1180
        self.rail_panel.setFixedWidth(208 if narrow else 224)
        self.inspector_panel.setFixedWidth(300 if narrow else 320)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt API
        paint_wallpaper(self)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 - Qt API
        if not self.maybe_save("closing"):
            event.ignore()
            return
        self._autosave_timer.stop()
        recovery.discard()
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
    parser.add_argument("--open", nargs="+", metavar="PATH", help="Open run files, folders or a saved session at start")
    parser.add_argument("--export", nargs=2, metavar=("FORMAT", "PATH"), help="Render the window to PATH and exit; FORMAT must be png")
    parser.add_argument("--version", action="version", version=branding.RAW_APP_LABEL)
    parser.add_argument("--verify", nargs="+", metavar="PATH",
                        help="Open run files or folders without a window, pair them, use the default mapping, apply no "
                             "rejection and write the contract CSV to --verification-output")
    parser.add_argument("--verification-output", metavar="OUT.csv", help="Where --verify writes the contract CSV")
    args = parser.parse_args(argv)
    if args.verify is not None and not args.verification_output:
        parser.error("--verify needs --verification-output OUT.csv")
    if args.verification_output and args.verify is None:
        parser.error("--verification-output is used only with --verify")
    if args.verify is not None and (args.export is not None or args.open):
        parser.error("--verify runs without a window; do not combine it with --open or --export")
    if args.export is not None and args.export[0].lower() != "png":
        parser.error(f"--export supports only png, not {args.export[0]!r}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(sys.argv[1:] if argv is None else argv)
    if args.verify is not None:
        return run_verify(args.verify, args.verification_output)
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
        if args.open:
            window.open_paths(args.open, synchronous=True)
        output = Path(args.export[1]).expanduser()
        if not export_window(window, str(output)):
            print(f"Could not write {output}", file=sys.stderr)
            return 1
        return 0

    window = MainWindow()
    window.show()
    if args.open:
        window.open_paths(args.open)
    QtCore.QTimer.singleShot(0, window.check_recovery)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
