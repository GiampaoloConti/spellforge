"""One way to call Claude for every agent: structured JSON out, streamed, measured.

Each agent owns its prompt and schema; this module owns the request details (per-model
options, prompt caching, refusal fallbacks), progress notes from the stream, error mapping,
and usage/cost accounting.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

import anthropic

if TYPE_CHECKING:
    from pydantic import BaseModel

BaseModelT = TypeVar("BaseModelT", bound="BaseModel")

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "low"  # measured: ~40% faster than "high" at equal success (docs/evals)
MAX_OUTPUT_TOKENS = 32_000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
PROGRESS_INTERVAL = 1.0
RETRY_ATTEMPTS = 3  # ponytail: fixed count + linear backoff; covers transient API blips
# Transient statuses to retry. 200 means the stream started, then failed mid-flight (an
# `error` SSE event: overload/5xx). The SDK's own max_retries only covers the initial
# request handshake, never a mid-stream failure, so one blip fails the whole forge.
RETRY_STATUSES = frozenset({200, 500, 502, 503, 529})

# USD per million tokens: (input, output). Cache writes cost 1.25x input, reads 0.1x.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

ProgressNote = Callable[[str], Awaitable[None]]


class AgentError(Exception):
    """An agent could not produce a usable answer (API failure, refusal, bad output)."""


@dataclass
class Usage:
    model: str = ""
    input_tokens: int = 0
    """All input tokens, including cache reads and writes."""
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    seconds: float = 0.0

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICES.get(self.model, (0.0, 0.0))
        uncached = self.input_tokens - self.cache_read_tokens - self.cache_write_tokens
        return (
            uncached * price_in
            + self.cache_write_tokens * price_in * 1.25
            + self.cache_read_tokens * price_in * 0.1
            + self.output_tokens * price_out
        ) / 1_000_000

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            model=self.model or other.model,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            seconds=self.seconds + other.seconds,
        )


@dataclass
class AgentConfig:
    """Model settings for one agent role, overridable per role from the environment.

    `SPELLFORGE_<ROLE>_MODEL` / `SPELLFORGE_<ROLE>_EFFORT` win over `SPELLFORGE_MODEL` /
    `SPELLFORGE_EFFORT`, which win over the defaults.
    """

    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT

    @classmethod
    def for_role(cls, role: str) -> AgentConfig:
        env = os.environ
        prefix = f"SPELLFORGE_{role.upper()}_"
        model, effort = ROLE_DEFAULTS.get(role, (DEFAULT_MODEL, DEFAULT_EFFORT))
        return cls(
            model=env.get(prefix + "MODEL") or env.get("SPELLFORGE_MODEL") or model,
            effort=env.get(prefix + "EFFORT") or env.get("SPELLFORGE_EFFORT") or effort,
        )


ROLE_DEFAULTS: dict[str, tuple[str, str]] = {
    # Measured in docs/evals: structured design and review work is as good and much faster on
    # Sonnet; drawing sprites is where Opus clearly wins.
    "writer": ("claude-opus-5", "low"),
    "designer": ("claude-sonnet-5", "low"),
    "balancer": ("claude-sonnet-5", "low"),
    "coder": ("claude-sonnet-5", "low"),
    "artist": ("claude-opus-5", "low"),
    "dungeon_master": ("claude-sonnet-5", "low"),
}


@dataclass
class Reply:
    data: dict[str, Any]
    content: list[Any] = field(default_factory=list)
    """The assistant content blocks, to replay verbatim in a follow-up turn."""
    usage: Usage = field(default_factory=Usage)


def request_options(model: str, effort: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Model-specific request settings.

    Opus-tier models get adaptive thinking, an effort level and server-side refusal
    fallbacks. Sonnet 5 gets thinking and effort. Haiku 4.5 supports neither.
    """
    options: dict[str, Any] = {
        "output_config": {"format": {"type": "json_schema", "schema": schema}}
    }
    if model.startswith("claude-haiku"):
        return options
    options["thinking"] = {"type": "adaptive"}
    options["output_config"]["effort"] = effort
    if model.startswith(("claude-opus-5", "claude-fable")):
        options["betas"] = [FALLBACK_BETA]
        options["fallbacks"] = "default"
    return options


