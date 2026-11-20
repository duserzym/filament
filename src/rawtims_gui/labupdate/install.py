"""Verified downloads, safe archive staging and detached application swaps."""

import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import plistlib
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from . import tls
from .manifest import validate_url
from .minisign import SignatureError, verify_file

CHUNK_SIZE = 1024 * 1024


class NotConfiguredError(ValueError):
    """This application has no production update key."""


def is_frozen() -> bool:
    """Whether this process is a packaged application."""
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path | None:
    """Find the running macOS bundle or Windows application directory."""
    if not is_frozen():
        return None
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        return next((p for p in executable.parents if p.suffix == ".app"), None)
    if sys.platform == "win32":
        return executable.parent
    return None


def can_replace(root) -> bool:
    """Require write access to both the installation and its parent."""
    return bool(root and Path(root).is_dir() and not Path(root).is_symlink()
                and os.access(root, os.W_OK) and os.access(Path(root).parent, os.W_OK))


def previous_path(root) -> Path:
    """Name the previous installation without depending on an app's name."""
    root = Path(root)
    return root.with_name(root.stem + ".previous.app" if root.suffix == ".app" else root.name + ".previous")


def cleanup_previous(root) -> None:
    """Remove the retained backup only after the new app starts successfully."""
    if root is None:
        return
    root = Path(root)
    previous = previous_path(root)
    if root.is_dir() and previous.is_dir() and not previous.is_symlink():
        shutil.rmtree(previous)


def _require_signature(config, release):
    if not config.pubkey.strip():
        raise NotConfiguredError("no public key configured")
    if not release.signature.strip():
        raise SignatureError("missing signature")


def download_archive(release, config, opener=tls.urlopen, *, progress=None, cancelled=None) -> Path:
    """Download into a fresh temporary folder and authenticate before returning."""
    _require_signature(config, release)
    url = validate_url(release.url)
    name = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name
    if config.asset_names:
        from .config import platform_key
        name = config.asset_names.get(platform_key(), name)
    if not name or PureWindowsPath(name).name != name or Path(name).name != name:
        raise ValueError("Invalid archive name")
    folder = Path(tempfile.mkdtemp(prefix="labupdate-download-"))
    path = folder / name
    try:
        request = urllib.request.Request(url, headers={"User-Agent": config.app_name + "-updater"})
        received = 0
        with opener(request, timeout=20) as response, path.open("wb") as output:
            total = int(response.headers.get("Content-Length", 0) or 0)
            if total < 0 or total > config.max_archive_bytes:
                raise ValueError("Archive exceeds size limit")
            while True:
                if cancelled and cancelled():
                    raise RuntimeError("Download cancelled")
                chunk = response.read(min(CHUNK_SIZE, config.max_archive_bytes - received + 1))
                if not chunk:
                    break
                received += len(chunk)
                if received > config.max_archive_bytes:
                    raise ValueError("Archive exceeds size limit")
                output.write(chunk)
                if progress:
                    progress(received, total)
            if total and received != total:
                raise ValueError("Incomplete update download")
        verify_file(path, release.signature, config.pubkey)
        return path
    except urllib.error.HTTPError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        with exc:
            excerpt = exc.read(240).decode("utf-8", errors="replace")
        raise ValueError(f"HTTP {exc.code}: {excerpt}") from exc
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def _safe_name(name):
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if (not name or "\x00" in name or path.is_absolute() or PureWindowsPath(name).drive
            or ".." in path.parts or any(":" in p for p in path.parts)):
        raise ValueError("Unsafe path in update archive")
    if not path.parts:
        raise ValueError("Unsafe path in update archive")
    return path


def _link_target(path, target, top):
    raw = target.replace("\\", "/")
    if "\x00" in raw or PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).drive:
        raise ValueError("Outside symbolic link in update archive")
    parts = list(path.parent.parts)
    for part in raw.split("/"):
        if part == "..":
            if len(parts) <= 1:
                raise ValueError("Outside symbolic link in update archive")
            parts.pop()
        elif part not in ("", "."):
            if ":" in part:
                raise ValueError("Unsafe symbolic link")
            parts.append(part)
    if not parts or parts[0] != top:
        raise ValueError("Outside symbolic link in update archive")
    return PurePosixPath(*parts)


