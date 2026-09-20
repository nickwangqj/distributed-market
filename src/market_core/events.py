"""The engine's event records — the contract between every service.

Every engine state change emits exactly one event, each with its own `seq`, and a single client
action expands into a contiguous run of them (.claude/docs/01-domain-model.md §6). The journal
is a log of these; the ledger settles from them; market data is built from them.

They are frozen dataclasses with an explicit JSON shape rather than pydantic models: they cross
a process boundary as journal lines, so their serialization has to be exactly what is written to
disk, and nothing here should depend on a web framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from market_core.enums import CancelReason, OrderStatus, OrderType, Side, TimeInForce
from market_core.orders import Order


@dataclass(frozen=True, slots=True)
class Event:
    """Common head of every event: where it sits in the sequence, and when it happened."""

    seq: int
    ts: str

    #: Discriminator written into the journal and the market-data feed.
    type: ClassVar[str] = "Event"

    def payload(self) -> dict[str, Any]:  # pragma: no cover - overridden by every subclass
        raise NotImplementedError

    def to_record(self) -> dict[str, Any]:
        """The journal line, minus the framing (crc) the store adds."""
        return {"seq": self.seq, "ts": self.ts, "type": self.type, "payload": self.payload()}


@dataclass(frozen=True, slots=True)
class OrderAccepted(Event):
    order: Order = field(kw_only=True)

    type: ClassVar[str] = "OrderAccepted"

    def payload(self) -> dict[str, Any]:
        return {"order": order_to_dict(self.order)}


@dataclass(frozen=True, slots=True)
class OrderRejected(Event):
    order_id: str = field(kw_only=True)
    reason: str = field(kw_only=True)

    type: ClassVar[str] = "OrderRejected"

    def payload(self) -> dict[str, Any]:
        return {"order_id": self.order_id, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Trade(Event):
    trade_id: str = field(kw_only=True)
    symbol: str = field(kw_only=True)
    price: int = field(kw_only=True)
    quantity: int = field(kw_only=True)
    taker_order_id: str = field(kw_only=True)
    maker_order_id: str = field(kw_only=True)
    taker_account_id: str = field(kw_only=True)
    maker_account_id: str = field(kw_only=True)
    taker_side: Side = field(kw_only=True)

    type: ClassVar[str] = "Trade"

    def __post_init__(self) -> None:
        # An account trading with itself is precisely what self-trade prevention exists to stop
        # (.claude/docs/04-matching-engine.md §4.1); if one ever reaches this constructor, the
        # matching logic is broken and the journal must not record it.
        if self.taker_account_id == self.maker_account_id:
            raise ValueError(
                f"self-trade for account {self.taker_account_id}: "
                "self-trade prevention should have cancelled the resting order"
            )
        if self.quantity <= 0:
            raise ValueError(f"trade quantity must be positive, got {self.quantity}")

    def payload(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "price": self.price,
            "quantity": self.quantity,
            "taker_order_id": self.taker_order_id,
            "maker_order_id": self.maker_order_id,
            "taker_account_id": self.taker_account_id,
            "maker_account_id": self.maker_account_id,
            "taker_side": str(self.taker_side),
        }


@dataclass(frozen=True, slots=True)
class OrderFilled(Event):
    order_id: str = field(kw_only=True)
    filled_qty: int = field(kw_only=True)
    remaining: int = field(kw_only=True)
    status: OrderStatus = field(kw_only=True)

    type: ClassVar[str] = "OrderFilled"

    def payload(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "filled_qty": self.filled_qty,
            "remaining": self.remaining,
            "status": str(self.status),
        }


@dataclass(frozen=True, slots=True)
class OrderCancelled(Event):
    order_id: str = field(kw_only=True)
    reason: CancelReason = field(kw_only=True)

    type: ClassVar[str] = "OrderCancelled"

    def payload(self) -> dict[str, Any]:
        return {"order_id": self.order_id, "reason": str(self.reason)}


@dataclass(frozen=True, slots=True)
class BookDelta(Event):
    """A price level's new absolute quantity. `new_qty == 0` means the level is gone.

    Absolute, never a signed change: a dropped message then corrupts one level recoverably
    instead of permanently (.claude/docs/07-market-data.md §3).
    """

    side: Side = field(kw_only=True)
    price: int = field(kw_only=True)
    new_qty: int = field(kw_only=True)

    type: ClassVar[str] = "BookDelta"

    def payload(self) -> dict[str, Any]:
        return {"side": str(self.side), "price": self.price, "new_qty": self.new_qty}


def order_to_dict(order: Order) -> dict[str, Any]:
    """Serialize an order for the journal. Integers stay integers; enums become their values."""
    return {
        "order_id": order.order_id,
        "client_order_id": order.client_order_id,
        "account_id": order.account_id,
        "symbol": order.symbol,
        "side": str(order.side),
        "order_type": str(order.order_type),
        "time_in_force": str(order.time_in_force),
        "price": order.price,
        "quantity": order.quantity,
        "filled_quantity": order.filled_quantity,
        "status": str(order.status),
        "created_seq": order.created_seq,
        "created_at": order.created_at,
        "cancel_reason": str(order.cancel_reason) if order.cancel_reason else None,
        "reserved_cad": order.reserved_cad,
    }


def order_from_dict(raw: dict[str, Any]) -> Order:
    """Rebuild an order from a journal line. The inverse of `order_to_dict`."""
    reason = raw.get("cancel_reason")
    return Order(
        order_id=raw["order_id"],
        client_order_id=raw["client_order_id"],
        account_id=raw["account_id"],
        symbol=raw["symbol"],
        side=Side(raw["side"]),
        order_type=OrderType(raw["order_type"]),
        time_in_force=TimeInForce(raw["time_in_force"]),
        price=raw["price"],
        quantity=raw["quantity"],
        filled_quantity=raw["filled_quantity"],
        status=OrderStatus(raw["status"]),
        created_seq=raw["created_seq"],
        created_at=raw["created_at"],
        cancel_reason=CancelReason(reason) if reason else None,
        reserved_cad=raw.get("reserved_cad"),
    )


#: Every event type, keyed by its discriminator — the engine's replay path and the market-data
#: consumer both dispatch on this.
EVENT_TYPES: dict[str, type[Event]] = {
    cls.type: cls
    for cls in (OrderAccepted, OrderRejected, Trade, OrderFilled, OrderCancelled, BookDelta)
}
