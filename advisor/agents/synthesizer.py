"""Synthesizer: turns analyst reports + debate into a final Recommendation.

The LLM only emits the judgment fields (direction, sizing, thesis,
confidence, invalidation, horizon) via SynthesizerOutput. Everything
provenance-related — id, created_at, prompt_version, model_id, and the
entry prices — is stamped in code so it can't drift from what actually ran.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from advisor.agents.base import MODEL, load_prompt, structured_call
from advisor.agents.debate import DebateResult
from advisor.schema import AnalystReport, InvalidationRule, Recommendation

logger = logging.getLogger(__name__)

PROMPT_NAME = "synthesizer"


class SynthesizerOutput(BaseModel):
    """Judgment fields the LLM is responsible for; the rest is stamped in code."""

    direction: str
    size_pct: float = Field(ge=0, le=5)
    thesis: str
    # A literal 0 or 1 confidence is not a calibrated estimate -- it's the
    # model refusing to commit to a number at all. _strict_schema (base.py)
    # strips numeric range keywords from the tool schema Anthropic sees
    # (strict tool mode rejects them), so this bound only fires in pydantic
    # validation + structured_call's self-repair retry, feeding the
    # violation back to the model rather than silently degenerating.
    confidence: float = Field(ge=0.05, le=0.95)
    invalidation: InvalidationRule
    horizon_days: int = Field(ge=5, le=30)


def synthesize(ticker: str, reports: list[AnalystReport], debate: DebateResult) -> Recommendation:
    """Synthesize analyst reports + debate into a final Recommendation for `ticker`."""
    payload = {
        "ticker": ticker,
        "reports": [r.model_dump() for r in reports],
        "debate": debate.model_dump(),
    }

    system_prompt, version = load_prompt(PROMPT_NAME)
    output = structured_call(
        system_prompt=system_prompt,
        user_payload=json.dumps(payload, default=str),
        output_model=SynthesizerOutput,
    )
    logger.debug("synthesizer prompt_version=%s ticker=%s", version, ticker)

    return Recommendation(
        ticker=ticker,
        direction=output.direction,
        size_pct=output.size_pct,
        thesis=output.thesis,
        confidence=output.confidence,
        invalidation=output.invalidation,
        horizon_days=output.horizon_days,
        prompt_version=version,
        model_id=MODEL,
    )
