"""App integration with the unchanged, signed lab update pathway (offline)."""

import ast
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import urllib.error
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from labupdate_signing import sign
from PySide6 import QtCore, QtTest, QtWidgets

from rawtims import branding
from rawtims_gui import main, update_config
from rawtims_gui.labupdate import platform_key
from rawtims_gui.labupdate.manifest import Release
from rawtims_gui.labupdate.minisign import parse_public_key, verify_file
from rawtims_gui.labupdate.qt import CheckUpdatesButton, Updater
from rawtims_gui.labupdate.release import build_feed
from rawtims_gui.labupdate.selftest import (
    SELF_TEST_DATA,
    SELF_TEST_PUBKEY,
    run_self_test,
)
from rawtims_gui.labupdate.tls import urlopen
from rawtims_gui.studio.theme import build_application
from rawtims_gui.update_widgets import UpdatesDialog
from scripts import build_desktop

ROOT = Path(__file__).resolve().parents[1]


def offline_opener(request, *, timeout):
    if request.full_url.startswith("https:"):
        raise urllib.error.URLError("offline")
    return urlopen(request, timeout=timeout)


@pytest.fixture
def signed_manifest(tmp_path):
    archive = tmp_path / "self-test.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("Self Test.app/Contents/MacOS/Self Test", SELF_TEST_DATA)
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({"version": "9.0.0", "notes": "Lab notes",
        "platforms": {platform_key(): {"url": archive.as_uri(), "signature": sign(archive.read_bytes())}}}))
    return manifest, archive


def test_application_config_and_bundled_notes():
    config = update_config.update_config()
    assert config.repo == "duserzym/filament"
    assert config.feed_url == "https://github.com/duserzym/filament/releases/latest/download/latest.json"
    assert config.download_page == "https://github.com/duserzym/filament/releases/latest"
    assert config.app_name == branding.DISPLAY_NAME
    assert (config.settings_org, config.settings_app) == (branding.QSETTINGS_ORG, branding.QSETTINGS_APP)
    assert config.opener is urlopen
    assert parse_public_key(config.pubkey).key_id.hex() == "e106fe1d3d43ead2"
    notes = config.release_notes(branding.VERSION)
    assert notes == (ROOT / "release-notes" / f"{branding.VERSION}.md").read_text().strip()
    assert 0 < len(notes) <= 600
    assert len(notes.splitlines()) <= 5
    assert all(line.startswith("- ") for line in notes.splitlines())
    assert config.release_notes("v" + branding.VERSION) == notes
    for version in ("", "../../README", "..\\README", "99.0.0"):
        assert config.release_notes(version) is None


def test_vendored_sources_parse_and_match_sha256_manifest():
    folder = ROOT / "src/rawtims_gui/labupdate"
    provenance = (folder / "VENDORED").read_text().splitlines()
    assert provenance[0] == ("Vendored from duserzym/UPbRPy GUI/labupdate at e3970b6 on 2026-11-20. "
                             "Do not edit; change the canonical copy and recopy.")
    manifest = dict(line.split("  ", 1)[::-1] for line in provenance[3:])
    actual = {p.name for p in folder.iterdir() if p.name != "__pycache__"}
    assert manifest.keys() | {"VENDORED"} == actual
    for name, digest in manifest.items():
        path = folder / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
        if path.suffix == ".py":
            tree = ast.parse(path.read_bytes(), filename=name)
            assert isinstance(tree, ast.Module)


