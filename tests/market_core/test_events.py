"""Event records and their journal round trip (.claude/docs/01-domain-model.md §6)."""

from __future__ import annotations

import json

import pytest

from market_core import (
    EVENT_TYPES,
    BookDelta,
    CancelReason,
    OrderAccepted,
    OrderCancelled,
    OrderFilled,
    OrderStatus,
    Side,
    Trade,
    order_from_dict,
    order_to_dict,
)
from tests.market_core.test_orders import make_order

TS = "2026-01-01T00:00:00.000+00:00"


class TestJournalRoundTrip:
    def test_order_survives_serialization(self) -> None:
        """Replay rebuilds orders from these dicts, so the round trip must be exact."""
        order = make_order().fill(40_000)
        assert order_from_dict(order_to_dict(order)) == order

    def test_cancelled_order_keeps_its_reason(self) -> None:
        order = make_order().cancel(CancelReason.SELF_TRADE_PREVENTION)
        assert (
            order_from_dict(order_to_dict(order)).cancel_reason
            is CancelReason.SELF_TRADE_PREVENTION
        )

    def test_every_event_is_json_serializable(self) -> None:
        """Events are journal lines; anything that cannot be written is unusable."""
        events = [
            OrderAccepted(seq=1, ts=TS, order=make_order()),
            Trade(
                seq=2,
                ts=TS,
                trade_id="trd_1",
                symbol="USDCAD",
                price=137_500,
                quantity=40_000,
                taker_order_id="ord_2",
                maker_order_id="ord_1",
                taker_account_id="acct_0002",
                maker_account_id="acct_0001",
                taker_side=Side.BUY,
            ),
            OrderFilled(
                seq=3,
                ts=TS,
                order_id="ord_1",
                filled_qty=40_000,
                remaining=60_000,
                status=OrderStatus.PARTIAL,
            ),
            OrderCancelled(seq=4, ts=TS, order_id="ord_1", reason=CancelReason.IOC_REMAINDER),
            BookDelta(seq=5, ts=TS, side=Side.BUY, price=137_500, new_qty=0),
        ]
        for event in events:
            record = event.to_record()
            assert json.loads(json.dumps(record)) == record
            assert record["type"] in EVENT_TYPES
            assert record["seq"] == event.seq


class TestTradeInvariants:
    def test_a_self_trade_cannot_be_constructed(self) -> None:
        """If one reaches this constructor the matching logic is broken; never journal it."""
        with pytest.raises(ValueError, match="self-trade"):
            Trade(
                seq=1,
                ts=TS,
                trade_id="trd_1",
                symbol="USDCAD",
                price=137_500,
                quantity=40_000,
                taker_order_id="ord_2",
                maker_order_id="ord_1",
                taker_account_id="acct_0001",
                maker_account_id="acct_0001",
                taker_side=Side.BUY,
            )

    def test_zero_quantity_trade_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            Trade(
                seq=1,
                ts=TS,
                trade_id="trd_1",
                symbol="USDCAD",
                price=137_500,
                quantity=0,
                taker_order_id="ord_2",
                maker_order_id="ord_1",
                taker_account_id="acct_0002",
                maker_account_id="acct_0001",
                taker_side=Side.BUY,
            )


class TestBookDelta:
    def test_zero_quantity_means_the_level_is_gone(self) -> None:
        """Absolute quantities, not signed changes — a dropped message stays recoverable."""
        delta = BookDelta(seq=1, ts=TS, side=Side.SELL, price=137_510, new_qty=0)
        assert delta.payload() == {"side": "SELL", "price": 137_510, "new_qty": 0}
