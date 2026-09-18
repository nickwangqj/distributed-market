"""Matching engine service.

Phase 1 stub. Phase 7 replaces this with the real engine: the serialized command loop, the
journal, and the SSE event stream (.claude/docs/04-matching-engine.md).
"""

from __future__ import annotations

import logging

from service_common import bootstrap, create_app

logger = logging.getLogger(__name__)

settings = bootstrap("engine")
app = create_app(settings)


def run() -> None:
    import uvicorn

    # Binding all interfaces is intentional: the process only ever runs inside a container.
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_config=None)


if __name__ == "__main__":
    run()
