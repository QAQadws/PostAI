from __future__ import annotations

from copy import deepcopy

from app.core.config import get_settings
from app.core.errors import LLMCallError, SchemaParseError
from app.core.llm_client import StructuredLLMClient
from app.schemas.agents import AdjustmentAction, AdjustmentVector
from app.schemas.layout import Box, FlexSpec, LayoutNode, LayoutStyle, LayoutTree
from app.schemas.state import GraphState


class SpatialLayoutPlanner:
    def __init__(self, llm_client: StructuredLLMClient | None = None) -> None:
        settings = get_settings()
        self.allow_model_fallback = settings.allow_model_fallback
        self.llm_client = llm_client or StructuredLLMClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            response_format=settings.llm_response_format,
        )

    async def run(self, state: GraphState) -> LayoutTree:
        if state.layout_tree and state.feedback_history:
            tree = deepcopy(state.layout_tree)
            for adjustment in state.feedback_history[-1].adjustments:
                self._apply_adjustment(tree.root, adjustment)
            return tree

        try:
            return await self._run_llm(state)
        except (LLMCallError, SchemaParseError) as exc:
            if self._configured_for_llm() and not self.allow_model_fallback:
                raise
            if self._configured_for_llm():
                state.warnings.append(f"SpatialLayoutPlanner LLM fallback: {exc}")
            return self._initial_layout(state)

    async def _run_llm(self, state: GraphState) -> LayoutTree:
        if state.content_plan is None or state.style is None:
            raise ValueError("content_plan and style are required before layout planning")

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a spatial layout planner for poster design. Return only JSON matching LayoutTree. "
                    "Use relative coordinates from 0 to 1. The root must be a container covering the full canvas. "
                    "Each content element should appear as an element node. Keep all boxes inside canvas, avoid overlap, "
                    "and set font_size, color, and align for text elements."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Canvas: {state.canvas.model_dump(mode='json')}\n"
                    f"Content plan: {state.content_plan.model_dump(mode='json')}\n"
                    f"Style guide: {state.style.model_dump(mode='json')}\n"
                    f"Feedback history: {[item.model_dump(mode='json') for item in state.feedback_history[-2:]]}"
                ),
            },
        ]
        tree = await self.llm_client.parse(messages=messages, response_model=LayoutTree)
        self._validate_layout_elements(tree, {element.id for element in state.content_plan.elements})
        return tree

    def _configured_for_llm(self) -> bool:
        return bool(self.llm_client.api_key and self.llm_client.base_url and not self.llm_client.model.startswith("mock-"))

    def _validate_layout_elements(self, tree: LayoutTree, element_ids: set[str]) -> None:
        used = {node.element_id for node in self._walk(tree.root) if node.node_type == "element" and node.element_id}
        required = {"title", "subtitle", "main_visual", "cta"} & element_ids
        missing = required - used
        unknown = used - element_ids
        if missing:
            raise SchemaParseError(f"Layout tree is missing required elements: {sorted(missing)}")
        if unknown:
            raise SchemaParseError(f"Layout tree references unknown elements: {sorted(unknown)}")

    def _walk(self, node: LayoutNode) -> list[LayoutNode]:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._walk(child))
        return nodes

    def _initial_layout(self, state: GraphState) -> LayoutTree:
        style = state.style
        if style is None:
            raise ValueError("style is required before layout planning")

        element_ids = {element.id for element in state.content_plan.elements} if state.content_plan else set()
        children: list[LayoutNode] = []

        if "main_visual" in element_ids:
            children.append(
                LayoutNode(
                    element_id="main_visual",
                    box=Box(x=0.08, y=0.25, width=0.84, height=0.42),
                    style=LayoutStyle(opacity=0.9, radius=0.035),
                    z_index=1,
                )
            )
        if "title" in element_ids:
            children.append(
                LayoutNode(
                    element_id="title",
                    box=Box(x=0.08, y=0.08, width=0.84, height=0.12),
                    style=LayoutStyle(color=style.text_color, font_size=0.052, font_weight="black", align="left"),
                    z_index=5,
                )
            )
        if "subtitle" in element_ids:
            children.append(
                LayoutNode(
                    element_id="subtitle",
                    box=Box(x=0.08, y=0.205, width=0.72, height=0.05),
                    style=LayoutStyle(color=style.accent_color, font_size=0.026, font_weight="medium", align="left"),
                    z_index=5,
                )
            )
        if "info" in element_ids:
            children.append(
                LayoutNode(
                    element_id="info",
                    box=Box(x=0.08, y=0.72, width=0.6, height=0.045),
                    style=LayoutStyle(color=style.text_color, font_size=0.022, font_weight="regular", align="left"),
                    z_index=5,
                )
            )
        if "cta" in element_ids:
            children.append(
                LayoutNode(
                    element_id="cta",
                    box=Box(x=0.08, y=0.82, width=0.34, height=0.07),
                    style=LayoutStyle(
                        color=style.primary_color,
                        background_color=style.accent_color,
                        font_size=0.025,
                        font_weight="bold",
                        align="center",
                        radius=0.04,
                    ),
                    z_index=6,
                )
            )

        if not children:
            children.append(
                LayoutNode(
                    element_id="title",
                    box=Box(x=0.08, y=0.08, width=0.84, height=0.12),
                    style=LayoutStyle(color=style.text_color, font_size=0.052, font_weight="black", align="left"),
                    z_index=5,
                )
            )

        root = LayoutNode(
            node_type="container",
            box=Box(x=0, y=0, width=1, height=1),
            flex=FlexSpec(direction="column"),
            z_index=0,
            children=children,
        )
        return LayoutTree(canvas=state.canvas, root=root)

    def _apply_adjustment(self, node: LayoutNode, adjustment: AdjustmentVector) -> bool:
        if node.node_type == "element" and node.element_id == adjustment.element_id:
            self._mutate_node(node, adjustment)
            return True
        for child in node.children:
            if self._apply_adjustment(child, adjustment):
                return True
        return False

    def _mutate_node(self, node: LayoutNode, adjustment: AdjustmentVector) -> None:
        if adjustment.action in {AdjustmentAction.move, AdjustmentAction.resize}:
            x = self._clamp(node.box.x + adjustment.dx, 0, 0.98)
            y = self._clamp(node.box.y + adjustment.dy, 0, 0.98)
            width = node.box.width + adjustment.d_width
            height = (node.box.height or 0.04) + adjustment.d_height
            if adjustment.scale:
                width *= adjustment.scale
                height *= adjustment.scale
            width = self._clamp(width, 0.03, 1 - x)
            height = self._clamp(height, 0.02, 1 - y)
            node.box = Box(x=x, y=y, width=width, height=height)
        if adjustment.action == AdjustmentAction.recolor and adjustment.new_color:
            node.style.color = adjustment.new_color
        if adjustment.action == AdjustmentAction.typography and adjustment.new_font_size:
            node.style.font_size = adjustment.new_font_size
        if adjustment.action == AdjustmentAction.z_order:
            node.z_index = int(self._clamp(node.z_index + adjustment.z_index_delta, 0, 100))

    def _clamp(self, value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))
