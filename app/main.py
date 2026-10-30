"""
FastAPI application entry point.

Serves the static web frontend from /web and mounts the API routers under /api.
"""

import logging
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.routers import auth, ips, locations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title="Prisma Access Egress IP Utility",
    version=version("prisma-access-egress-ips"),
    # /api serves the web page only and isn't offered as an interface: no published docs or schema
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # The default handler echoes each rejected value back, which would put API keys and
    # secrets in proxy and browser logs. Keep only where and why; the UI shows msg.
    detail = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


app.include_router(ips.router)
app.include_router(locations.router)
app.include_router(auth.router)

# Serve the static frontend. The SPA catch-all below handles direct navigation.
_web_dir = Path(__file__).parent.parent / "web"
app.mount("/static", StaticFiles(directory=str(_web_dir)), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(str(_web_dir / "index.html"))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
