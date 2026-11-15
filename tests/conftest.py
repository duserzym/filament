"""Test-session switches.

Adapted from UPbRPy commit f8c561f, tests/conftest.py, on 2026-11-14 (shard
options, collection report, blocked imports, isolated QSettings and the
runtime test-map recorder). Changes: RAWTIMS_ environment variables, source
folders src/ and scripts/, Qt offscreen by default, temporary XDG folders in
place of Studio's autosave/results/inbox/standards folders, and no updater
thread wait.

Qt settings are redirected to a temporary INI folder for the whole run, so
tests never read or write the viewer's real preferences (window geometry,
theme).

``RAWTIMS_BLOCK_IMPORTS=requests,keyring`` makes those packages unimportable
for the whole run (scripts/run_tests.py sets it by default)::

    RAWTIMS_BLOCK_IMPORTS=requests,keyring QT_QPA_PLATFORM=offscreen python -m pytest tests -q
"""

from __future__ import annotations

import importlib.abc
import json
import os
import operator
import signal
import sys
import tempfile
from pathlib import Path

import pytest


def pytest_addoption(parser):
    """Allow a collected file to be split between independent processes."""
    parser.addoption("--shard-index", type=int, default=0, help="Zero-based collection shard")
    parser.addoption("--shard-count", type=int, default=1, help="Number of collection shards")


def pytest_configure(config):
    index, count = config.getoption("shard_index"), config.getoption("shard_count")
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError("require --shard-count >= 1 and 0 <= --shard-index < --shard-count")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """Keep modulo positions after normal collection and marker filtering."""
    index, count = config.getoption("shard_index"), config.getoption("shard_count")
    kept, removed = [], []
    for position, item in enumerate(items):
        (kept if position % count == index else removed).append(item)
    items[:] = kept
    if removed:
        config.hook.pytest_deselected(items=removed)


def pytest_collection_finish(session):
    """Let the runner audit exact shard coverage, including parametrized IDs."""
    report = os.environ.get("RAWTIMS_TEST_COLLECTION")
    if report:
        Path(report).write_text(json.dumps([item.nodeid for item in session.items]))


# Install before collection, including GUI modules with import-time defaults.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# HOME-like folders: anything that follows the XDG variables (caches, config)
# writes to a temporary tree, never to the viewer's own folders.
_home_folder = tempfile.TemporaryDirectory(prefix="rawtims-test-home-")
for _variable, _name in (("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data")):
    os.environ[_variable] = str(Path(_home_folder.name) / _name)
# The app cache (session recovery copies) goes there too, on every platform.
os.environ["RAWTIMS_CACHE_DIR"] = str(Path(_home_folder.name) / "cache" / "app")


class _BlockedImports(importlib.abc.MetaPathFinder):
    def __init__(self, names: set[str]) -> None:
        self.names = names

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in self.names:
            raise ModuleNotFoundError(
                f"{fullname} is blocked by RAWTIMS_BLOCK_IMPORTS", name=fullname
            )
        return None


_blocked = {
    name.strip()
    for name in os.environ.get("RAWTIMS_BLOCK_IMPORTS", "").split(",")
    if name.strip()
}
if _blocked:
    for _name in list(sys.modules):
        if _name.split(".", 1)[0] in _blocked:
            del sys.modules[_name]
    sys.meta_path.insert(0, _BlockedImports(_blocked))


def _isolate_qt_settings() -> Path | None:
    try:
        from PySide6 import QtCore
    except ImportError:
        return
    import tempfile

    folder = tempfile.mkdtemp(prefix="rawtims-test-settings-")
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    for scope in (QtCore.QSettings.Scope.UserScope, QtCore.QSettings.Scope.SystemScope):
        QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, scope, folder)

    class IsolatedQSettings(QtCore.QSettings):
        """Redirect the organization-name overload, which always uses native settings."""

        def __init__(self, *args, **kwargs):
            if args and isinstance(args[0], str) and (len(args) < 2 or isinstance(args[1], str)):
                super().__init__(self.Format.IniFormat, self.Scope.UserScope, *args, **kwargs)
            else:
                super().__init__(*args, **kwargs)

    # Install before collection imports any GUI modules. Explicit format and
    # file-name overloads still go through to Qt unchanged; enums are inherited.
    QtCore.QSettings = IsolatedQSettings
    return Path(folder)


_qt_settings_folder = _isolate_qt_settings()


@pytest.fixture
def qt_settings_folder() -> Path:
    """Return the temporary settings root installed before test collection."""
    if _qt_settings_folder is None:
        pytest.skip("PySide6 is unavailable")
    return _qt_settings_folder


@pytest.fixture(autouse=True)
def gui_deadline_and_no_modal_dialogs(request, monkeypatch):
    """Fail an unexpected dialog immediately; bound each GUI test including teardown."""
    if not any(word in request.node.path.stem for word in ("gui", "window")):
        yield
        return
    from PySide6 import QtWidgets

    def unexpected(*args, **kwargs):
        raise AssertionError("GUI tests must inject dialog answers")

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", unexpected)
    for name in ("getOpenFileName", "getOpenFileNames", "getSaveFileName", "getExistingDirectory"):
        monkeypatch.setattr(QtWidgets.QFileDialog, name, unexpected)
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    def expired(signum, frame):
        raise TimeoutError(f"GUI test exceeded 45 seconds: {request.node.nodeid}")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 45)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class _OpenAuditSink:
    """Route open audits to Python while handling other events in C.

    The bound object.__setattr__ method is the audit callback. The open
    descriptor invokes the recorder; frequent reflection audits use a C no-op.
    Unknown event names retain only their latest arguments until a file boundary.
    """

    __slots__ = ("_callback", "__dict__")

    def __init__(self, callback):
        self._callback = callback

    def _opened(self, args):
        self._callback("open", args)

    open = property(fset=_opened)


