"""Shared fixtures: an isolated ledger, a Recommendation factory, and a fake market data provider."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import pytest

from advisor.ledger import Ledger
from advisor.schema import InvalidationRule, Recommendation


@pytest.fixture
def tmp_ledger(tmp_path: Path) -> Ledger:
    """A fresh Ledger backed by a SQLite file under pytest's tmp_path."""
    return Ledger(db_path=tmp_path / "ledger.db")


@pytest.fixture
def make_rec() -> Callable[..., Recommendation]:
    """Factory for a valid Recommendation, overridable via kwargs.

    Defaults entry_price=100.0 and benchmark_entry_price=500.0 so benchmark
    math in tests works out to round percentages without extra setup.
    """

    def _make(**overrides: Any) -> Recommendation:
        defaults: dict[str, Any] = {
            "id": "rec-1",
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            "ticker": "AAPL",
            "direction": "buy",
            "size_pct": 5.0,
            "thesis": "Test thesis.",
            "confidence": 0.75,
            "invalidation": InvalidationRule(type="price_below", level=90.0),
            "horizon_days": 30,
            "prompt_version": "v1",
            "model_id": "claude-sonnet-5",
            "entry_price": 100.0,
            "benchmark_entry_price": 500.0,
        }
        defaults.update(overrides)
        return Recommendation(**defaults)

    return _make


class FakeProvider:
    """In-memory MarketDataProvider stand-in: ticker -> price, no network calls."""

    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = prices

    def get_quote(self, ticker: str) -> float:
        return self.prices[ticker]

    def get_history(self, ticker: str, days: int) -> list[dict]:
        price = self.prices.get(ticker, 100.0)
        return [{"date": f"2026-01-{i + 1:02d}", "close": price} for i in range(min(days, 5))]

    def get_fundamentals(self, ticker: str) -> dict:
        return {"ticker": ticker, "pe_ratio": 20.0, "market_cap": 1_000_000_000}
