"""shadow.settle: invalidation vs horizon triggers, using FakeProvider and an injected clock."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from advisor.schema import InvalidationRule
from shadow import settle as settle_module
from tests.conftest import FakeProvider


@pytest.fixture(autouse=True)
def _no_op_close_position(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Alpaca paper mirror is out of scope for settle tests; make it a no-op."""
    monkeypatch.setattr(settle_module, "close_paper_position", lambda ticker: None)


def test_price_below_invalidation_closes(tmp_ledger, make_rec) -> None:
    rec = make_rec(
        id="rec-inv",
        invalidation=InvalidationRule(type="price_below", level=90.0),
        horizon_days=30,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    tmp_ledger.append_recommendation(rec)
    provider = FakeProvider({"AAPL": 85.0, "SPY": 505.0})
    now = datetime(2026, 1, 5, tzinfo=UTC)

    outcomes = settle_module.settle(ledger=tmp_ledger, provider=provider, now=now)

    assert len(outcomes) == 1
    assert outcomes[0].close_reason == "invalidation"
    assert outcomes[0].rec_id == rec.id
    assert tmp_ledger.open_recommendations() == []


def test_horizon_expiry_closes(tmp_ledger, make_rec) -> None:
    rec = make_rec(
        id="rec-horizon",
        invalidation=InvalidationRule(type="price_below", level=50.0),
        horizon_days=30,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    tmp_ledger.append_recommendation(rec)
    provider = FakeProvider({"AAPL": 105.0, "SPY": 505.0})
    now = datetime(2026, 1, 31, tzinfo=UTC)  # >= created_at + 30 days

    outcomes = settle_module.settle(ledger=tmp_ledger, provider=provider, now=now)

    assert len(outcomes) == 1
    assert outcomes[0].close_reason == "horizon"


def test_untriggered_unexpired_stays_open(tmp_ledger, make_rec) -> None:
    rec = make_rec(
        id="rec-open",
        invalidation=InvalidationRule(type="price_below", level=50.0),
        horizon_days=30,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    tmp_ledger.append_recommendation(rec)
    provider = FakeProvider({"AAPL": 105.0, "SPY": 505.0})
    now = datetime(2026, 1, 5, tzinfo=UTC)

    outcomes = settle_module.settle(ledger=tmp_ledger, provider=provider, now=now)

    assert outcomes == []
    open_ids = {r.id for r in tmp_ledger.open_recommendations()}
    assert rec.id in open_ids


def test_invalidation_wins_when_both_true(tmp_ledger, make_rec) -> None:
    rec = make_rec(
        id="rec-both",
        invalidation=InvalidationRule(type="price_below", level=90.0),
        horizon_days=30,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    tmp_ledger.append_recommendation(rec)
    provider = FakeProvider({"AAPL": 85.0, "SPY": 505.0})
    now = datetime(2026, 3, 1, tzinfo=UTC)  # well past horizon AND price triggers invalidation

    outcomes = settle_module.settle(ledger=tmp_ledger, provider=provider, now=now)

    assert len(outcomes) == 1
    assert outcomes[0].close_reason == "invalidation"
