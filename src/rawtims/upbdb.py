"""Qt-free, read-only UPbDB fraction lookups and explicitly confirmed snapshots.

Only authentication uses POST. The injectable transport takes (method, url,
headers, body) and returns Response; no live server is needed by tests.
Tokens live in the OS keychain or process memory, never in the lookup cache.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from rawtims.branding import (
    APP_NAME,
    CACHE_DIR_NAME,
    DATABASE_CACHE_FORMAT,
    DATABASE_KEYRING_SERVICE,
    DATABASE_LINK_FORMAT,
    VERSION,
)

KEYRING_SERVICE = DATABASE_KEYRING_SERVICE
LINK_FORMAT = DATABASE_LINK_FORMAT
CACHE_FORMAT = DATABASE_CACHE_FORMAT
MAX_LOOKUPS = 64


class DatabaseError(Exception):
    """A message suitable for display in the GUI."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class ConnectionFailed(DatabaseError):
    """The server could not be reached."""


class Cancelled(DatabaseError):
    """The person cancelled a lookup."""


def normalize_server(server: str) -> str:
    text = str(server or "").strip()
    if not text:
        raise DatabaseError("Enter the database server address.")
    if "://" not in text:
        host = text.split("/", 1)[0].split(":", 1)[0].lower()
        text = ("http://" if host in {"localhost", "127.0.0.1"} or text.startswith("[::1]")
                or host.endswith(".localhost") else "https://") + text
    try:
        parts = urlsplit(text)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError
        _ = parts.port
    except ValueError:
        raise DatabaseError("Enter an http(s) server address without credentials.") from None
    path = parts.path.rstrip("/")
    path = path.removesuffix("/v1")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


class TokenStore:
    """Keyring with an in-memory fallback, including failed keychain writes."""

    def __init__(self):
        self.memory: dict[str, str] = {}
        self.forgotten: set[str] = set()

    def get(self, server: str) -> str | None:
        server = normalize_server(server)
        if server in self.forgotten:
            return None
        if server in self.memory:
            return self.memory[server]
        try:
            return importlib.import_module("keyring").get_password(KEYRING_SERVICE, server)
        except Exception:  # noqa: BLE001 — keyring backends raise platform-specific errors; never log secrets.
            return None

    def set(self, server: str, token: str) -> None:
        server = normalize_server(server)
        self.forgotten.discard(server)
        self.memory[server] = token
        try:
            importlib.import_module("keyring").set_password(KEYRING_SERVICE, server, token)
        except Exception:  # noqa: BLE001 — keyring backends raise platform-specific errors; never log secrets.
            return  # Keep the process-memory token when the keychain is unavailable.

    def delete(self, server: str) -> None:
        server = normalize_server(server)
        self.memory.pop(server, None)
        self.forgotten.add(server)
        try:
            importlib.import_module("keyring").delete_password(KEYRING_SERVICE, server)
        except Exception:  # noqa: BLE001 — keyring backends raise platform-specific errors; never log secrets.
            return  # A forgotten token stays masked in this process.


TOKENS = TokenStore()


