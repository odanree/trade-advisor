"""evals.metrics: hit rate, alpha stats, drawdown, and calibration bucketing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from advisor.schema import Outcome
from evals.metrics import calibration, hit_rate, max_drawdown, mean_alpha, median_alpha


def _outcome(rec_id: str, alpha_pct: float, closed_at: datetime) -> Outcome:
    return Outcome(
        rec_id=rec_id,
        closed_at=closed_at,
        close_reason="horizon",
        exit_price=100.0,
        benchmark_exit_price=100.0,
        rec_return_pct=alpha_pct,
        benchmark_return_pct=0.0,
        alpha_pct=alpha_pct,
    )


def test_hit_rate_mean_median(make_rec) -> None:
    pairs = [
        (make_rec(id="a"), _outcome("a", 5.0, datetime(2026, 1, 1, tzinfo=UTC))),
        (make_rec(id="b"), _outcome("b", -3.0, datetime(2026, 1, 2, tzinfo=UTC))),
        (make_rec(id="c"), _outcome("c", 10.0, datetime(2026, 1, 3, tzinfo=UTC))),
    ]

    assert hit_rate(pairs) == pytest.approx(2 / 3)
    assert mean_alpha(pairs) == pytest.approx((5.0 - 3.0 + 10.0) / 3)
    assert median_alpha(pairs) == pytest.approx(5.0)


def test_max_drawdown_tracks_peak_to_trough(make_rec) -> None:
    pairs = [
        (make_rec(id="a"), _outcome("a", 5.0, datetime(2026, 1, 1, tzinfo=UTC))),
        (make_rec(id="b"), _outcome("b", -8.0, datetime(2026, 1, 2, tzinfo=UTC))),
        (make_rec(id="c"), _outcome("c", 2.0, datetime(2026, 1, 3, tzinfo=UTC))),
    ]
    # cumulative alpha: 5, -3, -1 -> peak 5, worst trough -3 -> drawdown 8
    assert max_drawdown(pairs) == pytest.approx(8.0)


def test_calibration_bucket_edges(make_rec) -> None:
    pairs = [
        (make_rec(id="a", confidence=0.1), _outcome("a", -1.0, datetime(2026, 1, 1, tzinfo=UTC))),
        (make_rec(id="b", confidence=0.5), _outcome("b", 1.0, datetime(2026, 1, 2, tzinfo=UTC))),
        (make_rec(id="c", confidence=0.85), _outcome("c", 1.0, datetime(2026, 1, 3, tzinfo=UTC))),
        (make_rec(id="d", confidence=1.0), _outcome("d", 1.0, datetime(2026, 1, 4, tzinfo=UTC))),
    ]

    buckets = calibration(pairs)
    by_label = {b["bucket"]: b for b in buckets}

    assert len(buckets) == 4
    assert by_label["0.0-0.5"]["n"] == 1  # confidence=0.1
    assert by_label["0.5-0.7"]["n"] == 1  # confidence=0.5 goes to the second bucket
    assert by_label["0.7-0.85"]["n"] == 0  # 0.85 does NOT land here
    assert by_label["0.85-1.0"]["n"] == 2  # confidence=0.85 goes to fourth bucket; 1.0 included
    assert by_label["0.85-1.0"]["hit_rate"] == pytest.approx(1.0)


def test_empty_input_returns_zeros_and_empty() -> None:
    assert hit_rate([]) == 0.0
    assert mean_alpha([]) == 0.0
    assert median_alpha([]) == 0.0
    assert max_drawdown([]) == 0.0
    assert calibration([]) == []
