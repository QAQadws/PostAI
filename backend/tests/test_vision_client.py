"""Tests for StructuredLLMClient.parse_vision and _vision_completion."""

import json

import pytest
from pydantic import BaseModel

from app.core.errors import LLMCallError, SchemaParseError
from app.core.llm_client import (
    StructuredLLMClient,
    _summarize_vision_messages,
)


class SampleOutput(BaseModel):
    name: str
    score: int = 0


# ── _summarize_vision_messages ──


def test_summarize_vision_text_only():
    messages = [{"role": "user", "content": "hello"}]
    result = _summarize_vision_messages(messages)
    assert "[user] hello" in result


def test_summarize_vision_with_image():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        }
    ]
    result = _summarize_vision_messages(messages)
    assert "[image:" in result
    assert "Describe this" in result


def test_summarize_vision_truncates_long_text():
    long_text = "x" * 3000
    messages = [{"role": "user", "content": long_text}]
    result = _summarize_vision_messages(messages)
    assert "truncated" in result


# ── parse_vision ──


async def test_parse_vision_returns_model_and_reasoning():
    """Happy path: content is valid JSON, reasoning is captured."""
    client = StructuredLLMClient(api_key="k", base_url="https://x.test", model="v")

    async def fake_completion(**kwargs):
        return ('{"name": "poster", "score": 90}', "I see a poster...")

    client._vision_completion = fake_completion  # type: ignore[method-assign]

    result, reasoning = await client.parse_vision(
        messages=[{"role": "user", "content": "test"}],
        response_model=SampleOutput,
    )
    assert isinstance(result, SampleOutput)
    assert result.name == "poster"
    assert result.score == 90
    assert reasoning == "I see a poster..."


async def test_parse_vision_raises_on_invalid_json():
    client = StructuredLLMClient(api_key="k", base_url="https://x.test", model="v")

    async def fake_completion(**kwargs):
        return ("not-valid-json", "")

    client._vision_completion = fake_completion  # type: ignore[method-assign]

    with pytest.raises(SchemaParseError):
        await client.parse_vision(
            messages=[{"role": "user", "content": "test"}],
            response_model=SampleOutput,
        )


async def test_parse_vision_raises_llm_call_error():
    client = StructuredLLMClient(api_key="k", base_url="https://x.test", model="v")

    async def fake_completion(**kwargs):
        raise LLMCallError("api down")

    client._vision_completion = fake_completion  # type: ignore[method-assign]

    with pytest.raises(LLMCallError):
        await client.parse_vision(
            messages=[{"role": "user", "content": "test"}],
            response_model=SampleOutput,
        )


async def test_parse_vision_raises_when_not_configured():
    client = StructuredLLMClient(api_key=None, base_url=None, model="mock-vision")
    with pytest.raises(LLMCallError, match="not configured"):
        await client.parse_vision(
            messages=[{"role": "user", "content": "test"}],
            response_model=SampleOutput,
        )


# ── _vision_completion (with monkeypatched httpx) ──


class _FakeResponse:
    """Minimal httpx.Response stand-in."""
    def __init__(self, data: dict, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]


class _FakeTransport:
    """An async context manager that replaces httpx.AsyncClient."""
    def __init__(self, response_data: dict, status_code: int = 200):
        self.response = _FakeResponse(response_data, status_code)
        self.payload_sent: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url, *, headers, json=None):
        self.url = url
        self.headers = headers
        self.payload_sent = json
        return self.response


async def test_vision_completion_sends_extra_body_when_thinking_on(monkeypatch):
    """When enable_thinking=True, extra_body is sent; no response_format."""
    fake = _FakeTransport({
        "choices": [{"message": {"content": '{"name":"x"}', "reasoning_content": "think"}}]
    })
    monkeypatch.setattr("app.core.llm_client.httpx.AsyncClient", lambda timeout: fake)

    client = StructuredLLMClient(api_key="k", base_url="https://x.test", model="v")
    content, reasoning = await client._vision_completion(
        messages=[{"role": "user", "content": "hi"}],
        response_model=SampleOutput,
        enable_thinking=True,
        thinking_budget=4096,
    )

    assert content == '{"name":"x"}'
    assert reasoning == "think"
    assert fake.payload_sent is not None
    assert fake.payload_sent["extra_body"] == {"enable_thinking": True, "thinking_budget": 4096}
    assert "response_format" not in fake.payload_sent  # Not sent with thinking on.


async def test_vision_completion_adds_response_format_when_thinking_off(monkeypatch):
    """When enable_thinking=False and format is json_object, response_format is set."""
    fake = _FakeTransport({
        "choices": [{"message": {"content": '{"name":"y"}', "reasoning_content": ""}}]
    })
    monkeypatch.setattr("app.core.llm_client.httpx.AsyncClient", lambda timeout: fake)

    client = StructuredLLMClient(
        api_key="k", base_url="https://x.test", model="v", response_format="json_object"
    )
    content, reasoning = await client._vision_completion(
        messages=[{"role": "user", "content": "hi"}],
        response_model=SampleOutput,
        enable_thinking=False,
    )

    assert content == '{"name":"y"}'
    assert reasoning == ""
    assert fake.payload_sent is not None
    assert "extra_body" not in fake.payload_sent
    assert fake.payload_sent["response_format"] == {"type": "json_object"}


async def test_vision_completion_raises_on_http_error(monkeypatch):
    fake = _FakeTransport({}, status_code=500)
    monkeypatch.setattr("app.core.llm_client.httpx.AsyncClient", lambda timeout: fake)

    client = StructuredLLMClient(api_key="k", base_url="https://x.test", model="v")
    with pytest.raises(LLMCallError, match="Vision request failed"):
        await client._vision_completion(
            messages=[{"role": "user", "content": "hi"}],
            response_model=SampleOutput,
        )


async def test_vision_completion_raises_on_missing_message(monkeypatch):
    fake = _FakeTransport({"choices": [{"not_message": True}]})
    monkeypatch.setattr("app.core.llm_client.httpx.AsyncClient", lambda timeout: fake)

    client = StructuredLLMClient(api_key="k", base_url="https://x.test", model="v")
    with pytest.raises(LLMCallError, match="choices\\[0\\].message"):
        await client._vision_completion(
            messages=[{"role": "user", "content": "hi"}],
            response_model=SampleOutput,
        )


async def test_vision_completion_raises_on_empty_content(monkeypatch):
    fake = _FakeTransport({
        "choices": [{"message": {"content": "   ", "reasoning_content": ""}}]
    })
    monkeypatch.setattr("app.core.llm_client.httpx.AsyncClient", lambda timeout: fake)

    client = StructuredLLMClient(api_key="k", base_url="https://x.test", model="v")
    with pytest.raises(LLMCallError, match="content is empty"):
        await client._vision_completion(
            messages=[{"role": "user", "content": "hi"}],
            response_model=SampleOutput,
        )
