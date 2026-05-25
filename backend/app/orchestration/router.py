from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.schemas.agents import AdjustmentAction
from app.schemas.state import GraphState


class RouteAction(str, Enum):
    final = "final"
    layout = "layout"
    style = "style"
    render = "render"


class RouteDecision(BaseModel):
    action: RouteAction
    reason: str


def route_after_critique(state: GraphState) -> RouteDecision:
    if not state.feedback_history:
        return RouteDecision(action=RouteAction.layout, reason="No critique is available yet.")

    latest = state.feedback_history[-1]
    if latest.passed or latest.score >= state.target_score:
        return RouteDecision(action=RouteAction.final, reason="Target score reached.")

    if state.iteration_count + 1 >= state.max_iterations:
        return RouteDecision(action=RouteAction.final, reason="Max iterations reached.")

    if len(state.feedback_history) >= 2 and latest.score <= state.feedback_history[-2].score:
        return RouteDecision(action=RouteAction.final, reason="Score did not improve in the latest iteration.")

    actions = {adjustment.action for adjustment in latest.adjustments}
    if AdjustmentAction.regenerate_background in actions:
        return RouteDecision(action=RouteAction.style, reason="Background needs regeneration or style changes.")
    if actions:
        return RouteDecision(action=RouteAction.layout, reason="Apply structured visual adjustment vectors.")
    return RouteDecision(action=RouteAction.layout, reason="Score is low; re-plan layout with critique context.")

