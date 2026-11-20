"""The app name lives only in rawtims/branding.py (SPEC section 7, "Naming in one place")."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from rawtims import _version, branding

ROOT = Path(__file__).resolve().parents[1]
SEARCHED = ("src", "scripts", "packaging")
ALLOWED = {Path("src/rawtims/branding.py"), Path("src/rawtims_gui/labupdate/VENDORED")}
LITERAL = re.compile(r"filament", re.IGNORECASE)


def test_app_name_literal_appears_only_in_branding():
    offenders = []
    for folder in SEARCHED:
        for path in sorted((ROOT / folder).rglob("*")):
            generated = "__pycache__" in path.parts or any(part.endswith(".egg-info") for part in path.parts)
            if not path.is_file() or generated or path.suffix in {".pyc", ".png", ".icns", ".ico", ".svg"}:
                continue
            relative = path.relative_to(ROOT)
            if relative in ALLOWED:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            offenders += [f"{relative}:{number}" for number, line in enumerate(text.splitlines(), 1) if LITERAL.search(line)]
    assert not offenders, "Read the name from rawtims.branding instead: " + ", ".join(offenders)


def test_branding_values_follow_the_app_name():
    assert branding.APP_NAME == "filament"
    assert branding.DISPLAY_NAME and branding.EXECUTABLE_NAME
    assert branding.BUNDLE_ID.endswith("." + branding.APP_NAME)
    assert branding.URL_SCHEME == branding.APP_NAME
    assert branding.QSETTINGS_APP == branding.APP_NAME and branding.QSETTINGS_ORG
    assert branding.CACHE_DIR_NAME == branding.APP_NAME
    assert branding.RAW_APP_LABEL == f"{branding.APP_NAME} {branding.VERSION}"
    assert branding.VERSION == _version.package_version() != "0+unknown"


def test_session_format_is_neutral():
    assert branding.SESSION_FORMAT == "rawtims session"
    assert branding.SESSION_FORMAT_VERSION == 2
    assert branding.SESSION_EXTENSION == ".rawtims"
    assert branding.APP_NAME not in branding.SESSION_FORMAT + branding.SESSION_EXTENSION


def test_version_is_written_only_in_pyproject():
    import tomllib

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert branding.VERSION == version
    for path in (ROOT / "src").rglob("*.py"):
        assert f'"{version}"' not in path.read_text(encoding="utf-8"), path


def test_curated_icon_assets_match_source_hashes():
    provenance = json.loads((ROOT / "docs/icon-provenance.json").read_text())
    assert len(provenance["source_commit"]) == 40
    assert len(provenance["files"]) == 10
    for relative, record in provenance["files"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == record["sha256"]


def test_windows_icon_preserves_curated_frames():
    from PIL import Image

    icon = Image.open(ROOT / "packaging" / branding.ICO_FILENAME)
    assert icon.ico.sizes() == {(s, s) for s in (16, 32, 48, 64, 128, 256)}
    for size in (16, 32, 64, 128, 256):
        frame = icon.ico.getimage((size, size))
        source = ROOT / "src/rawtims_gui/assets" / branding.GUI_ICON_FILENAMES[size]
        with Image.open(source) as original:
            assert frame.tobytes() == original.convert("RGBA").tobytes()


def test_qicon_selects_curated_small_pngs():
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from rawtims_gui.app_icon import build_app_icon

    app = QApplication.instance() or QApplication([])
    icon = build_app_icon()
    assert {s.width() for s in icon.availableSizes()} == set(branding.ICON_SIZES)
    for size in (16, 32):
        actual = icon.pixmap(size, size).toImage()
        path = ROOT / "src/rawtims_gui/assets" / branding.GUI_ICON_FILENAMES[size]
        expected = QImage(str(path))
        fmt = QImage.Format.Format_ARGB32_Premultiplied
        assert actual.convertToFormat(fmt) == expected.convertToFormat(fmt)
    assert app is QApplication.instance()
