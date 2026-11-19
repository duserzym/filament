"""Copy and verify a built macOS app, then atomically replace the installed app.

Only invoked by `make install`. Never remove the old app before the new copy
has passed signature and version verification. macOS RENAME_SWAP exchanges
nonempty directories atomically; the temporary name then holds the old app.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from rawtims import branding

try:
    from .build_desktop import (
        BUILD_ROOT,
        application_executable,
        application_path,
        verify_application_version,
    )
except ImportError:  # direct script invocation
    from build_desktop import (
        BUILD_ROOT,
        application_executable,
        application_path,
        verify_application_version,
    )


def refuse_running(*applications: Path) -> None:
    commands = subprocess.run(["ps", "-axo", "command="], check=True, capture_output=True, text=True).stdout
    if any(str(application_executable(app)) in line for app in applications for line in commands.splitlines()):
        raise RuntimeError("Quit the app before installing; an application executable is running.")


def atomic_replace(staged: Path, target: Path) -> None:
    if target.exists():
        libc = ctypes.CDLL(None, use_errno=True)
        swap = libc.renameatx_np
        swap.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        swap.restype = ctypes.c_int
        if swap(-2, os.fsencode(staged), -2, os.fsencode(target), 2):  # AT_FDCWD, RENAME_SWAP
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(target))
    else:
        staged.rename(target)


def install(application: Path, destination: Path = Path('/Applications')) -> Path:
    if sys.platform != 'darwin':
        raise RuntimeError('Installation is supported on macOS only.')
    if not application.is_dir() or not application_executable(application).is_file():
        raise RuntimeError(f'Build the application first: {application}')
    target = destination / f'{branding.DISPLAY_NAME}.app'
    refuse_running(application, target)
    staged = destination / f'.{branding.EXECUTABLE_NAME}-{uuid.uuid4().hex}.app'
    try:
        subprocess.run(['ditto', str(application), str(staged)], check=True)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(staged)], check=True)
        with tempfile.TemporaryDirectory(prefix='app-install-check-') as scratch:
            verify_application_version(staged, Path(scratch))
        refuse_running(application, target)
        atomic_replace(staged, target)
    finally:
        if staged.is_symlink():
            staged.unlink()
        elif staged.exists():
            shutil.rmtree(staged)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application', type=Path, default=application_path(BUILD_ROOT / 'dist'))
    args = parser.parse_args()
    print(f'Installed: {install(args.application.expanduser().resolve())}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
