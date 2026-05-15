"""
Auth endpoint — exchange SASE client credentials for a bearer token.
"""

from fastapi import APIRouter
from app.models import TokenRequest, TokenResponse
from app.services.prisma_client import fetch_bearer_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def get_token(req: TokenRequest) -> TokenResponse:
    """Exchange SASE client credentials (client_id, client_secret, tsg_id) for a bearer token."""
    data = await fetch_bearer_token(req.client_id, req.client_secret, req.tsg_id)
    return TokenResponse(
        access_token=data["access_token"],
        expires_in=data.get("expires_in"),
        token_type=data.get("token_type", "Bearer"),
    )
