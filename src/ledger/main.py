"""Account ledger service.

Phase 1 stub. Phase 8 adds balances, reservations, and settlement from the engine's event
stream (.claude/docs/05-account-ledger.md).
"""

from __future__ import annotations

from service_common import bootstrap, create_app

settings = bootstrap("ledger")
app = create_app(settings)
