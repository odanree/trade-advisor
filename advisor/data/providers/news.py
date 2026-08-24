"""yfinance-backed implementation of NewsProvider."""

from __future__ import annotations

import logging

import yfinance as yf

from advisor.data.providers.base import NewsProvider

logger = logging.getLogger(__name__)


class HeadlineProvider(NewsProvider):
    """Fetches recent headlines for a ticker via yfinance's Ticker.news.

    yfinance's news payload shape has shifted across versions (top-level
    "title" vs. a nested "content" dict), so both are tried defensively.
    On any failure this returns an empty list rather than raising, since
    sentiment analysis can degrade gracefully with no headlines.
    """

    def get_headlines(self, ticker: str, limit: int = 10) -> list[str]:
        try:
            items = yf.Ticker(ticker).news or []
        except Exception as exc:  # noqa: BLE001 - defensive against SDK internals
            logger.debug("news lookup failed for %s: %s", ticker, exc)
            return []

        titles: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            if not title:
                content = item.get("content")
                if isinstance(content, dict):
                    title = content.get("title")
            if title:
                titles.append(str(title))
            if len(titles) >= limit:
                break
        return titles
