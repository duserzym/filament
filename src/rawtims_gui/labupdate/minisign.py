"""Pure Python Ed25519 verification for Tauri's minisign envelopes."""

import base64
import binascii
from dataclasses import dataclass
import hashlib
from pathlib import Path

# RFC 8032 sections 5.1.3, 5.1.4 and 5.1.7. All operands are public.
P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, P - 2, P) % P
_I = pow(2, (P - 1) // 4, P)
_IDENTITY = (0, 1, 1, 0)


class SignatureError(ValueError):
    """A key, signature envelope or cryptographic check was invalid."""


@dataclass(frozen=True)
class TrustedInfo:
    """The authenticated text following the trusted-comment prefix."""

    comment: str


@dataclass(frozen=True)
class PublicKey:
    """Decoded minisign identifier and Ed25519 verification key."""

    key_id: bytes
    key: bytes


def _add(p, q):
    x, y, z, t = p
    u, v, w, s = q
    a = (y - x) * (v - u) % P
    b = (y + x) * (v + u) % P
    c = 2 * _D * t * s % P
    d = 2 * z * w % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return e * f % P, g * h % P, f * g % P, e * h % P


def _multiply(point, scalar):
    result = _IDENTITY
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(p, q):
    return (p[0] * q[2] - q[0] * p[2]) % P == 0 and (p[1] * q[2] - q[1] * p[2]) % P == 0


def _decode(encoded):
    if len(encoded) != 32:
        raise SignatureError("invalid point")
    packed = int.from_bytes(encoded, "little")
    y, sign = packed & ((1 << 255) - 1), packed >> 255
    if y >= P:
        raise SignatureError("invalid point")
    y2 = y * y % P
    denominator = (_D * y2 + 1) % P
    if not denominator:
        raise SignatureError("invalid point")
    x2 = (y2 - 1) * pow(denominator, P - 2, P) % P
    x = pow(x2, (P + 3) // 8, P)
    if x * x % P != x2:
        x = x * _I % P
    if x * x % P != x2 or (x == 0 and sign):
        raise SignatureError("invalid point")
    if x & 1 != sign:
        x = P - x
    return x, y, 1, x * y % P


_BASE = _decode(bytes.fromhex("58" + "66" * 31))


def _validate_point(point):
    # Reject small-order and mixed-order points, as well as non-canonical encodings.
    if _equal(point, _IDENTITY) or not _equal(_multiply(point, L), _IDENTITY):
        raise SignatureError("invalid point")


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify RFC 8032 Ed25519, with canonical scalars and subgroup validation."""
    try:
        if len(signature) != 64:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= L:
            return False
        a, r = _decode(public_key), _decode(signature[:32])
        _validate_point(a)
        _validate_point(r)
        k = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % L
        return _equal(_multiply(_BASE, s), _add(r, _multiply(a, k)))
    except (SignatureError, ValueError, TypeError):
        return False


def _b64(text):
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error, TypeError) as exc:
        raise SignatureError("malformed signature") from exc


def parse_public_key(pubkey: str) -> PublicKey:
    """Accept a Tauri base64 .pub file, raw .pub text or bare RW line."""
    if not pubkey or not pubkey.strip():
        raise SignatureError("no public key configured")
    try:
        text = pubkey.strip()
        if not text.startswith("untrusted comment:"):
            decoded = _b64(text)
            if len(decoded) == 42 and decoded[:2] == b"Ed":
                raw = decoded
            else:
                text = decoded.decode("utf-8").strip()
                raw = _b64(text.splitlines()[-1])
        else:
            lines = text.splitlines()
            if len(lines) != 2:
                raise SignatureError("malformed public key")
            raw = _b64(lines[1])
        if len(raw) != 42 or raw[:2] != b"Ed":
            raise SignatureError("malformed public key")
        _validate_point(_decode(raw[10:]))
        return PublicKey(raw[2:10], raw[10:])
    except (UnicodeError, IndexError, AttributeError) as exc:
        raise SignatureError("malformed public key") from exc


def _parse(signature_text, pubkey):
    key = parse_public_key(pubkey)
    try:
        text = signature_text.strip()
        if not text.startswith("untrusted comment:"):
            text = _b64(text).decode("utf-8")
        lines = text.splitlines()
        if len(lines) != 4 or not lines[0].startswith("untrusted comment: ") or not lines[2].startswith("trusted comment: "):
            raise SignatureError("malformed signature")
        raw, global_sig = _b64(lines[1]), _b64(lines[3])
        if len(raw) != 74 or raw[:2] not in (b"Ed", b"ED") or len(global_sig) != 64:
            raise SignatureError("malformed signature")
        if raw[2:10] != key.key_id:
            raise SignatureError("key id mismatch")
        return key, raw[:2], raw[10:], lines[2][len("trusted comment: "):], global_sig
    except (UnicodeError, AttributeError, IndexError) as exc:
        raise SignatureError("malformed signature") from exc


def _verify(message, parsed):
    key, algorithm, signature, comment, global_sig = parsed
    if not ed25519_verify(key.key, message, signature):
        raise SignatureError("bad signature")
    if not ed25519_verify(key.key, signature + comment.encode("utf-8"), global_sig):
        raise SignatureError("bad signature")
    return TrustedInfo(comment)


def verify_bytes(data: bytes, signature_text: str, pubkey: str) -> TrustedInfo:
    """Authenticate bytes and their trusted comment; failures raise SignatureError."""
    parsed = _parse(signature_text, pubkey)
    message = hashlib.blake2b(data, digest_size=64).digest() if parsed[1] == b"ED" else data
    return _verify(message, parsed)


def verify_file(path, signature_text: str, pubkey: str) -> TrustedInfo:
    """Authenticate a file, hashing ED messages in bounded streaming chunks."""
    parsed = _parse(signature_text, pubkey)
    if parsed[1] == b"ED":
        digest = hashlib.blake2b(digest_size=64)
        with Path(path).open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        message = digest.digest()
    else:
        message = Path(path).read_bytes()
    return _verify(message, parsed)
