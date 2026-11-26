"""Persistent acquisition facts and non-blocking run warnings."""
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from rawtims.readers.ionvantage_raw import raw_folder


class RunInfoPanel(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        self.text = QtWidgets.QLabel("Open a run to see acquisition information.")
        self.text.setWordWrap(True)
        self.text.setMinimumWidth(0)
        self.text.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
        self.text.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.text)
        layout.addStretch()

    def update_run(self, analysis, raw_reason="Checking raw acquisition method…"):
        if analysis is None:
            self.text.setText("Open a run to see acquisition information.")
            return
        run, meta = analysis.run, analysis.run.metadata
        imports = sorted({op['label'] for op in analysis._history_view() if op.get('label', '').startswith('Imported from Tripoli project ')})
        lines = [*imports, f"Sample: {meta.sample_id or 'unknown'}", f"Serial: {meta.serial or 'unknown'}",
                 f"Method: {meta.method or 'unknown'}", f"Start: {meta.analysis_start_raw or meta.analysis_start or 'unknown'}",
                 f"Blocks × cycles: {run.blocks_measured} × {meta.cycles_per_block or '?'} ({run.n_cycles} measured)",
                 f"Software: {meta.software or 'unknown'}", f"Workbook: {run.raw.name}",
                 f"Acquisition folder: {raw_folder(Path(run.raw.path)) or 'not available'}",
                 f"Acquisition method: {raw_reason}", f"Current route: {run.reduction_parameters.route}",
                 "Warnings:", *(run.warnings or ('None',))]
        if 'vendor_rejected' in meta.extra:
            import numpy as np
            lines += [f"Vendor X cells: {np.count_nonzero(meta.extra['vendor_rejected'])} (retained, not applied)",
                      f"Vendor missing cells: {np.count_nonzero(meta.extra['vendor_missing'])}",
                      f"Time basis: {meta.extra['time_basis']}", f"Blocks: {meta.extra['block_basis']}"]
        self.text.setText('\n\n'.join(str(line) for line in lines))
