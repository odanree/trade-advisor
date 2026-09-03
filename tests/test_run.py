"""run_pipeline skip logic: one-open-thesis-per-ticker invariant + same-day idempotency.

run_pipeline itself makes LLM + market/news provider calls, so it isn't
cleanly unit-testable without heavy mocking. The skip decision is pulled out
into the pure helper `_tickers_to_skip` (advisor/run.py) precisely so it can
be exercised here against a tmp ledger instead.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from advisor.ledger import Ledger
from advisor.run import _tickers_to_skip
from advisor.schema import Outcome


def test_tickers_to_skip_combines_same_day_and_open_rec(tmp_ledger: Ledger, make_rec) -> None:
    today = date(2026, 2, 1)
    yesterday = today - timedelta(days=1)

    open_buy = make_rec(id="open-1", ticker="AAPL", direction="buy", created_at=datetime(2026, 1, 15, tzinfo=UTC))

    settled = make_rec(id="settled-1", ticker="MSFT", direction="sell", created_at=datetime(2026, 1, 15, tzinfo=UTC))

    hold_yesterday = make_rec(
        id="hold-1", ticker="GOOGL", direction="hold", created_at=datetime.combine(yesterday, datetime.min.time(), tzinfo=UTC)
    )

    today_rec = make_rec(
        id="today-1", ticker="NVDA", direction="buy", created_at=datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    )

    tmp_ledger.append_recommendation(open_buy)
    tmp_ledger.append_recommendation(settled)
    tmp_ledger.append_recommendation(hold_yesterday)
    tmp_ledger.append_recommendation(today_rec)

    tmp_ledger.append_outcome(
        Outcome(
            rec_id=settled.id,
            closed_at=datetime(2026, 1, 20, tzinfo=UTC),
            close_reason="horizon",
            exit_price=95.0,
            benchmark_exit_price=510.0,
            rec_return_pct=-5.0,
            benchmark_return_pct=2.0,
            alpha_pct=-7.0,
        )
    )

    skip = _tickers_to_skip(tmp_ledger, today)

    assert "AAPL" in skip  # open buy rec -> skipped
    assert "MSFT" not in skip  # settled -> not skipped
    assert "GOOGL" not in skip  # hold from yesterday -> not skipped
    assert "NVDA" in skip  # rec created today -> skipped


def test_tickers_to_skip_applies_invalidation_cooldown(tmp_ledger: Ledger, make_rec) -> None:
    """Hysteresis against whipsaw: GOOGL was stopped out via invalidation on
    2026-08-27 and re-advised as a fresh buy the next day. A ticker
    invalidated within the last COOLDOWN_DAYS calendar days should stay
    skipped even after its open rec has settled; once cooldown lapses, or
    for a horizon-expiry close (a thesis that ran its course), it should
    not be skipped."""
    today = date(2026, 8, 28)

    def _close(ticker: str, rec_id: str, days_ago: int, close_reason: str) -> None:
        rec = make_rec(
            id=rec_id,
            ticker=ticker,
            direction="buy",
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        tmp_ledger.append_recommendation(rec)
        tmp_ledger.append_outcome(
            Outcome(
                rec_id=rec.id,
                closed_at=datetime.combine(today - timedelta(days=days_ago), datetime.min.time(), tzinfo=UTC),
                close_reason=close_reason,
                exit_price=90.0,
                benchmark_exit_price=500.0,
                rec_return_pct=-10.0,
                benchmark_return_pct=1.0,
                alpha_pct=-11.0,
            )
        )

    _close("GOOGL", "goog-inv", days_ago=2, close_reason="invalidation")
    _close("TSLA", "tsla-inv", days_ago=6, close_reason="invalidation")
    _close("AMD", "amd-horizon", days_ago=1, close_reason="horizon")

    skip = _tickers_to_skip(tmp_ledger, today)

    assert "GOOGL" in skip  # invalidated 2 days ago -> still cooling down
    assert "TSLA" not in skip  # invalidated 6 days ago -> cooldown lapsed
    assert "AMD" not in skip  # horizon close doesn't trigger cooldown
