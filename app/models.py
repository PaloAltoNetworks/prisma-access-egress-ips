"""
Pydantic models for request validation and response serialization.
"""

from typing import Literal, Optional
from pydantic import BaseModel, field_validator
from app.config import ENVIRONMENTS, NODE_PAYLOADS
import re

# --- Validation patterns ---
_VALID_API_KEY = re.compile(r'^[A-Za-z0-9\-_+=/.]{10,}$')
_VALID_LOCATION = re.compile(r'^[A-Za-z0-9\s\-()\,]{1,100}$')


# --- Shared request base ---
class EnvironmentMixin(BaseModel):
    environment: Literal["fedramp", "lab", "prod1", "prod4", "prod6", "prod8"]


# --- IP query requests ---
class IPQueryRequest(EnvironmentMixin):
    api_key: str
    node_type: str

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not _VALID_API_KEY.match(v.strip()):
            raise ValueError("Invalid API key format")
        return v.strip()

    @field_validator("node_type")
    @classmethod
    def validate_node_type(cls, v: str) -> str:
        if v not in NODE_PAYLOADS:
            raise ValueError(f"Unknown node_type '{v}'. Valid: {', '.join(NODE_PAYLOADS)}")
        return v


class BatchQueryRequest(EnvironmentMixin):
    api_key: str

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not _VALID_API_KEY.match(v.strip()):
            raise ValueError("Invalid API key format")
        return v.strip()


class PreAllocateRequest(EnvironmentMixin):
    api_key: str
    location: str

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not _VALID_API_KEY.match(v.strip()):
            raise ValueError("Invalid API key format")
        return v.strip()

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Location cannot be empty")
        if not _VALID_LOCATION.match(v):
            raise ValueError("Location contains invalid characters")
        return v


# --- Auth requests ---
class TokenRequest(BaseModel):
    client_id: str
    client_secret: str
    tsg_id: str


# --- Response models ---
class ZoneData(BaseModel):
    """IP addresses grouped by zone — the base unit of all IP responses."""
    zone: str
    addresses: list[str]


class RNSiteDetail(BaseModel):
    """Per-IP metadata for Remote Network nodes, including site associations."""
    zone: str
    address: str
    node_name: str
    sites: list[str]
    site_count: int


class IPQueryResponse(BaseModel):
    node_type: str
    environment: str
    data: list[ZoneData]
    # Only populated for rn / rn_all node types
    rn_site_details: Optional[list[RNSiteDetail]] = None
    rn_fqdn_suffix: Optional[str] = None


class BatchQueryResponse(BaseModel):
    environment: str
    # Keyed by node_type. Each value is the processed, exclusive IP list for that type.
    results: dict[str, list[ZoneData]]
    # Composite aggregates
    all: list[ZoneData]
    all_deployed: list[ZoneData]
    # RN metadata if present
    rn_site_details: Optional[dict[str, list[RNSiteDetail]]] = None


class PreAllocateResponse(BaseModel):
    environment: str
    location: str
    data: list[ZoneData]


class TokenResponse(BaseModel):
    access_token: str
    expires_in: Optional[int] = None
    token_type: str = "Bearer"
