"""Database sign-in and explicit fraction confirmation, with cancellable workers."""
from __future__ import annotations

from threading import Event

from PySide6 import QtCore, QtWidgets

from rawtims.fractions import Fraction, apply_link
from rawtims.upbdb import Client, DatabaseError, MatchResult, parse_fraction_id
from rawtims_gui.studio.workers import FunctionWorker

# Keep worker/signal wrappers alive if a dialog is closed during a request.
_WORKERS = set()


class _AsyncDialog(QtWidgets.QDialog):
    workFinished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancelled = Event()
        self.busy = False
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.setTextFormat(QtCore.Qt.TextFormat.PlainText)

    def run(self, function):
        self.busy = True
        self.set_busy(True)
        self.message.setText("Connecting… Cancel stops the lookup after the current request.")
        worker = FunctionWorker(function)
        worker.signals.succeeded.connect(self._succeeded)
        worker.signals.failed.connect(self._failed)
        worker.signals.finished.connect(self._finished)
        worker.signals.finished.connect(lambda w=worker: _WORKERS.discard(w))
        _WORKERS.add(worker)
        QtCore.QThreadPool.globalInstance().start(worker)

    @QtCore.Slot()
    def _finished(self):
        self.busy = False
        self.workFinished.emit()

    @QtCore.Slot(str, str)
    def _failed(self, message, _trace):
        self.busy = False
        if not self.cancelled.is_set():
            self.set_busy(False)
            self.message.setText(message)

    def reject(self):
        self.cancelled.set()
        super().reject()

    def closeEvent(self, event):
        self.cancelled.set()
        super().closeEvent(event)


