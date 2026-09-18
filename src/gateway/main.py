"""Public REST API service.

Phase 1 stub. Phase 9 adds authentication, validation, idempotency, and the reserve-then-submit
order path (.claude/docs/02-api-gateway.md).

Its readiness check is already real: the gateway reports ready only while both the engine and the
ledger are reachable, which is what gates startup order in Kubernetes and what proves the compose
network is wired correctly (.claude/docs/08-deployment.md §6).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from service_common import Readiness, bootstrap, create_app

logger = logging.getLogger(__name__)

settings = bootstrap("gateway")

PEER_TIMEOUT_SECONDS = 2.0


async def _peer_healthy(client: httpx.AsyncClient, name: str, base_url: str) -> str | None:
    """Return None when the peer is healthy, else a short reason."""
    try:
        response = await client.get(f"{base_url}/healthz", timeout=PEER_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return f"{name} unreachable ({type(exc).__name__})"
    if response.status_code != httpx.codes.OK:
        return f"{name} returned {response.status_code}"
    return None


async def check_peers() -> Readiness:
    """Ready only when both the engine and the ledger answer their health probe."""
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            _peer_healthy(client, "engine", settings.engine_url),
            _peer_healthy(client, "ledger", settings.ledger_url),
        )
    problems = [reason for reason in results if reason is not None]
    if problems:
        logger.warning("gateway not ready", extra={"problems": problems})
        return Readiness(ready=False, detail="; ".join(problems))
    return Readiness(ready=True)


app = create_app(settings, readiness=check_peers)
