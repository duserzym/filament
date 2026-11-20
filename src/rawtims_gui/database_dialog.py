"""Database sign-in and explicit fraction confirmation, with cancellable workers."""
from __future__ import annotations

from datetime import datetime
from html import escape
from threading import Event

from PySide6 import QtCore, QtGui, QtWidgets

from rawtims.fractions import Fraction, apply_link
from rawtims.upbdb import (
    Candidate,
    Client,
    DatabaseError,
    MatchResult,
    applied_chemistry_steps,
    cache_age,
    parse_fraction_id,
)
from rawtims_gui.studio.theme import active_theme
from rawtims_gui.studio.workers import FunctionWorker

# Keep worker/signal wrappers alive if a dialog is closed during a request.
_WORKERS = set()

_METHOD_NAMES = {
    "SP-TIMS-ANNEAL": "Anneal", "SP-TIMS-CA": "Chemical abrasion", "SP-TIMS-LEACH": "Leach",
    "SP-TIMS-WASH": "Wash", "SP-TIMS-SPIKE": "Spike", "SP-TIMS-DISS": "Dissolution",
    "SP-TIMS-CHLOR": "Chloride conversion", "SP-TIMS-COL": "Column chemistry", "SP-TIMS-LOAD": "Load",
}


class _CandidateDetails(QtWidgets.QTextBrowser):
    """Theme-aware, selectable details with a local clipboard action."""

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.anchorClicked.connect(self._copy_uid)
        self.fraction_uid = ""

    def _copy_uid(self, url):
        if url.toString() == "copy-uid" and self.fraction_uid:
            QtWidgets.QApplication.clipboard().setText(self.fraction_uid)

    def show_candidate(self, candidate: Candidate, *, offline: bool):
        theme = active_theme()
        f = candidate.fraction
        self.fraction_uid = f["id"]
        c = candidate.chemistry
        # Match the studio SectionTitle, SecondaryText and label typography.
        self.document().setDefaultStyleSheet(f"""
            body {{ color: {theme.text}; font-size: 12px; }}
            p {{ margin-top: 4px; margin-bottom: 4px; }}
            .heading {{ font-size: 16px; font-weight: 700; }}
            .section {{ color: {theme.muted}; font-size: 10px; font-weight: 600;
                        margin-top: 12px; margin-bottom: 5px; }}
            .muted {{ color: {theme.muted}; font-size: 11px; }}
            .outcome {{ color: {theme.danger}; font-weight: 600; }}
            a {{ color: {theme.accent}; text-decoration: none; }}
        """)
        header = escape(f"{candidate.sample['name']} {f['name']}")
        metadata = " · ".join(str(v) for v in (f.get("capsule_label"), f.get("capsule_set_name"),
                                                   candidate.batch.get("started_on"), f.get("status")) if v)
        parts = [f'<p class="heading">{header}</p>', f'<p class="muted">{escape(metadata)}</p>',
                 '<p class="section">Sources</p>']
        sources = [s for s in f.get("sources", []) if not s.get("retired_at")]
        for source in sources:
            labels = " · ".join(str(v) for v in (source.get("mount_name") or source.get("mount_label"),
                                                       source.get("spot_label"), source.get("grain_label")) if v)
            note = source.get("fragment_note") or "Fragment"
            fragment = f' <i class="muted">— {escape(note)}</i>' if source.get("is_fragment") else ""
            parts.append(f'<p>{escape(labels or "Source labels unavailable")}{fragment}</p>')
        if not sources:
            parts.append('<p class="muted">No LA source (sample-only fraction)</p>')
        parts.append('<p class="section">Chemistry</p>')
        steps = applied_chemistry_steps(candidate.batch, f["id"])
        for number, step in enumerate(steps, 1):
            name = _METHOD_NAMES.get(step.code, step.method_name)
            override = ' <i class="muted">(this capsule)</i>' if step.overridden else ""
            parameters = f' — {escape(step.text)}' if step.text else ""
            outcome = f' <span class="outcome">⚠ {escape(step.outcome.replace("_", " "))}</span>' if step.outcome else ""
            parts.append(f'<p>{number}. <b>{escape(name)}</b>{override}{parameters}{outcome}</p>')
        if not steps:
            parts.append('<p class="muted">No chemistry steps recorded</p>')
        parts.append('<p class="section">Spike</p>')
        if c.spike_solution or c.spike_weight_g is not None:
            spike = [escape(c.spike_solution or "Solution not recorded")]
            if c.spike_weight_g is not None:
                spike.append(f"{c.spike_weight_g:g} g")
            parts.append(f'<p>{" · ".join(spike)}</p>')
        else:
            parts.append('<p class="muted">No spike recorded yet</p>')
        try:
            stamp = datetime.fromisoformat(candidate.read_at).astimezone().strftime("%Y-%m-%d %H:%M")
            stamp += f" ({cache_age(candidate.read_at)})"
        except ValueError:
            stamp = candidate.read_at
        parts += ['<p class="section">Database</p>',
                  f'<p class="muted">Read {escape(stamp)}{" · from offline cache" if offline else ""}</p>',
                  (f'<p class="muted">Fraction UID: <span>{escape(self.fraction_uid[:8])}</span>'
                   ' &nbsp; <a href="copy-uid">Copy UID</a></p>')]
        if candidate.chemistry_message:
            parts.append(f'<p class="muted">{escape(candidate.chemistry_message)}</p>')
        self.setHtml("<body>" + "".join(parts) + "</body>")
        # QTextCharFormat tooltips work reliably in Qt rich text, including
        # when the UID is shortened or the surrounding paragraph wraps.
        uid_cursor = self.document().find(self.fraction_uid[:8], self.document().find("Fraction UID:").selectionEnd())
        uid_format = QtGui.QTextCharFormat()
        uid_format.setToolTip(self.fraction_uid)
        uid_cursor.mergeCharFormat(uid_format)
        self.verticalScrollBar().setValue(0)


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
        self.resize(900, 640)
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
        self.table.setMinimumHeight(self.table.horizontalHeader().height() + 4 * self.table.verticalHeader().defaultSectionSize() + 30)
        layout.addWidget(self.table, 2)
        self.summary = _CandidateDetails()
        layout.addWidget(self.summary, 3)
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
        self.summary.show_candidate(candidate, offline=self.match_result.offline)

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