def app_data_dir() -> Path:
    """Use the same platform root and override as recovery copies."""
    if os.environ.get("RAWTIMS_CACHE_DIR"):
        return Path(os.environ["RAWTIMS_CACHE_DIR"]).expanduser()
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return root / CACHE_DIR_NAME


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def cache_age(stamp: str) -> str:
    seconds = max(0, (datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds())
    if seconds < 60:
        return "less than a minute ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"


def parse_fraction_id(value: str) -> tuple[str, str] | None:
    parts = value.strip().rsplit(None, 1)
    if len(parts) == 2 and re.fullmatch(r"[a-z]{1,3}[0-9]{1,3}[a-z]?", parts[1], re.IGNORECASE):
        return parts[0], parts[1]
    return None


@dataclass(frozen=True)
class Source:
    grain_uid: str = ""
    spot_uid: str = ""
    mount_name: str = ""
    grain_label: str = ""
    spot_label: str = ""
    is_fragment: bool = False
    fragment_note: str = ""


@dataclass(frozen=True)
class ChemistrySummary:
    annealing: str = ""
    annealing_temperature_c: float | None = None
    annealing_duration_h: float | None = None
    chemical_abrasion: str = ""
    ca_temperature_c: float | None = None
    ca_duration_h: float | None = None
    chemistry_steps: str = ""
    spike_solution: str = ""
    spike_version_uid: str = ""
    spike_registry_id: str = ""
    spike_weight_g: float | None = None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise DatabaseError("The database returned a non-finite chemistry value.")
    return number


def _step_parameters_text(params: dict, definitions: list[dict]) -> str:
    definitions_by_key = {d.get("config_key") or d["name"]: d for d in definitions
                          if d.get("config_key") or d.get("name")}
    leading = ("temperature_c", "duration_h", "acid", "vessel")
    ordered_names = dict.fromkeys((*leading, *definitions_by_key, *params))
    parts = []
    for name in ordered_names:
        value = params.get(name)
        if value in (None, "", []):
            continue
        definition = definitions_by_key.get(name, {})
        if (isinstance(value, (int, float)) and not isinstance(value, bool)) or definition.get("type") in {"number", "integer"}:
            text = f"{float(value):g}"
        else:
            text = str(value)
        if name in leading:
            unit = {"temperature_c": "°C", "duration_h": "h"}.get(name)
        else:
            unit = definition.get("unit")
            label = re.sub(r"_(min|c|h|g)$", "", definition.get("name") or name).replace("_", " ")
            text = f"{label} {text}"
        parts.append(f"{text} {unit}" if unit else text)
    return ", ".join(parts)


def chemistry_summary(batch: dict, fraction_uid: str) -> ChemistrySummary:
    overrides = {r["step_id"]: r for r in batch.get("fraction_step_records", [])
                 if r.get("fraction_id") == fraction_uid}
    additions = {r["step_id"]: r for r in batch.get("spikes", []) if r.get("fraction_id") == fraction_uid}
    anneals, cas, texts, spike_values = [], [], [], {}
    for step in sorted(batch.get("steps", []), key=lambda s: s.get("ordinal", 0)):
        record = overrides.get(step["id"], {})
        if record.get("skipped"):
            continue
        params = {**step.get("parameters", {}), **record.get("parameters", {})}
        code = step["method_code"]
        if code == "SP-TIMS-SPIKE":
            addition = additions.get(step["id"], {})
            if addition.get("spike_version_id"):
                params["spike_version"] = addition["spike_version_id"]
            if addition.get("spike_weight_g") is not None:
                params["spike_weight_g"] = addition["spike_weight_g"]
        items = []
        for key, unit in (("temperature_c", "°C"), ("duration_h", "h")):
            if params.get(key) not in (None, "", []):
                items.append(f"{float(params[key]):g} {unit}")
        for key in ("acid", "vessel"):
            if params.get(key):
                items.append(str(params[key]))
        items += [f"{key}={value}" for key, value in params.items()
                  if key not in {"temperature_c", "duration_h", "acid", "vessel"} and value is not None]
        outcome = record.get("outcome") or params.get("outcome")
        text = ", ".join(items)
        if code == "SP-TIMS-CA" and outcome:
            text += f" ({outcome})"
        if code == "SP-TIMS-ANNEAL":
            anneals.append((text, params))
        elif code == "SP-TIMS-CA":
            cas.append((text, params))
        elif code == "SP-TIMS-SPIKE":
            addition = additions.get(step["id"], {})
            version_id = addition.get("spike_version_id") or params.get("spike_version") or ""
            version = batch.get("spike_versions", {}).get(version_id, {})
            key = "/".join(str(version[k]) for k in ("registry_id", "subfraction", "version")) if all(
                version.get(k) for k in ("registry_id", "subfraction", "version")) else ""
            spike_values = {"spike_version_uid": version_id, "spike_solution": key,
                            "spike_registry_id": version.get("registry_id", ""),
                            "spike_weight_g": _number(addition.get("spike_weight_g", params.get("spike_weight_g")))}
        if code == "SP-TIMS-SPIKE":
            weight = spike_values["spike_weight_g"]
            step_text = ", ".join(part for part in (key, f"{weight:g} g" if weight is not None else "") if part)
        else:
            step_text = _step_parameters_text(params, step.get("parameter_definitions") or [])
            if code == "SP-TIMS-CA" and outcome:
                step_text += f" ({outcome})"
        texts.append(f"{code} {step_text}".rstrip())
    def one(steps, key):
        return _number(steps[0][1].get(key)) if len(steps) == 1 else None
    return ChemistrySummary(
        annealing="; ".join(s[0] for s in anneals),
        annealing_temperature_c=one(anneals, "temperature_c"), annealing_duration_h=one(anneals, "duration_h"),
        chemical_abrasion="; ".join(s[0] for s in cas),
        ca_temperature_c=one(cas, "temperature_c"), ca_duration_h=one(cas, "duration_h"),
        chemistry_steps="; ".join(texts), **spike_values)


@dataclass(frozen=True)
class DatabaseLink:
    server: str
    fraction_uid: str
    sample_uid: str
    sample_name: str
    fraction_name: str
    capsule_label: str = ""
    capsule_set_name: str = ""
    batch_uid: str = ""
    batch_started_on: str = ""
    sources: list[Source] = field(default_factory=list)
    chemistry: ChemistrySummary = field(default_factory=ChemistrySummary)
    database_read_at: str = ""
    confirmed_at: str = ""
    confirmed_by: str = ""

    def __post_init__(self):
        object.__setattr__(self, "server", normalize_server(self.server))

    def to_dict(self) -> dict:
        return {"format": LINK_FORMAT, "format_version": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, record: dict) -> DatabaseLink:
        if not isinstance(record, dict) or record.get("format") != LINK_FORMAT or type(record.get("format_version")) is not int or record.get("format_version") != 1:
            raise ValueError("Unknown database link format or format_version; use an up-to-date app.")
        data = {k: v for k, v in record.items() if k not in {"format", "format_version"}}
        data["server"] = normalize_server(data["server"])
        data["sources"] = [Source(**s) for s in data.get("sources", [])]
        data["chemistry"] = ChemistrySummary(**data.get("chemistry", {}))
        return cls(**data)


@dataclass
class Candidate:
    fraction: dict
    sample: dict
    batch: dict
    read_at: str
    chemistry_message: str = ""

    @property
    def sample_label(self) -> str:
        """Distinguish same-named samples by project code and UUID tail."""
        project = self.sample.get("project") or self.sample.get("project_code") or ""
        code = (project.get("code") or project.get("name") or "") if isinstance(project, dict) else str(project)
        name = self.sample["name"] + (f" / {code}" if code else "")
        return f"{name} [{self.sample['id'][-8:]}]"

    @property
    def chemistry(self) -> ChemistrySummary:
        return chemistry_summary(self.batch, self.fraction["id"])

    def confirm(self, server: str, username: str) -> DatabaseLink:
        if not username:
            raise DatabaseError("Sign in to identify who confirmed this link.")
        f = self.fraction
        sources = [Source(grain_uid=s.get("grain_id") or "", spot_uid=s.get("spot_id") or "",
                          mount_name=s.get("mount_name") or s.get("mount_label") or "",
                          grain_label=s.get("grain_label") or "", spot_label=s.get("spot_label") or "",
                          is_fragment=bool(s.get("is_fragment")), fragment_note=s.get("fragment_note") or "")
                   for s in f.get("sources", []) if not s.get("retired_at")]
        # Semicolons are the contract's source-list delimiter and cannot be escaped.
        if any(";" in v for s in sources for v in (s.mount_name, s.grain_label, s.spot_label, s.fragment_note)):
            raise DatabaseError("A database source contains ';', which the fractions contract cannot represent.")
        return DatabaseLink(normalize_server(server), f["id"], self.sample["id"], self.sample["name"], f["name"],
                            f.get("capsule_label") or "", f.get("capsule_set_name") or "", f.get("batch_id") or "",
                            self.batch.get("started_on") or "", sources, self.chemistry,
                            self.read_at, now_iso(), username)


REFUSALS = {
    "not_parsed": "SampleID could not be parsed. Enter the sample and fraction name.",
    "no_sample": "No visible sample has that exact name or alias.",
    "no_fraction": "No active fraction with that name belongs to the matching samples.",
    "not_cached": "This sample has not been fetched and is unavailable offline.",
}


@dataclass
class MatchResult:
    candidates: list[Candidate] = field(default_factory=list)
    reason: str = ""
    offline: bool = False
    fetched_at: str = ""

    @property
    def message(self) -> str:
        text = REFUSALS.get(self.reason, f"{len(self.candidates)} candidate(s); select one to confirm.")
        if self.offline:
            text += " Offline · from cache, fetched " + (cache_age(self.fetched_at) if self.fetched_at else "never")
        return text


def sample_matches(sample: dict, query: str) -> bool:
    aliases = sample.get("aliases") or []
    names = [sample.get("name", ""), *(a.get("name", a.get("alias", "")) if isinstance(a, dict) else a for a in aliases)]
    return any(str(n).casefold() == query.strip().casefold() for n in names)


def match_fractions(samples: list[dict], fractions: list[dict], sample: str, name: str) -> MatchResult:
    exact = {s["id"]: s for s in samples if sample_matches(s, sample)}
    if not exact:
        return MatchResult(reason="no_sample")
    candidates = []
    for f in fractions:
        uid = (f.get("sample") or {}).get("id") or f.get("sample_id")
        if uid in exact and f.get("name", "").casefold() == name.strip().casefold() and not f.get("retired_at"):
            candidates.append(Candidate(f, exact[uid], {}, ""))
    return MatchResult(candidates, "" if candidates else "no_fraction")


@dataclass
class Response:
    status: int
    headers: dict
    payload: Any = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward bearer credentials to a redirected host.


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> Response:
    try:
        response = build_opener(_NoRedirect()).open(Request(url, data=body, headers=headers, method=method), timeout=15)
    except HTTPError as error:
        response = error
    except (URLError, OSError, TimeoutError):
        raise ConnectionFailed("Cannot reach the database. Check the address and your internet connection.") from None
    try:
        with response:
            raw = response.read()
            payload = json.loads(raw) if raw and response.code != 304 else None
            return Response(response.code, dict(response.headers), payload)
    except (ValueError, UnicodeError):
        raise DatabaseError("The database sent an unexpected answer.") from None
    except (OSError, TimeoutError):
        raise ConnectionFailed("The database connection was interrupted.") from None


class Client:
    def __init__(self, server: str, *, cache_dir: Path | None = None, transport=None, token_store=None, cancelled=None):
        self.server = normalize_server(server)
        self.transport = transport or urllib_transport
        self.tokens = token_store or TOKENS
        self.cancelled = cancelled or (lambda: False)
        folder = Path(cache_dir) if cache_dir is not None else app_data_dir() / "database"
        self.cache_path = folder / (hashlib.sha256(self.server.encode()).hexdigest() + ".json")
        self.cache = {"format": CACHE_FORMAT, "format_version": 1, "server": self.server, "lookups": {}, "batches": {}}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if data.get("format") == CACHE_FORMAT and data.get("format_version") == 1 and data.get("server") == self.server:
                self.cache = data
        except (OSError, ValueError, AttributeError):
            pass
        self.account = self.cache.get("account", {})
        self.status = "not connected"
        self.offline_only = False

    def _request(self, method, path, *, payload=None, headers=None, auth=True):
        if self.cancelled():
            raise Cancelled("Database lookup cancelled.")
        request_headers = {"User-Agent": f"{APP_NAME}/{VERSION}", "Accept": "application/json", **(headers or {})}
        if auth:
            token = self.tokens.get(self.server)
            if not token:
                raise DatabaseError(f"Sign in to {self.server} first.", status=401)
            request_headers["Authorization"] = f"Bearer {token}"
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        try:
            response = self.transport(method, f"{self.server}/v1/{path}", request_headers,
                                      json.dumps(payload).encode() if payload is not None else None)
        except (OSError, URLError, TimeoutError):
            raise ConnectionFailed(f"Cannot reach {self.server}. Check your internet connection.") from None
        if self.cancelled():
            raise Cancelled("Database lookup cancelled.")
        if response.status == 401:
            self.tokens.delete(self.server)
            raise DatabaseError(f"Sign in to {self.server} again.", status=401)
        if response.status >= 400 or 300 <= response.status < 304 or response.status > 304:
            messages = {403: "Your account does not have access to this database record.",
                        404: "Database record not found or not shared with you."}
            raise DatabaseError(messages.get(response.status, f"The database could not complete the request (HTTP {response.status})."), status=response.status)
        return response

    def login(self, username: str, password: str) -> None:
        data = self._request("POST", "auth/login", payload={"username": username, "password": password}, auth=False).payload
        if not isinstance(data, dict) or not data.get("token"):
            raise DatabaseError("The database returned no sign-in token.")
        self.tokens.set(self.server, data["token"])
        self._set_account(data.get("account") or self._request("GET", "accounts/me").payload)

    def use_token(self, token: str | None = None) -> None:
        if token:
            self.tokens.set(self.server, token.strip())
        self._set_account(self._request("GET", "accounts/me").payload)

    def _set_account(self, account):
        if not isinstance(account, dict) or not account.get("username"):
            raise DatabaseError("The database returned no account username.")
        if self.account and self.account.get("username") != account["username"]:
            self.cache["lookups"], self.cache["batches"] = {}, {}
        self.account = {"username": account["username"]}
        self.cache["account"] = self.account
        self.status = f"signed in as {account['username']}"
        self._save()

    def logout(self) -> None:
        # A cancelled lookup must not prevent an explicit sign-out from revoking
        # the token. Callers serialize operations on a client (as the GUI does).
        cancelled = self.cancelled
        self.cancelled = lambda: False
        try:
            self._request("POST", "auth/logout")
        except DatabaseError:
            pass
        finally:
            self.cancelled = cancelled
            self.tokens.delete(self.server)
            self.account = {}
            self.cache.update(account={}, lookups={}, batches={})
            self._save()
            self.status = "not connected"

    def _save(self):
        lookups = self.cache["lookups"]
        keep = sorted(lookups, key=lambda q: lookups[q]["fetched_at"])[-MAX_LOOKUPS:]
        self.cache["lookups"] = {q: lookups[q] for q in keep}
        referenced = {f.get("batch_id") for entry in self.cache["lookups"].values() for f in entry["fractions"]}
        self.cache["batches"] = {k: v for k, v in self.cache["batches"].items() if k in referenced}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        handle, path = tempfile.mkstemp(dir=self.cache_path.parent, prefix=".database-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(self.cache, stream, ensure_ascii=False, allow_nan=False)
            os.replace(path, self.cache_path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def _get(self, path, previous):
        headers = {"If-None-Match": previous["etag"]} if previous and previous.get("etag") else {}
        response = self._request("GET", path, headers=headers)
        if response.status == 304:
            if not previous:
                raise DatabaseError("The database returned 304 without a cached copy.")
            return {**previous, "fetched_at": now_iso()}
        lower = {k.lower(): v for k, v in response.headers.items()}
        return {"payload": response.payload, "etag": lower.get("etag"), "next": lower.get("x-next-cursor"), "fetched_at": now_iso()}

    def _list(self, endpoint, params, previous, pages):
        items, cursor, seen = [], None, set()
        while True:
            path = endpoint + "?" + urlencode({**params, **({"after": cursor} if cursor else {})})
            page = self._get(path, previous.get(path))
            if not isinstance(page["payload"], list):
                raise DatabaseError("The database returned an unexpected list.")
            pages[path] = page
            items.extend(page["payload"])
            cursor = page.get("next")
            if not cursor:
                return items
            if cursor in seen:
                raise DatabaseError("The database repeated a pagination cursor.")
            seen.add(cursor)

    def lookup(self, fraction_id: str = "", *, sample: str | None = None, name: str | None = None) -> MatchResult:
        if sample is None or name is None:
            parsed = parse_fraction_id(fraction_id)
            if parsed is None:
                return MatchResult(reason="not_parsed")
            sample, name = parsed
        if not sample.strip() or not name.strip():
            return MatchResult(reason="not_parsed")
        key = sample.strip().casefold()
        previous = self.cache["lookups"].get(key)
        offline = False
        try:
            if self.offline_only:
                raise ConnectionFailed("Offline cache requested")
            pages = {}
            samples = self._list("samples", {"q": sample.strip()}, previous.get("pages", {}) if previous else {}, pages)
            samples = [s for s in samples if sample_matches(s, sample)]
            for path, page in pages.items():
                if path.startswith("samples?"):
                    page["payload"] = [s for s in page["payload"] if sample_matches(s, sample)]
            fractions = []
            for s in samples:
                fractions += self._list("fractions", {"sample": s["id"], "limit": 500},
                                        previous.get("pages", {}) if previous else {}, pages)
            entry = {"samples": samples, "fractions": fractions, "fetched_at": now_iso(), "pages": pages}
            self.cache["lookups"][key] = entry
            self._save()
        except ConnectionFailed:
            offline = True
            entry = previous
            if entry is None:
                # A previously fetched sample may now be requested by an alias.
                matching = [e for e in self.cache["lookups"].values()
                            if any(sample_matches(s, sample) for s in e["samples"])]
                if not matching:
                    self.status = "offline · sample not cached"
                    return MatchResult(reason="not_cached", offline=True)
                entry = {
                    "samples": list({s["id"]: s for e in matching for s in e["samples"]}.values()),
                    "fractions": list({f["id"]: f for e in matching for f in e["fractions"]}.values()),
                    "fetched_at": min(e["fetched_at"] for e in matching),
                }
        fetched_batches = {}
        result = match_fractions(entry["samples"], entry["fractions"], sample, name)
        result.offline, result.fetched_at = offline, entry["fetched_at"]
        for candidate in result.candidates:
            candidate.read_at = entry["fetched_at"]
            batch_id = candidate.fraction.get("batch_id")
            if not batch_id:
                continue
            cached = self.cache["batches"].get(batch_id)
            try:
                if offline:
                    raise ConnectionFailed("Offline")
                batch = fetched_batches.get(batch_id) or self._get("tims/batches/" + quote(batch_id, safe=""), cached)
                fetched_batches[batch_id] = batch
                self.cache["batches"][batch_id] = batch
            except ConnectionFailed:
                offline = True
                result.offline = True
                batch = cached
                if not batch:
                    candidate.chemistry_message = "Offline: chemistry has not been cached. Linking is still allowed."
            except DatabaseError as error:
                if error.status not in (403, 404):
                    raise
                batch = None
                self.cache["batches"].pop(batch_id, None)
                candidate.chemistry_message = f"No chemistry access (HTTP {error.status}). Linking is still allowed; chemistry columns stay empty."
            if batch:
                candidate.batch = batch["payload"]
                candidate.read_at = min(candidate.read_at, batch["fetched_at"])
        if result.candidates:
            result.fetched_at = min(c.read_at for c in result.candidates)
        self._save()
        self.status = ("offline · from cache, fetched " + cache_age(result.fetched_at)) if result.offline else (
            f"signed in as {self.account.get('username', '?')}")
        return result
