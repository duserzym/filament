"""Deterministic pure Python signing of disposable test data, never production keys."""

import base64
import hashlib

SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
KEY_ID = b"test-key"
_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _Q - 2, _Q) % _Q
_B = (15112221349535400772501151409588531511454012693041857206046113283949847762202,
      46316835694926478169428394003475163141307993866256225615783033603165251855960, 1,
      0)
_B = (*_B[:3], _B[0] * _B[1] % _Q)


def _add(p, q):
    x, y, z, t = p
    u, v, w, s = q
    a, b = (y - x) * (v - u) % _Q, (y + x) * (v + u) % _Q
    c, d = 2 * _D * t * s % _Q, 2 * z * w % _Q
    e, f, g, h = b - a, d - c, d + c, b + a
    return e*f % _Q, g*h % _Q, f*g % _Q, e*h % _Q


def _mul(n):
    p, r = _B, (0, 1, 1, 0)
    while n:
        if n & 1:
            r = _add(r, p)
        p, n = _add(p, p), n >> 1
    x, y, z, _ = r
    inv = pow(z, _Q - 2, _Q)
    x, y = x * inv % _Q, y * inv % _Q
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _secret(seed):
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    return (scalar & ((1 << 254) - 8)) | (1 << 254), digest[32:]


def sign_ed25519(data, seed=SEED):
    """Create a deterministic RFC 8032 detached signature for test messages."""
    scalar, prefix = _secret(seed)
    key = _mul(scalar)
    r = int.from_bytes(hashlib.sha512(prefix + data).digest(), "little") % _L
    encoded_r = _mul(r)
    k = int.from_bytes(hashlib.sha512(encoded_r + key + data).digest(), "little") % _L
    return encoded_r + ((r + k * scalar) % _L).to_bytes(32, "little")


def public_key(seed=SEED, key_id=KEY_ID):
    """Return a Tauri-wrapped .pub file for a disposable key."""
    raw = base64.b64encode(b"Ed" + key_id + _mul(_secret(seed)[0])).decode()
    return base64.b64encode(("untrusted comment: test key\n" + raw + "\n").encode()).decode()


def sign(data, *, seed=SEED, key_id=KEY_ID, algorithm=b"ED", comment="labupdate test"):
    """Create a Tauri signature including the global signature over its comment."""
    message = hashlib.blake2b(data, digest_size=64).digest() if algorithm == b"ED" else data
    signature = sign_ed25519(message, seed)
    raw = base64.b64encode(algorithm + key_id + signature).decode()
    global_sig = base64.b64encode(sign_ed25519(signature + comment.encode(), seed)).decode()
    envelope = f"untrusted comment: test signature\n{raw}\ntrusted comment: {comment}\n{global_sig}\n"
    return base64.b64encode(envelope.encode()).decode()
