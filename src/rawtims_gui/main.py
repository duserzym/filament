"""Desktop entry point and main window (SPEC section 5, Phase 1 step 5: GUI step A).

The window has the workflow rail and the fraction list on the left, the
review area in the centre (mode bar Ratios | Intensities | Table, the cycle
plot wall or the cycle table) and the inspector on the right (Stats now;
Rules, Corrections and Export in the next step).

Every rejection goes through :class:`rawtims.analysis.Analysis` operations,
so statistics, plots and table update at once and Undo/Redo walk the
history. Nothing is rejected automatically (SPEC section 0, decision 3).

Command line (the executable name is branding.EXECUTABLE_NAME; the pip
console script is set in pyproject.toml)::

    <app> [--theme light|dark|system] [--open PATH ...]
    <app> --export png PATH [--open PATH ...]   # render the window offscreen and exit
    <app> --version
    <app> --verify ...          # not available yet: exits 2
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    # Run as a script (PyInstaller's entry point): make `src/` importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims import branding
from rawtims.analysis import Analysis
from rawtims.fractions import Fraction
from rawtims.mapping import ElementMapping
from rawtims_gui.cycle_table import CycleTable
from rawtims_gui.fraction_list import FractionList
from rawtims_gui.inspector import StatsPanel, placeholder_tab
from rawtims_gui.plots import PlotState, PlotWall
from rawtims_gui.studio.theme import NeumorphicFrame, WallpaperWidget, apply_theme, build_application, paint_wallpaper
from rawtims_gui.studio.widgets import ElidedLabel, SegmentButton, SegmentedBar, _WorkflowRailDelegate, elide_tab_titles
from rawtims_gui.studio.workers import FunctionWorker
from rawtims_gui.workspace import Workspace, describe_path, read_paths

WORKFLOW_STEPS = ("Import", "Review", "Correct", "Export")
ACTIVE_STEPS = ("Import", "Review")
INSPECTOR_TABS = ("Stats", "Rules", "Corrections", "Export")
PLOT_MODES = {"ratios": "Ratios", "intensities": "Intensities", "table": "Table"}
DEFAULT_SIZE = QtCore.QSize(1280, 800)
MINIMUM_SIZE = QtCore.QSize(1024, 640)
GEOMETRY_KEY = "window/geometry"
THEME_KEY = "theme_mode"
THEME_MODES = ("light", "dark", "system")
DEFAULT_INTENSITIES = 6
RUN_FILTER = "Run files (*.xls *.XLS *.TIMSDP *.timsdp);;All files (*)"
LEGEND = "● used  ○ excluded  × invalid  — mean, bands 2SE · 1σ · 2σ   Click or drag: toggle · ⌘-click, ⇧-drag: select · B: block"
LEGEND_TIP = ("Filled: used. Hollow red: excluded by hand or by block. Grey cross: invalid value (never used).\n"
              "Line: mean of the used cycles; bands from dark to light: 2SE, 1σ, 2σ.\n"
              "Click a point to toggle that cycle; drag a box to toggle the cycles inside.\n"
              "⌘-click (Ctrl-click) adds a point to the selection; ⇧-drag selects a box.\n"
              "Delete or Backspace rejects the selection; B toggles its block; right-click for the block menu.\n"
              "SYNCH on: edits apply to every contract-mapped function. ⌘ + wheel zooms a plot.")


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


class MainWindow(QtWidgets.QMainWindow):
    """The single main window."""

    importFinished = QtCore.Signal(object)  # rawtims_gui.workspace.ImportResult

    def __init__(self, *, restore_geometry: bool = True) -> None:
        super().__init__()
        self.settings = app_settings()
        self.workspace = Workspace()
        self.current: tuple[Fraction, str] | None = None
        self.selection: set[int] = set()
        self.focus_key: str | None = None
        self.last_row: int | None = None
        self.plot_mode = "ratios"
        self.plot_kind = "ratios"  # the plotted set (ratios or intensities) the table and picker follow
        self.log_ratio = False
        self.skipped: list[tuple[str, str]] = []
        self._plotted: dict[int, dict[str, list[str]]] = {}
        self._workers: set[FunctionWorker] = set()
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
        file_menu.addActions([self.open_files_action, self.open_folder_action])
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
        view.addActions([self.log_action, self.synch_action])
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
            if name not in ACTIVE_STEPS:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEnabled & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
                item.setToolTip(f"{name}: next step")
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
        self.centre_stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.centre_stack)
        self.import_page = self._build_import_page()
        self.review_page = self._build_review_page()
        self.centre_stack.addWidget(self.import_page)
        self.centre_stack.addWidget(self.review_page)
        return frame

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
        self.legend = ElidedLabel(LEGEND)
        self.legend.setObjectName("SecondaryText")
        self.legend.setToolTip(LEGEND_TIP)
        layout.addWidget(self.legend)
        return page

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
        for name, text in (
            ("Rules", "Chauvenet and k-σ, each previewed before it is applied: next step."),
            ("Corrections", "Oxide correction, 18O/16O and the function-to-contract mapping: next step."),
            ("Export", "Contract CSV preview, Tripoli clipboard block and cycles CSV: next step."),
        ):
            self.inspector_tabs.addTab(placeholder_tab(text), name)
        elide_tab_titles(self.inspector_tabs)
        layout.addWidget(self.inspector_tabs, 1)
        return frame

    def _build_status_bar(self) -> None:
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
        """Read files and folders on the shared thread pool (or here, for scripted use) and add them."""
        paths = [str(path) for path in paths]
        if not paths:
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

    def _show_skipped(self, skipped: list[tuple[str, str]]) -> None:
        self.skipped_list.clear()
        for path, reason in skipped:
            item = QtWidgets.QListWidgetItem(f"{describe_path(path)}: {reason}")
            item.setToolTip(path)
            self.skipped_list.addItem(item)
        count = len(skipped)
        self.skipped_list.setFixedHeight(min(280, 28 * max(1, count) + 12))
        self.skipped_button.setText(f"{count} skipped")
        self.skipped_button.setToolTip("Files that were not opened, and why")
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
        self._update_titles()
        return ok

    def _workflow_step_changed(self, row: int) -> None:
        if WORKFLOW_STEPS[row] == "Import" or self.analysis is None:
            self.centre_stack.setCurrentWidget(self.import_page)
        else:
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
        return PlotState(analysis, self.mapping, self.log_ratio, frozenset(self.selection))

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

    def _after_edit(self, *, rebuild: bool = False) -> None:
        """Everything that shows the analysis follows its current flags."""
        state = self._state()
        if state is not None and self.plot_mode != "table":
            self.plot_wall.refresh(state, rebuild=rebuild)
        self.cycle_table.cycle_model.refresh()
        self.stats_panel.update_stats(self.analysis, self.mapping, self.stats_keys())
        self._sync_controls()
        self._update_titles()

    def stats_keys(self) -> list[str]:
        keys = self.plotted_keys("ratios")
        if self.plot_kind == "intensities":
            keys += self.plotted_keys("intensities")
        return keys

    def _update_titles(self) -> None:
        analysis = self.analysis
        if analysis is None or self.current is None:
            self.setWindowTitle(branding.DISPLAY_NAME)
            self.run_title.setText("")
            self.run_label.setText("No run selected")
            self.cycles_label.setText("")
            self.history_label.setText("")
            return
        fraction, element = self.current
        self.setWindowTitle(f"{branding.DISPLAY_NAME} — {fraction.fraction_id} {element}")
        self.run_title.setText(f"{fraction.fraction_id} · {element} · {analysis.run.raw.name}")
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
                       self.log_action, *self.mode_actions.values()):
            action.setEnabled(has_run)
        self.function_button.setEnabled(has_run)
        self.synch_action.blockSignals(True)
        self.synch_action.setChecked(analysis.settings.synced if has_run else True)
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
        self._rebuild_view()

    def set_log_ratio(self, checked: bool) -> None:
        self.log_ratio = bool(checked)
        state = self._state()
        if state is not None:
            self.plot_wall.refresh(state, rebuild=True)
        self._sync_controls()

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

    def edit_keys(self, key: str | None) -> list[str] | None:
        """Functions an edit addresses: SYNCH on → every mapped function (and the one clicked); off → the one clicked."""
        analysis = self.analysis
        assert analysis is not None
        key = key or self.focus_key
        if not analysis.settings.synced:
            return [key] if key else None
        mapping = self.mapping
        base = list(mapping.function_keys) if mapping is not None and mapping.function_keys else self.plotted_keys("ratios")
        keys = list(dict.fromkeys([*base, *([key] if key else [])]))
        return keys or None

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
        scope = "every contract-mapped function" if analysis.settings.synced else key
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

    def set_synch(self, checked: bool) -> None:
        analysis = self.analysis
        if analysis is not None and analysis.settings.synced != bool(checked):
            analysis.set_setting("synced", bool(checked))
            self.statusBar().showMessage("SYNCH on: rejections apply to every contract-mapped function" if checked
                                         else "SYNCH off: rejections apply only to the function clicked", 5000)
        self._after_edit()

    def undo(self) -> None:
        analysis = self.analysis
        if analysis is not None and analysis.undo() is not None:
            self._after_edit()

    def redo(self) -> None:
        analysis = self.analysis
        if analysis is not None and analysis.redo() is not None:
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
    parser.add_argument("--open", nargs="+", metavar="PATH", help="Open run files or folders at start")
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
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
