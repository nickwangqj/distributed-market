"""Identifiers and injected time (.claude/docs/01-domain-model.md §3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from market_core import FixedClock, SequentialIdGenerator, UlidGenerator, make_ulid
from market_core.clock import SystemClock, format_timestamp
from market_core.ids import MAX_CLIENT_ORDER_ID, validate_client_order_id


class TestUlid:
    def test_is_26_crockford_characters(self) -> None:
        ulid = make_ulid(FixedClock())
        assert len(ulid) == 26
        assert set(ulid) <= set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")

    def test_excludes_ambiguous_letters(self) -> None:
        """Crockford drops I, L, O and U so an id cannot be misread or mistyped."""
        ulid = make_ulid(FixedClock(), randomness=0)
        assert not (set(ulid) & set("ILOU"))

    def test_sorts_chronologically(self) -> None:
        """The property that makes a log grep or a directory listing chronological."""
        clock = FixedClock()
        earlier = make_ulid(clock, randomness=0)
        clock.advance(1)
        later = make_ulid(clock, randomness=0)
        assert earlier < later

    def test_distinct_within_the_same_millisecond(self) -> None:
        clock = FixedClock()
        ids = {make_ulid(clock) for _ in range(1000)}
        assert len(ids) == 1000


class TestGenerators:
    def test_real_generator_prefixes(self) -> None:
        gen = UlidGenerator(FixedClock())
        assert gen.order_id().startswith("ord_")
        assert gen.trade_id().startswith("trd_")
        assert gen.account_id().startswith("acct_")

    def test_account_id_is_eight_hex_characters(self) -> None:
        account_id = UlidGenerator(FixedClock()).account_id()
        suffix = account_id.removeprefix("acct_")
        assert len(suffix) == 8
        int(suffix, 16)  # raises if it is not hex

    def test_sequential_generator_is_deterministic(self) -> None:
        """Tests must not depend on randomness (.claude/docs/09-testing-strategy.md §5)."""
        first, second = SequentialIdGenerator(), SequentialIdGenerator()
        assert [first.order_id() for _ in range(3)] == [second.order_id() for _ in range(3)]
        assert first.order_id() != first.order_id()


class TestClock:
    def test_system_clock_is_timezone_aware_utc(self) -> None:
        assert SystemClock().now().tzinfo is UTC

    def test_fixed_clock_does_not_move_on_its_own(self) -> None:
        clock = FixedClock()
        assert clock.now() == clock.now()
        clock.advance(60)
        assert clock.now() == datetime(2026, 1, 1, 0, 1, tzinfo=UTC)

    def test_timestamp_format_has_milliseconds(self) -> None:
        assert format_timestamp(FixedClock().now()) == "2026-01-01T00:00:00.000+00:00"


class TestClientOrderId:
    def test_accepts_an_ordinary_key(self) -> None:
        assert validate_client_order_id("alice-001") == "alice-001"

    @pytest.mark.parametrize(
        ("value", "why"),
        [
            ("", "empty"),
            ("x" * (MAX_CLIENT_ORDER_ID + 1), "too long"),
            ("has space", "whitespace"),
            ("tab\there", "whitespace"),
        ],
    )
    def test_rejects_unusable_keys(self, value: str, why: str) -> None:
        with pytest.raises(ValueError):
            validate_client_order_id(value)
