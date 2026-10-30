"""
Response headers: caching per path class, and the security headers on every response.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/static/style.css"])
def test_page_and_assets_revalidate(path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("method,path,body", [
    ("get", "/health", None),
    ("post", "/api/ips/query", {"api_key": "short"}),  # rejected with 422, still not stored
])
def test_api_and_health_are_not_stored(method, path, body):
    resp = client.request(method.upper(), path, json=body)
    assert resp.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/", "/static/app.js", "/health", "/does-not-exist"])
def test_security_headers_on_every_response(path):
    headers = client.get(path).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    csp = headers["content-security-policy"]
    for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "frame-ancestors 'none'",
                      "object-src 'none'"):
        assert directive in csp
    assert "unsafe-inline" not in csp


def test_unhandled_error_still_gets_the_headers(monkeypatch):
    from app.routers import ips

    async def broken(*args, **kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(ips, "probe_environment", broken)
    resp = TestClient(app, raise_server_exceptions=False).post(
        "/api/ips/batch", json={"api_key": "a" * 32, "environment": "prod1"}
    )
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal Server Error"}
    assert resp.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
