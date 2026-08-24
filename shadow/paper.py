"""Shadow-mode paper trading: mirror advisor recommendations into an Alpaca paper account.

This module must never raise. It sits off the advice path — if Alpaca is down,
misconfigured, or rejects an order, we log and move on rather than blocking the
advisor pipeline or the settle job.
"""

from __future__ import annotations

import logging
import os

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from advisor.schema import Recommendation

logger = logging.getLogger(__name__)

_FIXED_NOTIONAL_USD = 1000.0


def _get_client() -> TradingClient | None:
    """Build a paper-trading TradingClient from env creds, or None if unconfigured."""
    api_key = os.environ.get("ALPACA_PAPER_API_KEY")
    secret_key = os.environ.get("ALPACA_PAPER_SECRET_KEY")
    if not api_key or not secret_key:
        logger.warning(
            "ALPACA_PAPER_API_KEY / ALPACA_PAPER_SECRET_KEY not set; shadow paper mirror disabled."
        )
        return None
    try:
        return TradingClient(api_key=api_key, secret_key=secret_key, paper=True)
    except Exception:
        logger.exception("Failed to construct Alpaca paper TradingClient.")
        return None


def _has_open_position(client: TradingClient, ticker: str) -> bool:
    try:
        client.get_open_position(ticker)
        return True
    except Exception:
        return False


def mirror_recommendation(rec: Recommendation) -> str | None:
    """Mirror one recommendation into the Alpaca paper account as a fixed $1000 notional order.

    "buy" -> $1000 notional market buy.
    "sell" -> if an open paper position exists in the ticker, close it fully; else skip.
    "trim" -> if an open paper position exists, reduce it by $1000 notional; else skip.
    "hold" -> always skipped.

    Returns the Alpaca order id, or None if nothing was submitted (hold, no
    position to sell/trim, unconfigured credentials, or any Alpaca error).
    Never raises.
    """
    client = _get_client()
    if client is None:
        return None

    try:
        if rec.direction == "hold":
            logger.debug("Skipping paper mirror for hold rec %s (%s).", rec.id, rec.ticker)
            return None

        if rec.direction == "buy":
            order = MarketOrderRequest(
                symbol=rec.ticker,
                notional=_FIXED_NOTIONAL_USD,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            submitted = client.submit_order(order_data=order)
            return str(submitted.id)

        if rec.direction in ("sell", "trim"):
            if not _has_open_position(client, rec.ticker):
                logger.info(
                    "No open paper position in %s; skipping %s mirror for rec %s.",
                    rec.ticker,
                    rec.direction,
                    rec.id,
                )
                return None

            if rec.direction == "sell":
                closed = client.close_position(rec.ticker)
                order_id = getattr(closed, "id", None)
                return str(order_id) if order_id else None

            # trim: reduce the position by a fixed $1000 notional sell.
            order = MarketOrderRequest(
                symbol=rec.ticker,
                notional=_FIXED_NOTIONAL_USD,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            submitted = client.submit_order(order_data=order)
            return str(submitted.id)

        logger.warning("Unhandled direction %r for rec %s; skipping mirror.", rec.direction, rec.id)
        return None
    except Exception:
        logger.exception(
            "Alpaca error mirroring rec %s (%s %s); shadow mirror skipped.",
            rec.id,
            rec.direction,
            rec.ticker,
        )
        return None


def close_paper_position(ticker: str) -> None:
    """Close any open paper position in `ticker` at settle time. Never raises."""
    client = _get_client()
    if client is None:
        return
    try:
        if _has_open_position(client, ticker):
            client.close_position(ticker)
    except Exception:
        logger.exception("Alpaca error closing paper position for %s.", ticker)
