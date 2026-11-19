"""The installed package version, read from the distribution metadata.

``pyproject.toml`` is the only place the version is written. A source
checkout that was never installed falls back to reading that file, and
anything else reports ``0+unknown``. Frozen builds require the checkout
metadata stamp bundled by the spec and never fall back to the host environment.
"""

from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

DISTRIBUTION = "rawtims"


def package_version() -> str:
    """Return the version of the installed ``rawtims`` distribution."""
    if getattr(sys, "frozen", False):
        stamp = Path(__file__).resolve().parents[1] / "rawtims.egg-info" / "PKG-INFO"
        if stamp.is_file():
            version = metadata.PathDistribution(stamp.parent).version
            if version:
                return version
        raise RuntimeError(f"Missing frozen rawtims version stamp: {stamp}")
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
