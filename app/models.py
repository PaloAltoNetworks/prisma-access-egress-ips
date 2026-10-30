"""
Pydantic models for request validation and response serialization.
"""

from typing import Annotated, Any, Literal, Optional
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator
from app.config import ENVIRONMENTS, NODE_PAYLOADS
import re
import ssl

# --- Validation patterns ---
_VALID_API_KEY = re.compile(r'^[A-Za-z0-9\-_+=/.]{10,512}$')
_VALID_LOCATION = re.compile(r'^[A-Za-z0-9\s\-()\,]{1,100}$')


# Service-account credentials. Upper bounds are generous; they keep arbitrarily long
# values from being forwarded upstream.
_Credential = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
_TsgId = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r'^[0-9]{1,20}$')]


def _single_certificate(v: str) -> str:
    """Exactly one parseable PEM certificate, returned in canonical form."""
    if v.count("-----BEGIN CERTIFICATE-----") != 1:
        raise ValueError("Expected exactly one PEM certificate")
    try:
        pem = ssl.DER_cert_to_PEM_cert(ssl.PEM_cert_to_DER_cert(v.strip()))
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=pem)
    except (ValueError, ssl.SSLError):
        raise ValueError("Not a valid PEM certificate")
    return pem


_Pem = Annotated[str, StringConstraints(max_length=16384), AfterValidator(_single_certificate)]
_Host = Annotated[str, StringConstraints(to_lower=True, pattern=r'^[A-Za-z0-9.\-]{1,253}$')]


class _Strict(BaseModel):
    # The server is authoritative: a field it doesn't define is an error, not ignored.
    model_config = ConfigDict(extra="forbid")


# --- Certificates the user approved after a verification failure ---
class AnchorApproval(_Strict):
    """A CA trusted in addition to the usual roots, for every host. Hostname and expiry are still checked."""
    kind: Literal["anchor"]
    pem: _Pem


class LeafApproval(_Strict):
    """This exact certificate, for this host only. Nothing else is trusted for the host."""
    kind: Literal["leaf"]
    host: _Host
    pem: _Pem


CertificateApproval = Annotated[AnchorApproval | LeafApproval, Field(discriminator="kind")]


# --- Shared request base ---
class OutboundRequest(_Strict):
    # The browser keeps approvals in page memory for the session and sends them with each
    # request; the server keeps no state. Each comes from a verification failure's detail.
    approved_certificates: list[CertificateApproval] = Field(default_factory=list, max_length=20)


class EnvironmentMixin(OutboundRequest):
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
            raise ValueError(f"Unknown node_type. Valid: {', '.join(NODE_PAYLOADS)}")
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
class TokenRequest(OutboundRequest):
    client_id: _Credential
    client_secret: _Credential
    tsg_id: _TsgId


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


class EnvironmentSearchResult(BaseModel):
    # Environments skipped during auto-detection because their certificate couldn't be
    # verified; the UI lists them so the user can inspect each one.
    tls_failures: Optional[list[dict[str, Any]]] = None


class IPQueryResponse(EnvironmentSearchResult):
    node_type: str
    environment: str
    data: list[ZoneData]
    # Only populated for rn / rn_all node types
    rn_site_details: Optional[list[RNSiteDetail]] = None
    rn_fqdn_suffix: Optional[str] = None


class BatchQueryResponse(EnvironmentSearchResult):
    environment: str
    # Keyed by node_type. Each value is the processed, exclusive IP list for that type.
    results: dict[str, list[ZoneData]]
    # Composite aggregates
    all: list[ZoneData]
    all_deployed: list[ZoneData]
    # RN metadata if present
    rn_site_details: Optional[dict[str, list[RNSiteDetail]]] = None


class PreAllocateResponse(EnvironmentSearchResult):
    environment: str
    location: str
    data: list[ZoneData]


class TokenResponse(BaseModel):
    access_token: str
    expires_in: Optional[int] = None
    token_type: str = "Bearer"
