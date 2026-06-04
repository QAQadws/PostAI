import pytest


@pytest.fixture(autouse=True)
def isolate_model_env(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_MODEL", "mock-text")
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("VISION_BASE_URL", raising=False)
    monkeypatch.setenv("VISION_MODEL", "mock-vision")
    monkeypatch.delenv("IMAGE_API_KEY", raising=False)
    monkeypatch.delenv("IMAGE_BASE_URL", raising=False)
    monkeypatch.setenv("IMAGE_MODEL", "mock-image")
    monkeypatch.setenv("ALLOW_MODEL_FALLBACK", "true")
