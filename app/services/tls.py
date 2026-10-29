"""
TLS for outbound calls: public roots plus any CA certificates mounted in CUSTOM_CA_DIR,
and the error returned when a server's certificate can't be verified.
"""

import asyncio
import hashlib
import logging
import socket
import ssl
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import certifi
from fastapi import HTTPException

from app.config import CUSTOM_CA_DIR

logger = logging.getLogger(__name__)

TLS_VERIFY_FAILED = "tls_verify_failed"


def build_context(ca_dir: Path) -> ssl.SSLContext:
    """Public roots plus every *.pem / *.crt in ca_dir. Unreadable files are skipped and logged."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    loaded = False
    if ca_dir.is_dir():
        for path in sorted(ca_dir.iterdir()):
            if path.suffix.lower() not in (".pem", ".crt"):
                continue
            try:
                ctx.load_verify_locations(cafile=str(path))
                loaded = True
                logger.info("Trusting additional CA certificates from %s", path)
            except (ssl.SSLError, OSError) as exc:
                logger.error("Skipping %s: not a readable PEM certificate (%s)", path, exc)
    if loaded:
        # Corporate decryption CAs often miss RFC 5280 details (e.g. Authority Key Identifier)
        # that strict mode rejects; chain and hostname verification still apply.
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


@lru_cache(maxsize=1)
def verified_context() -> ssl.SSLContext:
    return build_context(Path(CUSTOM_CA_DIR))


def verify_setting(skip_tls_verify: bool) -> ssl.SSLContext | bool:
    return False if skip_tls_verify else verified_context()


def cert_verification_error(exc: BaseException) -> ssl.SSLCertVerificationError | None:
    """httpx wraps certificate failures in ConnectError; find the original in the chain."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLCertVerificationError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _name(rdns: tuple) -> str:
    fields = dict(item for rdn in rdns for item in rdn)
    cn, org = fields.get("commonName"), fields.get("organizationName")
    if cn and org and org not in cn:
        return f"{cn} ({org})"
    return cn or org or ", ".join(f"{k}={v}" for k, v in fields.items())


def describe_chain(parsed: list[dict], leaf_der: bytes) -> dict:
    """Summarize a presented chain (ssl get_info() dicts, leaf first) for the user to judge."""
    leaf = parsed[0]
    digest = hashlib.sha256(leaf_der).hexdigest().upper()
    return {
        "subject": _name(leaf.get("subject", ())),
        "alt_names": [v for k, v in leaf.get("subjectAltName", ()) if k == "DNS"][:10],
        "chain": [
            {"subject": _name(c.get("subject", ())), "issuer": _name(c.get("issuer", ()))}
            for c in parsed
        ],
        "not_before": leaf.get("notBefore"),
        "not_after": leaf.get("notAfter"),
        "sha256": ":".join(digest[i:i + 2] for i in range(0, len(digest), 2)),
    }


def _presented_certificate(host: str, port: int) -> dict | None:
    """The chain host presents, read with a bare handshake: no request data is sent."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                leaf_der = tls.get_unverified_chain()[0]
                # Parsed fields are only exposed on the private Certificate objects;
                # if that changes, the dialog simply omits the certificate details.
                parsed = [c.get_info() for c in tls._sslobj.get_unverified_chain()]
        return describe_chain(parsed, leaf_der)
    except Exception:
        return None


async def verification_failed(url: str, err: ssl.SSLCertVerificationError) -> HTTPException:
    """502 with a structured detail the frontend uses to offer an explicit opt-out."""
    parts = urlsplit(url)
    host = parts.hostname or url
    certificate = await asyncio.to_thread(_presented_certificate, host, parts.port or 443)
    reason = err.verify_message or str(err)
    top = certificate["chain"][-1]["issuer"] if certificate else None
    logger.error("Certificate verification failed for %s: %s (chain ends at: %s)", host, reason, top)
    return HTTPException(
        status_code=502,
        detail={
            "code": TLS_VERIFY_FAILED,
            "message": f"The certificate presented for {host} could not be verified: {reason}.",
            "host": host,
            "reason": reason,
            "certificate": certificate,
        },
    )
