"""shadow.benchmark: pure return/alpha math, no network."""

from __future__ import annotations

import pytest

from shadow.benchmark import alpha, benchmark_return_pct, rec_return_pct


def test_buy_alpha_approx(make_rec) -> None:
    rec = make_rec(direction="buy", entry_price=100.0, benchmark_entry_price=500.0)
    exit_price = 110.0  # +10%
    benchmark_exit_price = 510.0  # +2%

    assert rec_return_pct(rec, exit_price) == pytest.approx(10.0)
    assert benchmark_return_pct(rec, benchmark_exit_price) == pytest.approx(2.0)
    assert alpha(rec, exit_price, benchmark_exit_price) == pytest.approx(8.0)


def test_sell_direction_inverts_return(make_rec) -> None:
    rec = make_rec(direction="sell", entry_price=100.0, benchmark_entry_price=500.0)
    exit_price = 110.0  # price rose 10% -> a "sell" call scores -10%

    assert rec_return_pct(rec, exit_price) == pytest.approx(-10.0)


def test_trim_direction_inverts_return(make_rec) -> None:
    rec = make_rec(direction="trim", entry_price=100.0, benchmark_entry_price=500.0)
    exit_price = 90.0  # price fell 10% -> a "trim" call scores +10%

    assert rec_return_pct(rec, exit_price) == pytest.approx(10.0)


def test_missing_entry_price_raises(make_rec) -> None:
    rec = make_rec(entry_price=None)

    with pytest.raises(ValueError):
        rec_return_pct(rec, 100.0)


def test_missing_benchmark_entry_price_raises(make_rec) -> None:
    rec = make_rec(benchmark_entry_price=None)

    with pytest.raises(ValueError):
        benchmark_return_pct(rec, 500.0)
