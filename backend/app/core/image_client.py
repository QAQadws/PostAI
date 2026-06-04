from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.errors import ImageGenerationError
from app.core.logging import get_logger


logger = get_logger("image_client")


@dataclass(frozen=True)
class GeneratedImageData:
    image_bytes: bytes | None
    url: str | None
    width: int | None
    height: int | None
    mime_type: str = "image/png"


class OpenAICompatibleImageClient:
    """Small client for OpenAI-compatible image generation APIs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        size: str | None = None,
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.image_api_key
        self.base_url = base_url if base_url is not None else settings.image_base_url
        self.model = model if model is not None else settings.image_model
        self.size = size if size is not None else settings.image_size
        self.timeout = timeout if timeout is not None else settings.image_timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and not self.model.startswith("mock-"))

    async def generate(self, *, prompt: str, negative_prompt: str = "") -> GeneratedImageData:
        if not self.is_configured():
            raise ImageGenerationError("Image provider is not configured")

        url = self._generation_url()
        payload = self._generation_payload(prompt=prompt, negative_prompt=negative_prompt)

        logger.info("--> IMAGE CALL | %s | model=%s | size=%s", url, self.model, self.size)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000] if exc.response is not None else ""
            logger.error(
                "<-- IMAGE FAIL | %s | status=%s | error=%s | body=%s",
                url,
                exc.response.status_code if exc.response is not None else "?",
                exc.__class__.__name__,
                body,
            )
            raise ImageGenerationError(
                f"Image generation request failed with HTTP {exc.response.status_code}: {body}"
            ) from exc
        except httpx.HTTPError as exc:
            detail = str(exc) or exc.__class__.__name__
            logger.error("<-- IMAGE FAIL | %s | error=%s", url, detail)
            raise ImageGenerationError(f"Image generation request failed: {detail}") from exc

        width, height = _parse_size(self.size)
        try:
            data = response.json()
        except ValueError as exc:
            raise ImageGenerationError("Image generation response was not JSON") from exc

        if self._is_dashscope_native():
            image_url = self._extract_dashscope_image_url(data)
            if image_url:
                return GeneratedImageData(
                    image_bytes=None,
                    url=image_url,
                    width=width,
                    height=height,
                    mime_type="image/png",
                )
            raise ImageGenerationError("DashScope image response did not contain an image URL")

        try:
            item = data["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ImageGenerationError("Image generation response did not contain data[0]") from exc

        mime_type = str(item.get("mime_type") or "image/png")

        b64_value = item.get("b64_json") or item.get("image_base64") or item.get("base64")
        if isinstance(b64_value, str) and b64_value.strip():
            try:
                image_bytes = base64.b64decode(b64_value)
            except ValueError as exc:
                raise ImageGenerationError("Image generation returned invalid base64") from exc
            return GeneratedImageData(
                image_bytes=image_bytes,
                url=None,
                width=width,
                height=height,
                mime_type=mime_type,
            )

        image_url = item.get("url")
        if isinstance(image_url, str) and image_url.strip():
            return GeneratedImageData(
                image_bytes=None,
                url=image_url,
                width=width,
                height=height,
                mime_type=mime_type,
            )

        raise ImageGenerationError("Image generation response did not contain b64_json or url")

    def _generation_url(self) -> str:
        base = self.base_url.rstrip("/")
        if self._is_dashscope_native():
            if base.endswith("/services/aigc/multimodal-generation/generation"):
                return base
            return f"{base}/services/aigc/multimodal-generation/generation"
        if base.endswith("/images/generations"):
            return base
        return f"{base}/images/generations"

    def _generation_payload(self, *, prompt: str, negative_prompt: str = "") -> dict[str, Any]:
        if self._is_dashscope_native():
            parameters: dict[str, Any] = {
                "size": self.size.replace("x", "*"),
                "n": 1,
            }
            if negative_prompt:
                parameters["negative_prompt"] = negative_prompt
            return {
                "model": self.model,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": prompt}],
                        }
                    ]
                },
                "parameters": parameters,
            }

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": self.size,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        return payload

    def _is_dashscope_native(self) -> bool:
        base = (self.base_url or "").rstrip("/")
        return (
            "dashscope.aliyuncs.com/api/v1" in base
            and "compatible-mode" not in base
            and self.model.startswith("qwen-image")
        )

    def _extract_dashscope_image_url(self, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("image", "url", "image_url"):
                value = payload.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
            for value in payload.values():
                found = self._extract_dashscope_image_url(value)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = self._extract_dashscope_image_url(value)
                if found:
                    return found
        return None

    async def download_image(self, url: str) -> tuple[bytes, str]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ImageGenerationError(f"Could not download generated image URL: {exc}") from exc

        content_type = response.headers.get("content-type", "image/png").split(";", 1)[0].strip()
        if not content_type.startswith("image/"):
            raise ImageGenerationError(f"Generated image URL returned non-image content type: {content_type}")
        return response.content, content_type


def _parse_size(size: str) -> tuple[int | None, int | None]:
    parts = size.lower().split("x", 1)
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None
