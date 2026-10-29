"""
Request validation. Rejected requests return 422 before any upstream call; accepted
payloads are checked against the models directly so no test reaches a Prisma Access API.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import BatchQueryRequest, IPQueryRequest, PreAllocateRequest, TokenRequest

client = TestClient(app)

API_KEY = "a1B2c3D4e5F6g7H8i9J0-_+=/."

# The payloads web/app.js sends, with and without the session TLS opt-out.
WEB_PAGE_REQUESTS = [
    ("/api/ips/query", IPQueryRequest, {"api_key": API_KEY, "environment": "prod1", "node_type": "gw"}),
    ("/api/ips/batch", BatchQueryRequest, {"api_key": API_KEY, "environment": "prod1"}),
    ("/api/ips/pre-allocate", PreAllocateRequest,
     {"api_key": API_KEY, "environment": "prod1", "location": "US East (Virginia)"}),
]

TOKEN_REQUEST = {
    "client_id": "svc@1234567890.iam.panserviceaccount.com",
    "client_secret": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    "tsg_id": "1234567890",
}


@pytest.mark.parametrize("skip_tls", [False, True])
@pytest.mark.parametrize("path,model,body", WEB_PAGE_REQUESTS)
def test_web_page_requests_accepted(path, model, body, skip_tls):
    if skip_tls:
        body = {**body, "skip_tls_verify": True}
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
