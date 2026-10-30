"""
Request validation. Rejected requests return 422 before any upstream call; accepted
payloads are checked against the models directly so no test reaches a Prisma Access API.
"""

import pytest
import trustme
from fastapi.testclient import TestClient

from app.main import app
from app.models import BatchQueryRequest, IPQueryRequest, PreAllocateRequest, TokenRequest

client = TestClient(app)

API_KEY = "a1B2c3D4e5F6g7H8i9J0-_+=/."

# The payloads web/app.js sends, with and without certificates approved for the session.
WEB_PAGE_REQUESTS = [
    ("/api/ips/query", IPQueryRequest, {"api_key": API_KEY, "environment": "prod1", "node_type": "gw"}),
    ("/api/ips/batch", BatchQueryRequest, {"api_key": API_KEY, "environment": "prod1"}),
    ("/api/ips/pre-allocate", PreAllocateRequest,
     {"api_key": API_KEY, "environment": "prod1", "location": "US East (Virginia)"}),
]

CA_PEM = trustme.CA().cert_pem.bytes().decode()
ANCHOR = {"kind": "anchor", "pem": CA_PEM}
LEAF = {"kind": "leaf", "host": "api.example.com", "pem": CA_PEM}

TOKEN_REQUEST = {
    "client_id": "svc@1234567890.iam.panserviceaccount.com",
    "client_secret": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    "tsg_id": "1234567890",
}


@pytest.mark.parametrize("approvals", [[], [ANCHOR, LEAF]])
@pytest.mark.parametrize("path,model,body", WEB_PAGE_REQUESTS)
def test_web_page_requests_accepted(path, model, body, approvals):
    if approvals:
        body = {**body, "approved_certificates": approvals}
    model.model_validate(body)


def test_token_request_accepted():
    req = TokenRequest.model_validate({**TOKEN_REQUEST, "tsg_id": " 1234567890 "})
    assert req.tsg_id == "1234567890"


@pytest.mark.parametrize("path,body", [
    *[(path, body) for path, _, body in WEB_PAGE_REQUESTS],
    ("/api/auth/token", TOKEN_REQUEST),
])
def test_unknown_field_rejected(path, body):
    resp = client.post(path, json={**body, "unexpected": "x"})
    assert resp.status_code == 422


@pytest.mark.parametrize("path,body", [
    *[(path, {**body, "api_key": "a" * 513}) for path, _, body in WEB_PAGE_REQUESTS],
    ("/api/ips/pre-allocate", {**WEB_PAGE_REQUESTS[2][2], "location": "a" * 101}),
    ("/api/auth/token", {**TOKEN_REQUEST, "client_id": "a" * 257}),
    ("/api/auth/token", {**TOKEN_REQUEST, "client_secret": "a" * 257}),
    ("/api/auth/token", {**TOKEN_REQUEST, "tsg_id": "1" * 21}),
])
def test_over_long_value_rejected(path, body):
    resp = client.post(path, json=body)
    assert resp.status_code == 422


@pytest.mark.parametrize("field,value", [
    ("tsg_id", "12345abc"),
    ("tsg_id", ""),
    ("client_id", ""),
    ("client_secret", "   "),
])
def test_invalid_token_request_rejected(field, value):
    resp = client.post("/api/auth/token", json={**TOKEN_REQUEST, field: value})
    assert resp.status_code == 422


def test_longest_api_key_accepted():
    BatchQueryRequest.model_validate({"api_key": "a" * 512, "environment": "prod1"})


def test_skip_tls_verify_is_gone():
    body = {**WEB_PAGE_REQUESTS[1][2], "skip_tls_verify": True}
    assert client.post("/api/ips/batch", json=body).status_code == 422


@pytest.mark.parametrize("approval", [
    {"kind": "anchor", "pem": "not a certificate"},
    {"kind": "anchor", "pem": CA_PEM + CA_PEM},  # one approval trusts one certificate
    {"kind": "anchor", "pem": CA_PEM.replace("M", "!", 3)},
    {"kind": "anchor", "pem": CA_PEM, "host": "api.example.com"},
    {"kind": "leaf", "pem": CA_PEM},
    {"kind": "leaf", "host": "api.example.com/x", "pem": CA_PEM},
    {"kind": "skip", "pem": CA_PEM},
])
def test_invalid_approval_rejected(approval):
    body = {**WEB_PAGE_REQUESTS[1][2], "approved_certificates": [approval]}
    assert client.post("/api/ips/batch", json=body).status_code == 422


def test_too_many_approvals_rejected():
    body = {**WEB_PAGE_REQUESTS[1][2], "approved_certificates": [ANCHOR] * 21}
    assert client.post("/api/ips/batch", json=body).status_code == 422


def test_approval_pem_is_canonicalized():
    req = BatchQueryRequest.model_validate(
        {**WEB_PAGE_REQUESTS[1][2], "approved_certificates": [{**LEAF, "host": "API.Example.com", "pem": "  " + CA_PEM}]}
    )
    assert req.approved_certificates[0].pem == CA_PEM
    assert req.approved_certificates[0].host == "api.example.com"


def test_rejected_values_not_echoed():
    secret = "s3cr3t-" + "x" * 300
    resp = client.post("/api/auth/token", json={**TOKEN_REQUEST, "client_secret": secret})
    assert resp.status_code == 422
    assert secret not in resp.text
    assert resp.json()["detail"][0].keys() == {"loc", "msg"}


@pytest.mark.parametrize("token", ["a" * 8193, "a" * 8192 + "=" * 10, "abc def", "abc<script>", ""])
def test_invalid_bearer_token_rejected(token):
    resp = client.get("/api/locations", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_jwt_bearer_token_accepted():
    from app.routers.locations import _VALID_TOKEN
    assert _VALID_TOKEN.match("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl-_~+/==")
