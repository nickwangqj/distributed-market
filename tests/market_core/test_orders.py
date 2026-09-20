"""The order record and its lifecycle (.claude/docs/01-domain-model.md §5)."""

from __future__ import annotations

import pytest

from market_core import CancelReason, Order, OrderStatus, OrderType, Side, TimeInForce


def make_order(**overrides: object) -> Order:
    defaults: dict[str, object] = {
        "order_id": "ord_1",
        "client_order_id": "cli-1",
        "account_id": "acct_0001",
        "symbol": "USDCAD",
        "side": Side.BUY,
        "order_type": OrderType.LIMIT,
        "time_in_force": TimeInForce.GTC,
        "price": 137_500,
        "quantity": 100_000,
        "filled_quantity": 0,
        "status": OrderStatus.PENDING,
        "created_seq": 1,
        "created_at": "2026-01-01T00:00:00.000+00:00",
    }
    return Order(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestConstruction:
    def test_market_order_must_not_carry_a_price(self) -> None:
        with pytest.raises(ValueError, match="must not carry a price"):
            make_order(order_type=OrderType.MARKET, time_in_force=TimeInForce.IOC, price=137_500)

    def test_limit_order_must_carry_a_price(self) -> None:
        with pytest.raises(ValueError, match="must carry a price"):
            make_order(price=None)

    def test_market_order_cannot_be_gtc(self) -> None:
        """MARKET + GTC is rejected: a market order can never rest (decision D10)."""
        with pytest.raises(ValueError, match="always IOC"):
            make_order(order_type=OrderType.MARKET, price=None, time_in_force=TimeInForce.GTC)

    def test_filled_cannot_exceed_quantity(self) -> None:
        with pytest.raises(ValueError, match="filled_quantity"):
            make_order(filled_quantity=100_001)


class TestFilling:
    def test_partial_fill_leaves_the_order_partial(self) -> None:
        order = make_order().fill(40_000)
        assert order.filled_quantity == 40_000
        assert order.remaining == 60_000
        assert order.status is OrderStatus.PARTIAL

    def test_filling_the_remainder_completes_the_order(self) -> None:
        order = make_order().fill(40_000).fill(60_000)
        assert order.status is OrderStatus.FILLED
        assert order.remaining == 0

    def test_cannot_overfill(self) -> None:
        with pytest.raises(ValueError, match="exceeds remaining"):
            make_order().fill(100_001)

    def test_fills_do_not_mutate_the_original(self) -> None:
        """Orders are immutable, which is what makes replay reproduce state exactly."""
        original = make_order()
        original.fill(40_000)
        assert original.filled_quantity == 0


class TestTermination:
    def test_cancel_keeps_what_was_filled(self) -> None:
        order = make_order().fill(40_000).cancel(CancelReason.USER)
        assert order.status is OrderStatus.CANCELLED
        assert order.cancel_reason is CancelReason.USER
        assert order.filled_quantity == 40_000

    def test_cannot_cancel_a_terminal_order(self) -> None:
        order = make_order().fill(100_000)
        with pytest.raises(ValueError, match="terminal"):
            order.cancel(CancelReason.USER)

    @pytest.mark.parametrize(
        "status", [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]
    )
    def test_terminal_statuses(self, status: OrderStatus) -> None:
        assert status.is_terminal

    @pytest.mark.parametrize("status", [OrderStatus.OPEN, OrderStatus.PARTIAL])
    def test_resting_statuses(self, status: OrderStatus) -> None:
        assert status.is_resting
        assert not status.is_terminal


class TestResting:
    def test_gtc_limit_order_rests(self) -> None:
        assert make_order().rests_on_the_book

    def test_ioc_limit_order_does_not_rest(self) -> None:
        assert not make_order(time_in_force=TimeInForce.IOC).rests_on_the_book

    def test_market_order_does_not_rest(self) -> None:
        market = make_order(order_type=OrderType.MARKET, price=None, time_in_force=TimeInForce.IOC)
        assert not market.rests_on_the_book
        with pytest.raises(ValueError, match="never rest"):
            market.open_on_book()

    def test_untouched_remainder_opens_partially_filled_one_is_partial(self) -> None:
        assert make_order().open_on_book().status is OrderStatus.OPEN
        assert make_order().fill(40_000).open_on_book().status is OrderStatus.PARTIAL


class TestCrossing:
    """The crossing condition from .claude/docs/04-matching-engine.md §4, worked by example."""

    def test_buy_crosses_asks_at_or_below_its_limit(self) -> None:
        buy = make_order(side=Side.BUY, price=137_520)
        assert buy.crosses(137_515)  # better than the limit
        assert buy.crosses(137_520)  # equality crosses — it trades, it does not rest
        assert not buy.crosses(137_530)  # worse than the limit

    def test_sell_crosses_bids_at_or_above_its_limit(self) -> None:
        sell = make_order(side=Side.SELL, price=137_490)
        assert sell.crosses(137_495)
        assert sell.crosses(137_490)
        assert not sell.crosses(137_485)

    def test_market_order_crosses_anything(self) -> None:
        market = make_order(order_type=OrderType.MARKET, price=None, time_in_force=TimeInForce.IOC)
        assert market.crosses(1)
        assert market.crosses(10**9)

    def test_non_crossing_limit_order_rests_instead(self) -> None:
        """`SELL LIMIT @ 1.37500` against a best bid of 1.37495 trades nothing."""
        sell = make_order(side=Side.SELL, price=137_500)
        assert not sell.crosses(137_495)
        assert sell.rests_on_the_book
