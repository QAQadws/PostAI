from __future__ import annotations

from itertools import combinations

from app.core.config import get_settings
from app.core.errors import LLMCallError, SchemaParseError
from app.core.llm_client import StructuredLLMClient
from app.schemas.agents import AdjustmentAction, AdjustmentVector, CritiqueResult
from app.schemas.layout import LayoutNode
from app.schemas.state import GraphState


class HeuristicVLMCritic:
    def __init__(self, vision_client: StructuredLLMClient | None = None) -> None:
        settings = get_settings()
        self.allow_model_fallback = settings.allow_model_fallback
        self.vision_client = vision_client or StructuredLLMClient(
            api_key=settings.vision_api_key,
            base_url=settings.vision_base_url,
            model=settings.vision_model,
            response_format=settings.llm_response_format,
        )

    async def run(self, state: GraphState) -> CritiqueResult:
        try:
            return await self._run_vision_model(state)
        except (LLMCallError, SchemaParseError) as exc:
            if self._configured_for_vision() and not self.allow_model_fallback:
                raise
            if self._configured_for_vision():
                state.warnings.append(f"VLMCritic vision fallback: {exc}")
            return self._run_heuristic(state)

    async def _run_vision_model(self, state: GraphState) -> CritiqueResult:
        if state.render_result is None or not state.render_result.image_base64:
            raise LLMCallError("render result image_base64 is required for vision critique")
        if state.layout_tree is None or state.content_plan is None:
            raise LLMCallError("layout_tree and content_plan are required for vision critique")

        image_url = f"data:{state.render_result.mime_type};base64,{state.render_result.image_base64}"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict visual art director reviewing a generated poster. "
                    "Return only JSON matching CritiqueResult. Score readability, hierarchy, overlap, margins, "
                    "style consistency, and topic expression. Adjustments must be numeric vectors that can be applied by code."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Content plan: {state.content_plan.model_dump(mode='json')}\n"
                            f"Layout tree: {state.layout_tree.model_dump(mode='json')}\n"
                            "Critique this rendered poster and return structured feedback."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        return await self.vision_client.parse(messages=messages, response_model=CritiqueResult)

    def _run_heuristic(self, state: GraphState) -> CritiqueResult:
        if state.layout_tree is None:
            raise ValueError("layout_tree is required before critique")

        issues: list[str] = []
        adjustments: list[AdjustmentVector] = []
        nodes = [node for node in self._walk(state.layout_tree.root) if node.node_type == "element"]

        for node in nodes:
            if node.box.x < 0.04 or node.box.y < 0.04:
                issues.append(f"{node.element_id} is too close to canvas edge")
                adjustments.append(
                    AdjustmentVector(
                        element_id=node.element_id,
                        action=AdjustmentAction.move,
                        dx=0.02 if node.box.x < 0.04 else 0,
                        dy=0.02 if node.box.y < 0.04 else 0,
                        reason="Increase outer margin.",
                    )
                )
            if node.element_id in {"title", "subtitle", "info", "cta"} and not node.style.font_size:
                issues.append(f"{node.element_id} misses font size")
                adjustments.append(
                    AdjustmentVector(
                        element_id=node.element_id,
                        action=AdjustmentAction.typography,
                        new_font_size=0.026,
                        reason="Text nodes require explicit font size.",
                    )
                )

        for left, right in combinations(nodes, 2):
            if left.z_index == right.z_index and self._overlap_ratio(left, right) > 0.18:
                issues.append(f"{left.element_id} overlaps {right.element_id}")
                adjustments.append(
                    AdjustmentVector(
                        element_id=right.element_id,
                        action=AdjustmentAction.move,
                        dy=0.04,
                        reason="Reduce overlap between high-level layout elements.",
                    )
                )

        score = max(60, 92 - len(issues) * 8)
        passed = score >= state.target_score
        reasoning = "Layout is readable and balanced." if passed else "Layout needs spacing or typography corrections."
        return CritiqueResult(score=score, passed=passed, reasoning=reasoning, issues=issues, adjustments=adjustments[:4])

    def _configured_for_vision(self) -> bool:
        return bool(
            self.vision_client.api_key
            and self.vision_client.base_url
            and not self.vision_client.model.startswith("mock-")
        )

    def _walk(self, node: LayoutNode) -> list[LayoutNode]:
        result = [node]
        for child in node.children:
            result.extend(self._walk(child))
        return result

    def _overlap_ratio(self, left: LayoutNode, right: LayoutNode) -> float:
        left_h = left.box.height or 0.04
        right_h = right.box.height or 0.04
        x1 = max(left.box.x, right.box.x)
        y1 = max(left.box.y, right.box.y)
        x2 = min(left.box.x + left.box.width, right.box.x + right.box.width)
        y2 = min(left.box.y + left_h, right.box.y + right_h)
        if x2 <= x1 or y2 <= y1:
            return 0
        overlap = (x2 - x1) * (y2 - y1)
        smaller = min(left.box.width * left_h, right.box.width * right_h)
        return overlap / smaller if smaller else 0
