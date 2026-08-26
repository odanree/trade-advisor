"""evals.report: markdown scorecard, including the unrealized open-positions section."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from evals.report import scorecard
from tests.conftest import FakeProvider


class RaisingProvider:
    """MarketDataProvider stand-in whose get_quote always raises for a given ticker."""

    def __init__(self, bad_ticker: str, spy_price: float = 500.0) -> None:
        self.bad_ticker = bad_ticker
        self.spy_price = spy_price

    def get_quote(self, ticker: str) -> float:
        if ticker == self.bad_ticker:
            raise RuntimeError(f"no quote available for {ticker}")
        return self.spy_price

    def get_history(self, ticker: str, days: int) -> list[dict]:
        return []

    def get_fundamentals(self, ticker: str) -> dict:
        return {}


def test_scorecard_includes_provisional_unrealized_alpha(tmp_ledger, make_rec) -> None:
    rec = make_rec(
        id="rec-open-1",
        direction="buy",
        entry_price=100.0,
        benchmark_entry_price=500.0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    tmp_ledger.append_recommendation(rec)
    provider = FakeProvider({"AAPL": 110.0, "SPY": 510.0})

    markdown = scorecard(ledger=tmp_ledger, provider=provider)

    assert "Open positions" in markdown
    assert "provisional" in markdown
    assert "not part of the settled track record" in markdown
    # (110/100 - 1)*100 - (510/500 - 1)*100 = 10.0 - 2.0 = 8.0
    assert "8.00" in markdown


def test_scorecard_shows_na_when_quote_fails(tmp_ledger, make_rec) -> None:
    rec = make_rec(
        id="rec-open-2",
        ticker="AAPL",
        direction="buy",
        entry_price=100.0,
        benchmark_entry_price=500.0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    tmp_ledger.append_recommendation(rec)
    provider = RaisingProvider(bad_ticker="AAPL")

    markdown = scorecard(ledger=tmp_ledger, provider=provider)

    assert markdown  # scorecard still returns despite the quote failure
    assert "Open positions" in markdown
    assert "n/a" in markdown


def test_scorecard_no_open_recs(tmp_ledger) -> None:
    markdown = scorecard(ledger=tmp_ledger, provider=FakeProvider({}))

    assert "Open positions" in markdown
    assert "No open recommendations" in markdown
