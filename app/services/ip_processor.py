"""
Business logic for processing Prisma Access egress IP API responses.

Ported from the CLI — all file I/O removed. Functions return structured data
that is serialized to JSON by FastAPI and consumed by the frontend.
"""

import asyncio
import logging
from typing import Any, Optional

from fastapi import HTTPException

from app.config import (
    COMPONENTS_FOR_ALL,
    COMPONENTS_FOR_ALL_DEPLOYED,
    INDIVIDUAL_NODE_TYPES,
    MAX_CONCURRENT_REQUESTS,
)
from app.models import RNSiteDetail, ZoneData
from app.services.prisma_client import Approvals, fetch_prisma_ips
from app.services.tls import TLS_VERIFY_FAILED

logger = logging.getLogger(__name__)


# --- Response normalization ---

def process_api_response(
    api_data: Optional[dict[str, Any]],
    environment: str,
    node_type: str,
) -> list[ZoneData]:
    """
    Normalize the raw Prisma API response into a list of ZoneData.
    Returns an empty list when api_data is None (no IPs deployed). A response in an
    unexpected shape is an error rather than a silently shorter list: these lists end up
    in allow-lists.
    """
    if api_data is None:
        return []

    def malformed(what: str) -> HTTPException:
        logger.error("Unexpected response for %s/%s: %s", environment, node_type, what)
        return HTTPException(
            status_code=502,
            detail=f"Prisma Access API returned an unexpected response for {node_type}: {what}.",
        )

    if not isinstance(api_data, dict):
        raise malformed("not a JSON object")
    raw_result = api_data.get("result", [])
    if not isinstance(raw_result, list):
        raise malformed("'result' is not a list")

    result = []
    for item in raw_result:
        if not isinstance(item, dict):
            raise malformed("a zone entry is not an object")
        zone = item.get("zone") or "Unknown Zone"
        addresses = item.get("addresses") or []
        if not isinstance(zone, str) or not isinstance(addresses, list) \
                or not all(isinstance(a, str) for a in addresses):
            raise malformed(f"zone entry '{zone}' has an unexpected format")
        result.append(ZoneData(zone=zone, addresses=addresses))

    return result


# --- RN site metadata ---

def extract_rn_site_metadata(
    api_data: Optional[dict[str, Any]],
    environment: str,
    node_type: str,
) -> tuple[list[RNSiteDetail], str]:
    """
    Extract per-IP site association metadata from Remote Network API responses.
    Returns (site_details, fqdn_suffix). Both are empty/blank when data is absent.
    """
    if api_data is None:
        return [], ""

    site_details: list[RNSiteDetail] = []
    fqdn_suffix = ""

    raw_result = api_data.get("result", []) if isinstance(api_data, dict) else None
    if not isinstance(raw_result, list):
        return [], ""

    # Site metadata only annotates the IP list, so malformed entries are skipped, not fatal.
    for item in raw_result:
        if not isinstance(item, dict):
            continue
        zone = item.get("zone", "Unknown Zone")
        address_details = item.get("address_details") or []
        if not isinstance(address_details, list):
            continue
        ip_to_meta: dict[str, dict[str, Any]] = {}

        for detail in address_details:
            ip = detail.get("address") if isinstance(detail, dict) else None
            if not ip or not isinstance(ip, str):
                continue
            if ip not in ip_to_meta:
                ip_to_meta[ip] = {"node_name": None, "sites": [], "node_fqdn": None}

            node_names = detail.get("node_name", [])
            if isinstance(node_names, list):
                ip_to_meta[ip]["sites"] = node_names

            if detail.get("addressType") == "service_ip":
                fqdn = detail.get("node_fqdn", "")
                ip_to_meta[ip]["node_fqdn"] = fqdn
                if fqdn and ".rn." in fqdn:
                    parts = fqdn.split(".rn.", 1)
                    ip_to_meta[ip]["node_name"] = parts[0]
                    if not fqdn_suffix and len(parts) > 1:
                        fqdn_suffix = ".rn." + parts[1]

        for ip, meta in ip_to_meta.items():
            sites = meta["sites"] or []
            site_details.append(
                RNSiteDetail(
                    zone=zone,
                    address=ip,
                    node_name=meta["node_name"] or "unknown",
                    sites=sites,
                    site_count=len(sites),
                )
            )

    return site_details, fqdn_suffix


