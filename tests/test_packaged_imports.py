"""The GUI imports engine names from their defining submodule, never through the package.

``from rawtims import <name>`` for a name that is not a submodule would need a
lazy package ``__getattr__``, which PyInstaller cannot follow (Studio bug 1,
2026-11-11). The GUI also never imports UPbRPy's ``GUI`` package: the Studio
design pieces are vendored under rawtims_gui/studio/.
"""

from __future__ import annotations

import ast
from pathlib import Path
import pkgutil

import rawtims

ROOT = Path(__file__).resolve().parents[1]
GUI_SOURCES = sorted((ROOT / "src" / "rawtims_gui").rglob("*.py"))
SUBMODULES = {info.name for info in pkgutil.iter_modules(rawtims.__path__)}


def test_gui_does_not_import_names_through_the_engine_package():
    assert "branding" in SUBMODULES
    offenders = []
    for path in GUI_SOURCES:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "rawtims" and node.level == 0:
                offenders += [f"{path.relative_to(ROOT)}:{node.lineno} imports {alias.name}"
                              for alias in node.names if alias.name not in SUBMODULES]
    assert not offenders, "Import from the defining rawtims submodule instead: " + "; ".join(offenders)


def test_gui_never_imports_studio_packages():
    offenders = []
    for path in [*GUI_SOURCES, *sorted((ROOT / "scripts").glob("*.py"))]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            offenders += [f"{path.relative_to(ROOT)}:{node.lineno} {m}" for m in modules if m.split(".")[0] in {"GUI", "UPbRPy"}]
    assert not offenders, offenders


def test_vendored_studio_files_record_their_source():
    for name in ("theme.py", "widgets.py"):
        header = (ROOT / "src" / "rawtims_gui" / "studio" / name).read_text(encoding="utf-8").splitlines()[0]
        assert header.startswith("# Copied from UPbRPy commit 0b16f36, path GUI/"), name
