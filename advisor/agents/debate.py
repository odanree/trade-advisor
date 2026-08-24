"""Bull-vs-bear debate step: argues both sides from the analyst reports."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from advisor.agents.base import load_prompt, structured_call
from advisor.schema import AnalystReport

logger = logging.getLogger(__name__)

PROMPT_NAME = "debate"


class DebateResult(BaseModel):
    """The strongest bull and bear cases synthesized from the analyst reports."""

    bull_case: str
    bear_case: str


def run_debate(ticker: str, reports: list[AnalystReport]) -> DebateResult:
    """Run the bull-vs-bear debate over the analysts' reports for `ticker`."""
    payload = {
        "ticker": ticker,
        "reports": [r.model_dump() for r in reports],
    }

    system_prompt, version = load_prompt(PROMPT_NAME)
    result = structured_call(
        system_prompt=system_prompt,
        user_payload=json.dumps(payload, default=str),
        output_model=DebateResult,
    )
    logger.debug("debate prompt_version=%s ticker=%s", version, ticker)
    return result
