"""Shared domain vocabulary for the venue.

Types, money arithmetic, event records, and error definitions that every service agrees on.
Pure library: no I/O beyond reading a config file, no framework imports, so it stays trivially
testable and cannot drift between services (.claude/docs/01-domain-model.md).
"""

from market_core.clock import Clock, FixedClock, SystemClock, format_timestamp
from market_core.enums import CancelReason, OrderStatus, OrderType, Side, TimeInForce
from market_core.errors import ErrorCode, MarketError
from market_core.events import (
    EVENT_TYPES,
    BookDelta,
    Event,
    OrderAccepted,
    OrderCancelled,
    OrderFilled,
    OrderRejected,
    Trade,
    order_from_dict,
    order_to_dict,
)
from market_core.ids import (
    IdGenerator,
    SequentialIdGenerator,
    UlidGenerator,
    make_ulid,
    validate_client_order_id,
)
from market_core.instruments import USDCAD, Instrument, InstrumentRegistry
from market_core.orders import Order
from market_core.units import (
    CENTS,
    PRICE_SCALE,
    affordable_quantity,
    format_price,
    format_quantity,
    notional_cad,
    parse_price,
    parse_quantity,
)

__all__ = [
    "CENTS",
    "EVENT_TYPES",
    "PRICE_SCALE",
    "USDCAD",
    "BookDelta",
    "CancelReason",
    "Clock",
    "ErrorCode",
    "Event",
    "FixedClock",
    "IdGenerator",
    "Instrument",
    "InstrumentRegistry",
    "MarketError",
    "Order",
    "OrderAccepted",
    "OrderCancelled",
    "OrderFilled",
    "OrderRejected",
    "OrderStatus",
    "OrderType",
    "SequentialIdGenerator",
    "Side",
    "SystemClock",
    "TimeInForce",
    "Trade",
    "UlidGenerator",
    "affordable_quantity",
    "format_price",
    "format_quantity",
    "format_timestamp",
    "make_ulid",
    "notional_cad",
    "order_from_dict",
    "order_to_dict",
    "parse_price",
    "parse_quantity",
    "validate_client_order_id",
]
