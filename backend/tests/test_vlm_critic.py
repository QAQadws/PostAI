from app.agents.vlm_critic import HeuristicVLMCritic
from app.core.errors import LLMCallError
from app.schemas.agents import CritiqueResult
from app.schemas.layout import Box, LayoutNode, LayoutTree
from app.schemas.state import GraphState, RenderResult


class FakeVisionClient:
    api_key = "key"
    base_url = "https://example.test/v1"
    model = "vision-model"

    def __init__(self, output):
        self.output = output
        self.calls = 0

    async def parse(self, *, messages, response_model):
        self.calls += 1
        if isinstance(self.output, Exception):
            raise self.output
        assert messages[1]["content"][1]["type"] == "image_url"
        return self.output


def _state_for_critic() -> GraphState:
    state = GraphState(user_prompt="poster")
    state.layout_tree = LayoutTree(
        root=LayoutNode(
            node_type="container",
            box=Box(x=0, y=0, width=1, height=1),
            children=[LayoutNode(element_id="title", box=Box(x=0.08, y=0.08, width=0.8, height=0.1))],
        )
    )
    state.render_result = RenderResult(image_base64="iVBORw0KGgo=", width=1, height=1)
    from app.schemas.agents import ContentPlan, ElementContent
    from app.schemas.layout import ElementType

    state.content_plan = ContentPlan(
        poster_goal="test",
        elements=[ElementContent(id="title", type=ElementType.text, content="Title", priority=10)],
    )
    return state


async def test_vlm_critic_uses_vision_client():
    output = CritiqueResult(score=88, passed=True, reasoning="ok")
    client = FakeVisionClient(output)
    result = await HeuristicVLMCritic(vision_client=client).run(_state_for_critic())
    assert client.calls == 1
    assert result.score == 88


async def test_vlm_critic_falls_back_to_heuristic():
    client = FakeVisionClient(LLMCallError("vision unavailable"))
    state = _state_for_critic()
    result = await HeuristicVLMCritic(vision_client=client).run(state)
    assert client.calls == 1
    assert result.score >= 60
    assert state.warnings


async def test_vlm_critic_raises_when_fallback_disabled():
    client = FakeVisionClient(LLMCallError("vision unavailable"))
    state = _state_for_critic()
    critic = HeuristicVLMCritic(vision_client=client)
    critic.allow_model_fallback = False
    import pytest

    with pytest.raises(LLMCallError):
        await critic.run(state)
