"""Build a verified Tauri release feed from local signed archives and lab notes."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse

from . import minisign
from .manifest import parse_version


def build_feed(*, repo, version, notes_file, archives, pubkey_file, out, sign_with=None):
    """Verify every archive before publishing latest.json; return the feed dict."""
    version = version.removeprefix("v")
    if not parse_version(version)[3]:
        raise ValueError("The update feed requires a stable version")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("Expected repo owner/name")
    notes = Path(notes_file).read_text(encoding="utf-8")
    if not notes.strip() or len(notes) > 600:
        raise ValueError("Release notes must contain 1–600 characters")
    pubkey = Path(pubkey_file).read_text(encoding="utf-8")
    minisign.parse_public_key(pubkey)
    platforms = {}
    for target, path in archives.items():
        path = Path(path)
        if not path.is_file():
            raise ValueError(f"Missing archive: {path}")
        signature_file = Path(str(path) + ".sig")
        if not signature_file.exists() and sign_with:
            subprocess.run(["cargo", "tauri", "signer", "sign", "-f", str(sign_with), "-p", "", str(path)],
                           env={**os.environ, "TAURI_SIGNING_PRIVATE_KEY_PASSWORD": ""}, check=True)
        signature = signature_file.read_text(encoding="utf-8").strip()
        minisign.verify_file(path, signature, pubkey)
        platforms[target] = {"signature": signature,
            "url": f"https://github.com/{repo}/releases/download/v{version}/{urllib.parse.quote(path.name)}"}
    if not platforms:
        raise ValueError("No archives provided")
    feed = {"version": version, "notes": notes, "platforms": platforms}
    Path(out).write_text(json.dumps(feed, indent=2) + "\n", encoding="utf-8")
    return feed


def main(argv=None):
    """Run as python -m <vendored-package>.release."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "version", "notes-file", "darwin-aarch64", "pubkey-file", "out"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--windows-x86_64")
    parser.add_argument("--sign-with")
    args = parser.parse_args(argv)
    archives = {"darwin-aarch64": args.darwin_aarch64}
    if args.windows_x86_64:
        archives["windows-x86_64"] = args.windows_x86_64
    build_feed(repo=args.repo, version=args.version, notes_file=args.notes_file,
               archives=archives, pubkey_file=args.pubkey_file, out=args.out, sign_with=args.sign_with)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
