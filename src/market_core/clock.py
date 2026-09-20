"""Time, injected rather than read from the wall.

The engine never makes a decision from the clock — `seq` is what orders events
(.claude/docs/01-domain-model.md K2) — but timestamps are recorded on every event, and tests
must not depend on the wall clock (.claude/docs/09-testing-strategy.md §5).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Anything that can say what time it is."""

    def now(self) -> datetime: ...


class SystemClock:
    """The real clock. Always timezone-aware and always UTC."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class FixedClock:
    """A clock that does not move unless told to. For tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._now += timedelta(seconds=seconds)

    def set(self, moment: datetime) -> None:
        self._now = moment


def format_timestamp(moment: datetime) -> str:
    """RFC3339 with milliseconds, the form every event carries."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds")