@pytest.mark.parametrize("tampered", [False, True])
def test_cli_self_test_with_offline_file_manifest(tmp_path, monkeypatch, signed_manifest, tampered):
    manifest, archive = signed_manifest
    if tampered:
        archive.write_bytes(archive.read_bytes() + b"tampered")
    config = replace(update_config.update_config(), opener=offline_opener)
    monkeypatch.setattr(update_config, "update_config", lambda: config)
    monkeypatch.setattr(main, "MainWindow", lambda *a, **kw: pytest.fail("Self-test built a window"))
    monkeypatch.setattr(main, "build_application", lambda *a, **kw: pytest.fail("Self-test built QApplication"))
    output = tmp_path / "report.json"
    assert main.main(["--update-self-test", manifest.as_uri(), "--update-self-test-output", str(output)]) == int(tampered)
    report = json.loads(output.read_text())
    assert report["ok"] is not tampered
    assert report["https"]["status"] == "network"
    assert report["signature"]["tampered_rejected"] is True
    assert report["public_key"]["status"] == "ok"
    assert report["manifest"]["status"] == ("error" if tampered else "ok")
    if not tampered:
        assert report["manifest"]["archive_verified"] is True


def test_cli_dispatch_precedes_qt_imports(tmp_path, signed_manifest):
    manifest, _ = signed_manifest
    output = tmp_path / "report.json"
    # Run the actual module entry point with Qt imports forbidden and HTTPS
    # deliberately offline, while file:// still uses the configured transport.
    bootstrap = '''
import builtins, runpy, sys, urllib.error
from dataclasses import replace
from rawtims_gui import update_config
config = update_config.update_config()
def offline(request, *, timeout):
    if request.full_url.startswith("https:"):
        raise urllib.error.URLError("offline")
    return config.opener(request, timeout=timeout)
update_config.update_config = lambda: replace(config, opener=offline)
original_import = builtins.__import__
def no_qt(name, *args, **kwargs):
    if name.startswith("PySide6"):
        raise AssertionError("Self-test imported Qt")
    return original_import(name, *args, **kwargs)
builtins.__import__ = no_qt
sys.argv = ["app", *sys.argv[1:]]
runpy.run_module("rawtims_gui.main", run_name="__main__")
'''
    result = subprocess.run([sys.executable, "-c", bootstrap, "--update-self-test", manifest.as_uri(),
                             "--update-self-test-output", str(output)], check=False, cwd=tmp_path,
                            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["manifest"]["archive_verified"] is True


def test_normal_headless_cli_does_not_build_update_config(tmp_path, monkeypatch):
    monkeypatch.setattr(update_config, "update_config", lambda: pytest.fail("Unnecessary update config"))
    assert main.main(["--version-output", str(tmp_path / "version")]) == 0


@pytest.fixture
def app():
    return build_application(["updates-test"], theme_mode="light")


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("layout", ["wall", "classic"])
def test_window_update_controls_fit_1280x800(app, qt_settings_folder, theme, layout):
    build_application(["updates-test"], theme_mode=theme)
    window = main.MainWindow(restore_geometry=False, layout=layout)
    try:
        assert not window.updater._started
        window.resize(1280, 800)
        window.show()
        for _ in range(4):
            app.processEvents()
        assert window.size() == QtCore.QSize(1280, 800)
        assert window.updater._started
        assert window.check_updates_button.isVisible()
        assert window.check_updates_button.accessibleName() == "Check for updates"
        assert window.version_chip.isVisible()
        assert window.version_chip.text() == f"v{branding.VERSION}"
        for widget in (window.check_updates_button, window.version_chip):
            rect = QtCore.QRect(widget.mapTo(window, QtCore.QPoint()), widget.size())
            assert window.rect().contains(rect)
            assert widget.visibleRegion().boundingRect() == widget.rect()
        assert window.check_updates_button.whats_new_card.button is window.check_updates_button
        window.version_chip.open_dialog()
        assert window.version_chip._dialog.isVisible()
        window.version_chip._dialog.close()
        # Source checkouts never schedule a replacement check.
        assert window.updater.state.status == "unsupported"
    finally:
        window.close()
        assert window.updater._closing
        window.deleteLater()
        build_application(["updates-test"], theme_mode="light")


@pytest.mark.parametrize("previous,show", [(None, False), ("0.1.0", True), (branding.VERSION, False), ("9.0.0", False)])
def test_whats_new_once_after_version_change(app, tmp_path, previous, show):
    prefs = QtCore.QSettings(str(tmp_path / "updates.ini"), QtCore.QSettings.Format.IniFormat)
    prefs.setValue("updates/channel", "beta")
    if previous:
        prefs.setValue("updates/last_seen_version", previous)
    updater = Updater(update_config.update_config(), branding.VERSION, settings=prefs)
    button = CheckUpdatesButton(updater)
    button.show()
    received = []
    updater.whatsNew.connect(lambda *args: received.append(args))
    try:
        updater.start()
        for _ in range(3):
            app.processEvents()
        card = button.whats_new_card
        assert card.isVisible() is show
        assert len(received) == int(show)
        assert prefs.value("updates/last_seen_version") == branding.VERSION
        assert prefs.value("updates/channel") == "stable"
        if show:
            assert card.notes.text() == update_config.release_notes(branding.VERSION)
            QtTest.QTest.keyClick(card, QtCore.Qt.Key.Key_Escape)
            assert not card.isVisible()
        updater.start()
        app.processEvents()
        assert len(received) == int(show)
        # The popover's link can always reopen the running notes.
        button.popover.whats_new_link.linkActivated.emit("new")
        assert card.isVisible()
        assert card.heading.text() == f"What's new in v{branding.VERSION}"
        close = card.findChild(QtWidgets.QToolButton)
        close.click()
        assert not card.isVisible()
    finally:
        updater.shutdown()
        button.close()
        button.deleteLater()
        updater.deleteLater()


@pytest.mark.parametrize("pending,expected", [(True, "Saved manifest notes"), (False, "Updated to v0.2.0.")])
def test_whats_new_notes_fallback(app, tmp_path, pending, expected):
    prefs = QtCore.QSettings(str(tmp_path / "notes.ini"), QtCore.QSettings.Format.IniFormat)
    prefs.setValue("updates/pending_version", branding.VERSION if pending else "0.1.0")
    prefs.setValue("updates/pending_notes", "Saved manifest notes")
    config = replace(update_config.update_config(), release_notes=lambda version: None)
    updater = Updater(config, branding.VERSION, settings=prefs)
    assert updater.current_notes() == expected
    updater.shutdown()
    updater.deleteLater()


@pytest.mark.parametrize("status,manual", [("available", False), ("available", True), ("ready", False), ("ready", True)])
def test_update_notes_in_popover_and_settings(app, tmp_path, monkeypatch, status, manual):
    prefs = QtCore.QSettings(str(tmp_path / "views.ini"), QtCore.QSettings.Format.IniFormat)
    updater = Updater(update_config.update_config(), branding.VERSION, settings=prefs)
    button = CheckUpdatesButton(updater)
    dialog = UpdatesDialog(updater)
    release = Release("0.3.0", "- Print sheets fit A4 and Letter.\n- Review plots together.", None, "https://example.org/app", "signature")
    updater._emit(("check_started", manual))
    updater._emit(("found", release))
    if status == "ready":
        updater._emit("download_started")
        updater._emit(("downloaded", tmp_path / "archive"))
    state = updater.state
    opened = []
    from PySide6 import QtGui
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    try:
        for view in (button.popover, dialog):
            assert view.notes.text() == release.notes
            assert not view.notes.isHidden()
            assert not view.notes_link.isHidden()
            assert view.notes.height() == view.notes.fontMetrics().lineSpacing() * 4
            view.notes_link.linkActivated.emit("release")
        assert opened == ["https://github.com/duserzym/filament/releases/tag/v0.3.0"] * 2
        assert button.property("badge") is True
        assert button.property("busy") is False
        # A following busy state starts the rotation and removes notes.
        button.show()
        updater.stateChanged.emit(replace(state, status="checking"))
        assert button.property("busy") is True
        assert button.popover.notes.isHidden()
    finally:
        updater.shutdown()
        button.close()
        dialog.close()
        button.deleteLater()
        dialog.deleteLater()
        updater.deleteLater()


def test_supported_scheduler_and_shutdown(app, tmp_path, monkeypatch):
    from rawtims_gui.labupdate import install

    monkeypatch.setattr(install, "can_replace", lambda root: True)
    monkeypatch.setattr(install, "cleanup_previous", lambda root: None)
    prefs = QtCore.QSettings(str(tmp_path / "schedule.ini"), QtCore.QSettings.Format.IniFormat)
    updater = Updater(update_config.update_config(), branding.VERSION, settings=prefs, root=tmp_path / "app.app")
    updater.start_scheduler()
    assert updater._initial_timer.isActive() and updater._initial_timer.interval() == 8000
    assert updater._timer.isActive() and updater._timer.interval() == 6 * 60 * 60 * 1000
    updater.shutdown()
    assert not updater._initial_timer.isActive() and not updater._timer.isActive()
    updater.deleteLater()


@pytest.mark.parametrize("use_env", [False, True])
def test_mac_archive_preserves_symlinks_and_signs_verified_feed(tmp_path, monkeypatch, use_env):
    monkeypatch.setattr(build_desktop.sys, "platform", "darwin")
    monkeypatch.setattr(build_desktop.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(update_config, "PUBLIC_KEY", SELF_TEST_PUBKEY)
    app = tmp_path / f"{branding.DISPLAY_NAME}.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents/payload").write_text("binary")
    (app / "Contents/link").symlink_to("payload")
    dist = tmp_path / "dist"
    dist.mkdir()
    tarball = dist / f"{branding.DISPLAY_NAME}-{branding.VERSION}-macOS-arm64.app.tar.gz"
    signature = Path(str(tarball) + ".sig")
    signature.write_text("stale signature must be removed")
    key = tmp_path / "test.key"
    calls = []

    def external(command, **kwargs):
        calls.append(command)
        if command[0] == "ditto":
            with zipfile.ZipFile(command[-1], "w") as bundle:
                bundle.writestr(app.name + "/Contents/payload", "binary")
        else:
            assert command == ["cargo", "tauri", "signer", "sign", "-f", str(key), "-p", "", str(tarball)]
            assert not signature.exists()
            assert kwargs["env"]["TAURI_SIGNING_PRIVATE_KEY_PASSWORD"] == ""
            signature.write_text(sign(tarball.read_bytes()))

    monkeypatch.setattr(build_desktop.subprocess, "run", external)
    if use_env:
        monkeypatch.setenv("FILAMENT_UPDATER_KEY", str(key))
    else:
        monkeypatch.delenv("FILAMENT_UPDATER_KEY", raising=False)
    archive = build_desktop.archive_application(app, dist, sign_with=None if use_env else key)
    assert archive.is_file() and archive.with_suffix(".zip.sha256").is_file()
    assert [call[0] for call in calls] == ["ditto", "cargo"]
    with tarfile.open(tarball) as bundle:
        link = bundle.getmember(app.name + "/Contents/link")
        assert link.issym() and link.linkname == "payload"
        assert bundle.extractfile(app.name + "/Contents/payload").read() == b"binary"
    verify_file(tarball, signature.read_text(), SELF_TEST_PUBKEY)
    feed = json.loads((dist / "latest.json").read_text())
    assert feed["version"] == branding.VERSION
    assert feed["notes"].strip() == update_config.release_notes(branding.VERSION)
    assert feed["platforms"]["darwin-aarch64"]["url"] == (
        f"https://github.com/duserzym/filament/releases/download/v{branding.VERSION}/{tarball.name}")
    checksums = dict(line.split("  ", 1)[::-1] for line in (dist / "SHA256SUMS.txt").read_text().splitlines())
    assert set(checksums) == {archive.name, tarball.name, signature.name, "latest.json"}
    for name, digest in checksums.items():
        assert hashlib.sha256((dist / name).read_bytes()).hexdigest() == digest
    assert not (dist / "updater.pub").exists()


@pytest.mark.parametrize("notes", [None, "", " " * 5, "x" * 601])
def test_release_feed_refuses_missing_or_invalid_notes(tmp_path, notes):
    path = tmp_path / "notes.md"
    if notes is not None:
        path.write_text(notes)
    with pytest.raises((FileNotFoundError, ValueError)):
        build_feed(repo=update_config.REPO, version=branding.VERSION, notes_file=path,
                   archives={}, pubkey_file=tmp_path / "unused.pub", out=tmp_path / "latest.json")
    assert not (tmp_path / "latest.json").exists()


def test_frozen_smoke_uses_signed_archive_and_missing_ca_paths(tmp_path, monkeypatch, capsys):
    def frozen(application, arguments, work_directory, *, environment_overrides, check):
        assert check is False
        assert not Path(environment_overrides["SSL_CERT_FILE"]).exists()
        assert not Path(environment_overrides["SSL_CERT_DIR"]).exists()
        config = replace(update_config.update_config(), opener=offline_opener)
        report = run_self_test(config, arguments[1])
        Path(arguments[3]).write_text(json.dumps(report))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(build_desktop, "run_frozen", frozen)
    build_desktop.verify_update_self_test(tmp_path / "app.app", tmp_path)
    assert "Warning: frozen update HTTPS check unavailable" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["tampered", "verification", "pubkey", "manifest", "https", "tls", "exit", "traceback"])