for _audit_event in ("object.__getattr__", "object.__setattr__", "object.__delattr__", "sys._getframe"):
    setattr(_OpenAuditSink, _audit_event, property(fset=operator.is_))


class TestMapRecorder:
    """Record file-level Python execution and repository opens with stdlib hooks."""

    def __init__(self, root: Path, folder: Path):
        import time

        self.root = root.resolve()
        self.prefix = str(self.root) + os.sep
        self.source_prefixes = tuple(self.prefix + name + os.sep for name in ("src", "scripts"))
        self.folder = folder
        self.pid = os.getpid()
        self.current = None
        self.records = {}
        self.code_paths = {}
        self.open_paths = {}
        self.callback_seconds = 0.0
        self.clock = time.perf_counter
        self.started = self.clock()
        self.active = True
        monitoring = sys.monitoring
        self.tool = next((tool for tool in (monitoring.COVERAGE_ID, monitoring.PROFILER_ID, *range(6)) if monitoring.get_tool(tool) is None), None)
        if self.tool is None:
            raise RuntimeError("No free sys.monitoring tool ID for the test map")
        monitoring.use_tool_id(self.tool, "rawtims-test-map")
        monitoring.register_callback(self.tool, monitoring.events.PY_START, self.on_start)
        monitoring.set_events(self.tool, monitoring.events.PY_START)
        # Audit hooks cannot be removed; active=False makes this inert on finish.
        self.audit_sink = _OpenAuditSink(self.on_audit)
        sys.addaudithook(self.audit_sink.__setattr__)

    def start_file(self, path):
        before = self.clock()
        relative = self.repository_path(os.fspath(path))
        if relative != self.current:
            self.audit_sink.__dict__.clear()
            self.current = relative
            if relative:
                self.records.setdefault(relative, {"functions": set(), "files": set()})
            sys.monitoring.restart_events()
        self.callback_seconds += self.clock() - before

    def repository_path(self, path):
        if not isinstance(path, (str, bytes, os.PathLike)):
            return None
        path = os.fsdecode(path)
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        if not path.startswith(self.prefix):
            return None
        # Resolve symlinks and '..' before admitting a repository path.
        try:
            relative = Path(path).resolve().relative_to(self.root)
        except (ValueError, OSError):
            return None
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            return None
        return relative.as_posix()

    def on_start(self, code, offset):
        before = self.clock()
        if self.current:
            filename = code.co_filename
            if filename not in self.code_paths:
                self.code_paths[filename] = self.repository_path(filename) if filename.startswith(self.source_prefixes) else None
            path = self.code_paths[filename]
            if path:
                self.records[self.current]["functions"].add((path, code.co_qualname))
        self.callback_seconds += self.clock() - before
        return sys.monitoring.DISABLE

    def on_audit(self, event, args):
        if event != "open" or not self.active or not self.current:
            return
        before = self.clock()
        path = args[0]
        # Relative opens depend on cwd, so cache only absolute names.
        if isinstance(path, (str, bytes)) and os.path.isabs(path):
            if path not in self.open_paths:
                self.open_paths[path] = self.repository_path(path)
            relative = self.open_paths[path]
        else:
            relative = self.repository_path(path)
        if relative:
            self.records[self.current]["files"].add(relative)
        self.callback_seconds += self.clock() - before

    def finish(self):
        self.active = False
        self.audit_sink.__dict__.clear()
        sys.monitoring.set_events(self.tool, 0)
        sys.monitoring.register_callback(self.tool, sys.monitoring.events.PY_START, None)
        sys.monitoring.free_tool_id(self.tool)
        if os.getpid() != self.pid:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        record = {test: {key: sorted(values) for key, values in entry.items()} for test, entry in self.records.items()}
        (self.folder / f"{self.pid}.json").write_text(json.dumps(record) + "\n")
        (self.folder / f"{self.pid}.stats").write_text(json.dumps({"callback_seconds": self.callback_seconds, "session_seconds": self.clock() - self.started}) + "\n")


_recorder = None


def pytest_sessionstart(session):
    global _recorder
    folder = os.environ.get("RAWTIMS_TEST_MAP_DIR")
    if folder:
        _recorder = TestMapRecorder(Path(__file__).resolve().parents[1], Path(folder))


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    """Include imports and data reads during each test module's collection."""
    if _recorder is not None and isinstance(collector, pytest.Module):
        _recorder.start_file(collector.path)
    return (yield)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    if _recorder is not None:
        _recorder.start_file(item.path)
    return (yield)


def pytest_sessionfinish(session, exitstatus):
    global _recorder
    if _recorder is not None:
        _recorder.finish()
        _recorder = None
