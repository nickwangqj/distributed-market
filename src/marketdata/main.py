"""Market data service.

Phase 1 stub. Phase 10 adds the L2 replica and the WebSocket fan-out
(.claude/docs/07-market-data.md).
"""

from __future__ import annotations

from service_common import bootstrap, create_app

settings = bootstrap("marketdata")
app = create_app(settings)
