"""Build the desktop app with PyInstaller and smoke-test the frozen executable.

Adapted from UPbRPy commit f8c561f, scripts/build_desktop.py, on 2026-11-14.
Changes: names come from rawtims.branding and the spec is
packaging/rawtims.spec; the smoke test runs ``--version``, ``--export png`` of
the empty window and of the window with the B998 fixture run open (each over
10 KB), and ``--verify`` on the KU GHR1 IsoLinx Pb and U fixtures, whose
contract CSV must equal, cell by cell, the one the unfrozen source environment
writes (all columns but ``Exported At``); PYTHONPATH is removed from the
PyInstaller and smoke-test environments.

Run it with the interpreter of the environment to bundle (``make build``).
Output goes outside the repository, under
``<platform cache>/<branding.CACHE_DIR_NAME>/<checkout key>/{work,dist}``.
"""

from __future__ import annotations

import argparse
import csv
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
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tripoli"
SMOKE_RUN = FIXTURES / "ionvantage" / "BoiseState" / "B998_F11_13223M02_iz1_Pb1-14973.xls"
SMOKE_VERIFY = (
    FIXTURES / "timsdp" / "KU_IGL" / "IsolinxVersion2" / "GHR1 230921 F08b-216.TIMSDP",
    FIXTURES / "timsdp" / "KU_IGL" / "IsolinxVersion2" / "GHR1 230921F03 U-239.TIMSDP",
)
VOLATILE_COLUMNS = ("Exported At",)


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


def run_source(arguments: list[str], work_directory: Path) -> subprocess.CompletedProcess:
    """Run the same command from the source environment (this interpreter), for comparison with the frozen app."""
    environment = clean_environment()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run([sys.executable, "-m", "rawtims_gui.main", *arguments], cwd=work_directory, env=environment,
                            capture_output=True, text=True, timeout=300)
    output = result.stdout + result.stderr
    if result.returncode != 0 or "Traceback" in output:
        raise RuntimeError(f"The source app failed on {' '.join(arguments)} (exit {result.returncode}):\n{output[-4000:]}")
    return result


def compare_contract_files(frozen: Path, source: Path) -> int:
    """Raise unless both files have the same header and cells (``Exported At`` aside); return the row count."""
    with frozen.open(newline="", encoding="utf-8") as a, source.open(newline="", encoding="utf-8") as b:
        frozen_rows, source_rows = list(csv.reader(a)), list(csv.reader(b))
    if not frozen_rows or frozen_rows[0] != source_rows[0]:
        raise RuntimeError(f"Frozen and source --verify headers differ:\n{frozen_rows[:1]}\n{source_rows[:1]}")
    if len(frozen_rows) != len(source_rows):
        raise RuntimeError(f"Frozen --verify wrote {len(frozen_rows) - 1} rows, source {len(source_rows) - 1}")
    header = frozen_rows[0]
    for number, (left, right) in enumerate(zip(frozen_rows[1:], source_rows[1:]), start=2):
        for column, a_cell, b_cell in zip(header, left, right):
            if column not in VOLATILE_COLUMNS and a_cell != b_cell:
                raise RuntimeError(f"Line {number}, column {column!r}: frozen {a_cell!r}, source {b_cell!r}")
    return len(frozen_rows) - 1


def smoke_test_application(application: Path, work_directory: Path) -> list[str]:
    """Check ``--version``, offscreen PNGs of the empty window and of a loaded run, and ``--verify`` against the source app."""
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
    loaded = work_directory / "smoke-b998.png"
    loaded.unlink(missing_ok=True)
    run_frozen(application, ["--theme", "light", "--open", str(SMOKE_RUN), "--export", "png", str(loaded)], work_directory)
    size = loaded.stat().st_size if loaded.exists() else 0
    if size <= MINIMUM_PNG_BYTES:
        raise RuntimeError(f"The frozen app did not produce a valid screenshot of {SMOKE_RUN.name} ({size} bytes): {loaded}")
    lines.append(f"Frozen --open {SMOKE_RUN.name} --export png: {loaded} ({size} bytes)")
    frozen_csv, source_csv = work_directory / "smoke-verify-frozen.csv", work_directory / "smoke-verify-source.csv"
    for path in (frozen_csv, source_csv):
        path.unlink(missing_ok=True)
    inputs = [str(path) for path in SMOKE_VERIFY]
    run_frozen(application, ["--verify", *inputs, "--verification-output", str(frozen_csv)], work_directory)
    run_source(["--verify", *inputs, "--verification-output", str(source_csv)], work_directory)
    rows = compare_contract_files(frozen_csv, source_csv)
    lines.append(f"Frozen --verify: {rows} rows identical to the source app's (Exported At aside): {frozen_csv}")
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
