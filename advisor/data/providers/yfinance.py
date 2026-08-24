"""yfinance-backed implementation of MarketDataProvider.

Named ``yfinance.py`` to match the spec even though it shadows the
``yfinance`` package name; the import below is absolute (Python 3's default),
so it resolves to the installed package rather than this module.
"""

from __future__ import annotations

import logging

import yfinance as yf

from advisor.data.providers.base import MarketDataProvider, ProviderError

logger = logging.getLogger(__name__)


class YFinanceProvider(MarketDataProvider):
    """Fetches quotes, history, and fundamentals via the yfinance package.

    yfinance's fields are notoriously unstable (fast_info/info keys go
    missing or get renamed across versions and tickers), so every accessor
    here is defensive: it tries several fallbacks before raising a clear
    ProviderError.
    """

    def get_quote(self, ticker: str) -> float:
        t = yf.Ticker(ticker)
        try:
            price = t.fast_info.get("lastPrice") if hasattr(t.fast_info, "get") else t.fast_info.last_price
            if price:
                return float(price)
        except Exception as exc:  # noqa: BLE001 - defensive against SDK internals
            logger.debug("fast_info quote lookup failed for %s: %s", ticker, exc)

        try:
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            if price:
                return float(price)
        except Exception as exc:  # noqa: BLE001
            logger.debug("info quote lookup failed for %s: %s", ticker, exc)

        try:
            hist = t.history(period="1d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as exc:  # noqa: BLE001
            logger.debug("history quote lookup failed for %s: %s", ticker, exc)

        raise ProviderError(f"could not resolve a quote for {ticker!r}")

    def get_history(self, ticker: str, days: int) -> list[dict]:
        t = yf.Ticker(ticker)
        try:
            hist = t.history(period=f"{max(days, 1)}d")
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"could not fetch history for {ticker!r}: {exc}") from exc

        if hist is None or hist.empty:
            raise ProviderError(f"no history returned for {ticker!r}")

        bars: list[dict] = []
        for index, row in hist.iterrows():
            try:
                volume = row.get("Volume")
                volume_int = int(volume) if volume is not None and volume == volume else 0  # NaN != NaN
                bars.append(
                    {
                        "date": index.strftime("%Y-%m-%d") if hasattr(index, "strftime") else str(index),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": volume_int,
                    }
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug("skipping malformed history row for %s: %s", ticker, exc)
                continue
        return bars

    def get_fundamentals(self, ticker: str) -> dict:
        t = yf.Ticker(ticker)
        try:
            info = t.info
        except Exception as exc:  # noqa: BLE001
            logger.debug("fundamentals lookup failed for %s: %s", ticker, exc)
            return {}

        if not info:
            return {}

        keys = (
            "trailingPE",
            "forwardPE",
            "priceToBook",
            "marketCap",
            "dividendYield",
            "trailingEps",
            "forwardEps",
            "returnOnEquity",
            "debtToEquity",
            "revenueGrowth",
            "earningsGrowth",
            "profitMargins",
            "fiftyTwoWeekHigh",
            "fiftyTwoWeekLow",
            "shortName",
            "sector",
            "industry",
            "recommendationKey",
            "targetMeanPrice",
        )
        return {k: info[k] for k in keys if info.get(k) is not None}
