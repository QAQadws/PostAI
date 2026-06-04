"""IllustrationAgent — generates optional poster illustration assets."""

from __future__ import annotations

import re

from app.core.errors import ImageGenerationError, RenderError
from app.core.image_client import OpenAICompatibleImageClient
from app.render.asset_store import AssetStore
from app.schemas.agents import VisualSubject
from app.schemas.state import GeneratedIllustration, GraphState


class IllustrationAgent:
    """Decide which visual subjects need generated illustrations and create them.

    The agent is intentionally non-blocking for the poster pipeline: if image
    generation is unavailable or fails, it records warnings and returns the
    successful assets it has, usually an empty list.
    """

    def __init__(
        self,
        image_client: OpenAICompatibleImageClient | None = None,
        asset_store: AssetStore | None = None,
    ) -> None:
        self.image_client = image_client or OpenAICompatibleImageClient()
        self.asset_store = asset_store

    async def run(self, state: GraphState) -> list[GeneratedIllustration]:
        if not state.enable_generated_illustrations or state.max_generated_illustrations <= 0:
            return []
        if self._wants_no_generated_images(state.user_prompt):
            return []

        candidates = self._select_visual_subjects(state)
        if not candidates:
            return []

        if not self.image_client.is_configured():
            state.warnings.append("IllustrationAgent skipped: image provider is not configured")
            return []

        results: list[GeneratedIllustration] = []
        for subject in candidates[: state.max_generated_illustrations]:
            illustration_id = self._safe_id(subject.id)
            prompt = self._build_prompt(state, subject)
            negative_prompt = self._build_negative_prompt(subject)
            try:
                generated = await self.image_client.generate(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                )
                public_url = generated.url
                mime_type = generated.mime_type

                if generated.image_bytes:
                    public_url = await self._save_image(
                        generated.image_bytes,
                        job_id=state.job_id,
                        illustration_id=illustration_id,
                        mime_type=mime_type,
                    )
                elif generated.url:
                    try:
                        image_bytes, downloaded_mime = await self.image_client.download_image(generated.url)
                        mime_type = downloaded_mime
                        public_url = await self._save_image(
                            image_bytes,
                            job_id=state.job_id,
                            illustration_id=illustration_id,
                            mime_type=mime_type,
                        )
                    except (ImageGenerationError, RenderError) as exc:
                        state.warnings.append(
                            f"IllustrationAgent kept remote image URL for {subject.id}: {exc}"
                        )

                if not public_url:
                    raise ImageGenerationError("Image generation did not produce a usable URL")

                results.append(
                    GeneratedIllustration(
                        id=illustration_id,
                        source_visual_subject_id=subject.id,
                        description=subject.description,
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        url=public_url,
                        width=generated.width,
                        height=generated.height,
                        mime_type=self._normalize_mime_type(mime_type),
                        placement_hint=self._placement_hint(subject.description),
                        usage_guidance=(
                            "Use as a poster visual asset only when it improves the composition; "
                            "crop intentionally and keep required text readable."
                        ),
                        status="generated",
                    )
                )
            except (ImageGenerationError, RenderError) as exc:
                message = f"IllustrationAgent failed for {subject.id}: {exc}"
                state.warnings.append(message)
                results.append(
                    GeneratedIllustration(
                        id=illustration_id,
                        source_visual_subject_id=subject.id,
                        description=subject.description,
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        placement_hint=self._placement_hint(subject.description),
                        usage_guidance="Skipped because image generation failed.",
                        status="failed",
                        error=str(exc),
                    )
                )

        return results

    def _select_visual_subjects(self, state: GraphState) -> list[VisualSubject]:
        brief = state.poster_brief
        if not brief:
            return []
        if brief.content_strategy.image_policy == "omit":
            return []

        candidates: list[VisualSubject] = []
        for subject in brief.visual_subjects:
            if subject.presence == "omit" or subject.role == "none":
                continue
            if subject.role not in {"illustration", "symbol", "texture", "pattern", "shape", "ornament", "photo"}:
                continue
            candidates.append(subject)
        return candidates

    def _build_prompt(self, state: GraphState, subject: VisualSubject) -> str:
        reference_context = ""
        if state.reference_images:
            refs = [
                f"{index}. {image.description}"
                for index, image in enumerate(state.reference_images[:3], start=1)
            ]
            reference_context = " Reference cues: " + "; ".join(refs) + "."

        aspect = f"{state.canvas.width}:{state.canvas.height}"
        return (
            f"Create a high-quality standalone illustration asset for a poster. "
            f"Poster request: {state.user_prompt}. "
            f"Visual subject: {subject.description}. "
            f"Canvas aspect ratio: {aspect}. "
            f"Make it suitable for cropping and layering in an HTML/CSS poster layout. "
            f"Use clean edges, strong silhouette, no embedded text, no logo, no QR code, "
            f"no factual date/place/price details.{reference_context}"
        )

    def _build_negative_prompt(self, subject: VisualSubject) -> str:
        parts = [
            "text",
            "letters",
            "logo",
            "watermark",
            "QR code",
            "date",
            "venue",
            "price",
            "poster typography",
            "crowded layout",
        ]
        parts.extend(subject.avoid)
        return ", ".join(dict.fromkeys(part for part in parts if part))

    async def _save_image(
        self,
        image_bytes: bytes,
        *,
        job_id: str,
        illustration_id: str,
        mime_type: str,
    ) -> str:
        if self.asset_store is None:
            raise RenderError("asset store is not configured for generated illustrations")
        return await self.asset_store.save_generated_illustration(
            image_bytes,
            job_id=job_id,
            illustration_id=illustration_id,
            mime_type=mime_type,
        )

    def _placement_hint(self, description: str) -> str:
        lower = description.lower()
        if any(token in lower for token in ("background", "texture", "pattern")):
            return "Use as a cropped background or texture layer behind text."
        if any(token in lower for token in ("symbol", "icon", "mark")):
            return "Use as a focal symbol or repeated accent, not as a button."
        return "Use as the key visual or supporting illustration with deliberate cropping."

    def _wants_no_generated_images(self, prompt: str) -> bool:
        lower = prompt.lower()
        tokens = [
            "pure text",
            "type-only",
            "only text",
            "no image",
            "no visual",
            "不生成插图",
            "不要插图",
            "不要图片",
            "不用图片",
            "只用文字",
            "纯文字",
            "纯字",
        ]
        return any(token in prompt or token in lower for token in tokens)

    def _safe_id(self, value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-").lower()
        return safe or "generated-illustration"

    def _normalize_mime_type(self, mime_type: str) -> str:
        lowered = mime_type.lower()
        if lowered in {"image/jpeg", "image/webp"}:
            return lowered
        return "image/png"
