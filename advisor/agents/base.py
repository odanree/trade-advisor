"""Shared LLM plumbing used by every analyst/debate/synthesizer agent.

Centralizes client construction, prompt loading (with version extraction),
and a single structured-output call helper so each agent module only has to
supply a system prompt, a user payload, and a pydantic output model.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = os.getenv("ADVISOR_MODEL") or "claude-sonnet-5"

_PROMPTS_DIR = Path(__file__).parents[2] / "prompts"
_VERSION_RE = re.compile(r"<!--\s*version:\s*(\S+)\s*-->")

# Wrapper keys models sometimes nest tool input under instead of emitting the
# schema's fields at the top level (e.g. {"parameters": {...actual fields...}}).
_ENVELOPE_KEYS = {"parameters", "input", "properties", "arguments"}

# Total attempts (initial call + self-repair retries) before giving up.
_MAX_STRUCTURED_CALL_ATTEMPTS = 3

_client: anthropic.Anthropic | None = None


class StructuredCallError(Exception):
    """Raised when structured_call exhausts its self-repair attempts.

    Carries the last validation failure (a pydantic ValidationError, or a
    str describing a missing tool_use block) as `last_error` for logging/
    debugging by the caller.
    """

    def __init__(self, message: str, last_error: ValidationError | str | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


def _unwrap_envelope(data: object) -> object:
    """Descend through single-key wrapper objects like {"parameters": {...}}.

    Some models nest the actual output fields inside an envelope key instead
    of emitting them at the top level of the tool input. Keeps unwrapping as
    long as the data is a dict with exactly one key drawn from
    `_ENVELOPE_KEYS` whose value is itself a dict.
    """
    while isinstance(data, dict) and len(data) == 1:
        (key, value), = data.items()
        if key in _ENVELOPE_KEYS and isinstance(value, dict):
            data = value
        else:
            break
    return data


def _strict_schema(model: type[BaseModel]) -> dict:
    """Return `model`'s JSON schema tightened for Anthropic strict tool use.

    Strict mode requires every object node in the schema -- including
    submodels nested under `$defs` -- to declare `"additionalProperties":
    false` and a `"required"` list covering all of its properties. This
    walks the schema recursively (through `$defs`, `items`, and
    `anyOf`/`oneOf`/`allOf` branches) and tightens every object node in
    place, without inlining `$ref`/`$defs` -- the schema keeps referencing
    submodels by name, just with each definition tightened.
    """
    schema = model.model_json_schema()

    def _tighten(node: object) -> None:
        if not isinstance(node, dict):
            return

        properties = node.get("properties")
        if isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties.keys())
            for value in properties.values():
                _tighten(value)

        for defs_key in ("$defs", "definitions"):
            defs = node.get(defs_key)
            if isinstance(defs, dict):
                for value in defs.values():
                    _tighten(value)

        items = node.get("items")
        if isinstance(items, dict):
            _tighten(items)

        for combinator_key in ("anyOf", "oneOf", "allOf"):
            variants = node.get(combinator_key)
            if isinstance(variants, list):
                for variant in variants:
                    _tighten(variant)

    _tighten(schema)
    return schema


def get_client() -> anthropic.Anthropic:
    """Return a process-wide Anthropic client, reading ANTHROPIC_API_KEY from env."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def load_prompt(name: str) -> tuple[str, str]:
    """Load prompts/{name}.md and extract its `<!-- version: vN -->` header.

    Returns (prompt_text, version). Raises FileNotFoundError if the prompt
    is missing, and ValueError if it has no version header.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")

    match = _VERSION_RE.search(text)
    if not match:
        raise ValueError(f"prompts/{name}.md is missing a `<!-- version: vN -->` header")

    return text, match.group(1)


_MAX_MAX_TOKENS = 8000


def structured_call(
    system_prompt: str,
    user_payload: str,
    output_model: type[BaseModel],
    model: str = MODEL,
    max_tokens: int = 4000,
    client: anthropic.Anthropic | None = None,
) -> BaseModel:
    """Call Claude and force a validated instance of `output_model` out of it.

    The (large, stable) system prompt is cache_control'd as an ephemeral
    prompt-cache breakpoint since analysts reuse the same methodology prompt
    across many tickers per run. A single forced tool named "emit" carries
    the output schema, so the model has no path but to call it.

    Envelope wrappers (e.g. {"parameters": {...}}) around the tool input are
    unwrapped before validation. If the input still fails to validate against
    `output_model` (or the response has no tool_use block at all), the
    failure is fed back to the model as a self-repair retry: up to
    `_MAX_STRUCTURED_CALL_ATTEMPTS` total attempts, reusing the same system
    blocks so the prompt cache still hits.

    A response with `stop_reason == "max_tokens"` is treated as a failed
    attempt even if a tool_use block parsed and would otherwise validate --
    truncation mid-emission can silently drop or shorten fields (e.g. a
    DebateResult missing bear_case) without tripping schema validation. The
    self-repair retry after a truncation asks the model to re-emit with
    materially shorter field values, and doubles `max_tokens` for that retry
    (capped at `_MAX_MAX_TOKENS`) so the same limit doesn't just truncate
    again. Raises StructuredCallError if every attempt fails.
    """
    client = client or get_client()

    tool = {
        "name": "emit",
        "description": (
            f"Emit the result as a {output_model.__name__}. The input MUST be the flat "
            "field object matching the schema below, with every field at the TOP LEVEL "
            "of the tool input -- do not nest it inside a 'parameters', 'input', or any "
            "other wrapper key."
        ),
        "input_schema": _strict_schema(output_model),
        "strict": True,
    }
    system = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages: list[dict] = [{"role": "user", "content": user_payload}]

    current_max_tokens = max_tokens
    last_error: ValidationError | str | None = None
    for attempt in range(1, _MAX_STRUCTURED_CALL_ATTEMPTS + 1):
        response = client.messages.create(
            model=model,
            max_tokens=current_max_tokens,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": "emit"},
            messages=messages,
        )

        usage = response.usage
        logger.debug(
            "structured_call model=%s attempt=%s/%s max_tokens=%s cache_read=%s cache_creation=%s input=%s output=%s",
            model,
            attempt,
            _MAX_STRUCTURED_CALL_ATTEMPTS,
            current_max_tokens,
            getattr(usage, "cache_read_input_tokens", None),
            getattr(usage, "cache_creation_input_tokens", None),
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
        )

        truncated = response.stop_reason == "max_tokens"
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if truncated:
            last_error = (
                f"response truncated by max_tokens limit (stop_reason='max_tokens', "
                f"max_tokens={current_max_tokens}) -- output may be cut off mid-emission "
                "even if a tool_use block parsed"
            )
            logger.warning(
                "structured_call attempt %s/%s: %s", attempt, _MAX_STRUCTURED_CALL_ATTEMPTS, last_error
            )
        elif tool_use is None:
            last_error = f"no tool_use block in response (stop_reason={response.stop_reason!r})"
            logger.warning(
                "structured_call attempt %s/%s: %s", attempt, _MAX_STRUCTURED_CALL_ATTEMPTS, last_error
            )
        else:
            try:
                return output_model.model_validate(_unwrap_envelope(tool_use.input))
            except ValidationError as exc:
                last_error = exc
                logger.warning(
                    "structured_call attempt %s/%s: validation failed: %s",
                    attempt,
                    _MAX_STRUCTURED_CALL_ATTEMPTS,
                    exc,
                )

        if attempt == _MAX_STRUCTURED_CALL_ATTEMPTS:
            break

        messages.append({"role": "assistant", "content": response.content})

        if truncated:
            feedback_text = (
                "Your previous tool call was truncated by the token limit before it "
                "finished emitting (stop_reason='max_tokens'). Call the emit tool "
                "again, but re-emit with materially shorter field values so the full "
                "output fits within the token limit."
            )
            current_max_tokens = min(current_max_tokens * 2, _MAX_MAX_TOKENS)
        else:
            feedback_text = (
                f"Your tool call failed validation:\n{last_error}\n"
                "Call the emit tool again with a corrected input. Emit the fields at "
                "the TOP LEVEL of the tool input (no wrapper object). Follow the JSON "
                "schema exactly -- key_points must be a JSON array of plain strings, "
                "not HTML."
            )
        if tool_use is not None:
            # The prior assistant turn contains a tool_use block, so the API
            # requires the very next turn to answer it with a matching
            # tool_result -- a plain text user message here gets rejected
            # with a 400 ("tool_use ids were found without tool_result
            # blocks immediately after").
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "is_error": True,
                            "content": feedback_text,
                        }
                    ],
                }
            )
        else:
            # No tool_use block at all (e.g. the model stopped early), so
            # there's no tool_use id to answer -- plain text is fine.
            messages.append({"role": "user", "content": feedback_text})

    raise StructuredCallError(
        f"structured_call for {output_model.__name__} failed after "
        f"{_MAX_STRUCTURED_CALL_ATTEMPTS} attempts: {last_error}",
        last_error=last_error,
    )
