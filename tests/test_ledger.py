"""Ledger append-only behavior: open/closed filtering, run tracking, and roundtrips."""

from __future__ import annotations

from datetime import UTC, date, datetime

from advisor.ledger import Ledger
from advisor.schema import Outcome


def test_open_recommendations_excludes_holds_and_settled(tmp_ledger: Ledger, make_rec) -> None:
    buy_rec = make_rec(id="buy-1", direction="buy")
    hold_rec = make_rec(id="hold-1", direction="hold")
    settled_rec = make_rec(id="settled-1", direction="sell")

    tmp_ledger.append_recommendation(buy_rec)
    tmp_ledger.append_recommendation(hold_rec)
    tmp_ledger.append_recommendation(settled_rec)

    tmp_ledger.append_outcome(
        Outcome(
            rec_id=settled_rec.id,
            closed_at=datetime(2026, 2, 1, tzinfo=UTC),
            close_reason="horizon",
            exit_price=95.0,
            benchmark_exit_price=510.0,
            rec_return_pct=-5.0,
            benchmark_return_pct=2.0,
            alpha_pct=-7.0,
        )
    )

    open_ids = {rec.id for rec in tmp_ledger.open_recommendations()}

    assert open_ids == {buy_rec.id}
    assert hold_rec.id not in open_ids
    assert settled_rec.id not in open_ids


def test_tickers_with_rec_on_matches_calendar_day_only(tmp_ledger: Ledger, make_rec) -> None:
    today_rec_1 = make_rec(id="today-1", ticker="AAPL", created_at=datetime(2026, 2, 1, 9, 30, tzinfo=UTC))
    today_rec_2 = make_rec(id="today-2", ticker="MSFT", created_at=datetime(2026, 2, 1, 23, 59, tzinfo=UTC))
    yesterday_rec = make_rec(id="yesterday-1", ticker="GOOGL", created_at=datetime(2026, 1, 31, 9, 30, tzinfo=UTC))

    tmp_ledger.append_recommendation(today_rec_1)
    tmp_ledger.append_recommendation(today_rec_2)
    tmp_ledger.append_recommendation(yesterday_rec)

    tickers_today = tmp_ledger.tickers_with_rec_on(date(2026, 2, 1))

    assert tickers_today == {"AAPL", "MSFT"}
    assert "GOOGL" not in tickers_today


def test_tickers_with_rec_on_empty_when_no_recs(tmp_ledger: Ledger) -> None:
    assert tmp_ledger.tickers_with_rec_on(date(2026, 2, 1)) == set()


def test_run_exists_and_record_run(tmp_ledger: Ledger) -> None:
    assert tmp_ledger.run_exists("2026-01-01") is False
    tmp_ledger.record_run("2026-01-01")
    assert tmp_ledger.run_exists("2026-01-01") is True
    assert tmp_ledger.run_exists("2026-01-02") is False


def test_record_run_twice_same_key_is_idempotent(tmp_ledger: Ledger) -> None:
    """A same-day rerun may call record_run twice for one key (run.py now
    continues past run_exists() instead of early-returning); the second
    call must be a silent no-op rather than raise IntegrityError."""
    tmp_ledger.record_run("2026-01-01")
    tmp_ledger.record_run("2026-01-01")

    assert tmp_ledger.run_exists("2026-01-01") is True


def test_get_recommendation_roundtrip_preserves_fields(tmp_ledger: Ledger, make_rec) -> None:
    rec = make_rec(id="roundtrip-1")
    tmp_ledger.append_recommendation(rec)

    fetched = tmp_ledger.get_recommendation(rec.id)

    assert fetched is not None
    assert fetched == rec


def test_get_recommendation_missing_returns_none(tmp_ledger: Ledger) -> None:
    assert tmp_ledger.get_recommendation("does-not-exist") is None
