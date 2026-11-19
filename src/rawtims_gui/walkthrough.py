"""KD33 dead-time walkthrough, also deterministic without a visible window."""
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from rawtims.parity import drive_path
from rawtims.recalculation import load_dead_time_walkthrough
from rawtims_gui.workspace import Workspace

NAMES = ('KD33_z1_Pb.trip', 'KD33_z1_U_partial.trip')
STEPS = {
    1: 'Review KD33 z1 Pb + U. Exact Tripoli per-ratio rejections are restored as undoable history.',
    2: 'In Corrections › Reduction, use the raw route, change Pb Daly dead time from 36.3 to 40 ns, then Apply. U stays as acquired.',
    3: 'Inspect the parameter and ratio diff. Undo/Redo restores both values and parameters. Next: export.',
    4: 'Export needs shared cycles. Choose “Use shared cycles for export” for both runs, then save CSV or XLSX.',
    5: 'Send to IDTIMS_UPbRPy saves a contract CSV and opens the age app when configured. Date calculations happen there.',
}
REFERENCE = ('Legacy-mask reference dates (Ma), from the separate age engine: '
             '206/238 545.724 → 546.138; 207/235 545.752 → 545.409; '
             '207/206 545.868 → 542.367. A shared-cycle export has different masks; these are reference values, not live dates.')


def examples_folder(settings):
    return Path(settings.value('walkthrough/examples', str(drive_path()), type=str)).expanduser()


def availability(folder):
    missing = [name for name in NAMES if not (Path(folder) / name).is_file()]
    return ('Examples unavailable: ' + ', '.join(missing) + '. Choose the examples folder in Help.') if missing else ''


class Walkthrough(QtCore.QObject):
    def __init__(self, window, bar):
        super().__init__(window)
        self.window = window
        self.step = 0
        self.label = QtWidgets.QLabel()
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(0)
        layout = QtWidgets.QVBoxLayout(bar)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.label)
        row = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QPushButton('Back')
        self.next = QtWidgets.QPushButton('Next')
        self.shared = QtWidgets.QPushButton('Use shared cycles for export')
        self.close = QtWidgets.QPushButton('Close walkthrough')
        for button in (self.back, self.next, self.shared, self.close):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.bar = bar
        bar.hide()
        self.back.clicked.connect(lambda: self.set_step(max(1, self.step-1)))
        self.next.clicked.connect(self.advance)
        self.shared.clicked.connect(self.use_shared)
        self.close.clicked.connect(bar.hide)

    def start(self, *, folder=None, step=1, synchronous=False):
        folder = Path(folder) if folder else examples_folder(self.window.settings)
        problem = availability(folder)
        if problem:
            self.window.statusBar().showMessage(problem)
            return False
        if not self.window.maybe_save('walkthrough'):
            return False
        def install(analyses):
            workspace = Workspace(self.window.workspace.remembered)
            workspace.add(analyses)
            self.window._install_workspace(workspace, None, None)
            self.set_step(step, scripted=synchronous)
        if synchronous:
            install(load_dead_time_walkthrough(folder))
        else:
            self.window.reduction_controller.start_worker(lambda: load_dead_time_walkthrough(folder), install,
                                                          lambda message: self.window.statusBar().showMessage(message))
        return True

    def set_step(self, step, *, scripted=False):
        self.step = step
        w = self.window
        if step <= 3 or scripted:
            fraction = w.workspace.fractions[0]
            if w.analysis is not fraction.pb:
                w.select_run(fraction, 'Pb')
        if step >= 2 and (step <= 3 or scripted):
            w.show_correction_page('Reduction')
            if w.analysis.run.reduction_parameters.daly_dead_time_ns != 40:
                w.reduction_panel.dead_time.setText('40')
                if w.reduction_controller.support.get(w.analysis, (False, ''))[0]:
                    w.reduction_panel.route.setCurrentIndex(1)
        if scripted and step >= 3:
            # Headless uses the identical Apply path. Raw availability is verified
            # synchronously here so screenshots do not depend on event-loop timing.
            a = w.analysis
            from dataclasses import replace

            from rawtims.reduction_params import as_acquired
            from rawtims.reprocess import reprocess
            try:
                reprocess(a.run, replace(as_acquired(a.run), route='raw'))
            except (ValueError, OSError) as error:
                w.reduction_controller.probed(a, (False, str(error)))
            else:
                w.reduction_controller.probed(a, (True, 'Decoded and verified raw/workbook correspondence.'))
                w.reduction_panel.route.setCurrentIndex(1)
            w.reduction_controller.apply(synchronous=True)
        if step >= 4:
            w.set_workflow_step('Export')
        if scripted and step >= 5:
            self.use_shared()
        self.label.setText(f'Walkthrough {step}/5 · {STEPS[step]}')
        self.label.setToolTip(REFERENCE)
        self.shared.setVisible(step == 4)
        self.back.setEnabled(step > 1)
        self.next.setEnabled(step < 5)
        self.bar.show()

    def advance(self):
        if self.step == 2 and self.window.workspace.fractions[0].pb.run.reduction_parameters.daly_dead_time_ns != 40:
            self.label.setText('Set the Pb Daly dead time to 40 ns and press Apply before continuing.')
            return
        self.set_step(min(5, self.step+1))

    def use_shared(self):
        for a in self.window.workspace.analyses():
            if a.legacy_pending or not a.group_consistent():
                a.use_union_of_rejections()
        self.window._after_edit()
        self.label.setText('Shared cycles adopted in Pb and U (undoable per run). Save contract CSV or XLSX, then Next to Send. ' + REFERENCE)
