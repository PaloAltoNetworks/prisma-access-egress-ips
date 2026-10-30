"""
FastAPI application entry point.

Serves the static web frontend from /web and mounts the API routers under /api.
"""

import logging
from contextlib import asynccontextmanager
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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("%s %s starting", app.title, app.version)
    yield


app = FastAPI(
    title="Prisma Access Egress IP Utility",
    version=version("prisma-access-egress-ips"),
    lifespan=lifespan,
    # /api serves the web page only and isn't offered as an interface: no published docs or schema
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# The page loads only its own script, styles and images, and talks only to this server.
# index.html has no inline scripts, handlers or styles, so nothing needs 'unsafe-inline'.
_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def _add_headers(path: str, response):
    # The page and its assets revalidate on every load, so an upgraded container never
    # runs a cached app.js against a newer server. API responses carry credentials' results
    # and are never stored.
    is_page = path == "/" or path.startswith("/static/")
    response.headers["Cache-Control"] = "no-cache" if is_page else "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = _CSP
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    return _add_headers(request.url.path, await call_next(request))


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception) -> JSONResponse:
    # Unhandled errors are answered outside the middleware above, so add the headers here.
    # Starlette still re-raises the exception afterwards, so it's logged as before.
    return _add_headers(request.url.path, JSONResponse(status_code=500, content={"detail": "Internal Server Error"}))


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
    return {"status": "ok", "version": app.version}
