from __future__ import annotations

import base64
from pathlib import Path

from app.core.errors import RenderError
from app.schemas.state import RenderResult


class AssetStore:
    def __init__(self, base_dir: str | Path = "generated", public_path: str = "/assets") -> None:
        self.base_dir = Path(base_dir)
        self.public_path = public_path.rstrip("/")

    async def save_render(self, result: RenderResult, *, job_id: str, iteration: int) -> RenderResult:
        if not result.image_base64:
            return result

        self.base_dir.mkdir(parents=True, exist_ok=True)
        extension = "jpg" if result.mime_type == "image/jpeg" else "png"
        filename = f"{job_id}_{iteration}.{extension}"
        target = self.base_dir / filename
        try:
            target.write_bytes(base64.b64decode(result.image_base64))
        except ValueError as exc:
            raise RenderError("render result contains invalid base64 image data") from exc

        return result.model_copy(update={"image_url": f"{self.public_path}/{filename}"})
