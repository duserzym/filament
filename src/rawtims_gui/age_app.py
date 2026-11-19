"""Explicit hand-off launcher. No launch occurs during discovery or export."""
from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

BUNDLE_ID = 'org.idtims-upbrpy.reduction'
APP_NAMES = ('ID-TIMS Reduction.app', 'IDTIMS_UPbRPy.app')


def discover(command='', *, platform=None, roots=None):
    """Return an argv prefix (never a shell command) or None."""
    if command.strip():
        args = shlex.split(command)
        if not args:
            return None
        args = [os.path.expanduser(part) for part in args]
        if not (Path(args[0]).is_file() or shutil.which(args[0])):
            raise ValueError(f'Age app command not found: {args[0]}')
        return args
    platform = platform or sys.platform
    if platform == 'darwin':
        for root in roots if roots is not None else (Path('/Applications'), Path.home() / 'Applications'):
            root = Path(root)
            for app in root.glob('*.app'):
                matched = app.name in APP_NAMES
                info = app / 'Contents' / 'Info.plist'
                if info.is_file():
                    try:
                        matched |= plistlib.loads(info.read_bytes()).get('CFBundleIdentifier') == BUNDLE_ID
                    except (ValueError, plistlib.InvalidFileException):
                        pass
                if matched:
                    # A new process forwards --open through the age app's
                    # single-instance socket. open without -n drops new argv
                    # when the bundle is already running.
                    return ['open', '-n', '-a', str(app), '--args']
    executable = shutil.which('idtims-app')
    return [executable] if executable else None


def send(path, command='', *, launcher=subprocess.Popen, reveal=None):
    """A saved contract goes to --open; absence/failure reveals it instead."""
    try:
        prefix = discover(command)
        if prefix:
            launcher([*prefix, '--open', str(Path(path).resolve())])
            return 'Saved and opened in IDTIMS_UPbRPy.'
        message = 'Saved. IDTIMS_UPbRPy was not found; configure its command below.'
    except (OSError, ValueError) as error:
        message = f'Saved; could not open IDTIMS_UPbRPy: {error}.'
    if reveal is not None:
        reveal(Path(path))
    return message + ' Revealed the saved file.'


def reveal_file(path, *, platform=None, launcher=subprocess.Popen, open_folder=None):
    """Select a saved file in Finder; other desktops open its containing folder."""
    if (platform or sys.platform) == 'darwin':
        try:
            launcher(['/usr/bin/open', '-R', str(Path(path).resolve())])
            return
        except OSError:
            pass
    if open_folder is not None:
        open_folder(Path(path).parent)
