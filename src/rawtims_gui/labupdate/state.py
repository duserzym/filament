"""Immutable updater states, user messages and compact button presentation."""

from dataclasses import dataclass, replace
from pathlib import Path
import urllib.error

from . import tls
from .install import NotConfiguredError
from .manifest import NoPublicRelease
from .minisign import SignatureError

STATES = frozenset({"idle", "checking", "none", "available", "downloading", "ready", "installing", "error", "unsupported"})


@dataclass(frozen=True)
class UpdateState:
    """State value, retaining raw diagnostics separately from friendly messages."""

    status: str = "idle"
    info: object = None
    progress: int = 0
    total: int = 0
    path: Path | None = None
    message: str = ""
    manual: bool = False
    kind: str = ""
    app_name: str = "Application"
    host: str = "github.com"

    def __post_init__(self):
        if self.status not in STATES:
            raise ValueError(f"Unknown update state: {self.status}")


def transition(state: UpdateState, event) -> UpdateState:
    """Apply Studio-style events, ignoring illegal transitions and repeated checks."""
    name, *args = (event,) if isinstance(event, str) else event
    if name == "check_started":
        manual = bool(args and args[0])
        if state.status in {"checking", "downloading", "installing"} or (state.status == "ready" and not manual):
            return state
        return UpdateState("checking", manual=manual, app_name=state.app_name, host=state.host)
    if name == "unsupported":
        return replace(state, status="unsupported", message=str(args[0]), kind=args[1] if len(args) > 1 else "")
    if name == "no_update" and state.status == "checking":
        return replace(state, status="none")
    if name == "found" and state.status == "checking":
        return replace(state, status="available", info=args[0])
    if name == "download_started" and state.status == "available":
        return replace(state, status="downloading", progress=0, total=0)
    if name == "progress" and state.status == "downloading":
        return replace(state, progress=args[0], total=args[1])
    if name == "downloaded" and state.status == "downloading":
        return replace(state, status="ready", path=Path(args[0]))
    if name == "install_started" and state.status == "ready":
        return replace(state, status="installing")
    if name == "failed" and state.status in {"checking", "downloading", "ready", "installing"}:
        kind, _ = classify_error(args[0], app=state.app_name, host=state.host)
        return replace(state, status="error", path=None, message=str(args[0]), kind=kind)
    return state


def _message(kind, *, app, host, raw=""):
    return {
        "certificate": f"Could not verify the secure connection to {host}.",
        "offline": f"No internet connection, or {host} did not answer.",
        "no_release": f"No public release of {app} has been published.",
        "signature": "The update's signature did not match. Nothing was installed.",
        "not_writable": f"{app} cannot replace itself in this folder. Download the new version from GitHub.",
        "not_configured": "Updates are not configured for this build yet.",
        "other": "The update check failed: " + (raw[:117] + "…" if len(raw) > 120 else raw),
    }[kind]


def classify_error(exc, *, app="Application", host="github.com") -> tuple[str, str]:
    """Classify typed errors; callers supply application and update-host names."""
    raw = " ".join(str(exc).split())
    lower = raw.lower()
    if isinstance(exc, NotConfiguredError) or any(word in lower for word in ("pubkey", "public key", "not configured")):
        kind = "not_configured"
    elif tls.is_certificate_error(exc) or any(word in lower for word in ("certificate", "unknownissuer", "invalid peer certificate")):
        kind = "certificate"
    elif isinstance(exc, SignatureError) or any(word in lower for word in ("signature", "minisign", "verify")):
        kind = "signature"
    elif isinstance(exc, NoPublicRelease) or (isinstance(exc, urllib.error.HTTPError) and exc.code == 404) or any(word in lower for word in ("404", "release json", "could not fetch a valid release", "not found", "no assets")):
        kind = "no_release"
    elif isinstance(exc, (ConnectionError, TimeoutError)) or (isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError)) or any(word in lower for word in ("dns", "connect", "timed out", "timeout", "offline", "network", "error sending request", "enotfound", "urlerror")):
        kind = "offline"
    elif isinstance(exc, PermissionError) or "not writable" in lower:
        kind = "not_writable"
    else:
        kind = "other"
    return kind, _message(kind, app=app, host=host, raw=raw)


@dataclass(frozen=True)
class ButtonView:
    """Compact text, optional action, badge and animation flags."""

    text: str
    action: str | None
    badge: bool
    busy: bool


def button_view(state: UpdateState, version: str, auto_download=True) -> ButtonView:
    """Derive the compact UI while preserving state.message for a Details line."""
    info = state.info
    target = "v" + (info.get("version", "") if isinstance(info, dict) else getattr(info, "version", "")).removeprefix("v")
    current = "v" + version.removeprefix("v")
    percent = min(100, max(0, int(100 * state.progress / state.total))) if state.total else 0
    text = {
        "idle": f"Current version: {current}",
        "checking": "Checking for updates…",
        "none": f"Up to date ({current})",
        "available": f"Update available: {target}\nCurrent version: {current}",
        "downloading": f"Downloading {target}…" + (f" {percent}%" if state.total else ""),
        "ready": f"{target} is ready",
        "installing": f"Installing {target} and restarting…",
        "error": _message(state.kind or "other", app=state.app_name, host=state.host, raw=state.message),
        "unsupported": _message(state.kind, app=state.app_name, host=state.host, raw=state.message) if state.kind else state.message,
    }[state.status]
    action = ("download" if state.status == "available" and not auto_download else
              "restart" if state.status == "ready" else "page" if state.status == "unsupported" else None)
    return ButtonView(text, action, state.status in {"available", "ready"} or (state.status == "unsupported" and bool(info)), state.status in {"checking", "downloading", "installing"})