async def structured_call(
    client: anthropic.AsyncAnthropic,
    config: AgentConfig,
    *,
    system: str,
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    role: str,
    on_progress: ProgressNote | None = None,
    max_tokens: int = MAX_OUTPUT_TOKENS,
) -> Reply:
    """Ask Claude for JSON matching `schema`. Raises AgentError with a player-safe message."""
    started = time.perf_counter()
    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with client.beta.messages.stream(
                model=config.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                **request_options(config.model, config.effort, schema),
            ) as stream:
                await _report_progress(stream, role, on_progress)
                response = await stream.get_final_message()
            break
        except anthropic.AuthenticationError as exc:
            raise AgentError("the forge's API key was rejected") from exc
        except anthropic.RateLimitError as exc:
            raise AgentError("the forge is overloaded (rate limited); try again soon") from exc
        except anthropic.APIConnectionError as exc:
            if attempt + 1 < RETRY_ATTEMPTS:
                await asyncio.sleep(attempt + 1)
                continue
            raise AgentError("could not reach the forge's API") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in RETRY_STATUSES and attempt + 1 < RETRY_ATTEMPTS:
                await asyncio.sleep(attempt + 1)
                continue
            raise AgentError(f"the {role}'s API call failed ({exc.status_code})") from exc

    if response.stop_reason == "refusal":
        raise AgentError(f"the {role} declined this request")
    if response.stop_reason == "max_tokens":
        raise AgentError(f"the {role}'s answer got too long")
    text = next((block.text for block in response.content if block.type == "text"), None)
    try:
        data = json.loads(text or "")
    except ValueError as exc:
        raise AgentError(f"the {role} returned an unreadable answer") from exc
    if not isinstance(data, dict):
        raise AgentError(f"the {role} returned an unreadable answer")

    usage = response.usage
    cache_read = usage.cache_read_input_tokens or 0
    cache_write = usage.cache_creation_input_tokens or 0
    return Reply(
        data=data,
        content=list(response.content),
        usage=Usage(
            model=config.model,
            input_tokens=usage.input_tokens + cache_read + cache_write,
            output_tokens=usage.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            seconds=time.perf_counter() - started,
        ),
    )


async def _report_progress(stream: Any, role: str, on_progress: ProgressNote | None) -> None:
    """Turn stream events into short progress notes ("thinking…", "writing… 1.2k chars")."""
    thinking_reported = False
    characters = 0
    last_report = 0.0
    async for event in stream:
        if on_progress is None or event.type != "content_block_delta":
            continue
        if event.delta.type == "thinking_delta" and not thinking_reported:
            thinking_reported = True
            await on_progress(f"The {role} is thinking it through…")
        elif event.delta.type == "text_delta":
            characters += len(event.delta.text)
            now = time.perf_counter()
            if now - last_report >= PROGRESS_INTERVAL:
                last_report = now
                await on_progress(f"The {role} is writing… {characters / 1000:.1f}k characters")


def unescape(text: str) -> str:
    """Models occasionally double-escape characters in prose (a literal backslash-u2014).

    Decodes those sequences. Only for player-facing prose, never for source code.
    """
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


def credentials_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


async def validated_call(
    client: anthropic.AsyncAnthropic,
    config: AgentConfig,
    *,
    system: str,
    messages: list[dict[str, Any]],
    model: type[BaseModelT],
    role: str,
    on_progress: ProgressNote | None = None,
) -> tuple[BaseModelT, Reply]:
    """`structured_call` whose reply must also validate as `model`; one repair turn allowed.

    The JSON schema is derived from the model, so the shape is guaranteed by structured
    outputs; the repair turn covers value limits (e.g. mana_cost above the maximum).
    """
    from pydantic import ValidationError

    from spellforge.agents.specs import output_schema

    schema = output_schema(model)
    reply = await structured_call(
        client,
        config,
        system=system,
        messages=messages,
        schema=schema,
        role=role,
        on_progress=on_progress,
    )
    try:
        return model.model_validate(reply.data), reply
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors()
        )
    repair = messages + [
        {"role": "assistant", "content": reply.content},
        {
            "role": "user",
            "content": f"Your answer broke these limits: {problems}. Return the corrected JSON.",
        },
    ]
    second = await structured_call(
        client,
        config,
        system=system,
        messages=repair,
        schema=schema,
        role=role,
        on_progress=on_progress,
    )
    second.usage = reply.usage + second.usage
    try:
        return model.model_validate(second.data), second
    except ValidationError as exc:
        raise AgentError(f"the {role} kept breaking the rules of its task") from exc
