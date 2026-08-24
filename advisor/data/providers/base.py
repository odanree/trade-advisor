"""Provider protocols and shared exceptions for market/news data sources.

Analysts depend on these Protocols, not on any concrete provider, so the
yfinance-backed implementations can be swapped for another data vendor
without touching agent code.
"""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable


class ProviderError(RuntimeError):
    """Raised when a data provider cannot fulfil a request cleanly.

    Providers should raise this (with a clear message) instead of letting a
    raw KeyError/AttributeError from an underlying SDK bubble up, since
    upstream fields (e.g. yfinance's fast_info/info) go missing routinely.
    """


class OHLCVBar(TypedDict):
    """One day of OHLCV history."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@runtime_checkable
class MarketDataProvider(Protocol):
    """Source of quotes, price history, and fundamentals for a ticker."""

    def get_quote(self, ticker: str) -> float:
        """Latest known price for ``ticker``."""
        ...

    def get_history(self, ticker: str, days: int) -> list[dict]:
        """Up to ``days`` of daily OHLCV bars, oldest first.

        Each dict has keys: date, open, high, low, close, volume.
        """
        ...

    def get_fundamentals(self, ticker: str) -> dict:
        """Best-effort snapshot of fundamental metrics for ``ticker``."""
        ...


@runtime_checkable
class NewsProvider(Protocol):
    """Source of recent headlines for a ticker."""

    def get_headlines(self, ticker: str, limit: int = 10) -> list[str]:
        """Up to ``limit`` recent headline strings for ``ticker``."""
        ...
