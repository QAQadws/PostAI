from io import BytesIO

from PIL import Image

from app.agents.illustration_agent import IllustrationAgent
from app.core.errors import ImageGenerationError
from app.core.image_client import GeneratedImageData
from app.render.asset_store import AssetStore
from app.schemas.agents import ContentStrategy, PosterBriefV2, PosterIntent, PosterMessage, VisualSubject
from app.schemas.state import GraphState



def _tiny_png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _state_with_visuals(prompt: str = "制作一张机器人主题科技海报") -> GraphState:
    state = GraphState(user_prompt=prompt)
    state.poster_brief = PosterBriefV2(
        poster_intent=PosterIntent(primary_goal="robot poster"),
        content_strategy=ContentStrategy(image_policy="optional"),
        messages=[
            PosterMessage(id="headline", role="headline", content="机器人未来", importance=10, presence="required"),
        ],
        visual_subjects=[
            VisualSubject(id="main_visual", role="illustration", description="friendly robot silhouette", presence="recommended"),
            VisualSubject(id="texture", role="texture", description="subtle circuit texture", presence="optional"),
        ],
    )
    return state


class FakeImageClient:
    def __init__(self, *, configured=True, fail=False):
        self.configured = configured
        self.fail = fail
        self.calls = 0

    def is_configured(self):
        return self.configured

    async def generate(self, *, prompt, negative_prompt=""):
        self.calls += 1
        if self.fail:
            raise ImageGenerationError("provider failed")
        return GeneratedImageData(
            image_bytes=_tiny_png_bytes(),
            url=None,
            width=1024,
            height=1024,
            mime_type="image/png",
        )


async def test_illustration_agent_skips_when_provider_unconfigured(tmp_path):
    state = _state_with_visuals()
    client = FakeImageClient(configured=False)
    result = await IllustrationAgent(
        image_client=client,
        asset_store=AssetStore(tmp_path, "/assets"),
    ).run(state)
    assert result == []
    assert client.calls == 0
    assert any("not configured" in warning for warning in state.warnings)


async def test_illustration_agent_respects_disable_flag(tmp_path):
    state = _state_with_visuals()
    state.enable_generated_illustrations = False
    client = FakeImageClient()
    result = await IllustrationAgent(
        image_client=client,
        asset_store=AssetStore(tmp_path, "/assets"),
    ).run(state)
    assert result == []
    assert client.calls == 0


async def test_illustration_agent_respects_max_count_and_saves_asset(tmp_path):
    state = _state_with_visuals()
    state.max_generated_illustrations = 1
    client = FakeImageClient()
    result = await IllustrationAgent(
        image_client=client,
        asset_store=AssetStore(tmp_path, "/assets"),
    ).run(state)
    assert len(result) == 1
    assert client.calls == 1
    assert result[0].status == "generated"
    assert result[0].url.startswith("/assets/generated_illustrations/")
    assert (tmp_path / result[0].url.removeprefix("/assets/")).exists()


async def test_illustration_agent_skips_type_only_prompts(tmp_path):
    state = _state_with_visuals(prompt="做一张纯文字爵士海报，不要图片")
    client = FakeImageClient()
    result = await IllustrationAgent(
        image_client=client,
        asset_store=AssetStore(tmp_path, "/assets"),
    ).run(state)
    assert result == []
    assert client.calls == 0


async def test_illustration_agent_records_failed_asset(tmp_path):
    state = _state_with_visuals()
    state.max_generated_illustrations = 1
    client = FakeImageClient(fail=True)
    result = await IllustrationAgent(
        image_client=client,
        asset_store=AssetStore(tmp_path, "/assets"),
    ).run(state)
    assert len(result) == 1
    assert result[0].status == "failed"
    assert result[0].error
    assert state.warnings
