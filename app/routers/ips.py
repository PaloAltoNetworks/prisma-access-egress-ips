"""
IP query endpoints.

POST /api/ips/query       — single node type
POST /api/ips/batch       — all node types + composites
POST /api/ips/pre-allocate — pre-allocate Mobile User IPs for a location
"""

from fastapi import APIRouter, HTTPException
from app.models import (
    BatchQueryRequest,
    BatchQueryResponse,
    IPQueryRequest,
    IPQueryResponse,
    PreAllocateRequest,
    PreAllocateResponse,
    ZoneData,
)
from app.services.prisma_client import fetch_prisma_ips, find_working_environment, probe_environment
from app.services.ip_processor import (
    build_batch_response,
    extract_rn_site_metadata,
    process_api_response,
)

router = APIRouter(prefix="/api/ips", tags=["ips"])


@router.post("/query", response_model=IPQueryResponse)
async def query_node_type(req: IPQueryRequest) -> IPQueryResponse:
    """Fetch egress IPs for a single node type."""
    env = req.environment
    try:
        raw = await fetch_prisma_ips(env, req.node_type, req.api_key)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        env = await find_working_environment(req.api_key, exclude=req.environment)
        if env is None:
            raise HTTPException(status_code=401, detail="API key was rejected by all environments.")
        raw = await fetch_prisma_ips(env, req.node_type, req.api_key)

    data = process_api_response(raw, env, req.node_type)

    rn_site_details = None
    rn_fqdn_suffix = None
    if req.node_type in ("rn", "rn_all") and raw is not None:
        details, suffix = extract_rn_site_metadata(raw, env, req.node_type)
        if details:
            rn_site_details = details
            rn_fqdn_suffix = suffix

    return IPQueryResponse(
        node_type=req.node_type,
        environment=env,
        data=data,
        rn_site_details=rn_site_details,
        rn_fqdn_suffix=rn_fqdn_suffix,
    )


@router.post("/batch", response_model=BatchQueryResponse)
async def query_batch(req: BatchQueryRequest) -> BatchQueryResponse:
    """Fetch all node types concurrently, compute exclusive and composite lists."""
    env = req.environment

    # Probe with a single request before fanning out — avoids sending every batch
    # request to the wrong environment when the API key belongs to a different one.
    if await probe_environment(env, req.api_key) is False:
        env = await find_working_environment(req.api_key, exclude=req.environment)
        if env is None:
            raise HTTPException(status_code=401, detail="API key was rejected by all environments.")

    results, composite_all, composite_all_deployed, rn_site_details, _ = (
        await build_batch_response(env, req.api_key)
    )

    return BatchQueryResponse(
        environment=env,
        results=results,
        all=composite_all,
        all_deployed=composite_all_deployed,
        rn_site_details=rn_site_details if rn_site_details else None,
    )


@router.post("/pre-allocate", response_model=PreAllocateResponse)
async def pre_allocate(req: PreAllocateRequest) -> PreAllocateResponse:
    """Pre-allocate Mobile User IPs for a specific location."""
    env = req.environment
    payload = {
        "actionType": "pre_allocate",
        "serviceType": "gp_gateway",
        "location": [req.location],
    }
    try:
        raw = await fetch_prisma_ips(env, "gw", req.api_key, override_payload=payload)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        env = await find_working_environment(req.api_key, exclude=req.environment)
        if env is None:
            raise HTTPException(status_code=401, detail="API key was rejected by all environments.")
        raw = await fetch_prisma_ips(env, "gw", req.api_key, override_payload=payload)

    data = process_api_response(raw, env, "pre_allocate")

    return PreAllocateResponse(
        environment=env,
        location=req.location,
        data=data,
    )
