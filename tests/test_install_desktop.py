"""Exercise installation safety in temporary folders; never touch /Applications."""
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from scripts import install_desktop as installer


@pytest.mark.parametrize('failure', ['signature', 'version', None])
def test_install_verifies_before_swap_and_preserves_previous_on_failure(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(installer.sys, 'platform', 'darwin')
    source = tmp_path / 'build/Test.app'
    executable = source / 'Contents/MacOS' / installer.branding.EXECUTABLE_NAME
    executable.parent.mkdir(parents=True)
    executable.write_text('new')
    destination = tmp_path / 'applications'
    destination.mkdir()
    target = destination / f'{installer.branding.DISPLAY_NAME}.app'
    target.mkdir()
    (target / 'previous').write_text('old')
    calls = []
    def run(command, **kwargs):
        calls.append(command[0])
        if command[0] == 'ps':
            return SimpleNamespace(stdout='')
        if command[0] == 'ditto':
            shutil.copytree(command[1], command[2])
        if command[0] == 'codesign' and failure == 'signature':
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(installer.subprocess, 'run', run)
    def version(app, work):
        calls.append('version')
        assert (target / 'previous').read_text() == 'old'
        if failure == 'version':
            raise RuntimeError('version mismatch')
    monkeypatch.setattr(installer, 'verify_application_version', version)
    def swap(staged, installed):
        calls.append('swap')
        assert calls[-4:] == ['codesign', 'version', 'ps', 'swap']
        old = destination / 'old'
        installed.rename(old)
        staged.rename(installed)
        old.rename(staged)
    monkeypatch.setattr(installer, 'atomic_replace', swap)
    if failure:
        with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
            installer.install(source, destination)
        assert (target / 'previous').read_text() == 'old'
        assert 'swap' not in calls
    else:
        assert installer.install(source, destination) == target
        assert (target / 'Contents/MacOS' / installer.branding.EXECUTABLE_NAME).read_text() == 'new'
    assert list(destination.iterdir()) == [target]


def test_running_app_refused_before_copy(tmp_path, monkeypatch):
    app = tmp_path / 'Test.app'
    exe = app / 'Contents/MacOS' / installer.branding.EXECUTABLE_NAME
    monkeypatch.setattr(installer.sys, 'platform', 'darwin')
    monkeypatch.setattr(installer.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=str(exe) + ' --open example.xls\n'))
    with pytest.raises(RuntimeError, match='Quit the app'):
        installer.refuse_running(app)


def test_atomic_first_install_uses_rename(tmp_path):
    staged, target = tmp_path / 'staged.app', tmp_path / 'target.app'
    staged.mkdir()
    (staged / 'payload').write_text('new')
    installer.atomic_replace(staged, target)
    assert (target / 'payload').read_text() == 'new'
    assert not staged.exists()


def test_atomic_macos_swap_keeps_both_complete_directories(tmp_path):
    import sys
    if sys.platform != 'darwin':
        pytest.skip('macOS renameatx_np only')
    staged, target = tmp_path / 'staged.app', tmp_path / 'target.app'
    for path, text in ((staged, 'new'), (target, 'old')):
        path.mkdir()
        (path / 'payload').write_text(text)
    installer.atomic_replace(staged, target)
    assert (target / 'payload').read_text() == 'new'
    assert (staged / 'payload').read_text() == 'old'
