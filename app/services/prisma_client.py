"""
Async HTTP client for the Prisma Access egress IP API, SASE locations API, and OAuth.

Ported from the CLI's fetch_prisma_ips / fetch_bearer_token / fetch_locations,
adapted for async httpx and FastAPI error handling (HTTPException instead of sys.exit).
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
    LOCATIONS_API_URL,
    MIN_REQUEST_INTERVAL,
    NODE_PAYLOADS,
    OAUTH_TOKEN_URL,
)

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


# --- Egress IP API ---

async def fetch_prisma_ips(
    environment: str,
    node_type: str,
    api_key: str,
    override_payload: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """
    POST to the Prisma Access egress IP API and return the raw JSON response.

    Retries once without SSL verification on SSLError (preserving CLI behaviour).
    Returns None when the API signals no IPs exist for the requested service type.
    Raises HTTPException for all other errors.
    """
    url = API_URLS[environment]
    payload = override_payload if override_payload is not None else NODE_PAYLOADS[node_type]
    headers = {"header-api-key": api_key, "Content-Type": "application/json"}

    verify_ssl = True
    for attempt in range(2):
        try:
            await _enforce_rate_limit()
            async with httpx.AsyncClient(verify=verify_ssl, timeout=API_TIMEOUT_SECONDS) as client:
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

        except httpx.ConnectError as exc:
            # httpx surfaces SSL failures as ConnectError (requests used SSLError — different library)
            if attempt == 0:
                logger.warning("Connect error for %s, retrying without SSL verification: %s", url, exc)
                verify_ssl = False
            else:
                logger.error("Connect error persists without SSL verification: %s", exc)
                raise HTTPException(status_code=502, detail=f"Could not connect to Prisma Access API: {exc}")

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
            logger.error("Request error fetching %s/%s: %s", environment, node_type, exc)
            raise HTTPException(status_code=502, detail=f"Could not reach Prisma Access API: {exc}")

    return None


# --- SASE Locations API ---

async def fetch_locations(bearer_token: str) -> list[dict[str, Any]]:
    """GET all Prisma Access locations from the SASE Config API."""
    headers = {"Authorization": f"Bearer {bearer_token}", "Content-Type": "application/json"}
    try:
        await _enforce_rate_limit()
        async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
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
        raise HTTPException(status_code=502, detail=f"Could not reach Locations API: {exc}")


# --- OAuth ---

async def fetch_bearer_token(client_id: str, client_secret: str, tsg_id: str) -> dict[str, Any]:
    """Exchange client credentials for a SASE OAuth bearer token."""
    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT_SECONDS) as client:
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
        raise HTTPException(status_code=502, detail=f"Could not reach OAuth endpoint: {exc}")