def test_frozen_smoke_rejects_incomplete_or_failed_checks(tmp_path, monkeypatch, failure):
    def frozen(application, arguments, work_directory, **kwargs):
        config = replace(update_config.update_config(), opener=offline_opener)
        report = run_self_test(config, arguments[1])
        if failure == "tampered":
            report["signature"]["tampered_rejected"] = False
        elif failure == "verification":
            report["verification_ran"] = False
        elif failure == "pubkey":
            report["public_key"]["status"] = "not configured"
        elif failure == "manifest":
            report["manifest"]["archive_verified"] = False
        elif failure == "https":
            report["https"]["status"] = "certificate"
        elif failure == "tls":
            report["tls"] = {"status": "error"}
        Path(arguments[3]).write_text(json.dumps(report))
        return subprocess.CompletedProcess(arguments, int(failure == "exit"), "", "Traceback" if failure == "traceback" else "")

    monkeypatch.setattr(build_desktop, "run_frozen", frozen)
    with pytest.raises(RuntimeError, match="Frozen update self-test failed"):
        build_desktop.verify_update_self_test(tmp_path / "app.app", tmp_path)


def test_frozen_update_smoke_hides_homebrew_certificates(tmp_path, monkeypatch):
    monkeypatch.setattr(build_desktop.sys, "platform", "darwin")
    monkeypatch.setattr(build_desktop.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    seen = []
    monkeypatch.setattr(build_desktop.subprocess, "run", lambda cmd, **kw: (
        seen.append((cmd, kw)) or subprocess.CompletedProcess(cmd, 0, "", "")))
    overrides = {"SSL_CERT_FILE": str(tmp_path / "missing.pem"), "SSL_CERT_DIR": str(tmp_path / "missing-certs")}
    build_desktop.run_frozen(tmp_path / "app.app", ["--update-self-test"], tmp_path, environment_overrides=overrides)
    command, kwargs = seen[0]
    assert command[:2] == ["/usr/bin/sandbox-exec", "-f"]
    profile = Path(command[2]).read_text()
    assert '(deny file-read*' in profile
    assert '/opt/homebrew/etc/openssl@3' in profile and '/usr/local/etc/openssl@3' in profile
    assert all(kwargs["env"][key] == value for key, value in overrides.items())
