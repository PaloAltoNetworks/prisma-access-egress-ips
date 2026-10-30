"""
IP processing and batch behaviour: exclusive lists, composites, environment probing, and
failures that must surface as errors rather than as shorter IP lists.
"""

import json

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import NODE_PAYLOADS
from app.main import app
from app.models import ZoneData
from app.services import ip_processor

client = TestClient(app)

API_KEY = "a" * 32
BATCH = {"api_key": API_KEY, "environment": "prod1"}
QUERY = {**BATCH, "node_type": "gw"}
PROD1 = "api.prod.datapath.prismaaccess.com"
_TYPE_BY_PAYLOAD = {json.dumps(p, sort_keys=True): nt for nt, p in NODE_PAYLOADS.items()}


def node_type(request: httpx.Request) -> str:
    return _TYPE_BY_PAYLOAD.get(json.dumps(json.loads(request.content), sort_keys=True), "pre_allocate")


def ips(*addresses: str, zone: str = "US East") -> httpx.Response:
    return httpx.Response(200, json={"status": "success", "result": [{"zone": zone, "addresses": list(addresses)}]})


NO_IPS = httpx.Response(400, json={"status": "error", "result": "No IP found for the given service type"})
REJECTED = httpx.Response(401, json={"status": "error", "result": "Invalid API key"})


# --- Set operations ---

def test_subtract_ips_drops_emptied_zones():
    source = [ZoneData(zone="A", addresses=["1", "2"]), ZoneData(zone="B", addresses=["3"])]
    assert ip_processor.subtract_ips(source, [ZoneData(zone="X", addresses=["2", "3"])]) == [
        ZoneData(zone="A", addresses=["1"]),
    ]


def test_merge_zone_data_dedupes_and_sorts():
    merged = ip_processor.merge_zone_data([
        [ZoneData(zone="B", addresses=["2", "1"])],
        [ZoneData(zone="A", addresses=["9"]), ZoneData(zone="B", addresses=["1"])],
    ])
    assert merged == [ZoneData(zone="A", addresses=["9"]), ZoneData(zone="B", addresses=["1", "2"])]


def test_build_composite_backfills_ips_only_in_the_direct_response():
    fetched = {"gw": [ZoneData(zone="A", addresses=["1"])]}
    direct = [ZoneData(zone="A", addresses=["1"]), ZoneData(zone="C", addresses=["7"])]

    composite = ip_processor.build_composite(["gw"], fetched, [], [], [], direct)

    assert composite == [ZoneData(zone="A", addresses=["1"]), ZoneData(zone="C", addresses=["7"])]


# --- Response parsing ---

@pytest.mark.parametrize("body", [
    ["not", "an", "object"],
    {"status": "error"},
    {"result": None},
    {"result": "nope"},
    {"result": ["x"]},
    {"result": [{"zone": "A", "addresses": [1, 2]}]},
    {"result": [{"zone": "A", "addresses": "1.2.3.4"}]},
    {"result": [{"zone": "A", "addresses": ""}]},
])
def test_malformed_response_is_an_error_not_a_shorter_list(body):
    with pytest.raises(HTTPException) as exc:
        ip_processor.process_api_response(body, "prod1", "gw")
    assert exc.value.status_code == 502


def test_missing_addresses_mean_none():
    body = {"result": [{"zone": "A", "addresses": None}, {"zone": "B"}]}
    assert ip_processor.process_api_response(body, "prod1", "gw") == [
        ZoneData(zone="A", addresses=[]), ZoneData(zone="B", addresses=[]),
    ]


def test_rn_site_metadata_skips_malformed_entries():
    body = {"result": [
        {"zone": "B", "address_details": "junk"},
        {"zone": "A", "address_details": [
            "junk",
            {"address": "1.1.1.1", "addressType": "service_ip", "node_fqdn": "site1.rn.example.com",
             "node_name": ["branch-1", "branch-2"]},
        ]},
    ]}
    details, suffix = ip_processor.extract_rn_site_metadata(body, "prod1", "rn")
    assert [(d.address, d.node_name, d.site_count) for d in details] == [("1.1.1.1", "site1", 2)]
    assert suffix == ".rn.example.com"


# --- Single queries ---

