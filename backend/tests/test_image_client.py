import base64

from app.core.image_client import OpenAICompatibleImageClient


_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z8BQDwAFgwJ/lxwPugAAAABJRU5ErkJggg=="


class FakeResponse:
    def __init__(self, payload=None, content=b"", headers=None):
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, *, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        return FakeResponse(
            {
                "data": [
                    {
                        "b64_json": _TINY_PNG_B64,
                        "mime_type": "image/png",
                    }
                ]
            }
        )

    async def get(self, url):
        return FakeResponse(
            content=base64.b64decode(_TINY_PNG_B64),
            headers={"content-type": "image/png"},
        )


class FakeURLAsyncClient(FakeAsyncClient):
    async def post(self, url, headers=None, json=None):
        return FakeResponse({"data": [{"url": "https://example.test/generated.png"}]})


class FakeDashScopeAsyncClient(FakeAsyncClient):
    async def post(self, url, headers=None, json=None):
        return FakeResponse(
            {
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"image": "https://example.test/dashscope-generated.png"}
                                ]
                            }
                        }
                    ]
                }
            }
        )


async def test_image_client_parses_b64_json(monkeypatch):
    monkeypatch.setattr("app.core.image_client.httpx.AsyncClient", FakeAsyncClient)
    client = OpenAICompatibleImageClient(
        api_key="key",
        base_url="https://example.test/v1",
        model="image-model",
        size="1024x1024",
    )
    result = await client.generate(prompt="robot")
    assert result.image_bytes
    assert result.url is None
    assert result.width == 1024
    assert result.height == 1024


async def test_image_client_parses_url_response(monkeypatch):
    monkeypatch.setattr("app.core.image_client.httpx.AsyncClient", FakeURLAsyncClient)
    client = OpenAICompatibleImageClient(
        api_key="key",
        base_url="https://example.test/v1",
        model="image-model",
        size="1024x1024",
    )
    result = await client.generate(prompt="robot")
    assert result.image_bytes is None
    assert result.url == "https://example.test/generated.png"


async def test_image_client_parses_dashscope_native_response(monkeypatch):
    monkeypatch.setattr("app.core.image_client.httpx.AsyncClient", FakeDashScopeAsyncClient)
    client = OpenAICompatibleImageClient(
        api_key="key",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        model="qwen-image-2.0",
        size="1024x1024",
    )
    result = await client.generate(prompt="robot")
    assert result.image_bytes is None
    assert result.url == "https://example.test/dashscope-generated.png"
    assert result.width == 1024
    assert result.height == 1024


async def test_image_client_downloads_remote_url(monkeypatch):
    monkeypatch.setattr("app.core.image_client.httpx.AsyncClient", FakeAsyncClient)
    client = OpenAICompatibleImageClient(
        api_key="key",
        base_url="https://example.test/v1",
        model="image-model",
    )
    image_bytes, mime_type = await client.download_image("https://example.test/image.png")
    assert image_bytes
    assert mime_type == "image/png"
