"""Bounded Tauri latest.json parsing and semantic version comparison."""

from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import platform_key
from . import tls


class NoPublicRelease(ValueError):
    """An anonymous feed request returned 404 (missing or private release)."""


class NoUpdateForPlatform(ValueError):
    """The feed has no archive for the current Tauri platform."""


@dataclass(frozen=True)
class Release:
    """A validated release and selected platform's signed archive."""

    version: str
    notes: str
    pub_date: str | None
    url: str
    signature: str


def parse_version(value: str) -> tuple:
    """Return a comparable SemVer key, allowing a leading v and build metadata."""
    match = re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?", value)
    if match is None:
        raise ValueError(f"Invalid version: {value!r}")
    major, minor, patch, prerelease, build = match.groups()
    for group in (prerelease, build):
        if group is not None and any(not s for s in group.split(".")):
            raise ValueError(f"Invalid version: {value!r}")
    identifiers = []
    for part in prerelease.split(".") if prerelease else []:
        if part.isdigit():
            if len(part) > 1 and part[0] == "0":
                raise ValueError(f"Invalid version: {value!r}")
            identifiers.append((0, int(part)))
        else:
            identifiers.append((1, part))
    return int(major), int(minor), int(patch), prerelease is None, tuple(identifiers)


def compare_versions(a: str, b: str) -> int:
    """Return -1, 0 or 1 using SemVer precedence (ignoring build metadata)."""
    left, right = parse_version(a), parse_version(b)
    return (left > right) - (left < right)


def validate_url(url: str) -> str:
    """Allow HTTPS downloads and local file smoke tests, never plain HTTP."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"https", "file"} or (parsed.scheme == "https" and not parsed.hostname):
        raise ValueError("Update URL must use https:// or file://")
    if parsed.username or parsed.password or (parsed.scheme == "file" and parsed.netloc not in ("", "localhost")):
        raise ValueError("Invalid update URL")
    return url


def parse_manifest(data, config, *, target=None) -> Release:
    """Validate the complete platform map and select this machine's archive."""
    if isinstance(data, (str, bytes)):
        if len(data.encode("utf-8") if isinstance(data, str) else data) > config.max_manifest_bytes:
            raise ValueError("Manifest exceeds size limit")
        data = json.loads(data)
    if not isinstance(data, dict) or not isinstance(data.get("version"), str):
        raise ValueError("Invalid manifest version")
    parse_version(data["version"])
    notes, date = data.get("notes", ""), data.get("pub_date")
    if not isinstance(notes, str) or (date is not None and not isinstance(date, str)):
        raise ValueError("Invalid manifest notes or pub_date")
    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        raise ValueError("Invalid manifest platforms")
    for name, entry in platforms.items():
        if not isinstance(name, str) or not isinstance(entry, dict) or not isinstance(entry.get("url"), str) or not isinstance(entry.get("signature"), str):
            raise ValueError("Invalid platform entry")
        validate_url(entry["url"])
    selected = platforms.get(target or platform_key())
    if selected is None:
        raise NoUpdateForPlatform(target or platform_key())
    return Release(data["version"], notes, date, selected["url"], selected["signature"])


def fetch_manifest(config, opener=tls.urlopen) -> Release:
    """Fetch one bounded feed; anonymous 404 means no public release."""
    request = urllib.request.Request(validate_url(config.feed_url), headers={"User-Agent": config.app_name + "-updater", "Accept": "application/json"})
    try:
        with opener(request, timeout=20) as response:
            data = response.read(config.max_manifest_bytes + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            exc.close()
            raise NoPublicRelease("HTTP 404: no public release") from exc
        with exc:
            excerpt = exc.read(240).decode("utf-8", errors="replace")
        raise ValueError(f"HTTP {exc.code}: {excerpt}") from exc
    return parse_manifest(data, config)
