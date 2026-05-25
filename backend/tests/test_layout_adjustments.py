from app.agents.layout_planner import SpatialLayoutPlanner
from app.schemas.agents import AdjustmentAction, AdjustmentVector, CritiqueResult
from app.schemas.layout import CanvasSpec
from app.schemas.state import GraphState


async def test_layout_adjustment_moves_title():
    state = GraphState(user_prompt="AI conference", canvas=CanvasSpec(width=512, height=768))
    from app.agents.content_extractor import ContentExtractor
    from app.agents.style_director import StyleDirector

    state.content_plan = await ContentExtractor().run(state)
    state.style = await StyleDirector().run(state)
    planner = SpatialLayoutPlanner()
    state.layout_tree = await planner.run(state)
    original_y = next(node for node in state.layout_tree.root.children if node.element_id == "title").box.y
    state.feedback_history.append(
        CritiqueResult(
            score=70,
            passed=False,
            reasoning="move title",
            adjustments=[
                AdjustmentVector(
                    element_id="title",
                    action=AdjustmentAction.move,
                    dy=0.03,
                    reason="more margin",
                )
            ],
        )
    )
    updated = await planner.run(state)
    moved_y = next(node for node in updated.root.children if node.element_id == "title").box.y
    assert moved_y == original_y + 0.03

