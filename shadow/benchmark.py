"""Pure scoring functions: recommendation return, SPY-counterfactual return, and alpha.

No I/O, no side effects, no network — these are the arithmetic core that both
shadow.settle and evals.metrics build on.
"""

from __future__ import annotations

from advisor.schema import Recommendation


def rec_return_pct(rec: Recommendation, exit_price: float) -> float:
    """Percent return attributable to the recommendation itself.

    "buy" is scored directly: a higher exit price is a gain. "sell"/"trim" are
    scored inverse: the call is right when price falls after the exit signal.
    """
    if rec.entry_price is None:
        raise ValueError(f"Recommendation {rec.id} has no entry_price; cannot score return.")

    raw_pct = (exit_price / rec.entry_price - 1) * 100
    if rec.direction == "buy":
        return raw_pct
    if rec.direction in ("sell", "trim"):
        return -raw_pct
    raise ValueError(f"Recommendation {rec.id} has non-scorable direction {rec.direction!r}.")


def benchmark_return_pct(rec: Recommendation, benchmark_exit_price: float) -> float:
    """Percent return of the always-long-SPY counterfactual over the same window."""
    if rec.benchmark_entry_price is None:
        raise ValueError(
            f"Recommendation {rec.id} has no benchmark_entry_price; cannot score benchmark."
        )

    return (benchmark_exit_price / rec.benchmark_entry_price - 1) * 100


def alpha(rec: Recommendation, exit_price: float, benchmark_exit_price: float) -> float:
    """Recommendation return minus the SPY counterfactual return, in percentage points."""
    return rec_return_pct(rec, exit_price) - benchmark_return_pct(rec, benchmark_exit_price)
