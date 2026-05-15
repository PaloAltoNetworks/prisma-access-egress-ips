"""
Central configuration for the Prisma Access Egress IP worker.

Node type naming uses underscores throughout for consistency.
The old CLI used mixed hyphens/underscores (e.g. gw-pre, rn_all) — all normalized here.
"""

API_URLS: dict[str, str] = {
    "fedramp": "https://api.fed.prismaaccess.com/getPrismaAccessIP/v2",
    "lab":     "https://api.lab.datapath.prismaaccess.com/getPrismaAccessIP/v2",
    "prod1":   "https://api.prod.datapath.prismaaccess.com/getPrismaAccessIP/v2",
    "prod4":   "https://api.prod4.datapath.prismaaccess.com/getPrismaAccessIP/v2",
    "prod6":   "https://api.prod6.datapath.prismaaccess.com/getPrismaAccessIP/v2",
    "prod8":   "https://api.prod8.datapath.prismaaccess.com/getPrismaAccessIP/v2",
}

ENVIRONMENTS = list(API_URLS.keys())

# --- Locations / SASE Config API ---
LOCATIONS_API_URL = "https://api.sase.paloaltonetworks.com/sse/config/v1/locations"

# --- OAuth ---
OAUTH_TOKEN_URL = "https://auth.apps.paloaltonetworks.com/oauth2/access_token"

# --- Node type payloads sent to the Prisma Access egress IP API ---
# Keys use underscores consistently. gw_pre was previously gw-pre in the CLI.
NODE_PAYLOADS: dict[str, dict[str, str]] = {
    "gw":           {"serviceType": "gp_gateway",     "addrType": "all",                   "location": "deployed"},
    "gw_all":       {"serviceType": "gp_gateway",     "addrType": "all",                   "location": "all"},
    "gw_pre":       {"serviceType": "all",             "addrType": "pre_allocated",          "location": "all"},
    "pt":           {"serviceType": "gp_portal",       "addrType": "all",                   "location": "deployed"},
    "rbi":          {"serviceType": "rbi",             "addrType": "all",                   "location": "all"},
    "rn":           {"serviceType": "remote_network",  "addrType": "all",                   "location": "deployed"},
    "rn_all":       {"serviceType": "remote_network",  "addrType": "all",                   "location": "all"},
    "swg":          {"serviceType": "swg_proxy",       "addrType": "all",                   "location": "deployed"},
    "swg_lb":       {"serviceType": "swg_proxy",       "addrType": "network_load_balancer", "location": "deployed"},
    "swg_all":      {"serviceType": "swg_proxy",       "addrType": "all",                   "location": "all"},
    "all":          {"serviceType": "all",             "addrType": "all",                   "location": "all"},
    "all_deployed": {"serviceType": "all",             "addrType": "all",                   "location": "deployed"},
}

# Individual node types (excludes composite aggregates)
INDIVIDUAL_NODE_TYPES = [k for k in NODE_PAYLOADS if k not in ("all", "all_deployed")]

# Components that make up the composite aggregate types.
# gw_pre, swg, and swg_all have IPs subtracted before inclusion — see ip_processor.py.
COMPONENTS_FOR_ALL: list[str] = ["gw_all", "rn_all", "pt", "rbi", "swg_all", "swg_lb", "gw_pre"]
COMPONENTS_FOR_ALL_DEPLOYED: list[str] = ["gw", "rn", "pt", "rbi", "swg", "swg_lb"]

# --- HTTP client settings ---
API_TIMEOUT_SECONDS = 30
MAX_CONCURRENT_REQUESTS = 10
MIN_REQUEST_INTERVAL = 0.1  # seconds between requests
