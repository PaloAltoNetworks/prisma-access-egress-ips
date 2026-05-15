"""
FastAPI application entry point.

Serves the static web frontend from /web and mounts the API routers under /api.
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.routers import auth, ips, locations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title="Prisma Access Egress IP Utility",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

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
