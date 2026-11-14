"""Build the desktop app with PyInstaller and smoke-test the frozen executable.

Adapted from UPbRPy commit f8c561f, scripts/build_desktop.py, on 2026-11-14.
Changes: names come from rawtims.branding and the spec is
packaging/rawtims.spec; the smoke test runs ``--version`` and
``--export png`` on the empty window (fixture sessions and ``--verify`` come in
later steps); PYTHONPATH is removed from the PyInstaller and smoke-test
environments.

Run it with the interpreter of the environment to bundle (``make build``).
Output goes outside the repository, under
``<platform cache>/<branding.CACHE_DIR_NAME>/<checkout key>/{work,dist}``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

from rawtims import branding

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = PROJECT_ROOT / "packaging" / "rawtims.spec"
CACHE_BASE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    if sys.platform == "win32"
    else (Path.home() / "Library/Caches" if sys.platform == "darwin" else Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))))
)
CHECKOUT_KEY = hashlib.sha256(str(PROJECT_ROOT).encode()).hexdigest()[:12]
BUILD_ROOT = Path(os.environ.get("RAWTIMS_BUILD_ROOT", str(CACHE_BASE / branding.CACHE_DIR_NAME / CHECKOUT_KEY)))
MINIMUM_PNG_BYTES = 10_000


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return environment


def application_path(dist_directory: Path) -> Path:
    if sys.platform == "darwin":
        return dist_directory / f"{branding.DISPLAY_NAME}.app"
    if sys.platform == "win32":
        return dist_directory / branding.EXECUTABLE_NAME / f"{branding.EXECUTABLE_NAME}.exe"
    return dist_directory / branding.EXECUTABLE_NAME / branding.EXECUTABLE_NAME


def application_executable(application: Path) -> Path:
    if sys.platform == "darwin":
        return application / "Contents" / "MacOS" / branding.EXECUTABLE_NAME
    return application


def require_build_dependencies() -> None:
    missing = [name for name in ("PyInstaller", "PySide6", "pyqtgraph") if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError(
            f"Missing desktop build dependencies: {', '.join(missing)}. "
            "Install them with `python -m pip install -e \".[gui,build]\"` and rerun with the same interpreter."
        )


def run_pyinstaller(dist_directory: Path, work_directory: Path, *, clean: bool) -> Path:
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(dist_directory), "--workpath", str(work_directory)]
    if clean:
        command.append("--clean")
    command.append(str(SPEC_FILE))
    environment = clean_environment()
    # Keep PyInstaller's binary cache inside the disposable work tree.
    config = work_directory / "config"
    config.mkdir(parents=True, exist_ok=True)
    environment["PYINSTALLER_CONFIG_DIR"] = str(config)
    subprocess.run(command, cwd=PROJECT_ROOT, env=environment, check=True)
    application = application_path(dist_directory)
    if not application.exists() or not application_executable(application).exists():
        raise RuntimeError(f"PyInstaller completed without producing the expected application: {application}")
    return application


def run_frozen(application: Path, arguments: list[str], work_directory: Path) -> subprocess.CompletedProcess:
    """Run the frozen app offscreen; fail on a non-zero exit or a traceback."""
    environment = clean_environment()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [str(application_executable(application)), *arguments],
        cwd=work_directory,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    if result.returncode != 0 or "Traceback" in output:
        raise RuntimeError(f"The frozen app failed on {' '.join(arguments)} (exit {result.returncode}):\n{output[-4000:]}")
    return result


def smoke_test_application(application: Path, work_directory: Path) -> list[str]:
    """Check ``--version`` and an offscreen PNG of the empty window."""
    work_directory.mkdir(parents=True, exist_ok=True)
    lines = []
    version = run_frozen(application, ["--version"], work_directory).stdout.strip()
    if version != branding.RAW_APP_LABEL:
        raise RuntimeError(f"The frozen app reports {version!r}, expected {branding.RAW_APP_LABEL!r}")
    lines.append(f"Frozen --version: {version}")
    screenshot = work_directory / "smoke-empty.png"
    screenshot.unlink(missing_ok=True)
    run_frozen(application, ["--theme", "light", "--export", "png", str(screenshot)], work_directory)
    size = screenshot.stat().st_size if screenshot.exists() else 0
    if size <= MINIMUM_PNG_BYTES:
        raise RuntimeError(f"The frozen app did not produce a valid empty-window screenshot ({size} bytes): {screenshot}")
    lines.append(f"Frozen --export png: {screenshot} ({size} bytes)")
    return lines


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Build the {branding.DISPLAY_NAME} desktop application.")
    parser.add_argument("--dist-dir", type=Path, default=BUILD_ROOT / "dist", help="Output folder for the application.")
    parser.add_argument("--work-dir", type=Path, default=BUILD_ROOT / "work", help="Disposable PyInstaller work folder.")
    parser.add_argument("--clean", action=argparse.BooleanOptionalAction, default=True, help="Clear PyInstaller caches first (default: on).")
    parser.add_argument("--smoke-test", action=argparse.BooleanOptionalAction, default=True, help="Run the frozen app offscreen (default: on).")
    parser.add_argument("--print-build-root", action="store_true", help="Print the build root and exit (used by make clean-build).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    if arguments.print_build_root:
        print(BUILD_ROOT)
        return 0
    require_build_dependencies()
    dist_directory = arguments.dist_dir.expanduser().resolve()
    work_directory = arguments.work_dir.expanduser().resolve()
    for output in (dist_directory, work_directory):
        if output == PROJECT_ROOT or PROJECT_ROOT in output.parents:
            raise ValueError("Build outputs must be outside the source repository")
    dist_directory.mkdir(parents=True, exist_ok=True)
    work_directory.mkdir(parents=True, exist_ok=True)
    application = run_pyinstaller(dist_directory, work_directory, clean=arguments.clean)
    print(f"Application: {application}")
    if arguments.smoke_test:
        for line in smoke_test_application(application, work_directory / "smoke"):
            print(line)
        print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
