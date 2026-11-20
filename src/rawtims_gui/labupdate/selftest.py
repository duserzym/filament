"""Frozen-build TLS and signature smoke tests, including a mandatory rejection check."""

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from . import minisign, tls
from .manifest import fetch_manifest, validate_url

SELF_TEST_DATA = b"labupdate frozen-build verification\n"
SELF_TEST_PUBKEY = "dW50cnVzdGVkIGNvbW1lbnQ6IHRlc3Qga2V5ClJXUjBaWE4wTFd0bGVkZGFtQUdDc1FxMzFVdiswOGxrQnpvTzRYTHoycVlqSmE4Q0dtajNCMUVhCg=="
SELF_TEST_SIGNATURE = "dW50cnVzdGVkIGNvbW1lbnQ6IHRlc3Qgc2lnbmF0dXJlClJVUjBaWE4wTFd0bGVkdmxQU1NTcDhFeC84QXhOaFYyeWpXQk9PcSt2SVZJaVRGU3RlZ09PNTdDRUdaRmtrb2c5YXNaVVB0ZEFIanJEdnkybUl3YkQ5a2FKZklDOTlja0Z3WT0KdHJ1c3RlZCBjb21tZW50OiBsYWJ1cGRhdGUgdGVzdAora2J5T1MrcGJFbVpxaHRTRHNkN0tyVVB4RDNQcy92cmQzcUJqZWd5cmRTTTB1aTlWdlZiZ0VEQy9hZTdIUkVXbm5Kd1RlNy9xcThhQzNqVFFWQ0JBdz09Cg=="


def _verify_archive(release, config, archive_dir, opener):
    """Self-test only: verify an archive with the embedded disposable key."""
    if archive_dir is not None:
        name = Path(urllib.parse.unquote(urllib.parse.urlsplit(release.url).path)).name
        if not name:
            raise ValueError("Missing archive filename")
        path = Path(archive_dir) / name
        if path.stat().st_size > config.max_archive_bytes:
            raise ValueError("Archive exceeds size limit")
        minisign.verify_file(path, release.signature, SELF_TEST_PUBKEY)
        return
    with tempfile.TemporaryDirectory(prefix="labupdate-selftest-") as folder:
        path = Path(folder) / "archive"
        request = urllib.request.Request(validate_url(release.url))
        with opener(request, timeout=20) as response, path.open("wb") as output:
            received = 0
            while chunk := response.read(min(1024 * 1024, config.max_archive_bytes - received + 1)):
                received += len(chunk)
                if received > config.max_archive_bytes:
                    raise ValueError("Archive exceeds size limit")
                output.write(chunk)
        minisign.verify_file(path, release.signature, SELF_TEST_PUBKEY)


def run_self_test(config, manifest_url=None, archive_dir=None) -> dict:
    """Check trust, known signatures and optionally a disposable-key test feed."""
    opener = config.opener or tls.urlopen
    report = {"ok": True, "verification_ran": False}
    try:
        report["tls"] = tls.describe()
    except Exception as exc:
        report["tls"] = {"status": "error", "message": str(exc)}
        report["ok"] = False
    try:
        with opener(urllib.request.Request("https://github.com/"), timeout=20) as response:
            report["https"] = {"status": "ok", "http_status": getattr(response, "status", None)}
    except urllib.error.HTTPError as exc:
        report["https"] = {"status": "ok", "http_status": exc.code}
        exc.close()
    except Exception as exc:
        certificate = tls.is_certificate_error(exc)
        network = isinstance(exc, (urllib.error.URLError, OSError))
        report["https"] = {"status": "certificate" if certificate else "network" if network else "error", "message": str(exc)}
        if certificate or not network:
            report["ok"] = False
    try:
        minisign.verify_bytes(SELF_TEST_DATA, SELF_TEST_SIGNATURE, SELF_TEST_PUBKEY)
        try:
            minisign.verify_bytes(b"X" + SELF_TEST_DATA[1:], SELF_TEST_SIGNATURE, SELF_TEST_PUBKEY)
        except minisign.SignatureError:
            pass
        else:
            raise RuntimeError("Verifier accepted the tampered self-test vector")
        report["verification_ran"] = True
        report["signature"] = {"status": "ok", "tampered_rejected": True}
    except Exception as exc:
        report["ok"] = False
        report["signature"] = {"status": "error", "message": str(exc)}
    try:
        if not config.pubkey.strip():
            report["public_key"] = {"status": "not configured"}
        else:
            key = minisign.parse_public_key(config.pubkey)
            report["public_key"] = {"status": "ok", "key_id": key.key_id.hex()}
    except Exception as exc:
        report["ok"] = False
        report["public_key"] = {"status": "error", "message": str(exc)}
    if manifest_url is not None:
        try:
            release = fetch_manifest(replace(config, feed_url=manifest_url), opener)
            _verify_archive(release, config, archive_dir, opener)
            report["manifest"] = {"status": "ok", "version": release.version, "archive_verified": True}
        except Exception as exc:
            report["ok"] = False
            report["manifest"] = {"status": "error", "message": str(exc)}
    report["ok"] = bool(report["ok"] and report["verification_ran"])
    return report


def add_self_test_argument(parser):
    """Add the optional-URL self-test switch and Windows-safe JSON output path."""
    parser.add_argument("--update-self-test", nargs="?", const="", default=None, metavar="MANIFEST_URL")
    parser.add_argument("--update-self-test-output", metavar="FILE")


def handle_self_test(args, config) -> int | None:
    """Run before creating windows; return an exit code, or None for normal launch."""
    value = getattr(args, "update_self_test", None)
    if value is None:
        return None
    report = run_self_test(config, manifest_url=value or None)
    serialized = json.dumps(report, indent=2) + "\n"
    output = getattr(args, "update_self_test_output", None)
    if output:
        try:
            Path(output).write_text(serialized, encoding="utf-8")
        except OSError:
            return 1
    if sys.stdout is not None:
        print(serialized, end="")
    return 0 if report["ok"] else 1
