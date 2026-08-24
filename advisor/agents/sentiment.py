"""Sentiment analyst: reads recent headlines for a ticker."""

from __future__ import annotations

import json
import logging

from advisor.agents.base import load_prompt, structured_call
from advisor.data.providers.base import MarketDataProvider, NewsProvider
from advisor.schema import AnalystReport

logger = logging.getLogger(__name__)

ANALYST_NAME = "sentiment"

_HEADLINE_LIMIT = 10


def analyze(
    ticker: str, provider: MarketDataProvider, news_provider: NewsProvider | None = None
) -> AnalystReport:
    """Produce a sentiment-driven AnalystReport for `ticker` from headlines."""
    headlines: list[str] = []
    if news_provider is not None:
        headlines = news_provider.get_headlines(ticker, limit=_HEADLINE_LIMIT)

    payload = {
        "ticker": ticker,
        "headlines": headlines,
    }

    system_prompt, version = load_prompt(ANALYST_NAME)
    report = structured_call(
        system_prompt=system_prompt,
        user_payload=json.dumps(payload, default=str),
        output_model=AnalystReport,
    )
    report.analyst = ANALYST_NAME
    logger.debug("sentiment analyst prompt_version=%s ticker=%s", version, ticker)
    return report
