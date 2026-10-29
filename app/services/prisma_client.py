"""
Async HTTP client for the Prisma Access egress IP API, SASE locations API, and OAuth.

TLS is always verified (public roots plus any mounted custom CA). A certificate failure is
returned to the caller as a structured error; retrying without verification happens only
when the user explicitly sets skip_tls_verify on a request.
"""

import asyncio
import logging
import time
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from app.config import (
    API_TIMEOUT_SECONDS,
    API_URLS,
    ENVIRONMENTS,
    LOCATIONS_API_URL,
    MIN_REQUEST_INTERVAL,
    NODE_PAYLOADS,
    OAUTH_TOKEN_URL,
)
from app.services.tls import TLS_VERIFY_FAILED, cert_verification_error, verification_failed, verify_setting

logger = logging.getLogger(__name__)

# --- Rate limiting ---
# asyncio.Lock + timestamp replicates the CLI's threading.Lock approach, async-safely.
_rate_limit_lock = asyncio.Lock()
_last_request_time: float = 0.0


async def _enforce_rate_limit() -> None:
    global _last_request_time
    async with _rate_limit_lock:
        now = time.monotonic()
        wait = MIN_REQUEST_INTERVAL - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


def _client(skip_tls_verify: bool, timeout: float = API_TIMEOUT_SECONDS) -> httpx.AsyncClient:
    """Verified TLS unless the user explicitly opted out for this request."""
    return httpx.AsyncClient(verify=verify_setting(skip_tls_verify), timeout=timeout)


def _note_unverified(url: str, skip_tls_verify: bool) -> None:
    if skip_tls_verify:
        logger.warning("Certificate verification skipped at the user's request for %s", httpx.URL(url).host)


async def _request_error(url: str, exc: httpx.RequestError, what: str) -> HTTPException:
    """Map a transport failure; certificate failures get the structured opt-out error."""
    cert_err = cert_verification_error(exc)
    if cert_err is not None:
        return await verification_failed(url, cert_err)
    logger.error("Request error reaching %s: %s", what, exc)
    return HTTPException(status_code=502, detail=f"Could not reach {what}: {exc}")


# --- Egress IP API ---

async def fetch_prisma_ips(
    environment: str,
    node_type: str,
    api_key: str,
    override_payload: Optional[dict[str, Any]] = None,
    skip_tls_verify: bool = False,
) -> Optional[dict[str, Any]]:
    """
    POST to the Prisma Access egress IP API and return the raw JSON response.

    Returns None when the API signals no IPs exist for the requested service type.
    Raises HTTPException for all other errors.
    """
    url = API_URLS[environment]
    payload = override_payload if override_payload is not None else NODE_PAYLOADS[node_type]
    headers = {"header-api-key": api_key, "Content-Type": "application/json"}
    _note_unverified(url, skip_tls_verify)

    try:
        await _enforce_rate_limit()
        async with _client(skip_tls_verify) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code == 400:
            try:
                body = response.json()
                if body.get("status") == "error" and "No IP found" in body.get("result", ""):
                    logger.warning(
                        "No IPs for %s/%s: %s", environment, node_type, body.get("result")
                    )
                    return None
            except Exception:
                pass

        response.raise_for_status()
        return response.json()

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        try:
            api_body = exc.response.json()
        except Exception:
            api_body = exc.response.text
        logger.error("HTTP %s from Prisma API (%s/%s): %s", status, environment, node_type, api_body)

        if status == 401:
            raise HTTPException(
                status_code=401,
                detail=(
                    f"Authentication failed — your API key was rejected by the '{environment}' environment. "
                    f"Verify you have selected the correct environment for this key. "
                    f"API response: {api_body}"
                ),
            )
        raise HTTPException(
            status_code=status if 400 <= status < 500 else 502,
            detail=f"Prisma Access API returned {status}: {api_body}",
        )

    except httpx.RequestError as exc:
        raise await _request_error(url, exc, "Prisma Access API")


