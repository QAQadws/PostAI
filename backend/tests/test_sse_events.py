from app.core.events import event, format_sse
from app.orchestration.graph_runner import GraphRunner
from app.render.asset_store import AssetStore
from app.schemas.layout import CanvasSpec
from app.schemas.state import GraphState


async def test_sse_event_order_contains_final_output(tmp_path):
    state = GraphState(user_prompt="招聘海报", canvas=CanvasSpec(width=512, height=768), max_iterations=1)
    streamed = [event async for event in GraphRunner(asset_store=AssetStore(tmp_path, "/assets")).run_events(state)]
    events = [item.event for item in streamed]
    assert events[0] == "job_started"
    assert "render_preview" in events
    assert "final_output" in events
    assert events[-1] == "job_finished"
    assert any(
        item.event == "agent_complete" and item.data.get("agent") == "IllustrationAgent"
        for item in streamed
    )


def test_format_sse():
    rendered = format_sse(event("job_started", {"job_id": "1"}))
    assert rendered.startswith("event: job_started")
    assert "data:" in rendered
