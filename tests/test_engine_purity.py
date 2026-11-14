"""The engine package stays free of Qt, HTTP and keyring imports (SPEC section 7)."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "src" / "rawtims"
FORBIDDEN = ("PySide6", "shiboken6", "pyqtgraph", "requests", "keyring")

IMPORT_ALL = r'''
import importlib, json, pkgutil, sys
import rawtims
names = ["rawtims"]
for info in pkgutil.walk_packages(rawtims.__path__, "rawtims."):
    importlib.import_module(info.name)
    names.append(info.name)
roots = sorted({name.split(".")[0] for name in sys.modules})
print(json.dumps({"imported": names, "roots": roots}))
'''


def test_importing_every_engine_module_loads_no_gui_or_network_package():
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "RAWTIMS_BLOCK_IMPORTS")}
    result = subprocess.run([sys.executable, "-c", IMPORT_ALL], capture_output=True, text=True, env=env, timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    import json

    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert "rawtims.branding" in report["imported"]
    assert len(report["imported"]) == 1 + len([p for p in ENGINE.rglob("*.py") if p.name != "__init__.py"])
    leaked = sorted(set(FORBIDDEN) & set(report["roots"]))
    assert not leaked, f"importing rawtims loaded {leaked}"


def test_engine_package_has_no_lazy_getattr():
    tree = ast.parse((ENGINE / "__init__.py").read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert "__getattr__" not in names


def test_engine_sources_do_not_import_forbidden_packages():
    offenders = []
    for path in sorted(ENGINE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            for module in modules:
                if module.split(".")[0] in (*FORBIDDEN, "rawtims_gui"):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} {module}")
    assert not offenders, offenders
