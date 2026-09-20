"""Money, prices, and the arithmetic that moves between them.

Floats are banned in this module and everywhere downstream of it. Quantities and prices are
integers in minor units (.claude/docs/01-domain-model.md §2); decimal strings exist only at the
REST and WebSocket boundary, which is what `parse_*` and `format_*` are for.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from market_core.enums import Side

#: Price is quoted in ticks of 0.00001 CAD per USD, so a price times a USD-cent quantity is
#: scaled by 10**5 relative to CAD cents.
PRICE_SCALE = 10**5

#: Minor units per major unit, for both currencies.
CENTS = 100

#: Decimal places shown on the wire.
QUANTITY_DECIMALS = 2
PRICE_DECIMALS = 5


def notional_cad(quantity: int, price: int, taker_side: Side) -> int:
    """CAD cents owed for a fill of `quantity` USD cents at `price` ticks.

    Rounds to the nearest cent; on an exact half-cent tie, rounds **against the taker** — the
    taker chose to cross the spread, so it absorbs the ambiguity (decision K5).

    The result is a single number used for *both* legs of the trade: the taker's debit and the
    maker's credit are the same integer, which is what makes money conservation hold by
    construction. Computing the two sides separately would be a defect.
    """
    if quantity < 0 or price < 0:
        raise ValueError(f"quantity and price must be non-negative, got {quantity=} {price=}")

    whole, remainder = divmod(quantity * price, PRICE_SCALE)
    if remainder * 2 > PRICE_SCALE:
        return whole + 1
    if remainder * 2 == PRICE_SCALE and taker_side is Side.BUY:
        # The tie falls against the taker: a buyer pays the extra cent, a seller forgoes it.
        return whole + 1
    return whole


def affordable_quantity(reserved_cad: int, price: int, lot_size: int) -> int:
    """The largest whole-lot USD quantity that `reserved_cad` cents can buy at `price`.

    Used by the engine to clamp a market buy to its reservation (decision D7). Deliberately
    conservative: it floors twice, so the resulting fill can never cost more than was reserved.
    """
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")
    if lot_size <= 0:
        raise ValueError(f"lot_size must be positive, got {lot_size}")

    quantity = reserved_cad * PRICE_SCALE // price
    return quantity - quantity % lot_size


def _parse_decimal(text: str, scale: int, places: int, what: str) -> int:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{what} is not a decimal number: {text!r}") from exc

    if value.is_nan() or value.is_infinite():
        raise ValueError(f"{what} must be finite: {text!r}")

    scaled = value * scale
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{what} has more than {places} decimal places: {text!r}")
    return int(scaled)


def parse_quantity(text: str) -> int:
    """`"1000.00"` -> `100_000` USD cents."""
    return _parse_decimal(text, CENTS, QUANTITY_DECIMALS, "quantity")


def parse_price(text: str) -> int:
    """`"1.37500"` -> `137_500` ticks."""
    return _parse_decimal(text, PRICE_SCALE, PRICE_DECIMALS, "price")


def format_quantity(cents: int) -> str:
    """`100_000` -> `"1000.00"`. Strings on the wire keep clients out of float trouble."""
    return f"{Decimal(cents) / CENTS:.{QUANTITY_DECIMALS}f}"


def format_price(ticks: int) -> str:
    """`137_500` -> `"1.37500"`."""
    return f"{Decimal(ticks) / PRICE_SCALE:.{PRICE_DECIMALS}f}"
