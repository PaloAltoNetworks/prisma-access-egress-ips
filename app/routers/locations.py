"""
Locations endpoint — lists all Prisma Access locations via the SASE Config API.
Requires a SASE OAuth bearer token passed in the Authorization header.
"""

from fastapi import APIRouter, Header
from app.services.prisma_client import fetch_locations

router = APIRouter(prefix="/api/locations", tags=["locations"])


@router.get("")
async def get_locations(authorization: str = Header(..., alias="Authorization")) -> list[dict]:
    """
    Fetch all Prisma Access locations.
    Expects: Authorization: Bearer <token>
    """
    if not authorization.lower().startswith("bearer "):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Authorization header must use Bearer scheme")
    token = authorization[7:].strip()
    return await fetch_locations(token)
