from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.agents import ContentPlan, CritiqueResult, StyleGuide
from app.schemas.layout import CanvasSpec, LayoutTree


class RenderResult(BaseModel):
    image_base64: str | None = None
    image_url: str | None = None
    width: int
    height: int
    mime_type: Literal["image/png", "image/jpeg"] = "image/png"


class GraphStage(str, Enum):
    init = "init"
    content = "content"
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
    style: StyleGuide | None = None
    layout_tree: LayoutTree | None = None
    render_result: RenderResult | None = None
    iteration_count: int = 0
    max_iterations: int = 3
    target_score: int = 85
    feedback_history: list[CritiqueResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

