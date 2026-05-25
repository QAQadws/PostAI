from app.orchestration.router import RouteAction, route_after_critique
from app.schemas.agents import AdjustmentAction, AdjustmentVector, CritiqueResult
from app.schemas.state import GraphState


def test_router_finishes_when_score_passes():
    state = GraphState(user_prompt="poster")
    state.feedback_history.append(CritiqueResult(score=90, passed=True, reasoning="ok"))
    assert route_after_critique(state).action == RouteAction.final


def test_router_sends_background_issue_to_style():
    state = GraphState(user_prompt="poster")
    state.feedback_history.append(
        CritiqueResult(
            score=70,
            passed=False,
            reasoning="busy background",
            adjustments=[
                AdjustmentVector(
                    action=AdjustmentAction.regenerate_background,
                    reason="Background is too busy.",
                )
            ],
        )
    )
    assert route_after_critique(state).action == RouteAction.style