def _extract(archive, stage, *, mac, limit):
    """Preflight every entry; write files before links so links cannot redirect writes."""
    zipped = zipfile.is_zipfile(archive)
    bundle = zipfile.ZipFile(archive) if zipped else tarfile.open(archive, "r:gz")
    with bundle:
        entries, seen, total = [], set(), 0
        members = bundle.infolist() if zipped else bundle.getmembers()
        for member in members:
            name = member.filename if zipped else member.name
            path = _safe_name(name)
            # Reject duplicates (including case aliases) for case-insensitive app volumes.
            folded = path.as_posix().casefold()
            if folded in seen:
                raise ValueError("Duplicate path in update archive")
            seen.add(folded)
            mode = member.external_attr >> 16 if zipped else member.mode
            directory = member.is_dir() if zipped else member.isdir()
            link = stat.S_ISLNK(mode) if zipped else member.issym()
            if zipped:
                special = stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK)
            else:
                special = not (member.isfile() or directory or link)
            if special or (link and not mac):
                raise ValueError("Unsupported entry in update archive")
            size = member.file_size if zipped else member.size
            total += size
            if total > limit:
                raise ValueError("Expanded archive exceeds size limit")
            target = None
            if link:
                if size > 4096:
                    raise ValueError("Invalid symbolic link")
                target = bundle.read(member).decode("utf-8") if zipped else member.linkname
            entries.append((path, mode, directory, target, member))
        tops = {entry[0].parts[0] for entry in entries}
        if len(tops) != 1:
            raise ValueError("Archive must contain one application folder")
        top = tops.pop()
        if mac and not top.endswith(".app"):
            raise ValueError("Archive does not contain an app bundle")
        links = {path.as_posix().casefold() for path, _, _, target, _ in entries if target is not None}
        for path, _, _, target, _ in entries:
            if any(parent.as_posix().casefold() in links for parent in path.parents):
                raise ValueError("Archive entry traverses a symbolic link")
            if target is not None:
                _link_target(path, target, top)
        # All names and all link destinations were checked before writing.
        for path, mode, directory, target, member in entries:
            dest = stage.joinpath(*path.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if directory:
                dest.mkdir(exist_ok=True)
            elif target is None:
                source = bundle.open(member) if zipped else bundle.extractfile(member)
                with source, dest.open("xb") as output:
                    shutil.copyfileobj(source, output, CHUNK_SIZE)
                dest.chmod(mode & 0o777 or 0o644)
        for path, mode, directory, target, _ in entries:
            if target is not None:
                dest = stage.joinpath(*path.parts)
                # Resolve the entire chain too, catching cycles and chained escapes.
                dest.symlink_to(target)
        for path, _, _, target, _ in entries:
            if target is not None:
                try:
                    resolved = stage.joinpath(*path.parts).resolve()
                except (OSError, RuntimeError) as exc:
                    raise ValueError("Invalid symbolic link chain") from exc
                if not resolved.is_relative_to(stage / top):
                    raise ValueError("Outside symbolic link in update archive")
        for path, mode, directory, _, _ in reversed(entries):
            if directory:
                stage.joinpath(*path.parts).chmod(mode & 0o777 or 0o755)
        return stage / top


def detached_runner(command):
    """Launch a helper independently of the running application."""
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   cwd=str(Path(command[-1]).parent))
    if sys.platform == "win32":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)


def _executable(new, root, config):
    if root.suffix == ".app":
        name = config.app_name
        plist = new / "Contents/Info.plist"
        if plist.is_file():
            with plist.open("rb") as stream:
                name = plistlib.load(stream).get("CFBundleExecutable", name)
        if not isinstance(name, str) or Path(name).name != name or "\\" in name:
            raise ValueError("Invalid bundle executable")
        executable = new / "Contents/MacOS" / name
    else:
        executable = new / (root.name + ".exe")
    if not executable.is_file():
        raise ValueError("Archive does not contain the application executable")
    return executable


def prepare_install(archive, root, release, config, runner=detached_runner) -> Path:
    """Reverify, stage on the install volume, and start a helper waiting for exit."""
    _require_signature(config, release)
    archive, root = Path(archive), Path(root)
    if archive.stat().st_size > config.max_archive_bytes:
        raise ValueError("Archive exceeds size limit")
    verify_file(archive, release.signature, config.pubkey)
    if not can_replace(root):
        raise PermissionError("Installation folder is not writable")
    previous = previous_path(root)
    if previous.exists() or previous.is_symlink():
        raise ValueError("Previous installation still exists; restart before updating")
    stage = Path(tempfile.mkdtemp(prefix=".labupdate-install-", dir=root.parent))
    mac = root.suffix == ".app"
    try:
        new = _extract(archive, stage, mac=mac, limit=config.max_archive_bytes)
        executable = _executable(new, root, config)
        if mac:
            script = stage / "install.sh"
            old_q, new_q, prev_q, stage_q = map(shlex.quote, map(str, (root, new, previous, stage)))
            content = f'''#!/bin/sh
PID={os.getpid()}
while kill -0 "$PID" 2>/dev/null; do sleep 1; done
mv {old_q} {prev_q} || exit 1
if ! mv {new_q} {old_q}; then
    mv {prev_q} {old_q}
    exit 1
fi
xattr -dr com.apple.quarantine {old_q} 2>/dev/null || true
open -n {old_q}
rm -rf {stage_q}
'''
            command = ["/bin/sh", str(script)]
        else:
            script = stage / "install.cmd"
            def quote(path):
                value = str(path)
                if any(c in value for c in '\r\n"'):
                    raise ValueError("Unsafe helper path")
                return '"' + value.replace("%", "%%") + '"'
            old_q, new_q, prev_q, stage_q = map(quote, (root, new, previous, stage))
            launch_q = quote(root / executable.relative_to(new))
            content = f'''@echo off
chcp 65001 >nul
setlocal DisableDelayedExpansion
set PID={os.getpid()}
:wait
tasklist /FI "PID eq %PID%" /NH | find " %PID% " >nul
if errorlevel 1 goto replace
ping 127.0.0.1 -n 2 >nul
goto wait
:replace
move {old_q} {prev_q} >nul
if errorlevel 1 exit /b 1
move {new_q} {old_q} >nul
if errorlevel 1 (
    move {prev_q} {old_q} >nul
    exit /b 1
)
cd /d {quote(root.parent)}
start "" /D {old_q} {launch_q}
rmdir /s /q {stage_q}
'''
            command = ["cmd.exe", "/d", "/c", str(script)]
        script.write_text(content, encoding="utf-8", newline="\n" if mac else "\r\n")
        runner(command)
        return script
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
