"""Crash-recovery copies of the open session, in the per-viewer app cache (no Qt).

While a session has unsaved changes the window writes a recovery copy here
(debounced), never next to the user's files. The copy is an ordinary session
file (:func:`rawtims.session.save_session`) with one extra block::

    "recovery": {"pid": 4242, "session_path": "/…/run.rawtims" or null}

A clean close, a save, or "Don't Save" removes the window's copy. A copy left
by a process that is no longer running is offered for restore on the next
launch. The folder is ``<platform cache root>/<CACHE_DIR_NAME>/recovery``; the
environment variable :data:`CACHE_ENV` replaces ``<root>/<CACHE_DIR_NAME>``
(the tests point it at a temporary folder).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rawtims.branding import CACHE_DIR_NAME, SESSION_EXTENSION
from rawtims.session import SessionState, save_session

CACHE_ENV = "RAWTIMS_CACHE_DIR"
PREFIX = "recovery-"


def cache_dir() -> Path:
    """The app's per-viewer cache folder (not created here)."""
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return root / CACHE_DIR_NAME


def recovery_dir() -> Path:
    return cache_dir() / "recovery"


def recovery_path(pid: int | None = None) -> Path:
    """This process's recovery copy."""
    return recovery_dir() / f"{PREFIX}{os.getpid() if pid is None else pid}{SESSION_EXTENSION}"


def write_recovery(state: SessionState, session_path: str | os.PathLike[str] | None) -> Path:
    folder = recovery_dir()
    folder.mkdir(parents=True, exist_ok=True)
    extra = {"recovery": {"pid": os.getpid(), "session_path": str(session_path) if session_path is not None else None}}
    return save_session(state, recovery_path(), extra=extra)


def discard(path: str | os.PathLike[str] | None = None) -> None:
    """Remove a recovery copy (this process's when ``path`` is None). Missing files are fine."""
    try:
        Path(path if path is not None else recovery_path()).unlink()
    except FileNotFoundError:
        pass


def _process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class Recovery:
    """A recovery copy left by a process that is no longer running."""

    path: Path
    session_path: str | None
    saved_at: datetime | None

    @property
    def session_name(self) -> str:
        return Path(self.session_path).name if self.session_path else "Untitled"


def pending() -> list[Recovery]:
    """Recovery copies whose process is gone, newest first. Unreadable copies are skipped (and kept)."""
    folder = recovery_dir()
    if not folder.is_dir():
        return []
    found: list[Recovery] = []
    for path in folder.glob(f"{PREFIX}*{SESSION_EXTENSION}"):
        try:
            pid = int(path.name[len(PREFIX):-len(SESSION_EXTENSION)])
        except ValueError:
            continue
        if _process_running(pid):
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            block = document.get("recovery") or {}
            stamp = document.get("saved_at")
            saved_at = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
        except (OSError, ValueError, AttributeError):
            continue
        session_path = block.get("session_path") if isinstance(block, dict) else None
        found.append(Recovery(path, session_path if isinstance(session_path, str) else None, saved_at))
    found.sort(key=lambda r: r.path.stat().st_mtime if r.path.exists() else 0, reverse=True)
    return found


__all__ = ["CACHE_ENV", "Recovery", "cache_dir", "discard", "pending", "recovery_dir", "recovery_path", "write_recovery"]
