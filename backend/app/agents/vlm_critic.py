"""Vision-language critic — Phase 2 (HTML pipeline).

Critiques a rendered poster by sending the PNG image to a vision model along
with the HTML layout that produced it.  Uses ``parse_vision`` with
*enable_thinking* so the model can reason about what it sees before scoring.
"""

from __future__ import annotations

import json
from itertools import combinations

from app.core.config import get_settings
from app.core.errors import LLMCallError, SchemaParseError
from app.core.llm_client import StructuredLLMClient
from app.schemas.agents import CritiqueResult
from app.schemas.state import GraphState


class HeuristicVLMCritic:
    """Critique a rendered poster using a vision-language model.

    Sends the rendered PNG along with the HTML layout snippet and asks for
    structured feedback.  With *enable_thinking* the model first reasons
    about what it sees (stored in ``state.vision_reasoning``) and then
    emits a ``CritiqueResult`` with a literal ``vision_description``.

    Falls back to a deterministic heuristic when the vision model is
    unavailable.
    """

    def __init__(self, vision_client: StructuredLLMClient | None = None) -> None:
        settings = get_settings()
        self.allow_model_fallback = settings.allow_model_fallback
        self.enable_thinking = settings.vision_enable_thinking
        self.thinking_budget = settings.vision_thinking_budget
        self.vision_client = vision_client or StructuredLLMClient(
            api_key=settings.vision_api_key,
            base_url=settings.vision_base_url,
            model=settings.vision_model,
            response_format=settings.llm_response_format,
        )

    # ── public entry point ──

    async def run(self, state: GraphState) -> CritiqueResult:
        try:
            return await self._run_vision_model(state)
        except (LLMCallError, SchemaParseError) as exc:
            if self._configured_for_vision() and not self.allow_model_fallback:
                raise
            if self._configured_for_vision():
                state.warnings.append(f"VLMCritic vision fallback: {exc}")
            return self._run_heuristic(state)

    # ── vision model path ──

    async def _run_vision_model(self, state: GraphState) -> CritiqueResult:
        if state.render_result is None or not state.render_result.image_base64:
            raise LLMCallError("render result image_base64 is required for vision critique")
        if state.layout_html is None or state.content_plan is None:
            raise LLMCallError("layout_html and content_plan are required for vision critique")

        image_url = f"data:{state.render_result.mime_type};base64,{state.render_result.image_base64}"
        messages = self._build_vision_messages(state, image_url)

        result, reasoning = await self.vision_client.parse_vision(
            messages=messages,
            response_model=CritiqueResult,
            enable_thinking=self.enable_thinking,
            thinking_budget=self.thinking_budget,
        )

        if reasoning:
            state.vision_reasoning = reasoning

        return result

    def _build_vision_messages(self, state: GraphState, image_url: str) -> list[dict]:
        """Construct the multi-modal messages for the vision critique call.

        Sends the HTML layout (truncated) as context so the VLM can compare
        the design intent with the actual rendered pixels.
        """
        system_prompt = (
            "You are a strict visual art director reviewing a generated poster.\n\n"
            "Step 1 — Describe what you literally see in the image: colors, "
            "shapes, text content, layout structure, spacing, visual hierarchy. "
            "Put this in the **vision_description** field.\n\n"
            "Step 2 — Score the poster (0-100) on readability, hierarchy, overlap, "
            "margins, style consistency, and topic expression. "
            "Set **passed**=true if the poster is good enough to ship.\n"
            "Explain your scoring in the **reasoning** field.\n\n"
            "Step 3 — List specific **issues** you can literally see.\n\n"
            "Step 4 — Write concrete, actionable **suggestions** in natural "
            "language that a layout designer can follow to improve the HTML/CSS.\n\n"
            "Return ONLY a JSON object with exactly these fields — no schema, no extras:\n"
            '{"score": 85, "passed": true, "reasoning": "...", "vision_description": "...", "issues": ["..."], "suggestions": ["..."]}'
        )

        # Truncate HTML to avoid blowing up the prompt.
        html_snippet = state.layout_html[:3000] if state.layout_html else ""

        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Content plan: {state.content_plan.model_dump(mode='json')}\n"
                            f"HTML layout (first 3000 chars): {html_snippet}\n"
                            "Critique this rendered poster and return structured feedback."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]

    # ── heuristic fallback ──

    def _run_heuristic(self, state: GraphState) -> CritiqueResult:
        """Deterministic critique when the vision model is not available.

        Uses the HTML content and content_plan to perform basic checks.
        """
        if not state.content_plan or not state.content_plan.elements:
            raise ValueError("content_plan with elements is required before critique")

        elements = state.content_plan.elements
        html = state.layout_html or ""
        issues: list[str] = []
        suggestions: list[str] = []

        # Check that all required text elements appear in the HTML.
        for el in elements:
            if el.type.value == "text" and el.content and el.content not in html:
                issues.append(f"Text element '{el.id}' ({el.content}) may be missing from HTML")
                suggestions.append(
                    f"Ensure the text '{el.content}' appears in the HTML body for element '{el.id}'."
                )

        # Check for common anti-patterns.
        if "<body" not in html.lower() and "<html" not in html.lower():
            issues.append("HTML is missing <body> or <html> tags")
            suggestions.append("Add proper <!DOCTYPE html> and <body> structure to the HTML.")

        if "<style" not in html and "style=" not in html:
            issues.append("No CSS styling found in the HTML")
            suggestions.append("Add inline CSS or a <style> block for visual design.")

        score = max(60, 92 - len(issues) * 8)
        passed = score >= state.target_score
        reasoning = (
            "Layout contains expected elements and styling."
            if passed
            else "Layout is missing key elements or styling."
        )
        return CritiqueResult(
            score=score,
            passed=passed,
            reasoning=reasoning,
            vision_description="(heuristic — no vision model available)",
            issues=issues,
            suggestions=suggestions,
        )

    # ── helpers ──

    def _configured_for_vision(self) -> bool:
        return bool(
            self.vision_client.api_key
            and self.vision_client.base_url
            and not self.vision_client.model.startswith("mock-")
        )
