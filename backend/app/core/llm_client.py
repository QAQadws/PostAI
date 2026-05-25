from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from pydantic import ValidationError

from app.core.errors import LLMCallError, SchemaParseError
from app.orchestration.retry import retry_async


ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredLLMClient:
    """Thin placeholder for future OpenAI-compatible structured calls.

    This client targets OpenAI-compatible ``/chat/completions`` APIs. The
    built-in agents still work without API keys; this class is the replacement
    boundary for real Content/Style/Layout/VLM agents.
    """

    def __init__(
        self,
        api_key: str | None,
        base_url: str | None,
        model: str,
        timeout: float = 60,
        response_format: str = "json_schema",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self.response_format = response_format

    async def parse(self, *, messages: list[dict[str, Any]], response_model: type[ModelT]) -> ModelT:
        if not self.api_key or not self.base_url or self.model.startswith("mock-"):
            raise LLMCallError("LLM provider is not configured")

        async def _call() -> ModelT:
            content = await self._chat_completion(
                messages=self._messages_with_schema_hint(messages, response_model),
                response_model=response_model,
            )
            return self.validate_json(content, response_model)

        return await retry_async(_call, attempts=3, delay_seconds=0.4, exceptions=(LLMCallError, SchemaParseError))

    def _messages_with_schema_hint(
        self,
        messages: list[dict[str, Any]],
        response_model: type[ModelT],
    ) -> list[dict[str, Any]]:
        if self.response_format != "json_object":
            return messages
        schema_hint = (
            "You must return a single JSON object that validates against this JSON Schema. "
            "Do not return markdown, explanations, layout canvas specs, or any fields outside the schema. "
            f"Schema: {json.dumps(response_model.model_json_schema(), ensure_ascii=False)}"
        )
        return [{"role": "system", "content": schema_hint}, *messages]

    async def _chat_completion(self, *, messages: list[dict[str, Any]], response_model: type[ModelT]) -> str:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if self.response_format == "json_schema":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "schema": response_model.model_json_schema(),
                    "strict": True,
                },
            }
        elif self.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMCallError(f"LLM request failed: {exc}") from exc

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMCallError("LLM response did not contain choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMCallError("LLM response content is empty")
        return content

    def validate_json(self, content: str, response_model: type[ModelT]) -> ModelT:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise SchemaParseError(f"LLM output is not valid JSON: {exc}") from exc
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            raise SchemaParseError(f"LLM output failed schema validation: {exc}") from exc

    def validate_payload(self, payload: dict[str, Any], response_model: type[ModelT]) -> ModelT:
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            raise SchemaParseError(f"LLM output failed schema validation: {exc}") from exc
