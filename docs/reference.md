# Reference

## Environments

| Key | Endpoint |
| --- | -------- |
| `prod1` | `api.prod.datapath.prismaaccess.com` |
| `prod4` | `api.prod4.datapath.prismaaccess.com` |
| `prod6` | `api.prod6.datapath.prismaaccess.com` |
| `prod8` | `api.prod8.datapath.prismaaccess.com` |
| `fedramp` | `api.fed.prismaaccess.com` |
| `lab` | `api.lab.datapath.prismaaccess.com` |

If an environment rejects your API key, the tool tries the others in parallel and switches to the
one that accepts it. Environments it can't reach because of a certificate problem are listed
above the form; see [Trusting a custom CA](./custom-ca.md).

## Node types

| Key | Description | Notes |
| --- | ----------- | ----- |
| `gw` | GlobalProtect Gateway (deployed) | Currently active gateways |
| `gw_all` | GlobalProtect Gateway (all) | Includes provisioned but not yet deployed |
| `gw_pre` | Gateway pre-allocated IPs | Shown as returned. With a location, pre-allocates Mobile User IPs there |
| `pt` | GlobalProtect Portal (deployed) | |
| `rbi` | Remote Browser Isolation | |
| `rn` | Remote Network (deployed) | Currently active remote networks |
| `rn_all` | Remote Network (all) | Includes provisioned but not yet deployed |
| `swg` | SWG Proxy (deployed) | Excludes IPs also in `swg_lb` |
| `swg_lb` | SWG Network Load Balancer | |
| `swg_all` | SWG Proxy (all) | Excludes IPs also in `swg_lb` |
| `all` | Composite: every type, all locations | |
| `all_deployed` | Composite: every type, deployed only | |

**Deployed vs. all:** "deployed" returns IPs for infrastructure that is active now; "all" also
includes IPs that are provisioned but not yet in service.

**Overlaps:** `swg` and `swg_all` exclude the load balancer IPs, which have their own `swg_lb`
entry. In the `all` composite, pre-allocated IPs that also appear in `gw_all` or `swg_all` are
counted once.

For Remote Network types (`rn`, `rn_all`), results also list the sites behind each IP.

## Scripting

The tool is meant to be used through its web page. Its `/api/...` endpoints exist only to serve
that page, aren't a supported interface, and can change in any release. To automate egress IP
lookups, call the Prisma Access egress IP API directly with your API key, the same API this tool
uses; it's described in the Prisma Access documentation.
