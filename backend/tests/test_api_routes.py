from httpx import ASGITransport, AsyncClient

from app.main import app


async def test_generate_endpoint_returns_image():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/generate",
            json={"prompt": "制作一张科技风 AI 会议海报", "width": 512, "height": 768, "max_iterations": 1},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["final_image"]
    assert payload["image_url"].startswith("/assets/")


async def test_generate_stream_endpoint_emits_sse():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/generate/stream",
            json={"prompt": "招聘海报", "width": 512, "height": 768, "max_iterations": 1},
        )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: final_output" in response.text


async def test_generate_endpoint_returns_502_on_graph_error(monkeypatch):
    from app.orchestration.graph_runner import GraphRunner

    async def fail(self, state):
        raise RuntimeError("model failed")

    monkeypatch.setattr(GraphRunner, "run", fail)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/generate", json={"prompt": "x"})
    assert response.status_code == 502
    assert response.json()["detail"] == "model failed"
