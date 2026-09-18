"""The health-probe application every service is built on.

Phase 1 ships each service as this and nothing else, so the deployment can be proven while it is
trivial to debug (.claude/docs/10-implementation-progress.md §2). Later phases mount real routers
onto the app returned here and supply a meaningful readiness check.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from service_common.logging import configure_logging
from service_common.settings import Settings, load_settings

logger = logging.getLogger(__name__)

PHASE = "1 — stub service, no trading logic"


@dataclass(frozen=True, slots=True)
class Readiness:
    """Outcome of a readiness check: ready, plus an explanation when it is not."""

    ready: bool
    detail: str = ""


ReadinessCheck = Callable[[], Awaitable[Readiness]]
Lifespan = Callable[[FastAPI], AsyncIterator[None]]


async def _always_ready() -> Readiness:
    return Readiness(ready=True)


def _package_version() -> str:
    try:
        return version("distributed-market")
    except PackageNotFoundError:  # running from a source tree without an install
        return "0.0.0+dev"


def bootstrap(service: str) -> Settings:
    """Load settings and install JSON logging. Call this before building the app."""
    settings = load_settings(service)
    configure_logging(service, settings.log_level)
    return settings


def create_app(
    settings: Settings,
    *,
    readiness: ReadinessCheck | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    """Build a service app with `/healthz`, `/readyz`, and `/version`.

    `readiness` is what separates *alive* from *able to serve*: liveness only asks whether the
    process is running, while readiness gates traffic and startup order
    (.claude/docs/08-deployment.md §6).
    """
    check = readiness or _always_ready

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "service starting",
            extra={"port": settings.port, "data_dir": str(settings.data_dir)},
        )
        if lifespan is None:
            yield
        else:
            async for _ in lifespan(app):
                yield
        logger.info("service stopped")

    app = FastAPI(
        title=f"distributed-market {settings.service}",
        version=_package_version(),
        lifespan=_lifespan,
    )
    app.state.settings = settings

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": settings.service}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        result = await check()
        body = {"status": "ready" if result.ready else "not ready", "service": settings.service}
        if result.detail:
            body["detail"] = result.detail
        return JSONResponse(body, status_code=200 if result.ready else 503)

    @app.get("/version")
    async def version_() -> dict[str, str]:
        return {"service": settings.service, "version": _package_version(), "phase": PHASE}

    return app
