"""The closed vocabularies every service shares (.claude/docs/01-domain-model.md §4, §6)."""

from __future__ import annotations

from enum import StrEnum


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(StrEnum):
    """`FOK` and `GTD` are deliberately absent (decision D10).

    An enum rather than a boolean precisely so that adding them later is an additive change to
    this type and the validator, not a new field on the wire.
    """

    GTC = "GTC"
    IOC = "IOC"


class OrderStatus(StrEnum):
    PENDING = "PENDING"  # accepted by the gateway, funds reserved, not yet sequenced
    OPEN = "OPEN"  # resting on the book (limit only)
    PARTIAL = "PARTIAL"  # resting, partially filled
    FILLED = "FILLED"  # terminal
    CANCELLED = "CANCELLED"  # terminal — by owner, or an IOC/STP/cap remainder
    REJECTED = "REJECTED"  # terminal — validation or funds failure

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL

    @property
    def is_resting(self) -> bool:
        """True while the order occupies a place in the book."""
        return self in (OrderStatus.OPEN, OrderStatus.PARTIAL)


_TERMINAL = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
)


class CancelReason(StrEnum):
    USER = "USER"
    IOC_REMAINDER = "IOC_REMAINDER"  # market orders and IOC limit orders alike
    NOTIONAL_CAP_REACHED = "NOTIONAL_CAP_REACHED"  # market buy hit its reservation cap
    SELF_TRADE_PREVENTION = "SELF_TRADE_PREVENTION"  # cancels the *resting* order (D6)
    ADMIN = "ADMIN"
