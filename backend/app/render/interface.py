from __future__ import annotations

from typing import Protocol

from app.schemas.state import GraphState, RenderResult


class Renderer(Protocol):
    async def render(self, state: GraphState) -> RenderResult:
        """Render a poster from the current graph state."""

