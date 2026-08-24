"""Technicals analyst: reads price action off a summarized 120-day history.

The full daily bar series is never sent to the model — it's expensive and
mostly noise. Instead this module computes the standard summary stats in
Python (recent closes, moving averages, distance off 52-week extremes) and
sends only that compact payload.
"""

from __future__ import annotations

import json
import logging

from advisor.agents.base import load_prompt, structured_call
from advisor.data.providers.base import MarketDataProvider, ProviderError
from advisor.schema import AnalystReport

logger = logging.getLogger(__name__)

ANALYST_NAME = "technicals"

_HISTORY_DAYS = 120
_RECENT_CLOSES = 10


def _sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _summarize_history(bars: list[dict]) -> dict:
    closes = [b["close"] for b in bars if "close" in b]
    highs = [b["high"] for b in bars if "high" in b]
    lows = [b["low"] for b in bars if "low" in b]

    if not closes:
        return {}

    last_close = closes[-1]
    fifty_two_wk_high = max(highs) if highs else max(closes)
    fifty_two_wk_low = min(lows) if lows else min(closes)

    pct_off_high = (
        (last_close - fifty_two_wk_high) / fifty_two_wk_high * 100 if fifty_two_wk_high else None
    )
    pct_off_low = (
        (last_close - fifty_two_wk_low) / fifty_two_wk_low * 100 if fifty_two_wk_low else None
    )

    return {
        "recent_closes": closes[-_RECENT_CLOSES:],
        "last_close": last_close,
        "sma_20": _sma(closes, 20),
        "sma_50": _sma(closes, 50),
        "period_high": fifty_two_wk_high,
        "period_low": fifty_two_wk_low,
        "pct_off_period_high": pct_off_high,
        "pct_off_period_low": pct_off_low,
        "bars_available": len(closes),
    }


def analyze(ticker: str, provider: MarketDataProvider, news_provider=None) -> AnalystReport:
    """Produce a technicals-driven AnalystReport for `ticker`."""
    try:
        bars = provider.get_history(ticker, _HISTORY_DAYS)
    except ProviderError as exc:
        logger.warning("history unavailable for %s: %s", ticker, exc)
        bars = []

    payload = {
        "ticker": ticker,
        "summary": _summarize_history(bars),
    }

    system_prompt, version = load_prompt(ANALYST_NAME)
    report = structured_call(
        system_prompt=system_prompt,
        user_payload=json.dumps(payload, default=str),
        output_model=AnalystReport,
    )
    report.analyst = ANALYST_NAME
    logger.debug("technicals analyst prompt_version=%s ticker=%s", version, ticker)
    return report
