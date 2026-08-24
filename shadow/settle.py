"""Settle open recommendations: check invalidation/horizon triggers and close them out."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from advisor.data.providers.base import MarketDataProvider
from advisor.data.providers.yfinance import YFinanceProvider
from advisor.ledger import Ledger
from advisor.schema import Outcome

from shadow.benchmark import alpha, benchmark_return_pct, rec_return_pct
from shadow.paper import close_paper_position

logger = logging.getLogger(__name__)


def settle(
    ledger: Ledger | None = None,
    provider: MarketDataProvider | None = None,
    now: datetime | None = None,
) -> list[Outcome]:
    """Check every open recommendation for invalidation or horizon expiry.

    Dependency-injected (ledger/provider/now) so tests never hit the network or
    the real clock. For each open rec: fetch a quote, check the invalidation
    rule and the horizon deadline. If neither fires, leave it open. If either
    fires, close it out with an Outcome (invalidation wins when both are true
    in the same pass), append to the ledger, and close the mirrored paper
    position. Returns the outcomes created in this pass.
    """
    ledger = ledger or Ledger()
    provider = provider or YFinanceProvider()
    now = now or datetime.now(UTC)

    outcomes: list[Outcome] = []

    for rec in ledger.open_recommendations():
        try:
            quote = provider.get_quote(rec.ticker)
        except Exception:
            logger.exception(
                "Failed to fetch quote for %s (rec %s); skipping this settle pass.",
                rec.ticker,
                rec.id,
            )
            continue

        rule = rec.invalidation
        triggered = (rule.type == "price_below" and quote < rule.level) or (
            rule.type == "price_above" and quote > rule.level
        )
        expired = now >= rec.created_at + timedelta(days=rec.horizon_days)

        if not triggered and not expired:
            continue

        close_reason = "invalidation" if triggered else "horizon"

        try:
            benchmark_quote = provider.get_quote("SPY")
        except Exception:
            logger.exception(
                "Failed to fetch SPY quote while settling rec %s; skipping this settle pass.",
                rec.id,
            )
            continue

        outcome = Outcome(
            rec_id=rec.id,
            closed_at=now,
            close_reason=close_reason,
            exit_price=quote,
            benchmark_exit_price=benchmark_quote,
            rec_return_pct=rec_return_pct(rec, quote),
            benchmark_return_pct=benchmark_return_pct(rec, benchmark_quote),
            alpha_pct=alpha(rec, quote, benchmark_quote),
        )

        ledger.append_outcome(outcome)
        close_paper_position(rec.ticker)
        outcomes.append(outcome)

    return outcomes
