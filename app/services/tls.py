"""
TLS for outbound calls: public roots plus any CA certificates mounted in CUSTOM_CA_DIR, plus
the certificates the user approved for the session, and the error returned when a server's
certificate can't be verified.
"""

import hashlib
import logging
import ssl
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import certifi
import httpx
from fastapi import HTTPException

from app.config import CUSTOM_CA_DIR
from app.models import CertificateApproval

logger = logging.getLogger(__name__)

TLS_VERIFY_FAILED = "tls_verify_failed"

# OpenSSL verify results (X509_V_ERR_*). These mean the chain ends at an issuer that isn't
# trusted, so an approval trusts the top certificate presented, if there's a CA above the leaf.
# Any other failure (expired, not yet valid, hostname mismatch, ...) can only be approved for
# that exact leaf and host.
_UNTRUSTED_ISSUER = {
    2,   # unable to get issuer certificate
    18,  # self-signed certificate
    19,  # self-signed certificate in certificate chain
    20,  # unable to get local issuer certificate
    21,  # unable to verify the first certificate
}
_LEAF_ADJECTIVE = {9: "not-yet-valid ", 10: "expired "}
# X509_V_FLAG_NO_CHECK_TIME, which the ssl module doesn't name
_NO_CHECK_TIME = 0x200000


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


@lru_cache(maxsize=32)
def _anchor_context(pems: tuple[str, ...]) -> ssl.SSLContext:
    """The verified context plus approved CAs as extra trust anchors."""
    ctx = build_context(Path(CUSTOM_CA_DIR))
    for pem in pems:
        ctx.load_verify_locations(cadata=pem)
    # Same reasoning as for custom CAs: decryption CAs often fail strict RFC 5280 checks.
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


@lru_cache(maxsize=32)
def _leaf_context(pems: tuple[str, ...]) -> ssl.SSLContext:
    """
    Trusts only the approved leaf certificates: each is the sole trust anchor (partial chain),
    with hostname and time checks off. Anything else the host presents fails; only the holder
    of an approved certificate's private key can complete the handshake.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.load_verify_locations(cadata="".join(pems))
    # Plain ints: VerifyFlags operators would drop the bit the enum doesn't name
    ctx.verify_flags = int(ctx.verify_flags) | int(ssl.VERIFY_X509_PARTIAL_CHAIN) | _NO_CHECK_TIME
    return ctx


def context_for(host: str, approvals: Sequence[CertificateApproval] = ()) -> ssl.SSLContext:
    """The context for a connection to host: leaf approvals for the host win over everything else."""
    leaves = tuple(sorted({a.pem for a in approvals if a.kind == "leaf" and a.host == host}))
    if leaves:
        logger.warning("Trusting only the certificate the user approved for %s this session", host)
        return _leaf_context(leaves)
    anchors = tuple(sorted({a.pem for a in approvals if a.kind == "anchor"}))
    if anchors:
        logger.warning("Trusting %d CA certificate(s) the user approved this session for %s", len(anchors), host)
        return _anchor_context(anchors)
    return verified_context()


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


def _fingerprint(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def describe_chain(parsed: list[dict], ders: list[bytes]) -> dict:
    """
    Summarize a presented chain (ssl get_info() dicts and DER, leaf first) for the user to
    judge. Every certificate carries its SHA-256 fingerprint: a CA approval trusts the top
    one, and the user should be able to compare it with what their IT team published.
    """
    leaf = parsed[0]
    return {
        "subject": _name(leaf.get("subject", ())),
        "alt_names": [v for k, v in leaf.get("subjectAltName", ()) if k == "DNS"][:10],
        "chain": [
            {
                "subject": _name(c.get("subject", ())),
                "issuer": _name(c.get("issuer", ())),
                "sha256": _fingerprint(der),
            }
            for c, der in zip(parsed, ders)
        ],
        "not_before": leaf.get("notBefore"),
        "not_after": leaf.get("notAfter"),
        "sha256": _fingerprint(ders[0]),
    }


def _unverified_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def _presented_chain(url: str) -> tuple[list[bytes], list[dict]] | None:
    """
    The chain presented for url's host (DER and parsed, leaf first). Read through httpx with
    its proxy settings, so it describes the path that was rejected. The request carries no
    credentials and its response is discarded.
    """
    try:
        async with httpx.AsyncClient(verify=_unverified_context(), timeout=5) as client:
            async with client.stream("GET", httpx.URL(url).join("/")) as response:
                ssl_object = response.extensions["network_stream"].get_extra_info("ssl_object")
                ders = ssl_object.get_unverified_chain()
                # Parsed fields are only exposed on the private Certificate objects; if that
                # changes, the dialog omits the details and offers no approval.
                parsed = [c.get_info() for c in ssl_object._sslobj.get_unverified_chain()]
        return ders, parsed
    except Exception as exc:
        logger.warning("Could not read the certificate chain for %s: %s", httpx.URL(url).host, repr(exc))
        return None


def _approval(host: str, err: ssl.SSLCertVerificationError, ders: list[bytes], parsed: list[dict]):
    """What the user may approve for this failure (see _UNTRUSTED_ISSUER), and how to describe it."""
    # An anchor needs a CA above the leaf: the top certificate must be named as the issuer of
    # the one below it (the ssl module doesn't expose basicConstraints). A server that sends
    # only its leaf, or a self-signed leaf, gets a leaf approval for this host instead of
    # having that certificate trusted for every name it covers.
    issued_below = len(ders) > 1 and parsed[-1].get("subject") == parsed[-2].get("issuer")
    if err.verify_code in _UNTRUSTED_ISSUER and issued_below:
        approval = {"kind": "anchor", "pem": ssl.DER_cert_to_PEM_cert(ders[-1])}
        return approval, f"Trust {_name(parsed[-1].get('subject', ()))} for this session"
    approval = {"kind": "leaf", "host": host, "pem": ssl.DER_cert_to_PEM_cert(ders[0])}
    adjective = _LEAF_ADJECTIVE.get(err.verify_code, "")
    return approval, f"Accept this {adjective}certificate for {host} for this session"


async def verification_failed(url: str, err: ssl.SSLCertVerificationError) -> HTTPException:
    """502 with a structured detail the frontend uses to ask the user about an approval."""
    host = httpx.URL(url).host
    presented = await _presented_chain(url)
    certificate = approval = label = None
    if presented and presented[0] and len(presented[0]) == len(presented[1]):
        ders, parsed = presented
        certificate = describe_chain(parsed, ders)
        approval, label = _approval(host, err, ders, parsed)
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
            # Echoed back by the browser in approved_certificates if the user approves it
            "approval": approval,
            "approval_label": label,
        },
    )
