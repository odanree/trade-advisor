"""structured_call: envelope unwrapping, self-repair retries, and failure mode.

Uses a minimal stub Anthropic client (types.SimpleNamespace-style fakes) so
these tests exercise advisor.agents.base.structured_call without any network
calls. DebateResult (bull_case/bear_case) stands in as a representative
output_model -- the behavior under test is generic to structured_call, not
specific to any one schema.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pydantic import BaseModel, Field

from advisor.agents.base import StructuredCallError, _strict_schema, structured_call
from advisor.agents.debate import DebateResult


def _usage() -> SimpleNamespace:
    return SimpleNamespace(
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        input_tokens=10,
        output_tokens=10,
    )


def _tool_use_block(input_: dict, id_: str = "toolu_stub") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name="emit", input=input_)


def _response(input_: dict | None, stop_reason: str = "tool_use") -> SimpleNamespace:
    content = [_tool_use_block(input_)] if input_ is not None else []
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=_usage())


class StubMessages:
    """Fake `client.messages` that hands back canned responses in order."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class StubClient:
    """Fake Anthropic client exposing only the `messages.create` surface used."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.messages = StubMessages(responses)


def test_enveloped_input_unwraps_and_validates_on_first_try() -> None:
    client = StubClient(
        [_response({"parameters": {"bull_case": "Strong earnings.", "bear_case": "Valuation stretched."}})]
    )

    result = structured_call(
        system_prompt="sys",
        user_payload="payload",
        output_model=DebateResult,
        client=client,
    )

    assert result == DebateResult(bull_case="Strong earnings.", bear_case="Valuation stretched.")
    assert len(client.messages.calls) == 1


def test_invalid_then_valid_retries_once_and_feeds_back_error() -> None:
    bad_tool_use_id = "toolu_bad_attempt"
    # Build the first (failing) response explicitly so its tool_use id is
    # identifiable and reused in the assertion below.
    client = StubClient(
        [
            SimpleNamespace(
                content=[_tool_use_block({}, id_=bad_tool_use_id)],
                stop_reason="tool_use",
                usage=_usage(),
            ),
            _response({"bull_case": "Strong earnings.", "bear_case": "Valuation stretched."}),
        ]
    )

    result = structured_call(
        system_prompt="sys",
        user_payload="payload",
        output_model=DebateResult,
        client=client,
    )

    assert result == DebateResult(bull_case="Strong earnings.", bear_case="Valuation stretched.")
    assert len(client.messages.calls) == 2

    second_call_messages = client.messages.calls[1]["messages"]
    # Original user turn, the assistant's failed tool call, and our
    # self-repair follow-up -- which must be a tool_result answering the
    # prior turn's tool_use block, not a plain text user message, or the
    # real API rejects it with a 400.
    assert len(second_call_messages) == 3
    assert second_call_messages[0] == {"role": "user", "content": "payload"}
    assert second_call_messages[1]["role"] == "assistant"

    follow_up = second_call_messages[2]
    assert follow_up["role"] == "user"
    assert isinstance(follow_up["content"], list)
    tool_result = follow_up["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == bad_tool_use_id
    assert tool_result["is_error"] is True
    assert "failed validation" in tool_result["content"]
    assert "TOP LEVEL" in tool_result["content"]

    # System blocks must be identical across retries so the prompt cache hits.
    assert client.messages.calls[0]["system"] == client.messages.calls[1]["system"]


def test_no_tool_use_block_retries_with_plain_text_feedback() -> None:
    """When a response has no tool_use block at all, there's no id to answer,
    so the self-repair follow-up must be a plain text user message instead
    of a tool_result block.
    """
    client = StubClient(
        [
            _response(None, stop_reason="end_turn"),
            _response({"bull_case": "Strong earnings.", "bear_case": "Valuation stretched."}),
        ]
    )

    result = structured_call(
        system_prompt="sys",
        user_payload="payload",
        output_model=DebateResult,
        client=client,
    )

    assert result == DebateResult(bull_case="Strong earnings.", bear_case="Valuation stretched.")

    follow_up = client.messages.calls[1]["messages"][2]
    assert follow_up["role"] == "user"
    assert isinstance(follow_up["content"], str)
    assert "failed validation" in follow_up["content"]


def test_truncated_response_retries_with_larger_max_tokens() -> None:
    """A stop_reason='max_tokens' response must be treated as a failed
    attempt -- even when it carries a tool_use block whose input would
    otherwise validate -- since truncation mid-emission can silently drop or
    shorten fields without tripping schema validation. The self-repair
    retry must call out the truncation and bump max_tokens for the retry.
    """
    client = StubClient(
        [
            _response(
                {"bull_case": "Strong earnings.", "bear_case": "Valuation stretched."},
                stop_reason="max_tokens",
            ),
            _response({"bull_case": "Strong earnings.", "bear_case": "Valuation stretched."}),
        ]
    )

    result = structured_call(
        system_prompt="sys",
        user_payload="payload",
        output_model=DebateResult,
        max_tokens=4000,
        client=client,
    )

    assert result == DebateResult(bull_case="Strong earnings.", bear_case="Valuation stretched.")
    assert len(client.messages.calls) == 2

    first_max_tokens = client.messages.calls[0]["max_tokens"]
    second_max_tokens = client.messages.calls[1]["max_tokens"]
    assert first_max_tokens == 4000
    assert second_max_tokens > first_max_tokens

    follow_up = client.messages.calls[1]["messages"][2]
    assert follow_up["role"] == "user"
    assert isinstance(follow_up["content"], list)
    tool_result = follow_up["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["is_error"] is True
    assert "truncated" in tool_result["content"].lower()
    assert "shorter" in tool_result["content"].lower()


def test_all_attempts_invalid_raises_structured_call_error() -> None:
    client = StubClient([_response({}), _response({}), _response({})])

    with pytest.raises(StructuredCallError) as exc_info:
        structured_call(
            system_prompt="sys",
            user_payload="payload",
            output_model=DebateResult,
            client=client,
        )

    assert len(client.messages.calls) == 3
    assert exc_info.value.last_error is not None


class _Address(BaseModel):
    street: str
    city: str


class _Person(BaseModel):
    name: str
    address: _Address


def test_strict_schema_tightens_every_object_node_including_defs() -> None:
    schema = _strict_schema(_Person)

    # Top-level node: additionalProperties False + required covers every property.
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"name", "address"}

    # The nested submodel lives under $defs (not inlined) and must be
    # tightened the same way as the top-level node.
    address_def = schema["$defs"]["_Address"]
    assert address_def["additionalProperties"] is False
    assert set(address_def["required"]) == {"street", "city"}

    # $ref/$defs structure is preserved, not inlined.
    assert schema["properties"]["address"]["$ref"] == "#/$defs/_Address"


class _RangedSub(BaseModel):
    confidence: float = Field(ge=0, le=1)


class _RangedModel(BaseModel):
    horizon_days: int = Field(ge=1, le=10)
    score: float = Field(ge=0, le=1)
    sub: _RangedSub


def test_strict_schema_strips_numeric_range_keywords() -> None:
    """Anthropic's strict tool mode 400s on 'minimum'/'maximum' (and the
    exclusive/multipleOf variants) for integer/number schema nodes. These
    must be stripped from the schema sent to the API -- top level and
    inside nested submodels under $defs -- while range enforcement still
    lives on the pydantic model itself (Field(ge=..., le=...)), and
    additionalProperties/required tightening is unaffected.
    """
    schema = _strict_schema(_RangedModel)

    _RANGE_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}

    def _assert_no_range_keys(node: object) -> None:
        if isinstance(node, dict):
            assert not (_RANGE_KEYS & node.keys()), f"range keys leaked into schema node: {node}"
            for value in node.values():
                _assert_no_range_keys(value)
        elif isinstance(node, list):
            for item in node:
                _assert_no_range_keys(item)

    _assert_no_range_keys(schema)

    # additionalProperties/required tightening still applies at both levels.
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"horizon_days", "score", "sub"}

    sub_def = schema["$defs"]["_RangedSub"]
    assert sub_def["additionalProperties"] is False
    assert set(sub_def["required"]) == {"confidence"}

    # The pydantic model itself must still enforce the range so an
    # out-of-range value fails validation and triggers the self-repair retry.
    with pytest.raises(Exception):
        _RangedModel(horizon_days=99, score=0.5, sub=_RangedSub(confidence=0.5))
