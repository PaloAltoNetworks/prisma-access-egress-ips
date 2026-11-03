"""
Async HTTP client for the Prisma Access egress IP API, SASE locations API, and OAuth.

TLS is always verified (public roots plus any mounted custom CA). A certificate failure is
returned to the caller as a structured error; nothing retries on its own. The only extra
trust comes from certificates the user approved, sent with each request.
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from app.config import (
    API_TIMEOUT_SECONDS,
    API_URLS,
    COMMERCIAL_ENVIRONMENTS,
    LOCATIONS_API_URL,
    MIN_REQUEST_INTERVAL,
    NODE_PAYLOADS,
    OAUTH_TOKEN_URL,
    display_name,
)
from app.models import CertificateApproval
from app.services.tls import TLS_VERIFY_FAILED, cert_verification_error, context_for, verification_failed

Approvals = Sequence[CertificateApproval]

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


def _client(url: str, approvals: Approvals, timeout: float = API_TIMEOUT_SECONDS) -> httpx.AsyncClient:
    """Verified TLS for url's host, including any certificates the user approved for it."""
    return httpx.AsyncClient(verify=context_for(httpx.URL(url).host, approvals), timeout=timeout)


async def _request_error(url: str, exc: httpx.RequestError, what: str) -> HTTPException:
    """Map a transport failure; certificate failures get the structured approval error."""
    cert_err = cert_verification_error(exc)
    if cert_err is not None:
        return await verification_failed(url, cert_err)
    if isinstance(exc, httpx.TimeoutException):
        logger.error("Timed out reaching %s: %s", what, type(exc).__name__)
        return HTTPException(status_code=504, detail=f"Timed out reaching {what}.")
    # Some httpx errors stringify to an empty message
    reason = str(exc) or type(exc).__name__
    logger.error("Request error reaching %s: %s", what, reason)
    return HTTPException(status_code=502, detail=f"Could not reach {what}: {reason}")


# One retry for responses that usually mean "try again shortly"
_RETRY_STATUSES = {429, 502, 503, 504}
_RETRY_DELAY = 1.0      # seconds, when the reply has no usable Retry-After
_RETRY_MAX_DELAY = 5.0


def _retry_delay(response: httpx.Response) -> float:
    try:
        delay = float(response.headers.get("Retry-After", _RETRY_DELAY))
    except ValueError:
        delay = _RETRY_DELAY
    return min(max(delay, 0.0), _RETRY_MAX_DELAY)


def _excerpt(response: httpx.Response, limit: int = 500) -> Any:
    """An upstream body for an error message: parsed JSON if possible, otherwise text, bounded."""
    try:
        body = response.json()
    except ValueError:
        body = response.text
    text = body if isinstance(body, str) else str(body)
    return body if len(text) <= limit else text[:limit] + "…"


def _no_ips(response: httpx.Response) -> bool:
    """The API's 400 reply for a service type with no IPs. It means the key was accepted."""
    if response.status_code != 400:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("status") == "error" \
        and "No IP found" in str(body.get("result", ""))


# --- Egress IP API ---

async def fetch_prisma_ips(
    environment: str,
    node_type: str,
    api_key: str,
    override_payload: Optional[dict[str, Any]] = None,
    approvals: Approvals = (),
) -> Optional[dict[str, Any]]:
    """
    POST to the Prisma Access egress IP API and return the raw JSON response.

    Returns None when the API signals no IPs exist for the requested service type.
    Raises HTTPException for all other errors.
    """
    url = API_URLS[environment]
    payload = override_payload if override_payload is not None else NODE_PAYLOADS[node_type]
    headers = {"header-api-key": api_key, "Content-Type": "application/json"}

    try:
        async with _client(url, approvals) as client:
            for attempt in (1, 2):
                await _enforce_rate_limit()
                response = await client.post(url, headers=headers, json=payload)
                if attempt == 1 and response.status_code in _RETRY_STATUSES:
                    delay = _retry_delay(response)
                    logger.warning("HTTP %s from Prisma API (%s/%s); retrying in %.1fs",
                                   response.status_code, environment, node_type, delay)
                    await asyncio.sleep(delay)
                    continue
                break

        if _no_ips(response):
            logger.warning("No IPs for %s/%s", environment, node_type)
            return None

        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            logger.error("Non-JSON response from Prisma API (%s/%s)", environment, node_type)
            raise HTTPException(
                status_code=502,
                detail=f"Prisma Access API returned a response that isn't JSON for {node_type}.",
            )

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        api_body = _excerpt(exc.response)
        logger.error("HTTP %s from Prisma API (%s/%s): %s", status, environment, node_type, api_body)

        if status == 401:
            raise key_rejected_by(environment, api_body)
        raise HTTPException(
            status_code=status if 400 <= status < 500 else 502,
            detail=f"Prisma Access API returned {status}: {api_body}",
        )

    except httpx.RequestError as exc:
        raise await _request_error(url, exc, "Prisma Access API")


