"""
Smoke tests that gate the container build. No test reaches a Prisma Access API.
"""

import logging
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _pyproject_version() -> str:
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    return pyproject["project"]["version"]


def test_health_reports_version():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": _pyproject_version()}


def test_version_matches_pyproject():
    assert app.version == _pyproject_version()


def test_startup_logs_version(caplog):
    caplog.set_level(logging.INFO, logger="app.main")
    with TestClient(app):
        pass
    assert f"Prisma Access Egress IP Utility {_pyproject_version()} starting" in caplog.messages


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
