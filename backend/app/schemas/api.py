from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.agents import ContentPlan, CritiqueResult, StyleGuide
from app.schemas.layout import LayoutTree
from app.schemas.state import RenderResult


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)
    width: int = Field(default=1024, ge=256, le=4096)
    height: int = Field(default=1536, ge=256, le=4096)
    max_iterations: int = Field(default=3, ge=1, le=5)
    target_score: int = Field(default=85, ge=1, le=100)


class GenerateResponse(BaseModel):
    job_id: str
    final_image: str | None
    image_url: str | None = None
    score: int | None = None
    warnings: list[str] = Field(default_factory=list)
    content_plan: ContentPlan | None = None
    style: StyleGuide | None = None
    layout_tree: LayoutTree | None = None
    render_result: RenderResult | None = None
    critiques: list[CritiqueResult] = Field(default_factory=list)

