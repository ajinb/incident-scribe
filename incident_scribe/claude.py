"""The one place incident-scribe talks to the Claude API.

Every call is:

* **budget-checked** — input tokens are counted (``messages.count_tokens``, a
  free endpoint) before the paid request, and an over-budget prompt fails
  closed with :class:`TokenBudgetExceeded` instead of spending money;
* **schema-constrained** — structured outputs (``output_format=<pydantic model>``)
  make the API return JSON that validates against the model;
* **refusal-aware** — on models that support it, the server-side
  ``fallbacks: "default"`` route re-runs a declined request on Anthropic's
  recommended fallback; a refusal that survives is raised, never parsed;
* **audited** — the event-sourcing log records model, prompt version, latency
  and token usage for every call.
"""

from __future__ import annotations

import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .patterns.event_sourcing import ApiTimer, log_api_call
from .prompts import PROMPT_VERSION

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EFFORT = "medium"
DEFAULT_MAX_TOKENS = 16_000
DEFAULT_MAX_INPUT_TOKENS = 100_000

# Models that accept ``fallbacks: "default"`` on the Claude API. Sending the
# parameter to any other model is a 400, so it is opt-in by model.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}

T = TypeVar("T", bound=BaseModel)


class ClaudeCallError(RuntimeError):
    """The call completed but did not produce a usable answer."""


class TokenBudgetExceeded(ClaudeCallError):
    """The prompt is larger than the per-call input budget; nothing was billed."""


def get_model() -> str:
    return os.environ.get("INCIDENT_SCRIBE_MODEL", DEFAULT_MODEL)


def get_effort() -> str:
    return os.environ.get("INCIDENT_SCRIBE_EFFORT", DEFAULT_EFFORT)


def get_max_tokens() -> int:
    return int(os.environ.get("INCIDENT_SCRIBE_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))


def get_max_input_tokens() -> int:
    return int(os.environ.get("INCIDENT_SCRIBE_MAX_INPUT_TOKENS", str(DEFAULT_MAX_INPUT_TOKENS)))


def _count_input_tokens(
    client: anthropic.Anthropic, model: str, system: str, user_content: str
) -> int:
    try:
        counted = client.messages.count_tokens(
            model=model,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return counted.input_tokens
    except anthropic.APIStatusError as e:
        if e.status_code in (400, 401, 403, 404):
            raise  # a real configuration problem; the paid call would fail too
        # Counting is best-effort; a conservative estimate keeps the budget honest.
        return (len(system) + len(user_content)) // 3


@retry(
    retry=retry_if_exception_type(
        (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=10),
    reraise=True,
)
def call_structured(
    client: anthropic.Anthropic,
    *,
    system: str,
    user_content: str,
    output_model: type[T],
    stage: str,
    max_input_tokens: int | None = None,
) -> T:
    """Run one schema-constrained call and return the validated pydantic object."""
    model = get_model()
    budget = max_input_tokens if max_input_tokens is not None else get_max_input_tokens()

    input_tokens = _count_input_tokens(client, model, system, user_content)
    if input_tokens > budget:
        raise TokenBudgetExceeded(
            f"{stage}: prompt is {input_tokens:,} input tokens, over the {budget:,}-token "
            "per-call budget. Trim the thread or raise INCIDENT_SCRIBE_MAX_INPUT_TOKENS."
        )

    kwargs: dict = {}
    if model in _FALLBACK_MODELS:
        kwargs = {"betas": [_FALLBACK_BETA], "fallbacks": "default"}

    with ApiTimer() as timer:
        try:
            response = client.beta.messages.parse(
                model=model,
                max_tokens=get_max_tokens(),
                system=system,
                messages=[{"role": "user", "content": user_content}],
                output_format=output_model,
                output_config={"effort": get_effort()},
                **kwargs,
            )
        except ValidationError as e:
            # The SDK validates while parsing, so a reply cut off at max_tokens
            # surfaces here as invalid JSON rather than as a stop_reason.
            raise ClaudeCallError(
                f"{stage}: structured output did not validate, most often because the reply "
                f"hit max_tokens={get_max_tokens()}. Raise INCIDENT_SCRIBE_MAX_TOKENS or lower "
                f"INCIDENT_SCRIBE_EFFORT. ({e.error_count()} validation error(s))"
            ) from e

    log_api_call(
        stage=stage,
        model=response.model,
        prompt_version=PROMPT_VERSION,
        input_text=user_content[:500],
        output_text="".join(b.text for b in response.content if b.type == "text")[:500],
        latency_ms=timer.elapsed_ms,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        raise ClaudeCallError(f"{stage}: the model declined the request (category={category}).")
    if response.stop_reason == "max_tokens":
        raise ClaudeCallError(
            f"{stage}: output hit max_tokens={get_max_tokens()} before the JSON was complete. "
            "Raise INCIDENT_SCRIBE_MAX_TOKENS or lower INCIDENT_SCRIBE_EFFORT."
        )
    if response.parsed_output is None:
        raise ClaudeCallError(f"{stage}: response carried no structured output.")
    return response.parsed_output