def test_no_ips_reply_returns_an_empty_list(upstream):
    state, _ = upstream
    state["handler"] = lambda request: NO_IPS
    resp = client.post("/api/ips/query", json=QUERY)
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_non_json_success_is_a_502(upstream):
    state, _ = upstream
    state["handler"] = lambda request: httpx.Response(200, text="<html>Blocked by proxy</html>")
    resp = client.post("/api/ips/query", json=QUERY)
    assert resp.status_code == 502
    assert "isn't JSON" in resp.json()["detail"]


def test_timeout_is_a_504_with_a_message(upstream):
    state, _ = upstream

    def timeout(request):
        raise httpx.ReadTimeout("", request=request)

    state["handler"] = timeout
    resp = client.post("/api/ips/query", json=QUERY)
    assert resp.status_code == 504
    assert resp.json()["detail"] == "Timed out reaching Prisma Access API."


def test_upstream_error_body_is_truncated(upstream):
    state, _ = upstream
    state["handler"] = lambda request: httpx.Response(500, text="x" * 5000)
    detail = client.post("/api/ips/query", json=QUERY).json()["detail"]
    assert len(detail) < 600


def test_pre_allocate_sends_the_location(upstream):
    state, _ = upstream
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return ips("5.5.5.5")

    state["handler"] = handler
    resp = client.post("/api/ips/pre-allocate", json={**BATCH, "location": "US East"})

    assert resp.status_code == 200
    assert resp.json()["data"] == [{"zone": "US East", "addresses": ["5.5.5.5"]}]
    assert seen == [{"actionType": "pre_allocate", "serviceType": "gp_gateway", "location": ["US East"]}]


# --- Environment probing ---

def test_probe_ignores_errors_from_other_environments(upstream):
    state, _ = upstream

    def handler(request):
        host = request.url.host
        if host == "api.fed.prismaaccess.com":
            return httpx.Response(503, text="maintenance")
        if host == "api.prod4.datapath.prismaaccess.com":
            return ips("4.4.4.4")
        return REJECTED

    state["handler"] = handler
    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 200
    assert resp.json()["environment"] == "prod4"


def test_probe_counts_the_no_ips_reply_as_accepted(upstream):
    state, _ = upstream
    state["handler"] = lambda request: NO_IPS if request.url.host == "api.lab.datapath.prismaaccess.com" else REJECTED
    resp = client.post("/api/ips/query", json=QUERY)
    assert resp.status_code == 200
    assert resp.json()["environment"] == "lab"


# --- Batch ---

def _batch_handler(overrides=None):
    overrides = overrides or {}
    data = {"swg": ips("1.1.1.1", "9.9.9.9"), "swg_lb": ips("9.9.9.9"), "gw": ips("2.2.2.2")}

    def handler(request):
        nt = node_type(request)
        if nt in overrides:
            return overrides[nt](request) if callable(overrides[nt]) else overrides[nt]
        return data.get(nt, NO_IPS)

    return handler


def test_batch_lists_swg_without_load_balancer_ips(upstream):
    state, _ = upstream
    state["handler"] = _batch_handler()

    resp = client.post("/api/ips/batch", json=BATCH)

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results["swg"] == [{"zone": "US East", "addresses": ["1.1.1.1"]}]
    assert results["swg_lb"] == [{"zone": "US East", "addresses": ["9.9.9.9"]}]


@pytest.mark.parametrize("failure", [
    httpx.Response(429, json={"status": "error", "result": "Too many requests"}),
    httpx.Response(500, text="server error"),
])
def test_batch_fails_when_any_node_type_fails(upstream, failure):
    state, _ = upstream
    state["handler"] = _batch_handler({"swg_lb": failure})

    resp = client.post("/api/ips/batch", json=BATCH)

    assert resp.status_code == 502
    assert resp.json()["detail"].startswith("Could not fetch swg_lb, so the results would be incomplete.")


def test_batch_names_every_failed_type(upstream):
    state, _ = upstream
    error = httpx.Response(500, text="server error")
    state["handler"] = _batch_handler({"rn_all": error, "gw_all": error})

    detail = client.post("/api/ips/batch", json=BATCH).json()["detail"]

    assert "gw_all" in detail and "rn_all" in detail


def test_batch_certificate_failure_keeps_the_structured_detail(upstream):
    import ssl

    state, _ = upstream

    def cert_failure(request):
        err = ssl.SSLCertVerificationError(1, "certificate verify failed")
        err.verify_code, err.verify_message = 19, "self-signed certificate in certificate chain"
        raise httpx.ConnectError("certificate verify failed", request=request) from err

    state["handler"] = _batch_handler({"pt": cert_failure})
    resp = client.post("/api/ips/batch", json=BATCH)

    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "tls_verify_failed"


