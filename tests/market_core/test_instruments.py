"""Instrument config and the validation it drives (.claude/docs/01-domain-model.md §2.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_core import USDCAD, ErrorCode, Instrument, InstrumentRegistry, MarketError

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_CONFIG = REPO_ROOT / "data" / "config" / "instruments.json"


@pytest.fixture
def usdcad() -> Instrument:
    return InstrumentRegistry.from_file(SHIPPED_CONFIG).get(USDCAD)


class TestShippedConfig:
    """The committed fixture is what every loop actually runs with; it must stay valid."""

    def test_loads_and_matches_the_design(self, usdcad: Instrument) -> None:
        assert usdcad.base == "USD"
        assert usdcad.quote == "CAD"
        assert usdcad.tick_size == 1
        assert usdcad.lot_size == 100
        assert usdcad.min_qty == 100
        assert usdcad.price_band_pct == 10
        # C$100,000.00 in cents — the market-buy spending cap (decision D7).
        assert usdcad.market_buy_max_notional == 10_000_000

    def test_unknown_symbol_raises_the_wire_error(self) -> None:
        registry = InstrumentRegistry.from_file(SHIPPED_CONFIG)
        with pytest.raises(MarketError) as exc:
            registry.get("EURUSD")
        assert exc.value.code is ErrorCode.UNKNOWN_SYMBOL
        assert exc.value.http_status == 400

    def test_missing_field_is_a_load_error(self, tmp_path: Path) -> None:
        broken = tmp_path / "instruments.json"
        broken.write_text(json.dumps({"USDCAD": {"base": "USD"}}))
        with pytest.raises(ValueError, match="missing field"):
            InstrumentRegistry.from_file(broken)


class TestQuantityValidation:
    def test_accepts_a_whole_lot(self, usdcad: Instrument) -> None:
        usdcad.validate_quantity(100_000)

    def test_rejects_a_partial_lot(self, usdcad: Instrument) -> None:
        with pytest.raises(MarketError) as exc:
            usdcad.validate_quantity(150)
        assert exc.value.code is ErrorCode.VALIDATION_ERROR
        assert exc.value.details["lot_size"] == 100

    @pytest.mark.parametrize("quantity", [0, -100])
    def test_rejects_non_positive(self, usdcad: Instrument, quantity: int) -> None:
        with pytest.raises(MarketError, match="must be positive"):
            usdcad.validate_quantity(quantity)

    def test_rejects_beyond_the_maximum(self, usdcad: Instrument) -> None:
        with pytest.raises(MarketError, match="between"):
            usdcad.validate_quantity(usdcad.max_qty + usdcad.lot_size)


class TestPriceValidation:
    def test_accepts_a_tick_multiple(self, usdcad: Instrument) -> None:
        usdcad.validate_price(137_500)

    def test_rejects_non_positive(self, usdcad: Instrument) -> None:
        with pytest.raises(MarketError, match="must be positive"):
            usdcad.validate_price(0)


class TestPriceBand:
    def test_no_reference_means_no_band(self, usdcad: Instrument) -> None:
        """A venue that has never traded must accept some first order."""
        assert usdcad.within_price_band(999_999, reference=None)

    def test_inside_the_band(self, usdcad: Instrument) -> None:
        assert usdcad.within_price_band(137_500, reference=137_000)

    def test_exactly_on_the_edge_is_inside(self, usdcad: Instrument) -> None:
        assert usdcad.within_price_band(110_000, reference=100_000)  # +10%
        assert usdcad.within_price_band(90_000, reference=100_000)  # -10%

    @pytest.mark.parametrize("price", [110_001, 89_999])
    def test_outside_the_band(self, usdcad: Instrument, price: int) -> None:
        """A fat-finger guard: 13.7520 typed for 1.37520 is what this catches."""
        assert not usdcad.within_price_band(price, reference=100_000)
