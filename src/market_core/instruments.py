"""Instrument configuration and the validation it drives.

Loaded from `data/config/instruments.json`, never hardcoded
(.claude/docs/01-domain-model.md §2.2).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from market_core.errors import ErrorCode, MarketError

USDCAD = "USDCAD"


@dataclass(frozen=True, slots=True)
class Instrument:
    """The tradable's rules: units, limits, and the guards applied to an order."""

    symbol: str
    base: str
    quote: str
    tick_size: int
    lot_size: int
    min_qty: int
    max_qty: int
    price_band_pct: int
    market_buy_max_notional: int

    @classmethod
    def from_dict(cls, symbol: str, raw: dict[str, Any]) -> Instrument:
        try:
            return cls(
                symbol=symbol,
                base=str(raw["base"]),
                quote=str(raw["quote"]),
                tick_size=int(raw["tick_size"]),
                lot_size=int(raw["lot_size"]),
                min_qty=int(raw["min_qty"]),
                max_qty=int(raw["max_qty"]),
                price_band_pct=int(raw["price_band_pct"]),
                market_buy_max_notional=int(raw["market_buy_max_notional"]),
            )
        except KeyError as exc:
            raise ValueError(f"instrument {symbol}: missing field {exc.args[0]!r}") from exc

    def validate_quantity(self, quantity: int) -> None:
        """Raise `MarketError` unless the quantity is a legal size for this instrument."""
        if quantity <= 0:
            raise MarketError(ErrorCode.VALIDATION_ERROR, f"quantity must be positive: {quantity}")
        if quantity % self.lot_size:
            raise MarketError(
                ErrorCode.VALIDATION_ERROR,
                f"quantity must be a multiple of the lot size {self.lot_size}",
                {"quantity": quantity, "lot_size": self.lot_size},
            )
        if quantity < self.min_qty or quantity > self.max_qty:
            raise MarketError(
                ErrorCode.VALIDATION_ERROR,
                f"quantity must be between {self.min_qty} and {self.max_qty}",
                {"quantity": quantity, "min_qty": self.min_qty, "max_qty": self.max_qty},
            )

    def validate_price(self, price: int) -> None:
        """Raise `MarketError` unless the price is positive and on the tick grid."""
        if price <= 0:
            raise MarketError(ErrorCode.VALIDATION_ERROR, f"price must be positive: {price}")
        if price % self.tick_size:
            raise MarketError(
                ErrorCode.VALIDATION_ERROR,
                f"price must be a multiple of the tick size {self.tick_size}",
                {"price": price, "tick_size": self.tick_size},
            )

    def within_price_band(self, price: int, reference: int | None) -> bool:
        """Is `price` inside ±`price_band_pct` of the reference?

        A `None` reference means the venue has neither traded nor quoted two-sided, so there is
        nothing to measure against and the band does not apply — a cold-started venue has to
        accept some first order (.claude/docs/01-domain-model.md §2.2).
        """
        if reference is None:
            return True
        margin = reference * self.price_band_pct
        return abs(price - reference) * 100 <= margin


class InstrumentRegistry:
    """Every instrument the venue knows about. One, for now."""

    def __init__(self, instruments: dict[str, Instrument]) -> None:
        self._instruments = instruments

    @classmethod
    def from_file(cls, path: Path) -> InstrumentRegistry:
        raw = json.loads(path.read_text())
        return cls({symbol: Instrument.from_dict(symbol, body) for symbol, body in raw.items()})

    def get(self, symbol: str) -> Instrument:
        """Look up an instrument, or raise the error the API boundary already knows how to send."""
        try:
            return self._instruments[symbol]
        except KeyError:
            raise MarketError(
                ErrorCode.UNKNOWN_SYMBOL,
                f"unknown symbol: {symbol}",
                {"known": sorted(self._instruments)},
            ) from None

    def __contains__(self, symbol: object) -> bool:
        return symbol in self._instruments

    def __len__(self) -> int:
        return len(self._instruments)