# --- IP set operations ---

def subtract_ips(
    source: list[ZoneData],
    to_subtract: list[ZoneData],
) -> list[ZoneData]:
    """Remove any IPs in `to_subtract` from `source`. Used to produce exclusive lists."""
    if not source:
        return []
    if not to_subtract:
        return source

    subtract_set = {addr for zone in to_subtract for addr in zone.addresses}

    result = []
    for zone_data in source:
        exclusive = [a for a in zone_data.addresses if a not in subtract_set]
        if exclusive:
            result.append(ZoneData(zone=zone_data.zone, addresses=exclusive))
    return result


def merge_zone_data(datasets: list[list[ZoneData]]) -> list[ZoneData]:
    """Merge and de-duplicate multiple ZoneData lists, sorted by zone then address."""
    by_zone: dict[str, set[str]] = {}
    for dataset in datasets:
        for zone_data in dataset:
            by_zone.setdefault(zone_data.zone, set()).update(zone_data.addresses)
    return [
        ZoneData(zone=zone, addresses=sorted(addrs))
        for zone, addrs in sorted(by_zone.items())
    ]


def extract_ip_set(data: list[ZoneData]) -> tuple[set[str], dict[str, str]]:
    """Return (set of all IPs, mapping of IP → zone) from a ZoneData list."""
    ip_set: set[str] = set()
    ip_to_zone: dict[str, str] = {}
    for zone_data in data:
        for addr in zone_data.addresses:
            ip_set.add(addr)
            ip_to_zone[addr] = zone_data.zone
    return ip_set, ip_to_zone


# --- Composite aggregation ---

def build_composite(
    component_keys: list[str],
    fetched: dict[str, list[ZoneData]],
    exclusive_swg: list[ZoneData],
    exclusive_swg_all: list[ZoneData],
    exclusive_gw_pre: list[ZoneData],
    direct_data: list[ZoneData],
) -> list[ZoneData]:
    """
    Aggregate component IP lists into a composite (all / all_deployed) set.

    Uses exclusive versions for swg, swg_all, and gw_pre.
    Adds any IPs present in the direct API response but absent from components (tagged 'other').
    """
    parts: list[list[ZoneData]] = []
    for key in component_keys:
        if key == "swg":
            parts.append(exclusive_swg)
        elif key == "swg_all":
            parts.append(exclusive_swg_all)
        elif key == "gw_pre":
            parts.append(exclusive_gw_pre)
        else:
            parts.append(fetched.get(key, []))

    merged = merge_zone_data(parts)

    # Validation: find IPs in the direct API response not covered by components
    merged_ips, _ = extract_ip_set(merged)
    direct_ips, direct_ip_to_zone = extract_ip_set(direct_data)
    missing = direct_ips - merged_ips

    if missing:
        logger.warning("%d IPs in direct composite response not found in components", len(missing))
        extra_by_zone: dict[str, list[str]] = {}
        for ip in missing:
            zone = direct_ip_to_zone.get(ip, "Unknown")
            extra_by_zone.setdefault(zone, []).append(ip)
        for zone, addrs in extra_by_zone.items():
            merged = merge_zone_data([merged, [ZoneData(zone=zone, addresses=addrs)]])

    return merged


# --- Batch fetch orchestration ---

def _raise_for_failures(results: dict[str, Any]) -> None:
    """
    Fail the whole batch if any node type failed. A missing type would otherwise show as
    empty, and leave its IPs in the lists it should be subtracted from (swg_lb from swg).
    """
    failures = {nt: r for nt, r in results.items() if isinstance(r, BaseException)}
    if not failures:
        return
    for exc in failures.values():
        # Certificate failures keep their structured detail so the page can offer an approval.
        is_cert = isinstance(exc, HTTPException) and isinstance(exc.detail, dict) \
            and exc.detail.get("code") == TLS_VERIFY_FAILED
        if is_cert or not isinstance(exc, HTTPException):
            raise exc
    logger.error("Batch failed for %s", ", ".join(failures))
    first_type, first = next(iter(failures.items()))
    raise HTTPException(
        status_code=502,
        detail=(
            f"Could not fetch {', '.join(failures)}, so the results would be incomplete. "
            f"{first_type}: {first.detail}"
        ),
    )


