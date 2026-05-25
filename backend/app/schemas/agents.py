from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.layout import ElementType


class ElementContent(BaseModel):
    id: str = Field(description="Stable element id, such as title or main_visual")
    type: ElementType
    content: str
    priority: int = Field(default=5, ge=1, le=10)
    alt: str | None = None


class ContentPlan(BaseModel):
    elements: list[ElementContent] = Field(default_factory=list)
    poster_goal: str
    target_audience: str | None = None


class StyleGuide(BaseModel):
    theme_keywords: list[str] = Field(default_factory=list)
    background_prompt: str
    negative_prompt: str | None = None
    primary_color: str
    secondary_color: str
    accent_color: str
    text_color: str
    font_family: str = "sans-serif"
    mood: str


class AdjustmentAction(str, Enum):
    move = "move"
    resize = "resize"
    recolor = "recolor"
    typography = "typography"
    z_order = "z_order"
    regenerate_background = "regenerate_background"


class AdjustmentVector(BaseModel):
    element_id: str | None = None
    action: AdjustmentAction
    dx: float = Field(default=0, ge=-1, le=1)
    dy: float = Field(default=0, ge=-1, le=1)
    d_width: float = Field(default=0, ge=-1, le=1)
    d_height: float = Field(default=0, ge=-1, le=1)
    scale: float | None = Field(default=None, gt=0, le=3)
    new_color: str | None = None
    new_font_size: float | None = Field(default=None, gt=0)
    z_index_delta: int = Field(default=0, ge=-20, le=20)
    reason: str


class CritiqueResult(BaseModel):
    score: int = Field(ge=0, le=100)
    passed: bool
    reasoning: str
    issues: list[str] = Field(default_factory=list)
    adjustments: list[AdjustmentVector] = Field(default_factory=list)

