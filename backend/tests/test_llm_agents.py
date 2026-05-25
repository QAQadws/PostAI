from app.agents.content_extractor import ContentExtractor
from app.agents.layout_planner import SpatialLayoutPlanner
from app.agents.style_director import StyleDirector
from app.core.errors import LLMCallError
from app.schemas.agents import ContentPlan, ElementContent, StyleGuide
from app.schemas.layout import Box, CanvasSpec, ElementType, LayoutNode, LayoutStyle, LayoutTree
from app.schemas.state import GraphState


class FakeLLMClient:
    api_key = "key"
    base_url = "https://example.test/v1"
    model = "real-model"

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    async def parse(self, *, messages, response_model):
        self.calls += 1
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class FakeMalformedContentClient:
    api_key = "key"
    base_url = "https://example.test/v1"
    model = "real-model"

    async def parse(self, *, messages, response_model):
        from app.core.errors import SchemaParseError

        raise SchemaParseError("bad schema")

    async def _chat_completion(self, *, messages, response_model):
        import json

        return json.dumps(
            {
                "elements": [
                    {"id": "background", "type": "rect", "props": {"fill": "#0a0a2e"}},
                    {"id": "title", "type": "text", "props": {"text": "AI 会议"}},
                    {"id": "main_visual", "type": "image", "props": {"prompt": "AI visual"}},
                    {"id": "cta", "type": "group", "children": [{"type": "text", "text": "立即报名"}]},
                ]
            },
            ensure_ascii=False,
        )

    def validate_payload(self, payload, response_model):
        return response_model.model_validate(payload)


async def test_content_extractor_uses_llm_output():
    llm = FakeLLMClient(
        [
            ContentPlan(
                poster_goal="launch",
                elements=[
                    ElementContent(id="title", type=ElementType.text, content="发布会", priority=10),
                    ElementContent(id="subtitle", type=ElementType.text, content="未来已来", priority=8),
                    ElementContent(id="main_visual", type=ElementType.image, content="robot", priority=7),
                    ElementContent(id="cta", type=ElementType.text, content="报名", priority=5),
                ],
            )
        ]
    )
    result = await ContentExtractor(llm_client=llm).run(GraphState(user_prompt="AI 发布会"))
    assert llm.calls == 1
    assert result.poster_goal == "launch"


async def test_content_extractor_normalizes_layout_like_payload():
    result = await ContentExtractor(llm_client=FakeMalformedContentClient()).run(GraphState(user_prompt="AI 会议"))
    ids = {element.id for element in result.elements}
    assert {"title", "subtitle", "main_visual", "cta"} <= ids
    assert result.poster_goal


async def test_style_director_falls_back_when_llm_fails():
    llm = FakeLLMClient([LLMCallError("network down")])
    state = GraphState(user_prompt="科技海报")
    result = await StyleDirector(llm_client=llm).run(state)
    assert result.mood == "futuristic"
    assert state.warnings


async def test_style_director_raises_when_fallback_disabled():
    llm = FakeLLMClient([LLMCallError("network down")])
    agent = StyleDirector(llm_client=llm)
    agent.allow_model_fallback = False
    state = GraphState(user_prompt="科技海报")
    import pytest

    with pytest.raises(LLMCallError):
        await agent.run(state)


async def test_layout_planner_uses_llm_output():
    tree = LayoutTree(
        canvas=CanvasSpec(width=512, height=768),
        root=LayoutNode(
            node_type="container",
            box=Box(x=0, y=0, width=1, height=1),
            children=[
                LayoutNode(
                    element_id="title",
                    box=Box(x=0.1, y=0.1, width=0.8, height=0.1),
                    style=LayoutStyle(color="#FFFFFF", font_size=0.05, align="left"),
                ),
                LayoutNode(
                    element_id="subtitle",
                    box=Box(x=0.1, y=0.22, width=0.8, height=0.05),
                    style=LayoutStyle(color="#FFFFFF", font_size=0.03, align="left"),
                ),
                LayoutNode(element_id="main_visual", box=Box(x=0.1, y=0.32, width=0.8, height=0.35)),
                LayoutNode(
                    element_id="cta",
                    box=Box(x=0.1, y=0.8, width=0.3, height=0.08),
                    style=LayoutStyle(color="#000000", font_size=0.03, align="center"),
                ),
            ],
        ),
    )
    llm = FakeLLMClient([tree])
    state = GraphState(user_prompt="AI 发布会", canvas=CanvasSpec(width=512, height=768))
    state.content_plan = ContentPlan(
        poster_goal="launch",
        elements=[
            ElementContent(id="title", type=ElementType.text, content="发布会", priority=10),
            ElementContent(id="subtitle", type=ElementType.text, content="未来已来", priority=8),
            ElementContent(id="main_visual", type=ElementType.image, content="robot", priority=7),
            ElementContent(id="cta", type=ElementType.text, content="报名", priority=5),
        ],
    )
    state.style = StyleGuide(
        theme_keywords=["tech"],
        background_prompt="clean",
        primary_color="#000000",
        secondary_color="#111111",
        accent_color="#00E5FF",
        text_color="#FFFFFF",
        mood="futuristic",
    )
    result = await SpatialLayoutPlanner(llm_client=llm).run(state)
    assert llm.calls == 1
    assert result.root.children[0].element_id == "title"
