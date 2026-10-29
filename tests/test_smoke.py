"""
Smoke tests that gate the container build. No test reaches a Prisma Access API.
"""

import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_version_matches_pyproject():
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    assert app.version == pyproject["project"]["version"]


def test_index_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_invalid_request_rejected_before_upstream_call():
    resp = client.post(
        "/api/ips/query",
        json={"api_key": "short", "environment": "prod1", "node_type": "gw"},
    )
    assert resp.status_code == 422


def test_api_docs_and_schema_are_not_published():
    for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
        assert client.get(path).status_code == 404
