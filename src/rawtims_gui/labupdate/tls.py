"""Cached verified HTTPS using operating-system or bundled trust roots."""

from functools import cache
import os
from pathlib import Path
import ssl
import urllib.error
import urllib.request


@cache
def _trust():
    try:
        import truststore
    except ImportError:
        truststore = None
    source = "system"
    bundle = None
    if truststore is not None:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        source = "truststore"
    else:
        try:
            import certifi
        except ImportError:
            certifi = None
        if certifi is not None:
            bundle = certifi.where()
            context = ssl.create_default_context(cafile=bundle)
            context.load_default_certs()
            source = "certifi+system"
        else:
            context = ssl.create_default_context()
    extra = {}
    for name, argument, predicate in (("SSL_CERT_FILE", "cafile", Path.is_file),
                                      ("SSL_CERT_DIR", "capath", Path.is_dir)):
        value = os.environ.get(name)
        if value and predicate(Path(value)):
            extra[argument] = value
    if extra:
        context.load_verify_locations(**extra)
    return context, {"source": source, "cafile": bundle, "environment": extra}


def https_context() -> ssl.SSLContext:
    """Return the shared verifying TLS context."""
    return _trust()[0]


@cache
def _opener():
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=https_context()))


def urlopen(request, *, timeout):
    """Open a request with a socket stall timeout, without a transfer deadline."""
    return _opener().open(request, timeout=timeout)


def reset_cache() -> None:
    """Discard cached roots and connections after trust settings change."""
    _opener.cache_clear()
    _trust.cache_clear()


def describe() -> dict:
    """Describe the selected trust source and accepted environment overrides."""
    info = _trust()[1]
    return {**info, "environment": dict(info["environment"])}


def is_certificate_error(exc) -> bool:
    """Recognize direct, urllib-wrapped and textual certificate failures."""
    if isinstance(exc, ssl.SSLCertVerificationError):
        return True
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, ssl.SSLCertVerificationError):
        return True
    return any(s in str(exc).lower() for s in ("certificate verify failed", "certificate_verify_failed"))
