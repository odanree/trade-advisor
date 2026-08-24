"""Pure metrics over the closed recommendation ledger: (Recommendation, Outcome) pairs.

No I/O — all functions take the list already pulled from Ledger.closed() and
degrade gracefully (0.0 / empty list) on empty input rather than raising.
"""

from __future__ import annotations

from statistics import median

from advisor.schema import Outcome, Recommendation

Pair = tuple[Recommendation, Outcome]

# [low, high) except the last bucket, which is [low, high] inclusive.
_CALIBRATION_BUCKETS: list[tuple[float, float, str]] = [
    (0.0, 0.5, "0.0-0.5"),
    (0.5, 0.7, "0.5-0.7"),
    (0.7, 0.85, "0.7-0.85"),
    (0.85, 1.0, "0.85-1.0"),
]


def hit_rate(pairs: list[Pair]) -> float:
    """Fraction of closed recommendations with positive alpha."""
    if not pairs:
        return 0.0
    wins = sum(1 for _, outcome in pairs if outcome.alpha_pct > 0)
    return wins / len(pairs)


def mean_alpha(pairs: list[Pair]) -> float:
    """Mean alpha (percentage points) across closed recommendations."""
    if not pairs:
        return 0.0
    return sum(outcome.alpha_pct for _, outcome in pairs) / len(pairs)


def median_alpha(pairs: list[Pair]) -> float:
    """Median alpha (percentage points) across closed recommendations."""
    if not pairs:
        return 0.0
    return median(outcome.alpha_pct for _, outcome in pairs)


def max_drawdown(pairs: list[Pair]) -> float:
    """Largest peak-to-trough decline in cumulative alpha, ordered by close time.

    Returned as a non-negative percentage-point value: 0.0 if cumulative alpha
    never falls below its running peak, or if there are no closed pairs.
    """
    if not pairs:
        return 0.0

    ordered = sorted(pairs, key=lambda pair: pair[1].closed_at)
    cumulative = 0.0
    peak = 0.0
    worst_drawdown = 0.0
    for _, outcome in ordered:
        cumulative += outcome.alpha_pct
        peak = max(peak, cumulative)
        worst_drawdown = max(worst_drawdown, peak - cumulative)
    return worst_drawdown


def calibration(pairs: list[Pair]) -> list[dict]:
    """Bucket closed recommendations by stated confidence and measure realized hit rate.

    Buckets: [0, 0.5), [0.5, 0.7), [0.7, 0.85), [0.85, 1.0] (only the last
    bucket includes its upper edge). Returns [] when there are no closed pairs;
    otherwise always returns all four buckets, with n=0/hit_rate=0.0 for any
    bucket with no members.
    """
    if not pairs:
        return []

    results: list[dict] = []
    for low, high, label in _CALIBRATION_BUCKETS:
        is_last_bucket = high == 1.0
        bucket_pairs = [
            (rec, outcome)
            for rec, outcome in pairs
            if low <= rec.confidence < high or (is_last_bucket and rec.confidence == high)
        ]
        results.append(
            {
                "bucket": label,
                "n": len(bucket_pairs),
                "hit_rate": hit_rate(bucket_pairs),
            }
        )
    return results
