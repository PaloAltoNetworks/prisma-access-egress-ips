"""
Certificate verification: failures surface as a structured error, nothing retries on its
own, and approved certificates reach the HTTP client only when the browser sends them.
"""

import hashlib
import shutil
import ssl

import certifi
import httpx
import pytest
import trustme
from fastapi.testclient import TestClient

from app.main import app
from app.services import prisma_client, tls

client = TestClient(app)

def _first_root_der(index: int = 0) -> bytes:
    """The index-th certificate in certifi's bundle, as DER."""
    bundle = open(certifi.where()).read()
    begin, end = "-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"
    start = -1
    for _ in range(index + 1):
        start = bundle.index(begin, start + 1)
    return ssl.PEM_cert_to_DER_cert(bundle[start: bundle.index(end, start) + len(end)])


QUERY = {"api_key": "a" * 32, "environment": "prod1", "node_type": "gw"}


def _cert_failure(request: httpx.Request) -> httpx.Response:
    err = ssl.SSLCertVerificationError(1, "certificate verify failed")
    err.verify_code, err.verify_message = 19, "self-signed certificate in certificate chain"
    raise httpx.ConnectError("certificate verify failed", request=request) from err


def test_cert_failure_returns_structured_error_without_retry(upstream):
    state, calls = upstream
    state["handler"] = _cert_failure

    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail["code"] == tls.TLS_VERIFY_FAILED
    assert detail["host"] == "api.prod.datapath.prismaaccess.com"
    assert detail["reason"] == "self-signed certificate in certificate chain"
    assert calls == [[]]


def test_batch_probe_cert_failure_is_not_treated_as_unreachable(upstream):
    state, calls = upstream
    state["handler"] = _cert_failure

    resp = client.post("/api/ips/batch", json={"api_key": "a" * 32, "environment": "prod1"})

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == tls.TLS_VERIFY_FAILED
    assert calls == [[]]


def test_approvals_are_passed_through_per_request(upstream):
    _, calls = upstream
    approval = {"kind": "anchor", "pem": trustme.CA().cert_pem.bytes().decode()}

    assert client.post("/api/ips/query", json={**QUERY, "approved_certificates": [approval]}).status_code == 200
    assert client.post("/api/ips/query", json=QUERY).status_code == 200

    assert [[a.model_dump() for a in c] for c in calls] == [[approval], []]


def test_other_connect_errors_are_plain_502(upstream):
    state, _ = upstream

    def refused(request):
        raise httpx.ConnectError("connection refused", request=request)

    state["handler"] = refused
    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 502
    assert isinstance(resp.json()["detail"], str)


def test_no_approvals_uses_the_verified_context():
    assert tls.context_for("api.example.com") is tls.verified_context()


def test_custom_ca_dir_adds_certificates_and_skips_bad_files(tmp_path, monkeypatch):
    # Shrink the public roots to one certificate so additions from the directory are visible.
    bundle_path = certifi.where()
    bundle = open(bundle_path).read()
    end = "-----END CERTIFICATE-----"
    one_root = tmp_path / "one-root.pem"
    one_root.write_text(bundle[: bundle.index(end) + len(end)] + "\n")
    monkeypatch.setattr(tls.certifi, "where", lambda: str(one_root))

    ca_dir = tmp_path / "certs"
    ca_dir.mkdir()
    default = tls.build_context(ca_dir)
    assert default.cert_store_stats()["x509_ca"] == 1
    assert default.verify_flags & ssl.VERIFY_X509_STRICT

    shutil.copy(bundle_path, ca_dir / "corp.pem")
    (ca_dir / "broken.crt").write_text("not a certificate")
    (ca_dir / "notes.txt").write_text("ignored")

    ctx = tls.build_context(ca_dir)

    assert ctx.cert_store_stats()["x509_ca"] > 1
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname
    assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT


def test_describe_chain_summarizes_every_certificate():
    parsed = [
        {
            "subject": ((("commonName", "api.prod.datapath.prismaaccess.com"),),),
            "issuer": ((("commonName", "Forward Trust CA"),), (("organizationName", "Example Corp"),)),
            "subjectAltName": (("DNS", "api.prod.datapath.prismaaccess.com"), ("IP Address", "10.0.0.1")),
            "notBefore": "Jan  1 00:00:00 2026 GMT",
            "notAfter": "Jan  1 00:00:00 2027 GMT",
        },
        {
            "subject": ((("commonName", "Forward Trust CA"),),),
            "issuer": ((("commonName", "Example Corp Root CA"),),),
        },
    ]
    leaf_der, ca_der = _first_root_der(), _first_root_der(1)

    cert = tls.describe_chain(parsed, [leaf_der, ca_der])

    assert cert["subject"] == "api.prod.datapath.prismaaccess.com"
    assert cert["alt_names"] == ["api.prod.datapath.prismaaccess.com"]
    assert [link["issuer"] for link in cert["chain"]] == [
        "Forward Trust CA (Example Corp)",
        "Example Corp Root CA",
    ]
    assert cert["not_after"] == "Jan  1 00:00:00 2027 GMT"
    assert cert["sha256"].replace(":", "") == hashlib.sha256(leaf_der).hexdigest().upper()
    # Each certificate carries its own fingerprint, so a CA approval can show the CA's
    assert [link["sha256"].replace(":", "") for link in cert["chain"]] == [
        hashlib.sha256(der).hexdigest().upper() for der in (leaf_der, ca_der)
    ]
    assert cert["chain"][0]["sha256"] != cert["chain"][1]["sha256"]


def test_cert_failure_on_one_environment_does_not_hide_a_match(upstream):
    state, _ = upstream

    def handler(request):
        host = request.url.host
        if host == "api.lab.datapath.prismaaccess.com":
            return _cert_failure(request)
        if host == "api.prod4.datapath.prismaaccess.com":
            return httpx.Response(200, json={"status": "success", "result": []})
        return httpx.Response(401, json={"status": "error", "result": "Invalid API key"})

    state["handler"] = handler
    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 200
    body = resp.json()
    assert body["environment"] == "prod4"
    assert [f["host"] for f in body["tls_failures"]] == ["api.lab.datapath.prismaaccess.com"]


def test_rejected_key_lists_environments_that_could_not_be_checked(upstream):
    state, _ = upstream

    def handler(request):
        if request.url.host == "api.lab.datapath.prismaaccess.com":
            return _cert_failure(request)
        return httpx.Response(401, json={"status": "error", "result": "Invalid API key"})

    state["handler"] = handler
    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["code"] == "key_rejected"
    assert [f["host"] for f in detail["tls_failures"]] == ["api.lab.datapath.prismaaccess.com"]


def test_cert_failure_everywhere_opens_the_dialog(upstream):
    state, _ = upstream

    def handler(request):
        if request.url.host == "api.prod.datapath.prismaaccess.com":
            return httpx.Response(401, json={"status": "error", "result": "Invalid API key"})
        return _cert_failure(request)

    state["handler"] = handler
    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == tls.TLS_VERIFY_FAILED


def test_plain_rejection_keeps_string_detail(upstream):
    state, _ = upstream
    state["handler"] = lambda request: httpx.Response(401, json={"status": "error", "result": "Invalid API key"})

    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 401
    assert resp.json()["detail"].startswith("API key was rejected by every commercial environment.")
