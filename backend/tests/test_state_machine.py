from app.orchestration.graph_runner import GraphRunner
from app.render.asset_store import AssetStore
from app.schemas.layout import CanvasSpec
from app.schemas.state import GraphState


async def test_graph_runner_produces_final_output(tmp_path):
    state = GraphState(user_prompt="制作一张科技风 AI 会议海报", canvas=CanvasSpec(width=512, height=768), max_iterations=2)
    response = await GraphRunner(asset_store=AssetStore(tmp_path, "/assets")).run(state)
    assert response.job_id == state.job_id
    assert response.final_image
    assert response.image_url
    assert response.score is not None
    assert response.layout_tree is not None
