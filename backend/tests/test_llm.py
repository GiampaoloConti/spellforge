"""structured_call retries transient mid-stream API failures (the `(200)` forge error)."""

import asyncio

import anthropic
import httpx
import pytest

from spellforge.agents.llm import AgentConfig, AgentError, structured_call

SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


class _Usage:
    input_tokens = 10
    output_tokens = 5
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _Text:
    type = "text"
    text = '{"ok": true}'


class _Response:
    stop_reason = "end_turn"
    content = [_Text()]
    usage = _Usage()


async def _empty(self):  # async iterator over stream events: none
    return
    yield


class _Stream:
    """One `async with client...stream(...) as stream` result: fail or return."""

    def __init__(self, outcome):
        self._outcome = outcome

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    __aiter__ = lambda self: _empty(self)  # noqa: E731

    async def get_final_message(self):
        if isinstance(self._outcome, Exception):
            raise self._outcome  # models a mid-stream error after the 200 handshake
        return self._outcome


class _Client:
    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0
        self.beta = self.messages = self  # client.beta.messages.stream -> self.stream

    def stream(self, **_):
        self.calls += 1
        return _Stream(self._outcomes.pop(0))


def _status_error(code):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError(
        "boom", response=httpx.Response(code, request=request), body=None
    )


def _call(client):
    return asyncio.run(
        structured_call(
            client,
            AgentConfig(model="claude-sonnet-5"),
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            schema=SCHEMA,
            role="balancer",
        )
    )


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr("spellforge.agents.llm.asyncio.sleep", instant)


def test_retries_a_transient_midstream_200_then_succeeds():
    client = _Client(_status_error(200), _Response())
    assert _call(client).data == {"ok": True}
    assert client.calls == 2


def test_gives_up_after_the_attempt_budget():
    client = _Client(_status_error(200), _status_error(200), _status_error(503))
    with pytest.raises(AgentError):
        _call(client)
    assert client.calls == 3


def test_non_transient_status_is_not_retried():
    client = _Client(_status_error(400))
    with pytest.raises(AgentError):
        _call(client)
    assert client.calls == 1
