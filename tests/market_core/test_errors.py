"""The error taxonomy (.claude/docs/01-domain-model.md §7)."""

from __future__ import annotations

import pytest

from market_core import ErrorCode, MarketError


class TestErrorCodes:
    @pytest.mark.parametrize(
        ("code", "status"),
        [
            (ErrorCode.VALIDATION_ERROR, 400),
            (ErrorCode.UNKNOWN_SYMBOL, 400),
            (ErrorCode.PRICE_OUT_OF_BAND, 400),
            (ErrorCode.UNAUTHENTICATED, 401),
            (ErrorCode.NOT_ORDER_OWNER, 403),
            (ErrorCode.ORDER_NOT_FOUND, 404),
            (ErrorCode.DUPLICATE_CLIENT_ORDER_ID, 409),
            (ErrorCode.ORDER_NOT_CANCELLABLE, 409),
            (ErrorCode.INSUFFICIENT_FUNDS, 422),
            (ErrorCode.ENGINE_UNAVAILABLE, 503),
        ],
    )
    def test_documented_http_mapping(self, code: ErrorCode, status: int) -> None:
        assert code.http_status == status

    def test_every_code_has_a_status(self) -> None:
        """A new code without a status would surface as a 500 at the boundary."""
        for code in ErrorCode:
            assert 400 <= code.http_status < 600


class TestMarketError:
    def test_wire_shape(self) -> None:
        error = MarketError(ErrorCode.INSUFFICIENT_FUNDS, "not enough CAD", {"available": 100})
        assert error.to_wire() == {
            "error": {
                "code": "INSUFFICIENT_FUNDS",
                "message": "not enough CAD",
                "details": {"available": 100},
            }
        }

    def test_details_are_omitted_when_empty(self) -> None:
        assert MarketError(ErrorCode.ORDER_NOT_FOUND, "no such order").to_wire() == {
            "error": {"code": "ORDER_NOT_FOUND", "message": "no such order"}
        }

    def test_carries_its_own_status(self) -> None:
        """The taxonomy travels with the failure, so no boundary has to map it by hand."""
        assert MarketError(ErrorCode.ENGINE_UNAVAILABLE, "down").http_status == 503

    def test_is_catchable_as_an_exception(self) -> None:
        with pytest.raises(MarketError):
            raise MarketError(ErrorCode.VALIDATION_ERROR, "bad input")
