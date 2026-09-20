"""Money arithmetic — the rounding rule is the exit criterion for Phase 3."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from market_core import PRICE_SCALE, Side, affordable_quantity, notional_cad
from market_core.units import format_price, format_quantity, parse_price, parse_quantity


class TestNotionalRounding:
    """The worked table from .claude/docs/01-domain-model.md §2.1, verbatim."""

    @pytest.mark.parametrize(
        ("quantity", "price", "buy_expected", "sell_expected", "note"),
        [
            (100, 137_504, 138, 138, "137.504 rounds to nearest, same both sides"),
            (100, 137_501, 138, 138, "137.501 rounds to nearest, same both sides"),
            (100, 137_499, 137, 137, "137.499 rounds to nearest, same both sides"),
            (100, 137_500, 138, 137, "137.5 is a tie: against the taker, either way"),
            (200, 137_500, 275, 275, "275.0 exactly: nothing to round"),
        ],
    )
    def test_worked_table(
        self, quantity: int, price: int, buy_expected: int, sell_expected: int, note: str
    ) -> None:
        assert notional_cad(quantity, price, Side.BUY) == buy_expected, note
        assert notional_cad(quantity, price, Side.SELL) == sell_expected, note

    def test_tie_direction_flips_with_the_taker(self) -> None:
        """The whole point of the rule: the *taker* absorbs the half cent, whichever side it is."""
        buy = notional_cad(100, 137_500, Side.BUY)
        sell = notional_cad(100, 137_500, Side.SELL)
        assert buy - sell == 1
        assert buy > sell  # the buyer pays more, the seller receives less

    def test_near_tie_is_not_a_tie(self) -> None:
        """Guards an implementation that treats "close to half" as a tie."""
        assert notional_cad(100, 137_501, Side.BUY) == notional_cad(100, 137_501, Side.SELL)

    def test_rejects_negative_inputs(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            notional_cad(-100, 137_500, Side.BUY)


class TestNotionalProperties:
    @given(
        quantity=st.integers(min_value=0, max_value=10**9),
        price=st.integers(min_value=1, max_value=10**7),
        side=st.sampled_from(Side),
    )
    def test_never_more_than_half_a_cent_from_exact(
        self, quantity: int, price: int, side: Side
    ) -> None:
        """Rounding to nearest, so the error is bounded by half a cent — in either direction."""
        result = notional_cad(quantity, price, side)
        exact_scaled = quantity * price
        assert abs(result * PRICE_SCALE - exact_scaled) * 2 <= PRICE_SCALE

    @given(
        quantity=st.integers(min_value=0, max_value=10**8),
        price=st.integers(min_value=1, max_value=10**7),
    )
    def test_the_two_sides_differ_by_at_most_one_cent(self, quantity: int, price: int) -> None:
        """Side only ever decides a tie, so it can move the answer by at most one cent."""
        buy = notional_cad(quantity, price, Side.BUY)
        sell = notional_cad(quantity, price, Side.SELL)
        assert buy - sell in (0, 1)

    @given(
        a=st.integers(min_value=0, max_value=10**8),
        b=st.integers(min_value=0, max_value=10**8),
        price=st.integers(min_value=1, max_value=10**7),
        side=st.sampled_from(Side),
    )
    def test_monotonic_in_quantity(self, a: int, b: int, price: int, side: Side) -> None:
        """More quantity never costs less."""
        low, high = sorted((a, b))
        assert notional_cad(low, price, side) <= notional_cad(high, price, side)


class TestAffordableQuantity:
    def test_worked_example_from_the_ledger_doc(self) -> None:
        """C$100,000.00 at 1.37520 buys $72,716.00 — see .claude/docs/05-account-ledger.md §3.1."""
        assert affordable_quantity(10_000_000, 137_520, lot_size=100) == 7_271_600

    def test_result_is_always_affordable(self) -> None:
        """The clamp's reason for existing: a fill it permits can never exceed the reservation."""
        reserved, price = 10_000_000, 137_520
        quantity = affordable_quantity(reserved, price, lot_size=100)
        assert notional_cad(quantity, price, Side.BUY) <= reserved

    @given(
        reserved=st.integers(min_value=0, max_value=10**9),
        price=st.integers(min_value=1, max_value=10**7),
        lot_size=st.sampled_from([1, 10, 100, 1000]),
    )
    def test_never_permits_overspending(self, reserved: int, price: int, lot_size: int) -> None:
        quantity = affordable_quantity(reserved, price, lot_size)
        assert quantity >= 0
        assert quantity % lot_size == 0
        assert notional_cad(quantity, price, Side.BUY) <= reserved

    def test_rejects_nonsense_configuration(self) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            affordable_quantity(1000, 0, lot_size=100)
        with pytest.raises(ValueError, match="lot_size must be positive"):
            affordable_quantity(1000, 137_500, lot_size=0)


class TestWireConversion:
    @pytest.mark.parametrize(
        ("text", "cents"),
        [("1000.00", 100_000), ("0.01", 1), ("0", 0), ("72716.00", 7_271_600)],
    )
    def test_quantity_round_trip(self, text: str, cents: int) -> None:
        assert parse_quantity(text) == cents
        assert parse_quantity(format_quantity(cents)) == cents

    @pytest.mark.parametrize(
        ("text", "ticks"),
        [("1.37500", 137_500), ("1.37501", 137_501), ("0.00001", 1)],
    )
    def test_price_round_trip(self, text: str, ticks: int) -> None:
        assert parse_price(text) == ticks
        assert format_price(ticks) == text

    def test_rejects_excess_precision(self) -> None:
        """Silently truncating a client's extra digit would lose money quietly."""
        with pytest.raises(ValueError, match="decimal places"):
            parse_quantity("1.005")
        with pytest.raises(ValueError, match="decimal places"):
            parse_price("1.375005")

    @pytest.mark.parametrize("text", ["", "abc", "1.0.0", "NaN", "Infinity"])
    def test_rejects_non_numbers(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_quantity(text)
