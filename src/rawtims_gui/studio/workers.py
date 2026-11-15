# Copied from UPbRPy commit 0b16f36, path GUI/workers.py, on 2026-11-14.
# Local changes: none (the whole file, unchanged below this header).
"""Small Qt worker adapter for keeping reduction calculations off the UI thread."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6 import QtCore


class WorkerSignals(QtCore.QObject):
    """Signals emitted by a :class:`FunctionWorker`."""

    succeeded = QtCore.Signal(object)
    failed = QtCore.Signal(str, str)
    finished = QtCore.Signal()


class FunctionWorker(QtCore.QRunnable):
    """Run one argument-free callable on Qt's shared worker pool."""

    def __init__(self, function: Callable[[], Any]) -> None:
        """Store the callable without executing it on the GUI thread."""
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @QtCore.Slot()
    def run(self) -> None:
        """Execute the callable and report either its value or traceback."""
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(str(exc), traceback.format_exc())
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


__all__ = ["FunctionWorker", "WorkerSignals"]
