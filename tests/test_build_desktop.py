"""Build-checkout version metadata and mandatory frozen version validation."""

import runpy
import shutil
import sys
from importlib import metadata, util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from rawtims import _version, branding
from scripts import build_desktop

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("stale_format", ["egg-info", "dist-info"])
@pytest.mark.parametrize("target_platform", ["darwin", "win32"])
def test_spec_stamps_checkout_version_despite_stale_metadata(tmp_path, monkeypatch, stale_format, target_platform):
    stale = tmp_path / "stale"
    info = stale / f"rawtims.{stale_format}"
    info.mkdir(parents=True)
    (info / ("PKG-INFO" if stale_format == "egg-info" else "METADATA")).write_text(
        "Metadata-Version: 2.1\nName: rawtims\nVersion: 0.0.1\n\n"
    )
    monkeypatch.syspath_prepend(str(stale))
    assert metadata.version("rawtims") == "0.0.1"

    # Execute the real spec with PyInstaller stubbed: no dependency or build.
    # SPECPATH selects the checkout, not installed code.
    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_submodules = lambda name: []

    def copy_metadata(name):
        assert name != "rawtims", "Must not look up the venv's rawtims metadata"
        return []

    hooks.copy_metadata = copy_metadata
    for name in ("PyInstaller", "PyInstaller.utils"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setitem(sys.modules, hooks.__name__, hooks)
    # Recipe evaluation is independent of installed build dependencies.
    certifi = ModuleType("certifi")
    certifi.where = lambda: str(tmp_path / "cacert.pem")
    monkeypatch.setitem(sys.modules, "certifi", certifi)
    captured = SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[
        # Analysis can automatically copy metadata for version() calls.
        ("rawtims.egg-info/PKG-INFO", "stale-egg-info", "DATA"),
        ("rawtims-0.0.1.dist-info/METADATA", "stale-dist-info", "DATA"),
        ("other.dist-info/METADATA", "other-metadata", "DATA"),
    ])

    def analysis(*args, **kwargs):
        assert (certifi.where(), "certifi") in kwargs["datas"]
        assert {"truststore", "certifi"} <= set(kwargs["hiddenimports"])
        assert (str(ROOT / "release-notes/*.md"), "rawtims_gui/release-notes") in kwargs["datas"]
        assert any("*.png" in source and target == "rawtims_gui/assets"
                   for source, target in kwargs["datas"])
        return captured

    icon_calls = {}

    def capture_icon(kind):
        def capture(*args, **kwargs):
            icon_calls[kind] = Path(kwargs["icon"])
        return capture

    with monkeypatch.context() as spec_patches:
        spec_patches.setattr(util, "find_spec", lambda name: None)
        spec_patches.setattr(sys, "path", list(sys.path))
        spec_patches.setattr(sys, "platform", target_platform)
        runpy.run_path(str(ROOT / "packaging/rawtims.spec"), init_globals={
            "SPECPATH": str(ROOT / "packaging"), "workpath": str(tmp_path / "work"),
            "Analysis": analysis,
            **dict.fromkeys(("PYZ", "EXE", "COLLECT", "BUNDLE"), lambda *a, **kw: None),
            "EXE": capture_icon("EXE"), "BUNDLE": capture_icon("BUNDLE"),
        })

    expected_icon = branding.ICO_FILENAME if target_platform == "win32" else branding.ICON_FILENAME
    assert icon_calls["EXE"] == ROOT / "packaging" / expected_icon
    assert icon_calls["EXE"].is_file()
    if target_platform == "darwin":
        assert icon_calls["BUNDLE"] == ROOT / "packaging" / branding.ICON_FILENAME
    else:
        assert "BUNDLE" not in icon_calls

    assert ("other.dist-info/METADATA", "other-metadata", "DATA") in captured.datas
    assert len(captured.datas) == 2
    destination_file, source, kind = captured.datas[-1]
    assert (destination_file, kind) == ("rawtims.egg-info/PKG-INFO", "DATA")
    destination = str(Path(destination_file).parent)
    bundle = tmp_path / "bundle"
    (bundle / destination).mkdir(parents=True)
    shutil.copy2(source, bundle / destination / "PKG-INFO")
    expected = build_desktop.project_version()
    assert metadata.PathDistribution(bundle / destination).version == expected

    monkeypatch.setattr(_version, "__file__", str(bundle / "rawtims/_version.py"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _version.package_version() == expected
    # The stamp wins even though normal metadata lookup still finds 0.0.1.
    assert metadata.version("rawtims") == "0.0.1"
    monkeypatch.setattr(sys, "path", [str(bundle)])
    assert metadata.version("rawtims") == expected


def test_frozen_missing_stamp_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.setattr(_version, "__file__", str(tmp_path / "rawtims/_version.py"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(metadata, "version", lambda name: "0.0.1")
    with pytest.raises(RuntimeError, match="Missing frozen rawtims version"):
        _version.package_version()


def test_version_output_uses_updater_version_without_starting_gui(tmp_path, monkeypatch):
    from rawtims_gui import main

    monkeypatch.setattr(main.branding, "VERSION", "1.2.3")

    def unexpected(*args, **kwargs):
        pytest.fail("Version output must exit before starting the GUI")

    monkeypatch.setattr(main, "build_application", unexpected)
    monkeypatch.setattr(main, "MainWindow", unexpected)
    output = tmp_path / "version.txt"
    assert main.main(["--theme", "light", "--version-output", str(output)]) == 0
    assert output.read_text() == "1.2.3\n"


@pytest.mark.parametrize("reported", ["current", "0.0.1", "", None])
def test_verify_application_version(tmp_path, monkeypatch, reported):
    application = tmp_path / "fake.app"
    output = tmp_path / "frozen-version.txt"
    expected = build_desktop.project_version()
    output.write_text(expected)  # A previous successful run must not mask failure.

    def run_frozen(app, arguments, work_directory):
        assert (app, arguments, work_directory) == (
            application, ["--version-output", str(output)], tmp_path,
        )
        assert not output.exists()
        if reported is not None:
            output.write_text((expected if reported == "current" else reported) + "\n")

    monkeypatch.setattr(build_desktop, "run_frozen", run_frozen)
    if reported == "current":
        build_desktop.verify_application_version(application, tmp_path)
    else:
        with pytest.raises(RuntimeError, match="Frozen app version mismatch"):
            build_desktop.verify_application_version(application, tmp_path)


@pytest.mark.parametrize("reported", ["current", "0.0.1"])
def test_build_checks_version_even_without_smoke_test(tmp_path, monkeypatch, reported):
    monkeypatch.setattr(build_desktop, "require_build_dependencies", lambda: None)
    monkeypatch.setattr(build_desktop, "run_pyinstaller", lambda *a, **kw: tmp_path / "fake.app")
    monkeypatch.setattr(build_desktop, "sign_application", lambda app: None)
    archived = []
    monkeypatch.setattr(build_desktop, "archive_application", lambda *args: archived.append(args))

    def run_frozen(app, arguments, work_directory):
        Path(arguments[1]).write_text(
            build_desktop.project_version() if reported == "current" else reported
        )

    monkeypatch.setattr(build_desktop, "run_frozen", run_frozen)
    arguments = ["--dist-dir", str(tmp_path / "dist"), "--work-dir", str(tmp_path / "work"),
                 "--no-smoke-test", "--archive"]
    if reported == "current":
        assert build_desktop.main(arguments) == 0
        assert len(archived) == 1
    else:
        with pytest.raises(RuntimeError, match="Frozen app version mismatch"):
            build_desktop.main(arguments)
        assert not archived


@pytest.mark.parametrize('identity', ['', '-', 'UPb Lab Code Signing'])
def test_signing_commands_and_order(monkeypatch, tmp_path, identity):
    monkeypatch.setattr(build_desktop.sys, 'platform', 'darwin')
    monkeypatch.setenv('APPLE_SIGNING_IDENTITY', identity)
    calls = []
    monkeypatch.setattr(build_desktop.subprocess, 'run', lambda command, **kw: calls.append((command, kw)))
    app = tmp_path / 'test.app'
    build_desktop.sign_application(app)
    expected = [] if identity in ('', '-') else [
        (['codesign', '--force', '--deep', '--timestamp=none', '--sign', identity, str(app)], {'check': True}),
        (['codesign', '--verify', '--deep', '--strict', str(app)], {'check': True}),
    ]
    assert calls == expected


def test_signing_failure_stops_build_before_version_and_archive(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setattr(build_desktop, 'require_build_dependencies', lambda: None)
    monkeypatch.setattr(build_desktop, 'run_pyinstaller', lambda *a, **kw: tmp_path / 'test.app')
    def reject(app):
        raise subprocess.CalledProcessError(1, 'codesign')
    monkeypatch.setattr(build_desktop, 'sign_application', reject)
    monkeypatch.setattr(build_desktop, 'run_frozen', lambda *a: pytest.fail('Unverified signature reached launch'))
    monkeypatch.setattr(build_desktop, 'archive_application', lambda *a: pytest.fail('Unverified signature reached archive'))
    with pytest.raises(subprocess.CalledProcessError):
        build_desktop.main(['--dist-dir', str(tmp_path / 'dist'), '--work-dir', str(tmp_path / 'work'), '--archive'])


def test_archive_has_matching_sha256(monkeypatch, tmp_path):
    import hashlib
    from zipfile import ZipFile
    monkeypatch.setattr(build_desktop.sys, 'platform', 'linux')
    app = tmp_path / 'app'
    app.mkdir()
    (app / 'payload').write_text('test')
    archive = build_desktop.archive_application(app, tmp_path)
    assert archive.with_suffix('.zip.sha256').read_text() == f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n'
    with ZipFile(archive) as zipped:
        assert zipped.read('app/payload') == b'test'
