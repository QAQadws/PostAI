from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class CanvasSpec(BaseModel):
    width: int = Field(default=1024, ge=256, le=4096)
    height: int = Field(default=1536, ge=256, le=4096)
    unit: Literal["px"] = "px"


class ElementType(str, Enum):
    text = "text"
    image = "image"
    shape = "shape"
    group = "group"


class Box(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float | None = Field(default=None, gt=0, le=1)

    @model_validator(mode="after")
    def must_fit_canvas(self) -> "Box":
        height = self.height or 0
        if self.x + self.width > 1:
            raise ValueError("box exceeds canvas width")
        if height and self.y + height > 1:
            raise ValueError("box exceeds canvas height")
        return self


class LayoutStyle(BaseModel):
    color: str | None = None
    background_color: str | None = None
    opacity: float = Field(default=1.0, ge=0, le=1)
    font_size: float | None = Field(default=None, gt=0, le=0.15)
    font_weight: Literal["regular", "medium", "bold", "black"] | None = None
    align: Literal["left", "center", "right"] | None = None
    radius: float | None = Field(default=None, ge=0, le=1)


class FlexSpec(BaseModel):
    direction: Literal["row", "column"] = "column"
    justify: Literal["start", "center", "end", "space-between", "space-around"] = "start"
    align: Literal["start", "center", "end", "stretch"] = "start"
    gap: float = Field(default=0.02, ge=0, le=0.2)
    padding: float = Field(default=0, ge=0, le=0.2)


class LayoutNode(BaseModel):
    id: str = Field(default_factory=lambda: f"node_{uuid4().hex[:8]}")
    element_id: str | None = None
    node_type: Literal["container", "element"] = "element"
    box: Box
    style: LayoutStyle = Field(default_factory=LayoutStyle)
    flex: FlexSpec | None = None
    z_index: int = Field(default=1, ge=0, le=100)
    children: list["LayoutNode"] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_tree_shape(self) -> "LayoutNode":
        if self.node_type == "container" and self.element_id is not None:
            raise ValueError("container nodes must not bind an element_id")
        if self.node_type == "element" and self.children:
            raise ValueError("element nodes must not have children")
        if self.node_type == "element" and not self.element_id:
            raise ValueError("element nodes require element_id")
        return self


class LayoutTree(BaseModel):
    canvas: CanvasSpec = Field(default_factory=CanvasSpec)
    root: LayoutNode

    @model_validator(mode="after")
    def root_must_be_container(self) -> "LayoutTree":
        if self.root.node_type != "container":
            raise ValueError("layout root must be a container")
        return self

