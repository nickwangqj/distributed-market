"""The order record (.claude/docs/01-domain-model.md §4, §5).

Orders are immutable: every transition returns a new instance. There is no in-place amend in
this phase — a client changes an order by cancelling and submitting a new one (decision K7 in
the gateway doc), which is also why nothing here mutates.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from market_core.enums import CancelReason, OrderStatus, OrderType, Side, TimeInForce


@dataclass(frozen=True, slots=True)
class Order:
    """One order, at one point in its life."""

    order_id: str
    client_order_id: str
    account_id: str
    symbol: str
    side: Side
    order_type: OrderType
    time_in_force: TimeInForce
    price: int | None  # ticks; None for MARKET
    quantity: int  # USD cents, original
    filled_quantity: int  # USD cents, cumulative
    status: OrderStatus
    created_seq: int
    created_at: str  # RFC3339, informational only — never used for ordering
    cancel_reason: CancelReason | None = None
    #: CAD cents locked for this order. Only a market BUY needs it at match time, where it is a
    #: hard spending limit (decision D7); it is carried for every order so the engine never has
    #: to special-case reading it.
    reserved_cad: int | None = None

    def __post_init__(self) -> None:
        if self.order_type is OrderType.MARKET and self.price is not None:
            raise ValueError("a market order must not carry a price")
        if self.order_type is OrderType.LIMIT and self.price is None:
            raise ValueError("a limit order must carry a price")
        if self.order_type is OrderType.MARKET and self.time_in_force is not TimeInForce.IOC:
            raise ValueError("a market order is always IOC and can never rest")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if not 0 <= self.filled_quantity <= self.quantity:
            raise ValueError(
                f"filled_quantity must be within [0, {self.quantity}], got {self.filled_quantity}"
            )

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled_quantity

    @property
    def rests_on_the_book(self) -> bool:
        """Only a GTC limit order can leave a remainder resting (decision D10)."""
        return self.order_type is OrderType.LIMIT and self.time_in_force is TimeInForce.GTC

    def fill(self, quantity: int) -> Order:
        """Apply a fill, returning the order at its new status."""
        if quantity <= 0:
            raise ValueError(f"fill quantity must be positive, got {quantity}")
        if quantity > self.remaining:
            raise ValueError(f"fill of {quantity} exceeds remaining {self.remaining}")

        filled = self.filled_quantity + quantity
        status = OrderStatus.FILLED if filled == self.quantity else OrderStatus.PARTIAL
        return replace(self, filled_quantity=filled, status=status)

    def cancel(self, reason: CancelReason) -> Order:
        """Terminate the order, keeping whatever it had already filled."""
        if self.status.is_terminal:
            raise ValueError(f"cannot cancel an order in terminal status {self.status}")
        return replace(self, status=OrderStatus.CANCELLED, cancel_reason=reason)

    def reject(self) -> Order:
        if self.status.is_terminal:
            raise ValueError(f"cannot reject an order in terminal status {self.status}")
        return replace(self, status=OrderStatus.REJECTED)

    def open_on_book(self) -> Order:
        """Mark a remainder as resting — OPEN if untouched, PARTIAL if it already traded."""
        if not self.rests_on_the_book:
            raise ValueError(f"{self.order_type}/{self.time_in_force} orders never rest")
        status = OrderStatus.PARTIAL if self.filled_quantity else OrderStatus.OPEN
        return replace(self, status=status)

    def crosses(self, maker_price: int) -> bool:
        """Would this order trade against a resting order at `maker_price`?

        A market order has no price bound, so it crosses everything. A limit order accepts its
        limit price or better, never worse — which is why the comparison flips with the side
        (.claude/docs/04-matching-engine.md §4).
        """
        if self.price is None:
            return True
        if self.side is Side.BUY:
            return maker_price <= self.price
        return maker_price >= self.price
