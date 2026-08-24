"""Fundamentals analyst: values a ticker off its financial metrics."""

from __future__ import annotations

import json
import logging

from advisor.agents.base import load_prompt, structured_call
from advisor.data.providers.base import MarketDataProvider, ProviderError
from advisor.schema import AnalystReport

logger = logging.getLogger(__name__)

ANALYST_NAME = "fundamentals"


def analyze(ticker: str, provider: MarketDataProvider, news_provider=None) -> AnalystReport:
    """Produce a fundamentals-driven AnalystReport for `ticker`."""
    try:
        quote = provider.get_quote(ticker)
    except ProviderError:
        quote = None

    fundamentals = provider.get_fundamentals(ticker)

    payload = {
        "ticker": ticker,
        "current_price": quote,
        "fundamentals": fundamentals,
    }

    system_prompt, version = load_prompt(ANALYST_NAME)
    report = structured_call(
        system_prompt=system_prompt,
        user_payload=json.dumps(payload, default=str),
        output_model=AnalystReport,
    )
    report.analyst = ANALYST_NAME
    logger.debug("fundamentals analyst prompt_version=%s ticker=%s", version, ticker)
    return report
