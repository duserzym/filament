"""Build the desktop app with PyInstaller and smoke-test the frozen executable.

Adapted from UPbRPy commit f8c561f, scripts/build_desktop.py, on 2026-11-14.
Changes: names come from rawtims.branding and the spec is
packaging/rawtims.spec; the smoke test runs ``--version``, ``--export png`` of
the empty window, the B998 fixture and a synthetic raw walkthrough (each over
10 KB), validates bundled guide/icon/XLSX resources, and ``--verify`` on the KU GHR1 IsoLinx Pb and U fixtures, whose
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
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

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


def project_version() -> str:
    return str(tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])


def sign_application(application: Path) -> None:
    """Use the lab identity when configured; retain ad hoc signing otherwise."""
    identity = os.environ.get("APPLE_SIGNING_IDENTITY", "").strip()
    if sys.platform != "darwin" or not identity or identity == "-":
        return
    subprocess.run(["codesign", "--force", "--deep", "--timestamp=none", "--sign", identity, str(application)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(application)], check=True)
    print(f"Signed with: {identity}")


def verify_application_version(application: Path, work_directory: Path) -> None:
    """Mandatory after signing, even when optional smoke tests are disabled."""
    work_directory.mkdir(parents=True, exist_ok=True)
    output = work_directory / "frozen-version.txt"
    output.unlink(missing_ok=True)
    run_frozen(application, ["--version-output", str(output)], work_directory)
    reported = output.read_text(encoding="utf-8").strip() if output.exists() else ""
    expected = project_version()
    if reported != expected:
        raise RuntimeError(f"Frozen app version mismatch: expected {expected} from pyproject.toml, reported {reported!r} ({application})")
    print(f"Frozen --version-output: {reported}")


def archive_application(application: Path, dist_directory: Path, *, sign_with: Path | None = None) -> Path:
    """Keep the ZIP and add a symlink-preserving update archive, feed and checksums."""
    archive = dist_directory / f"{branding.EXECUTABLE_NAME}-{project_version()}-{sys.platform}-{platform.machine()}.zip"
    archive.unlink(missing_ok=True)
    Path(str(archive) + ".sig").unlink(missing_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(application), str(archive)], check=True)
    else:
        root = application.parent if application.is_file() else application
        shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=root.parent, base_dir=root.name)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    assets = [archive]
    signed_archive = archive
    target = "windows-x86_64" if sys.platform == "win32" else None
    if sys.platform == "darwin":
        tarball = dist_directory / f"{branding.DISPLAY_NAME}-{project_version()}-macOS-{platform.machine()}.app.tar.gz"
        Path(str(tarball) + ".sig").unlink(missing_ok=True)
        with tarfile.open(tarball, "w:gz", dereference=False) as bundle:
            bundle.add(application, arcname=application.name)
        assets.append(tarball)
        signed_archive = tarball
        target = "darwin-aarch64" if platform.machine() == "arm64" else None
    key = sign_with or os.environ.get(f"{branding.APP_NAME.upper()}_UPDATER_KEY")
    if key:
        if target is None:
            raise ValueError("Signed feeds support macOS arm64 and Windows x86_64")
        from rawtims_gui.labupdate.release import build_feed
        from rawtims_gui.update_config import PUBLIC_KEY, REPO
        public_key = dist_directory / "updater.pub"
        public_key.write_text(PUBLIC_KEY, encoding="utf-8")
        try:
            feed = dist_directory / "latest.json"
            build_feed(repo=REPO, version=project_version(),
                       notes_file=PROJECT_ROOT / "release-notes" / f"{project_version()}.md",
                       archives={target: signed_archive}, pubkey_file=public_key,
                       out=feed, sign_with=Path(key).expanduser())
        finally:
            public_key.unlink(missing_ok=True)
        assets.extend([Path(str(signed_archive) + ".sig"), feed])
    checksums = []
    for asset in assets:
        with asset.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        checksums.append(f"{digest}  {asset.name}\n")
    (dist_directory / "SHA256SUMS.txt").write_text("".join(checksums), encoding="utf-8")
    return archive


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
    missing = [name for name in ("PyInstaller", "PySide6", "pyqtgraph", "keyring", "truststore", "certifi") if importlib.util.find_spec(name) is None]
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


def run_frozen(application: Path, arguments: list[str], work_directory: Path, *,
               environment_overrides: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run the frozen app offscreen; fail on a non-zero exit or a traceback."""
    environment = clean_environment()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment.update(environment_overrides or {})
    command = [str(application_executable(application)), *arguments]
    sandbox = shutil.which("sandbox-exec") if sys.platform == "darwin" and "--update-self-test" in arguments else None
    if sandbox:
        profile = work_directory / "no-homebrew-ca.sb"
        profile.write_text(
            '(version 1)\n(allow default)\n'
            '(deny file-read* (subpath "/opt/homebrew/etc/openssl@3") '
            '(subpath "/usr/local/etc/openssl@3"))\n', encoding="utf-8",
        )
        command = [sandbox, "-f", str(profile), *command]
    result = subprocess.run(
        command,
        cwd=work_directory,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    if check and (result.returncode != 0 or "Traceback" in output):
        raise RuntimeError(f"The frozen app failed on {' '.join(arguments)} (exit {result.returncode}):\n{output[-4000:]}")
    return result


def run_source(arguments: list[str], work_directory: Path) -> subprocess.CompletedProcess:
    """Run the same command from the source environment (this interpreter), for comparison with the frozen app."""
    environment = clean_environment()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run([sys.executable, "-m", "rawtims_gui.main", *arguments], cwd=work_directory, env=environment,
                            capture_output=True, check=False, text=True, timeout=300)
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
    expected_label = f"{branding.APP_NAME} {project_version()}"
    if version != expected_label:
        raise RuntimeError(f"The frozen app reports {version!r}, expected {expected_label!r}")
    lines.append(f"Frozen --version: {version}")
    screenshot = work_directory / "smoke-empty.png"
    screenshot.unlink(missing_ok=True)
    run_frozen(application, ["--smoke-checks", "--theme", "light", "--export", "png", str(screenshot)], work_directory)
    size = screenshot.stat().st_size if screenshot.exists() else 0
    if size <= MINIMUM_PNG_BYTES:
        raise RuntimeError(f"The frozen app did not produce a valid empty-window screenshot ({size} bytes): {screenshot}")
    lines.append(f"Frozen --export png: {screenshot} ({size} bytes)")
    loaded = work_directory / "smoke-b998.png"
    loaded.unlink(missing_ok=True)
    run_frozen(application, ["--smoke-checks", "--theme", "light", "--open", str(SMOKE_RUN), "--export", "png", str(loaded)], work_directory)
    size = loaded.stat().st_size if loaded.exists() else 0
    if size <= MINIMUM_PNG_BYTES:
        raise RuntimeError(f"The frozen app did not produce a valid screenshot of {SMOKE_RUN.name} ({size} bytes): {loaded}")
    lines.append(f"Frozen --open {SMOKE_RUN.name} --export png: {loaded} ({size} bytes)")
    # Reuse the reprocessing tests' invented .raw acquisition, never Drive data.
    try:
        from make_raw_fixture import synthetic_raw, write_synthetic_workbook
    except ImportError:
        from scripts.make_raw_fixture import synthetic_raw, write_synthetic_workbook
    fixture_root = work_directory / "synthetic-walkthrough"
    shutil.rmtree(fixture_root, ignore_errors=True)
    fixture_root.mkdir()
    folder, params = synthetic_raw(fixture_root, cycles=5)
    write_synthetic_workbook(folder, params)
    walkthrough = work_directory / "smoke-walkthrough.png"
    walkthrough.unlink(missing_ok=True)
    run_frozen(application, ["--smoke-checks", "--theme", "light", "--walkthrough-fixture", str(folder),
                            "--walkthrough-step", "3", "--export", "png", str(walkthrough)], work_directory)
    if not walkthrough.exists() or walkthrough.stat().st_size <= MINIMUM_PNG_BYTES:
        raise RuntimeError("Frozen synthetic walkthrough did not render")
    from zipfile import ZipFile
    for png in (screenshot, loaded, walkthrough):
        with ZipFile(png.with_suffix(".xlsx")) as book:
            if "xl/workbook.xml" not in book.namelist():
                raise RuntimeError(f"Frozen XLSX dependency check failed: {png}")
    lines.append(f"Frozen synthetic .raw walkthrough Apply + PNG + XLSX dependency checks: {walkthrough}")
    frozen_csv, source_csv = work_directory / "smoke-verify-frozen.csv", work_directory / "smoke-verify-source.csv"
    for path in (frozen_csv, source_csv):
        path.unlink(missing_ok=True)
    inputs = [str(path) for path in SMOKE_VERIFY]
    run_frozen(application, ["--verify", *inputs, "--verification-output", str(frozen_csv)], work_directory)
    run_source(["--verify", *inputs, "--verification-output", str(source_csv)], work_directory)
    rows = compare_contract_files(frozen_csv, source_csv)
    lines.append(f"Frozen --verify: {rows} rows identical to the source app's (Exported At aside): {frozen_csv}")
    verify_update_self_test(application, work_directory)
    lines.append("Frozen signed update manifest, archive, tamper rejection and TLS checks passed")
    return lines


def verify_update_self_test(application: Path, work_directory: Path) -> None:
    """Verify a local signed feed and mandatory tamper rejection in the frozen app."""
    from rawtims_gui.labupdate.config import platform_key
    from rawtims_gui.labupdate.selftest import SELF_TEST_DATA

    # The disposable private test key stays in the source-side test helper.
    # It is never bundled or used by the production updater.
    helper = importlib.util.spec_from_file_location("labupdate_smoke_signing", PROJECT_ROOT / "tests/labupdate_signing.py")
    signing = importlib.util.module_from_spec(helper)
    helper.loader.exec_module(signing)
    archive = work_directory / "update-self-test.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("Self Test.app/Contents/MacOS/Self Test", SELF_TEST_DATA)
    signature = signing.sign(archive.read_bytes())
    manifest = work_directory / "update-self-test.json"
    manifest.write_text(json.dumps({"version": project_version(), "notes": "Frozen update check",
        "platforms": {platform_key(): {"url": archive.as_uri(), "signature": signature}}}), encoding="utf-8")
    output = work_directory / "update-self-test-result.json"
    output.unlink(missing_ok=True)
    result = run_frozen(application,
        ["--update-self-test", manifest.as_uri(), "--update-self-test-output", str(output)],
        work_directory, environment_overrides={
            "SSL_CERT_FILE": str(work_directory / "nonexistent-cert.pem"),
            "SSL_CERT_DIR": str(work_directory / "nonexistent-certs"),
        }, check=False)
    try:
        report = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Frozen update self-test did not return JSON: {result.stderr[-4000:]}") from exc
    required = (report.get("ok") is True, report.get("verification_ran") is True,
                report.get("signature", {}).get("tampered_rejected") is True,
                report.get("signature", {}).get("status") == "ok",
                report.get("public_key", {}).get("status") == "ok",
                report.get("manifest", {}).get("status") == "ok",
                report.get("manifest", {}).get("archive_verified") is True,
                report.get("https", {}).get("status") in {"ok", "network"},
                bool(report.get("tls", {}).get("source")),
                report.get("tls", {}).get("status") != "error")
    if result.returncode != 0 or "Traceback" in result.stderr or not all(required):
        raise RuntimeError(f"Frozen update self-test failed: {report}")
    if report["https"]["status"] == "network":
        print(f"Warning: frozen update HTTPS check unavailable: {report['https'].get('message', '')}")


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Build the {branding.DISPLAY_NAME} desktop application.")
    parser.add_argument("--dist-dir", type=Path, default=BUILD_ROOT / "dist", help="Output folder for the application.")
    parser.add_argument("--work-dir", type=Path, default=BUILD_ROOT / "work", help="Disposable PyInstaller work folder.")
    parser.add_argument("--clean", action=argparse.BooleanOptionalAction, default=True, help="Clear PyInstaller caches first (default: on).")
    parser.add_argument("--smoke-test", action=argparse.BooleanOptionalAction, default=True, help="Run the frozen app offscreen (default: on).")
    parser.add_argument("--archive", action="store_true", help="Create ZIP, update archive and SHA256 checksums after validation")
    parser.add_argument("--sign-with", type=Path, help="Updater key file (or <APPNAME>_UPDATER_KEY); requires --archive")
    parser.add_argument("--print-build-root", action="store_true", help="Print the build root and exit (used by make clean-build).")
    args = parser.parse_args(argv)
    if args.sign_with and not args.archive:
        parser.error("--sign-with requires --archive")
    return args


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
    sign_application(application)
    verify_application_version(application, work_directory)
    print(f"Application: {application}")
    if arguments.smoke_test:
        for line in smoke_test_application(application, work_directory / "smoke"):
            print(line)
        print("Smoke test passed.")
    if arguments.archive:
        options = {"sign_with": arguments.sign_with} if arguments.sign_with else {}
        print(f"Archive: {archive_application(application, dist_directory, **options)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
