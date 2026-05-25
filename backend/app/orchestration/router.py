"""Routing logic — Phase 2 version.

Decides whether the iteration loop should finalise the poster or run another
round of layout / style planning.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.schemas.state import GraphState

# Keywords that suggest a style/background change rather than layout tweaks.
_STYLE_KEYWORDS = {"background", "color scheme", "palette", "mood", "style", "theme", "font family"}


class RouteAction(str, Enum):
    final = "final"
    layout = "layout"
    style = "style"
    render = "render"


class RouteDecision(BaseModel):
    action: RouteAction
    reason: str


def route_after_critique(state: GraphState) -> RouteDecision:
    """Decide the next pipeline action based on the most recent critique.

    Natural-language suggestions are scanned for style-related keywords.
    """
    if not state.feedback_history:
        return RouteDecision(action=RouteAction.layout, reason="No critique is available yet.")

    latest = state.feedback_history[-1]
    # Honour `min_iterations` — the caller controls how many VLM review cycles
    # must happen before score-based early exit is allowed.
    # iteration_count == number of completed iterations so far.
    min_ok = state.iteration_count >= state.min_iterations

    if min_ok and latest.score >= state.target_score:
        return RouteDecision(action=RouteAction.final, reason="Target score reached.")
    if min_ok and latest.passed and latest.score >= state.target_score - 10:
        return RouteDecision(action=RouteAction.final, reason="VLM passed and score is close to target.")

    if state.iteration_count + 1 >= state.max_iterations:
        return RouteDecision(action=RouteAction.final, reason="Max iterations reached.")

    if len(state.feedback_history) >= 2 and latest.score <= state.feedback_history[-2].score:
        return RouteDecision(action=RouteAction.final, reason="Score did not improve in the latest iteration.")

    all_text = " ".join(latest.suggestions + latest.issues).lower()
    if any(keyword in all_text for keyword in _STYLE_KEYWORDS):
        return RouteDecision(action=RouteAction.style, reason="Suggestions mention style/background changes.")

    if latest.suggestions or latest.issues:
        return RouteDecision(action=RouteAction.layout, reason="Apply layout improvements based on feedback.")

    return RouteDecision(action=RouteAction.layout, reason="Score is low; re-plan layout with critique context.")
