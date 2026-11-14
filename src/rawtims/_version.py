"""The installed package version, read from the distribution metadata.

``pyproject.toml`` is the only place the version is written. A source
checkout that was never installed falls back to reading that file, and
anything else reports ``0+unknown``.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

DISTRIBUTION = "rawtims"


def package_version() -> str:
    """Return the version of the installed ``rawtims`` distribution."""
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        pass
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        import tomllib

        return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
    except (OSError, KeyError, ValueError):
        return "0+unknown"
