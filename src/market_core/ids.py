"""Identifier generation (.claude/docs/01-domain-model.md §3).

Order and trade ids are ULIDs: 26 characters of Crockford base32 over a 48-bit millisecond
timestamp and 80 bits of randomness. Two properties earn their place here — they sort
lexicographically by creation time, which makes a directory listing or a log grep chronological,
and they carry no coordination cost, so the gateway can mint an order id without asking anyone.

Implemented here rather than pulled in as a dependency: it is thirty lines, and it keeps the id
generator injectable so tests can be deterministic.
"""

from __future__ import annotations

import os
import secrets
from typing import Protocol

from market_core.clock import Clock, SystemClock

# Crockford base32: no I, L, O or U, so an id cannot be misread aloud or mistyped into one.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_LENGTH = 26
_TIMESTAMP_CHARS = 10
_RANDOM_BITS = 80

ACCOUNT_PREFIX = "acct_"
ORDER_PREFIX = "ord_"
TRADE_PREFIX = "trd_"

MAX_CLIENT_ORDER_ID = 64


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, index = divmod(value, 32)
        chars.append(_ALPHABET[index])
    return "".join(reversed(chars))


def make_ulid(clock: Clock, randomness: int | None = None) -> str:
    """A 26-character ULID for the current instant."""
    timestamp_ms = int(clock.now().timestamp() * 1000)
    entropy = secrets.randbits(_RANDOM_BITS) if randomness is None else randomness
    return _encode(timestamp_ms, _TIMESTAMP_CHARS) + _encode(
        entropy, _ULID_LENGTH - _TIMESTAMP_CHARS
    )


class IdGenerator(Protocol):
    """Mints the identifiers a service is responsible for."""

    def order_id(self) -> str: ...
    def trade_id(self) -> str: ...
    def account_id(self) -> str: ...


class UlidGenerator:
    """The real generator: ULIDs for orders and trades, random hex for accounts."""

    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()

    def order_id(self) -> str:
        return ORDER_PREFIX + make_ulid(self._clock)

    def trade_id(self) -> str:
        return TRADE_PREFIX + make_ulid(self._clock)

    def account_id(self) -> str:
        return ACCOUNT_PREFIX + os.urandom(4).hex()


class SequentialIdGenerator:
    """Deterministic ids for tests: `ord_000...001`, `trd_000...001`, `acct_00000001`."""

    def __init__(self) -> None:
        self._counters = {"order": 0, "trade": 0, "account": 0}

    def _next(self, kind: str, prefix: str, width: int) -> str:
        self._counters[kind] += 1
        return prefix + str(self._counters[kind]).zfill(width)

    def order_id(self) -> str:
        return self._next("order", ORDER_PREFIX, _ULID_LENGTH)

    def trade_id(self) -> str:
        return self._next("trade", TRADE_PREFIX, _ULID_LENGTH)

    def account_id(self) -> str:
        return self._next("account", ACCOUNT_PREFIX, 8)


def validate_client_order_id(value: str) -> str:
    """Client order ids are free-form, but bounded — they are stored and indexed per account."""
    if not value:
        raise ValueError("client_order_id must not be empty")
    if len(value) > MAX_CLIENT_ORDER_ID:
        raise ValueError(
            f"client_order_id must be at most {MAX_CLIENT_ORDER_ID} characters, got {len(value)}"
        )
    if not value.isprintable() or any(c.isspace() for c in value):
        raise ValueError(f"client_order_id must be printable with no whitespace: {value!r}")
    return value