class ConnectDialog(_AsyncDialog):
    def __init__(self, server: str = "", parent=None, *, client_factory=Client):
        super().__init__(parent)
        self.setWindowTitle("Connect to UPbDB")
        self.resize(480, 310)
        self.client_factory = client_factory
        self.client = None
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.server = QtWidgets.QLineEdit(server)
        self.username = QtWidgets.QLineEdit()
        self.password = QtWidgets.QLineEdit()
        self.password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.token = QtWidgets.QLineEdit()
        self.token.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        for label, widget in (("Server", self.server), ("Username", self.username), ("Password", self.password),
                              ("Or pasted token", self.token)):
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addWidget(self.message)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.connect_button = buttons.addButton("Connect", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.cache_button = buttons.addButton("Use offline cache", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        self.connect_button.clicked.connect(self.connect_database)
        self.cache_button.clicked.connect(self.use_cache)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_busy(self, busy):
        for widget in (self.server, self.username, self.password, self.token, self.connect_button, self.cache_button):
            widget.setEnabled(not busy)

    def connect_database(self):
        server, username, password, token = self.server.text(), self.username.text(), self.password.text(), self.token.text()
        self.password.clear()
        self.token.clear()
        def connect():
            client = self.client_factory(server, cancelled=self.cancelled.is_set)
            if token.strip() or not password:
                client.use_token(token or None)
            else:
                client.login(username.strip(), password)
            return client
        self.run(connect)

    def use_cache(self):
        server = self.server.text()
        self.password.clear()
        self.token.clear()
        def cached():
            client = self.client_factory(server, cancelled=self.cancelled.is_set)
            if not client.account.get("username"):
                raise DatabaseError("No previously signed-in account is cached for this server. Connect first.")
            client.offline_only = True
            client.status = "offline · using cache"
            return client
        self.run(cached)

    @QtCore.Slot(object)
    def _succeeded(self, client):
        self.busy = False
        if self.cancelled.is_set():
            return
        self.client = client
        self.accept()


class LinkDialog(_AsyncDialog):
    def __init__(self, client: Client, fraction_id: str, parent=None, *, fraction: Fraction | None = None):
        super().__init__(parent)
        self.setWindowTitle("Link fraction to database")
        self.resize(880, 600)
        self.setMaximumSize(900, 640)
        self.client = client
        self.fraction = fraction
        self.link = None
        self.match_result = MatchResult(reason="not_parsed")
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QHBoxLayout()
        parsed = parse_fraction_id(fraction_id)
        self.sample = QtWidgets.QLineEdit(parsed[0] if parsed else "")
        self.name = QtWidgets.QLineEdit(parsed[1] if parsed else "")
        self.lookup_button = QtWidgets.QPushButton("Find candidates")
        form.addWidget(QtWidgets.QLabel("Sample"))
        form.addWidget(self.sample, 2)
        form.addWidget(QtWidgets.QLabel("Fraction"))
        form.addWidget(self.name, 1)
        form.addWidget(self.lookup_button)
        layout.addLayout(form)
        layout.addWidget(self.message)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Sample / project / UUID", "Fraction", "Capsule / set", "Batch start", "Status", "Sources"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 240)
        self.table.setColumnWidth(5, 230)
        layout.addWidget(self.table, 2)
        self.summary = QtWidgets.QPlainTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        self.link_button = buttons.addButton("Link", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole)
        self.link_button.setEnabled(False)
        self.link_button.setVisible(False)
        layout.addWidget(buttons)
        buttons.rejected.connect(self.reject)
        self.lookup_button.clicked.connect(self.lookup)
        self.link_button.clicked.connect(self.confirm)
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.sample.textChanged.connect(self.invalidate)
        self.name.textChanged.connect(self.invalidate)
        self.show_result(self.match_result)

    def invalidate(self):
        self.show_result(MatchResult(reason="not_parsed"))

    def set_busy(self, busy):
        for widget in (self.sample, self.name, self.lookup_button, self.table):
            widget.setEnabled(not busy)
        self.link_button.setEnabled(False)

    def lookup(self):
        sample, name = self.sample.text(), self.name.text()
        self.show_result(MatchResult())
        self.cancelled.clear()
        self.client.cancelled = self.cancelled.is_set
        self.run(lambda: self.client.lookup(sample=sample, name=name))

    @QtCore.Slot(object)
    def _succeeded(self, result):
        self.busy = False
        if not self.cancelled.is_set():
            self.set_busy(False)
            self.show_result(result)

    def show_result(self, result: MatchResult):
        self.match_result = result
        self.table.clearSelection()
        self.table.setRowCount(len(result.candidates))
        self.summary.clear()
        self.message.setText(result.message)
        for row, candidate in enumerate(result.candidates):
            f = candidate.fraction
            sources = []
            for source in f.get("sources", []):
                if source.get("retired_at"):
                    continue
                sources.append(" · ".join(str(v) for v in (
                    source.get("mount_name") or source.get("mount_label"), source.get("spot_label"),
                    source.get("grain_label"), source.get("fragment_note") if source.get("is_fragment") else "") if v))
            values = [candidate.sample_label, f["name"],
                      " ".join(v for v in (f.get("capsule_label"), f.get("capsule_set_name")) if v),
                      candidate.batch.get("started_on", ""), f.get("status", ""), "; ".join(sources)]
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value + (f"\nSample UUID: {candidate.sample['id']}" if column == 0 else ""))
                self.table.setItem(row, column, item)
        self.table.clearSelection()  # A single result still requires a deliberate click.
        self.link_button.setVisible(bool(result.candidates))
        self.link_button.setEnabled(False)

    def selection_changed(self):
        selected = self.table.selectionModel().selectedRows()
        self.link_button.setEnabled(len(selected) == 1 and not self.busy)
        if len(selected) != 1:
            self.summary.clear()
            return
        candidate = self.match_result.candidates[selected[0].row()]
        c = candidate.chemistry
        self.summary.setPlainText("\n".join(filter(None, [
            candidate.chemistry_message, "Annealing: " + (c.annealing or "—"),
            "Chemical abrasion: " + (c.chemical_abrasion or "—"), "Steps: " + (c.chemistry_steps or "—"),
            "Spike: " + (c.spike_solution or "—"),
            "Spike weight (g): " + (repr(c.spike_weight_g) if c.spike_weight_g is not None else "—"),
            "Fraction UID: " + candidate.fraction["id"], "Database read at: " + candidate.read_at])))

    def confirm(self):
        selected = self.table.selectionModel().selectedRows()
        if len(selected) != 1 or self.busy:
            return
        try:
            self.link = self.match_result.candidates[selected[0].row()].confirm(self.client.server, self.client.account.get("username", ""))
        except DatabaseError as error:
            self.message.setText(str(error))
            return
        if self.fraction is not None:
            apply_link(self.fraction, self.link)
        self.accept()
