"""
Environments: FedRAMP environments are never part of key auto-detection, and users see
environment names rather than internal keys.
"""

import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import API_URLS, COMMERCIAL_ENVIRONMENTS, FEDRAMP_ENVIRONMENTS, display_name
from app.main import app
from app.models import BatchQueryRequest

client = TestClient(app)

API_KEY = "a" * 32
REJECTED = httpx.Response(401, json={"status": "error", "result": "Invalid API key"})
HOSTS = {env: httpx.URL(url).host for env, url in API_URLS.items()}
COMMERCIAL_HOSTS = {HOSTS[e] for e in COMMERCIAL_ENVIRONMENTS}
FEDRAMP_HOSTS = {HOSTS[e] for e in FEDRAMP_ENVIRONMENTS}

ENDPOINTS = [
    ("/api/ips/query", {"node_type": "gw"}),
    ("/api/ips/batch", {}),
    ("/api/ips/pre-allocate", {"location": "US East"}),
]


def _recording(state, handler):
    hosts: list[str] = []

    def record(request):
        hosts.append(request.url.host)
        return handler(request)

    state["handler"] = record
    return hosts


@pytest.mark.parametrize("environment", sorted(FEDRAMP_ENVIRONMENTS))
@pytest.mark.parametrize("path,extra", ENDPOINTS)
def test_fedramp_rejection_searches_nothing(upstream, path, extra, environment):
    state, _ = upstream
    hosts = _recording(state, lambda request: REJECTED)

    resp = client.post(path, json={"api_key": API_KEY, "environment": environment, **extra})

    assert resp.status_code == 401
    assert set(hosts) == {HOSTS[environment]}
    detail = resp.json()["detail"]
    assert f"rejected by the {display_name(environment)} environment" in detail
    assert not re.search(r"\bfedramp", detail)  # the internal key never reaches the user


@pytest.mark.parametrize("path,extra", ENDPOINTS)
def test_commercial_rejection_probes_only_commercial_hosts(upstream, path, extra):
    state, _ = upstream
    hosts = _recording(state, lambda request: REJECTED)

    resp = client.post(path, json={"api_key": API_KEY, "environment": "prod1", **extra})

    assert resp.status_code == 401
    assert set(hosts) == COMMERCIAL_HOSTS
    assert "If this is a FedRAMP key, select the FedRAMP environment." in resp.json()["detail"]


def test_fedramp_key_is_not_found_from_a_commercial_environment(upstream):
    state, _ = upstream
    ok = httpx.Response(200, json={"status": "success", "result": []})
    hosts = _recording(state, lambda request: ok if request.url.host in FEDRAMP_HOSTS else REJECTED)

    resp = client.post("/api/ips/query", json={"api_key": API_KEY, "environment": "prod1", "node_type": "gw"})

    assert resp.status_code == 401
    assert not FEDRAMP_HOSTS & set(hosts)


def test_unchecked_environments_message_keeps_the_fedramp_hint(upstream):
    state, _ = upstream
    prod1 = HOSTS["prod1"]
    state["handler"] = lambda request: REJECTED if request.url.host == prod1 else httpx.Response(503, text="down")

    resp = client.post("/api/ips/query", json={"api_key": API_KEY, "environment": "prod1", "node_type": "gw"})

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "If this is a FedRAMP key, select the FedRAMP environment." in detail
    assert not re.search(r"\bfedramp", detail)


def test_fedramp_high_query_uses_its_endpoint(upstream):
    state, _ = upstream
    ok = httpx.Response(200, json={"status": "success", "result": [{"zone": "US East", "addresses": ["1.1.1.1"]}]})
    hosts = _recording(state, lambda request: ok)

    resp = client.post("/api/ips/query", json={"api_key": API_KEY, "environment": "fedramp_high", "node_type": "gw"})

    assert resp.status_code == 200
    assert resp.json()["environment"] == "fedramp_high"
    assert hosts == ["api.highprod.prismasasegov.com"]


def test_unknown_environment_rejected(upstream):
    state, _ = upstream
    hosts = _recording(state, lambda request: REJECTED)

    resp = client.post("/api/ips/batch", json={"api_key": API_KEY, "environment": "fedramp-high"})

    assert resp.status_code == 422
    assert hosts == []


def test_display_names():
    assert display_name("fedramp") == "FedRAMP Moderate"
    assert display_name("fedramp_high") == "FedRAMP High"
    assert display_name("prod1") == "prod1"


def test_validation_accepts_fedramp_high():
    req = BatchQueryRequest(api_key=API_KEY, environment="fedramp_high")
    assert req.environment == "fedramp_high"


def test_dropdown_matches_the_server():
    # The page lists every environment once, FedRAMP ones under their own group, with names.
    html = (Path(__file__).parent.parent / "web" / "index.html").read_text()
    select = re.search(r'<select class="form-select" id="environment">(.*?)</select>', html, re.S).group(1)
    groups = dict(re.findall(r'<optgroup label="([^"]+)">(.*?)</optgroup>', select, re.S))
    options = {
        label: dict(re.findall(r'<option value="([^"]+)">([^<]+)</option>', body)) for label, body in groups.items()
    }
    assert set(options) == {"Commercial", "FedRAMP"}
    assert set(options["Commercial"]) == set(COMMERCIAL_ENVIRONMENTS)
    assert set(options["FedRAMP"]) == FEDRAMP_ENVIRONMENTS
    for group in options.values():
        for key, label in group.items():
            assert label == display_name(key)