def test_batch_does_not_switch_environment_on_a_server_error(upstream):
    state, _ = upstream
    hosts = set()

    def handler(request):
        hosts.add(request.url.host)
        return httpx.Response(503, text="maintenance") if request.url.host == PROD1 else ips("8.8.8.8")

    state["handler"] = handler
    resp = client.post("/api/ips/batch", json=BATCH)

    assert resp.status_code == 502
    assert hosts == {PROD1}


def test_rejection_with_unchecked_environments_is_not_a_plain_rejection(upstream):
    state, _ = upstream
    state["handler"] = lambda request: REJECTED if request.url.host == PROD1 else httpx.Response(503, text="down")

    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert detail.startswith("API key was rejected by every environment that could be checked.")
    assert "fedramp" in detail and "prod8" in detail


# --- Retry ---

def test_one_retry_on_a_rate_limit(upstream):
    state, _ = upstream
    replies = [httpx.Response(429, headers={"Retry-After": "0"}), ips("3.3.3.3")]
    state["handler"] = lambda request: replies.pop(0)

    resp = client.post("/api/ips/query", json=QUERY)

    assert resp.status_code == 200
    assert resp.json()["data"] == [{"zone": "US East", "addresses": ["3.3.3.3"]}]


def test_only_one_retry(upstream):
    state, _ = upstream
    count = []

    def handler(request):
        count.append(1)
        return httpx.Response(503, text="down")

    state["handler"] = handler
    assert client.post("/api/ips/query", json=QUERY).status_code == 502
    assert len(count) == 2


def test_retry_delay_is_bounded():
    from app.services.prisma_client import _retry_delay
    assert _retry_delay(httpx.Response(429, headers={"Retry-After": "3600"})) == 5.0
    assert _retry_delay(httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})) == 1.0


# --- Batch: probing and the remaining failure paths ---

def test_batch_proceeds_when_the_probe_is_inconclusive(upstream):
    state, _ = upstream
    hosts, probed = set(), []

    def handler(request):
        hosts.add(request.url.host)
        if not probed:
            probed.append(1)
            return httpx.Response(500, text="probe hiccup")
        return _batch_handler()(request)

    state["handler"] = handler
    resp = client.post("/api/ips/batch", json=BATCH)

    assert resp.status_code == 200
    assert resp.json()["environment"] == "prod1"
    assert hosts == {PROD1}


def test_batch_switches_environment_when_the_key_is_rejected(upstream):
    state, _ = upstream
    state["handler"] = lambda request: (
        _batch_handler()(request) if request.url.host == "api.prod6.datapath.prismaaccess.com" else REJECTED
    )
    resp = client.post("/api/ips/batch", json=BATCH)
    assert resp.status_code == 200
    assert resp.json()["environment"] == "prod6"


def test_batch_fails_when_a_composite_fetch_fails(upstream):
    state, _ = upstream
    state["handler"] = _batch_handler({"all": httpx.Response(500, text="boom")})
    resp = client.post("/api/ips/batch", json=BATCH)
    assert resp.status_code == 502
    assert resp.json()["detail"].startswith("Could not fetch all, so the results would be incomplete.")


def test_batch_of_timeouts_is_a_504(upstream):
    state, _ = upstream

    def timeout(request):
        raise httpx.ReadTimeout("", request=request)

    state["handler"] = _batch_handler({"pt": timeout, "rbi": timeout})
    resp = client.post("/api/ips/batch", json=BATCH)
    assert resp.status_code == 504
    assert "pt: Timed out reaching Prisma Access API." in resp.json()["detail"]


def test_unexpected_error_in_a_batch_is_not_swallowed(upstream, monkeypatch):
    state, _ = upstream
    state["handler"] = _batch_handler()
    real = ip_processor.process_api_response

    def broken(api_data, environment, node_type):
        if node_type == "pt":
            raise RuntimeError("bug")
        return real(api_data, environment, node_type)

    monkeypatch.setattr(ip_processor, "process_api_response", broken)
    resp = TestClient(app, raise_server_exceptions=False).post("/api/ips/batch", json=BATCH)
    assert resp.status_code == 500
