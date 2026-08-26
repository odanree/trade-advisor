"""advisor.agents.synthesizer: SynthesizerOutput horizon_days validation (5-30 day cap)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from advisor.agents.synthesizer import SynthesizerOutput
from advisor.schema import InvalidationRule


def _payload(**overrides: Any) -> dict:
    defaults: dict[str, Any] = {
        "direction": "buy",
        "size_pct": 5.0,
        "thesis": "Test thesis.",
        "confidence": 0.75,
        "invalidation": InvalidationRule(type="price_below", level=90.0),
        "horizon_days": 15,
    }
    defaults.update(overrides)
    return defaults


def test_horizon_days_above_cap_raises() -> None:
    with pytest.raises(ValidationError):
        SynthesizerOutput(**_payload(horizon_days=45))


def test_horizon_days_at_upper_bound_passes() -> None:
    output = SynthesizerOutput(**_payload(horizon_days=30))
    assert output.horizon_days == 30


def test_horizon_days_at_lower_bound_passes() -> None:
    output = SynthesizerOutput(**_payload(horizon_days=5))
    assert output.horizon_days == 5


def test_horizon_days_below_lower_bound_raises() -> None:
    with pytest.raises(ValidationError):
        SynthesizerOutput(**_payload(horizon_days=4))
