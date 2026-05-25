from pathlib import Path

from app.render.asset_store import AssetStore
from app.schemas.state import RenderResult


async def test_asset_store_saves_base64_png(tmp_path: Path):
    result = RenderResult(
        image_base64="iVBORw0KGgo=",
        width=1,
        height=1,
        mime_type="image/png",
    )
    saved = await AssetStore(tmp_path, "/assets").save_render(result, job_id="job", iteration=2)
    assert saved.image_url == "/assets/job_2.png"
    assert (tmp_path / "job_2.png").exists()
