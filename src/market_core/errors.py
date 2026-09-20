"""The error taxonomy every service answers with (.claude/docs/01-domain-model.md §7)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"
    PRICE_OUT_OF_BAND = "PRICE_OUT_OF_BAND"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    NOT_ORDER_OWNER = "NOT_ORDER_OWNER"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
    DUPLICATE_CLIENT_ORDER_ID = "DUPLICATE_CLIENT_ORDER_ID"
    ORDER_NOT_CANCELLABLE = "ORDER_NOT_CANCELLABLE"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS[self]


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.UNKNOWN_SYMBOL: 400,
    ErrorCode.PRICE_OUT_OF_BAND: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.NOT_ORDER_OWNER: 403,
    ErrorCode.ORDER_NOT_FOUND: 404,
    ErrorCode.DUPLICATE_CLIENT_ORDER_ID: 409,
    ErrorCode.ORDER_NOT_CANCELLABLE: 409,
    ErrorCode.INSUFFICIENT_FUNDS: 422,
    ErrorCode.ENGINE_UNAVAILABLE: 503,
}


class MarketError(Exception):
    """A failure with a wire representation.

    Carrying the code on the exception means a service never has to map exceptions to status
    codes by hand at the boundary — the taxonomy travels with the failure.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def http_status(self) -> int:
        return self.code.http_status

    def to_wire(self) -> dict[str, Any]:
        """The shape every non-2xx response carries."""
        body: dict[str, Any] = {"code": str(self.code), "message": self.message}
        if self.details:
            body["details"] = self.details
        return {"error": body}

    def __repr__(self) -> str:
        return f"MarketError({self.code}, {self.message!r})"
