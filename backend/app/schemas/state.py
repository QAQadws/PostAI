from __future__ import annotations

from enum import Enum
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.schemas.agents import ArtDirectionV2, ContentPlan, CritiqueResult, PosterBriefV2, StyleGuide
from app.schemas.layout import CanvasSpec, LayoutTree


class ReferenceImage(BaseModel):
    url: str = Field(
        min_length=10,
        max_length=2048,
        description="Reference image URL (http/https)",
    )
    description: str = Field(
        min_length=1,
        max_length=500,
        description="How this image should guide poster design",
    )

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("reference image URL must be a valid http/https URL")
        return value


class RenderResult(BaseModel):
    image_base64: str | None = None
    image_url: str | None = None
    width: int
    height: int
    mime_type: Literal["image/png", "image/jpeg"] = "image/png"
    console_errors: list[str] = Field(
        default_factory=list,
        description="Browser console errors captured during rendering (CSS, font loading, etc.)",
    )


class GeneratedIllustration(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    source_visual_subject_id: str | None = Field(default=None, max_length=120)
    description: str = Field(min_length=1, max_length=1200)
    prompt: str = Field(min_length=1, max_length=3000)
    negative_prompt: str = Field(default="", max_length=1200)
    url: str | None = Field(default=None, max_length=2048)
    width: int | None = Field(default=None, ge=1, le=4096)
    height: int | None = Field(default=None, ge=1, le=4096)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"] = "image/png"
    placement_hint: str = Field(default="", max_length=800)
    usage_guidance: str = Field(default="", max_length=800)
    status: Literal["generated", "failed", "skipped"] = "generated"
    error: str | None = Field(default=None, max_length=1000)


class GraphStage(str, Enum):
    init = "init"
    content = "content"
    illustration = "illustration"
    style = "style"
    layout = "layout"
    render = "render"
    critique = "critique"
    final = "final"
    error = "error"


class GraphState(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    user_prompt: str
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    stage: GraphStage = GraphStage.init
    content_plan: ContentPlan | None = None
    poster_brief: PosterBriefV2 | None = Field(
        default=None,
        description="Phase 2 structured poster brief — richer than ContentPlan; set by ContentExtractor",
    )
    style: StyleGuide | None = None
    art_direction: ArtDirectionV2 | None = Field(
        default=None,
        description="Phase 3 structured art direction — richer than StyleGuide; set by StyleDirector",
    )
    layout_tree: LayoutTree | None = None
    layout_html: str | None = Field(
        default=None,
        description="HTML/CSS document produced by the layout planner for browser rendering",
    )
    html_url: str | None = Field(
        default=None,
        description="Public URL of the saved HTML source file",
    )
    render_result: RenderResult | None = None
    iteration_count: int = 0
    max_iterations: int = 3
    min_iterations: int = Field(default=0, ge=0, le=4, description="Minimum VLM reviews before early score-based exit")
    target_score: int = 85
    reference_images: list[ReferenceImage] = Field(
        default_factory=list,
        description="Optional user-provided reference images with descriptions",
    )
    enable_generated_illustrations: bool = True
    max_generated_illustrations: int = Field(default=3, ge=0, le=5)
    generated_illustrations: list[GeneratedIllustration] = Field(
        default_factory=list,
        description="AI-generated illustration assets available to layout planning",
    )
    feedback_history: list[CritiqueResult] = Field(default_factory=list)
    vision_reasoning: str = Field(
        default="",
        description="Latest VLM chain-of-thought reasoning about the rendered poster",
    )
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
