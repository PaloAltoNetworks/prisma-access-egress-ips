"""
Locations endpoint — lists all Prisma Access locations via the SASE Config API.
Requires a SASE OAuth bearer token passed in the Authorization header.
"""

import re

from fastapi import APIRouter, Header, HTTPException
from app.services.prisma_client import fetch_locations

# RFC 6750 b64token, bounded so an arbitrarily long value is never forwarded upstream
_VALID_TOKEN = re.compile(r'^[A-Za-z0-9\-._~+/]{1,8192}={0,2}$')

router = APIRouter(prefix="/api/locations", tags=["locations"])


@router.get("")
async def get_locations(
    authorization: str = Header(..., alias="Authorization"),
) -> list[dict]:
    """
    Fetch all Prisma Access locations.
    Expects: Authorization: Bearer <token>
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must use Bearer scheme")
    token = authorization[7:].strip()
    if not _VALID_TOKEN.match(token):
        raise HTTPException(status_code=401, detail="Invalid bearer token format")
    return await fetch_locations(token)
