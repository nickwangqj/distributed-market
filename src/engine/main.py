"""Matching engine service.

Phase 1 stub, extended in Phase 2 with the data-directory lock and a heartbeat file so the
volume mount and the single-engine guarantee are both proven before any trading logic exists.

Phase 7 replaces the body of this with the real engine: the serialized command loop, the
journal, and the SSE event stream (.claude/docs/04-matching-engine.md).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import FastAPI

from service_common import DataDirectoryLocked, SingleWriterLock, bootstrap, create_app

logger = logging.getLogger(__name__)

settings = bootstrap("engine")
lock = SingleWriterLock(settings.data_dir)

HEARTBEAT_SECONDS = 5.0


async def _heartbeat() -> None:
    """Write proof-of-life to the volume, so a mount that is missing or read-only is loud."""
    path = settings.data_dir / "state" / "engine-heartbeat.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        payload = {
            "service": settings.service,
            "ts": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "data_dir": str(settings.data_dir),
        }
        path.write_text(json.dumps(payload) + "\n")
        await asyncio.sleep(HEARTBEAT_SECONDS)


async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_heartbeat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = create_app(settings, lifespan=lifespan)


def run() -> None:
    import uvicorn

    try:
        lock.acquire()
    except DataDirectoryLocked as exc:
        # Exiting non-zero is the whole point: a second engine must never reach the book.
        logger.error("refusing to start", extra={"reason": str(exc)})
        sys.exit(1)

    try:
        # Binding all interfaces is intentional: the process only ever runs inside a container.
        uvicorn.run(app, host="0.0.0.0", port=settings.port, log_config=None)
    finally:
        lock.release()


if __name__ == "__main__":
    run()