# --- SASE Locations API ---

async def fetch_locations(bearer_token: str, skip_tls_verify: bool = False) -> list[dict[str, Any]]:
    """GET all Prisma Access locations from the SASE Config API."""
    headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"}
    _note_unverified(LOCATIONS_API_URL, skip_tls_verify)
    try:
        await _enforce_rate_limit()
        async with _client(skip_tls_verify) as client:
            response = await client.get(LOCATIONS_API_URL, headers=headers)
        response.raise_for_status()
        data = response.json()
        # The API returns a list directly or a dict with a data key
        if isinstance(data, list):
            return data
        return data.get("data", data)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Locations API error: {exc.response.text}",
        )
    except httpx.RequestError as exc:
        raise await _request_error(LOCATIONS_API_URL, exc, "Locations API")


# --- OAuth ---

async def fetch_bearer_token(
    client_id: str, client_secret: str, tsg_id: str, skip_tls_verify: bool = False
) -> dict[str, Any]:
    """Exchange client credentials for a SASE OAuth bearer token."""
    _note_unverified(OAUTH_TOKEN_URL, skip_tls_verify)
    try:
        async with _client(skip_tls_verify) as client:
            response = await client.post(
                OAUTH_TOKEN_URL,
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials", "scope": f"tsg_id:{tsg_id}"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"OAuth token error: {exc.response.text}",
        )
    except httpx.RequestError as exc:
        raise await _request_error(OAUTH_TOKEN_URL, exc, "OAuth endpoint")


# --- Environment auto-detection ---

async def probe_environment(environment: str, api_key: str, skip_tls_verify: bool = False) -> bool | None:
    """
    Lightweight auth probe for one environment.
    Returns True if the key is accepted (any non-401 HTTP response),
    False on 401, None if unreachable. Certificate failures raise, so the user can decide.
    """
    url = API_URLS[environment]
    payload = NODE_PAYLOADS["gw"]
    headers = {"header-api-key": api_key, "Content-Type": "application/json"}
    try:
        async with _client(skip_tls_verify, timeout=10) as client:
            response = await client.post(url, headers=headers, json=payload)
        return response.status_code != 401
    except httpx.RequestError as exc:
        cert_err = cert_verification_error(exc)
        if cert_err is not None:
            raise await verification_failed(url, cert_err)
        return None


async def find_working_environment(
    api_key: str, exclude: Optional[str] = None, skip_tls_verify: bool = False
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """
    Probe all environments (except `exclude`) in parallel.

    Returns the first environment that accepts the API key (or None), plus the certificate
    failures seen along the way so the UI can list them without blocking the query. Only
    when every probe fails on its certificate is the failure raised for the user to decide.
    """
    envs = [e for e in ENVIRONMENTS if e != exclude]
    results = await asyncio.gather(
        *[probe_environment(e, api_key, skip_tls_verify) for e in envs], return_exceptions=True
    )
    tls_failures: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, HTTPException) and isinstance(result.detail, dict) \
                and result.detail.get("code") == TLS_VERIFY_FAILED:
            tls_failures.append(result.detail)
        elif isinstance(result, BaseException):
            raise result
    if results and len(tls_failures) == len(results):
        raise HTTPException(status_code=502, detail=tls_failures[0])
    for env, ok in zip(envs, results):
        if ok is True:
            return env, tls_failures
    return None, tls_failures


def key_rejected(tls_failures: list[dict[str, Any]]) -> HTTPException:
    """401 for a key no reachable environment accepted, listing any hosts that couldn't be checked."""
    if not tls_failures:
        return HTTPException(status_code=401, detail="API key was rejected by all environments.")
    return HTTPException(
        status_code=401,
        detail={
            "code": "key_rejected",
            "message": "API key was rejected by every environment that could be checked.",
            "tls_failures": tls_failures,
        },
    )
