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


class CritiqueResult(BaseModel):
    """Phase 2 critique — pure natural-language feedback.

    The VLM describes what it sees, lists issues, and gives actionable
    suggestions in human language.
    """

    score: int = Field(ge=0, le=100)
    passed: bool
    reasoning: str
    vision_description: str = Field(
        default="",
        description="Literal description of what the vision model sees in the rendered poster",
    )
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(
        default_factory=list,
        description="Natural-language actionable suggestions for the layout planner",
    )