async def fetch_all_node_types(
    environment: str,
    api_key: str,
    approvals: Approvals = (),
) -> tuple[dict[str, list[ZoneData]], dict[str, Any]]:
    """
    Fetch all individual node types concurrently (respecting MAX_CONCURRENT_REQUESTS).

    Returns:
        fetched: node_type → ZoneData list (processed)
        raw_rn:  node_type → raw API response, for rn/rn_all only (for site metadata)
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def _fetch_one(node_type: str) -> tuple[str, list[ZoneData], Optional[dict[str, Any]]]:
        async with semaphore:
            raw = await fetch_prisma_ips(environment, node_type, api_key, approvals=approvals)
            processed = process_api_response(raw, environment, node_type)
            raw_for_rn = raw if node_type in ("rn", "rn_all") else None
            return node_type, processed, raw_for_rn

    tasks = [_fetch_one(nt) for nt in INDIVIDUAL_NODE_TYPES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    _raise_for_failures(dict(zip(INDIVIDUAL_NODE_TYPES, results)))

    fetched: dict[str, list[ZoneData]] = {}
    raw_rn: dict[str, Any] = {}

    for result in results:
        node_type, processed, raw = result
        fetched[node_type] = processed
        if raw is not None:
            raw_rn[node_type] = raw

    return fetched, raw_rn


async def build_batch_response(
    environment: str,
    api_key: str,
    approvals: Approvals = (),
) -> tuple[
    dict[str, list[ZoneData]],  # exclusive results per node type
    list[ZoneData],              # composite all
    list[ZoneData],              # composite all_deployed
    dict[str, list[RNSiteDetail]],  # RN site details per node type
    dict[str, str],              # RN fqdn suffix per node type
]:
    """
    Full batch pipeline: fetch all node types, compute exclusives, build composites.
    Mirrors the CLI's process_all_node_types_batch but returns data instead of writing files.
    """
    fetched, raw_rn = await fetch_all_node_types(environment, api_key, approvals)

    # Compute exclusive IP lists
    exclusive_swg     = subtract_ips(fetched.get("swg", []),     fetched.get("swg_lb", []))
    exclusive_swg_all = subtract_ips(fetched.get("swg_all", []), fetched.get("swg_lb", []))
    exclusive_gw_pre  = subtract_ips(
        fetched.get("gw_pre", []),
        fetched.get("gw_all", []) + fetched.get("swg_all", []),
    )

    # Build per-type results for display.
    # swg/swg_all are shown exclusive of swg_lb (which has its own tab).
    # gw_pre uses addrType=pre_allocated — a distinct set — so display the raw fetch.
    # The exclusive_gw_pre is only used below when building the composite "all" list.
    exclusive_results: dict[str, list[ZoneData]] = {}
    for nt in INDIVIDUAL_NODE_TYPES:
        if nt == "swg":
            exclusive_results[nt] = exclusive_swg
        elif nt == "swg_all":
            exclusive_results[nt] = exclusive_swg_all
        else:
            exclusive_results[nt] = fetched.get(nt, [])

    # Fetch composite types directly for validation
    raw_all          = await fetch_prisma_ips(environment, "all",          api_key, approvals=approvals)
    raw_all_deployed = await fetch_prisma_ips(environment, "all_deployed", api_key, approvals=approvals)
    direct_all          = process_api_response(raw_all,          environment, "all")
    direct_all_deployed = process_api_response(raw_all_deployed, environment, "all_deployed")

    composite_all = build_composite(
        COMPONENTS_FOR_ALL, fetched,
        exclusive_swg, exclusive_swg_all, exclusive_gw_pre, direct_all,
    )
    composite_all_deployed = build_composite(
        COMPONENTS_FOR_ALL_DEPLOYED, fetched,
        exclusive_swg, exclusive_swg_all, exclusive_gw_pre, direct_all_deployed,
    )

    # Extract RN site metadata
    rn_site_details: dict[str, list[RNSiteDetail]] = {}
    rn_fqdn_suffixes: dict[str, str] = {}
    for nt in ("rn", "rn_all"):
        if nt in raw_rn:
            details, suffix = extract_rn_site_metadata(raw_rn[nt], environment, nt)
            if details:
                rn_site_details[nt] = details
                rn_fqdn_suffixes[nt] = suffix

    return exclusive_results, composite_all, composite_all_deployed, rn_site_details, rn_fqdn_suffixes