# --- SASE Locations API ---

async def fetch_locations(bearer_token: str) -> list[dict[str, Any]]:
    """GET all Prisma Access locations from the SASE Config API."""
    headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"}
    try:
        await _enforce_rate_limit()
        async with _client(LOCATIONS_API_URL, ()) as client:
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
            detail=f"Locations API error: {_excerpt(exc.response)}",
        )
    except httpx.RequestError as exc:
        raise await _request_error(LOCATIONS_API_URL, exc, "Locations API")


# --- OAuth ---

async def fetch_bearer_token(
    client_id: str, client_secret: str, tsg_id: str, approvals: Approvals = ()
) -> dict[str, Any]:
    """Exchange client credentials for a SASE OAuth bearer token."""
    try:
        async with _client(OAUTH_TOKEN_URL, approvals) as client:
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
            detail=f"OAuth token error: {_excerpt(exc.response)}",
        )
    except httpx.RequestError as exc:
        raise await _request_error(OAUTH_TOKEN_URL, exc, "OAuth endpoint")


# --- Environment auto-detection ---

async def probe_environment(environment: str, api_key: str, approvals: Approvals = ()) -> bool | None:
    """
    Lightweight auth probe for one environment.
    Returns True if the key is accepted (a 2xx, or the 400 that reports no IPs), False on 401,
    None if unknown (unreachable, or any other status). Certificate failures raise, so the
    user can decide.
    """
    url = API_URLS[environment]
    payload = NODE_PAYLOADS["gw"]
    headers = {"header-api-key": api_key, "Content-Type": "application/json"}
    try:
        async with _client(url, approvals, timeout=10) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code == 401:
            return False
        if response.is_success or _no_ips(response):
            return True
        logger.warning("Probe of %s returned %s; treating it as unknown", environment, response.status_code)
        return None
    except httpx.RequestError as exc:
        cert_err = cert_verification_error(exc)
        if cert_err is not None:
            raise await verification_failed(url, cert_err)
        return None


async def find_working_environment(
    api_key: str, exclude: Optional[str] = None, approvals: Approvals = ()
) -> tuple[Optional[str], list[dict[str, Any]], list[str]]:
    """
    Probe the commercial environments (except `exclude`) in parallel. FedRAMP environments
    are never probed, and callers don't search at all when a FedRAMP environment was selected.

    Returns the first environment that accepts the API key (or None), the certificate
    failures seen along the way so the UI can list them without blocking the query, and the
    environments whose answer was unknown (unreachable or an unexpected status). Only when
    every probe fails on its certificate is the failure raised for the user to decide.
    """
    envs = [e for e in COMMERCIAL_ENVIRONMENTS if e != exclude]
    results = await asyncio.gather(
        *[probe_environment(e, api_key, approvals) for e in envs], return_exceptions=True
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
            return env, tls_failures, []
    unknown = [env for env, ok in zip(envs, results) if ok is None]
    return None, tls_failures, unknown


_FEDRAMP_HINT = (
    " FedRAMP environments aren't searched. If this is a FedRAMP key, select the FedRAMP environment."
)


def key_rejected_by(environment: str, api_body: Any = None) -> HTTPException:
    """401 for a key the selected environment rejected."""
    detail = (
        f"Authentication failed — your API key was rejected by the {display_name(environment)} environment. "
        "Verify you have selected the correct environment for this key."
    )
    if api_body is not None:
        detail += f" API response: {api_body}"
    return HTTPException(status_code=401, detail=detail)


def key_rejected(tls_failures: list[dict[str, Any]], unknown: list[str] = ()) -> HTTPException:
    """
    For a key no commercial environment accepted. If some couldn't be checked, the key may
    still belong to one of them, so that's a 502 naming them rather than a 401.
    """
    if not tls_failures and not unknown:
        return HTTPException(
            status_code=401, detail="API key was rejected by every commercial environment." + _FEDRAMP_HINT
        )
    message = "API key was rejected by every commercial environment that could be checked."
    if unknown:
        message += (
            f" Couldn't check {', '.join(display_name(e) for e in unknown)} (unreachable or returned an error);"
            " the key may belong to one of them, so try again later."
        )
    message += _FEDRAMP_HINT
    status = 502 if unknown else 401
    if not tls_failures:
        return HTTPException(status_code=status, detail=message)
    return HTTPException(
        status_code=status,
        detail={"code": "key_rejected", "message": message, "tls_failures": tls_failures},
    )
