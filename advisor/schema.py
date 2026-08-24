"""Pydantic v2 data contracts shared across the trade-advisor package.

This module is the cross-package contract: field names and types here are
relied on by ``shadow/``, ``evals/``, ``cli.py`` and the ledger. Do not rename
fields without coordinating across those packages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class InvalidationRule(BaseModel):
    """Condition under which an open recommendation should be closed early."""

    type: Literal["price_below", "price_above"]
    level: float


class AnalystReport(BaseModel):
    """Single-analyst output feeding into the bull/bear debate."""

    analyst: str
    stance: Literal["bull", "bear", "neutral"]
    summary: str
    key_points: list[str]


class Recommendation(BaseModel):
    """A synthesized, ledger-appendable trade recommendation."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ticker: str
    direction: Literal["buy", "sell", "trim", "hold"]
    size_pct: float
    thesis: str
    confidence: float
    invalidation: InvalidationRule
    horizon_days: int
    prompt_version: str
    model_id: str
    entry_price: float | None = None
    benchmark_entry_price: float | None = None


class Outcome(BaseModel):
    """Closure record for a recommendation, scored against the benchmark."""

    rec_id: str
    closed_at: datetime
    close_reason: Literal["invalidation", "horizon", "manual"]
    exit_price: float
    benchmark_exit_price: float
    rec_return_pct: float
    benchmark_return_pct: float
    alpha_pct: float


class Position(BaseModel):
    """A single holding parsed from a brokerage positions export."""

    symbol: str
    quantity: float
    current_value: float
