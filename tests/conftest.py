"""
Shared fixtures. No test reaches a Prisma Access API.
"""

import httpx
import pytest

from app.services import prisma_client, tls


@pytest.fixture
def upstream(monkeypatch):
    """Route outbound calls to a handler and record the approvals each call was given."""
    calls: list[list] = []
    state = {"handler": lambda request: httpx.Response(200, json={"status": "success", "result": []})}

    def fake_client(url: str, approvals, timeout: float = 30) -> httpx.AsyncClient:
        calls.append(list(approvals))
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: state["handler"](r)))

    async def no_certificate_lookup(url: str) -> None:
        return None

    monkeypatch.setattr(prisma_client, "_client", fake_client)
    monkeypatch.setattr(prisma_client, "MIN_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(tls, "_presented_chain", no_certificate_lookup)
    return state, calls
