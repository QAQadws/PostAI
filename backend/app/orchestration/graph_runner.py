from __future__ import annotations

from collections.abc import AsyncIterator

from app.agents.content_extractor import ContentExtractor
from app.agents.layout_planner import SpatialLayoutPlanner
from app.agents.style_director import StyleDirector
from app.agents.vlm_critic import HeuristicVLMCritic
from app.core.config import get_settings
from app.core.events import SSEEvent, event
from app.orchestration.retry import retry_async
from app.orchestration.router import RouteAction, route_after_critique
from app.render.asset_store import AssetStore
from app.schemas.api import GenerateResponse
from app.schemas.state import GraphStage, GraphState


class GraphRunner:
    def __init__(
        self,
        content_extractor: ContentExtractor | None = None,
        style_director: StyleDirector | None = None,
        layout_planner: SpatialLayoutPlanner | None = None,
        renderer=None,
        asset_store: AssetStore | None = None,
        critic: HeuristicVLMCritic | None = None,
    ) -> None:
        from app.render.pillow_renderer import PillowPosterRenderer

        settings = get_settings()
        self.content_extractor = content_extractor or ContentExtractor()
        self.style_director = style_director or StyleDirector()
        self.layout_planner = layout_planner or SpatialLayoutPlanner()
        self.renderer = renderer or PillowPosterRenderer()
        self.asset_store = asset_store or AssetStore(settings.asset_dir, settings.asset_url_path)
        self.critic = critic or HeuristicVLMCritic()

    async def run_events(self, state: GraphState) -> AsyncIterator[SSEEvent]:
        try:
            yield event("job_started", {"job_id": state.job_id})

            state.stage = GraphStage.content
            yield event("agent_start", {"job_id": state.job_id, "agent": "ContentExtractor", "message": "Parsing poster content"})
            state.content_plan = await retry_async(lambda: self.content_extractor.run(state), attempts=3)
            yield event("agent_complete", {"job_id": state.job_id, "agent": "ContentExtractor", "result": state.content_plan.model_dump(mode="json")})

            state.stage = GraphStage.style
            yield event("agent_start", {"job_id": state.job_id, "agent": "StyleDirector", "message": "Planning visual style"})
            state.style = await retry_async(lambda: self.style_director.run(state), attempts=3)
            yield event("agent_complete", {"job_id": state.job_id, "agent": "StyleDirector", "result": state.style.model_dump(mode="json")})

            best_response: GenerateResponse | None = None
            best_score = -1

            while state.iteration_count < state.max_iterations:
                state.stage = GraphStage.layout
                yield event("agent_start", {"job_id": state.job_id, "agent": "SpatialLayoutPlanner", "message": "Planning layout tree"})
                state.layout_tree = await retry_async(lambda: self.layout_planner.run(state), attempts=3)
                yield event("agent_complete", {"job_id": state.job_id, "agent": "SpatialLayoutPlanner", "result": state.layout_tree.model_dump(mode="json")})

                state.stage = GraphStage.render
                yield event("agent_start", {"job_id": state.job_id, "agent": "RenderInterface", "message": "Rendering poster preview"})
                state.render_result = await retry_async(lambda: self.renderer.render(state), attempts=2)
                state.render_result = await self.asset_store.save_render(
                    state.render_result,
                    job_id=state.job_id,
                    iteration=state.iteration_count,
                )
                yield event("render_preview", {"job_id": state.job_id, "iteration": state.iteration_count, **state.render_result.model_dump(mode="json")})

                state.stage = GraphStage.critique
                yield event("agent_start", {"job_id": state.job_id, "agent": "VLMCritic", "message": "Reviewing visual result"})
                critique = await retry_async(lambda: self.critic.run(state), attempts=2)
                state.feedback_history.append(critique)
                yield event("critique", {"job_id": state.job_id, **critique.model_dump(mode="json")})

                if critique.score > best_score:
                    best_score = critique.score
                    best_response = self.build_response(state)

                decision = route_after_critique(state)
                if decision.action == RouteAction.final:
                    if critique.score < state.target_score and not critique.passed:
                        state.warnings.append(decision.reason)
                        yield event("warning", {"job_id": state.job_id, "message": decision.reason})
                    break

                state.iteration_count += 1
                if decision.action == RouteAction.style:
                    state.stage = GraphStage.style
                    yield event("agent_start", {"job_id": state.job_id, "agent": "StyleDirector", "message": decision.reason})
                    state.style = await retry_async(lambda: self.style_director.run(state), attempts=3)
                    yield event("agent_complete", {"job_id": state.job_id, "agent": "StyleDirector", "result": state.style.model_dump(mode="json")})

            state.stage = GraphStage.final
            response = self._finalize_response(best_response, state)
            yield event("final_output", response.model_dump(mode="json"))
            yield event("job_finished", {"job_id": state.job_id, "stage": state.stage.value})
        except Exception as exc:
            failed_stage = state.stage.value
            state.stage = GraphStage.error
            state.error = str(exc)
            yield event(
                "error",
                {
                    "job_id": state.job_id,
                    "stage": failed_stage,
                    "message": str(exc),
                    "recoverable": False,
                },
            )

    async def run(self, state: GraphState) -> GenerateResponse:
        final: GenerateResponse | None = None
        async for sse_event in self.run_events(state):
            if sse_event.event == "final_output":
                final = GenerateResponse.model_validate(sse_event.data)
            if sse_event.event == "error":
                raise RuntimeError(str(sse_event.data.get("message", "generation failed")))
        if final is None:
            raise RuntimeError("generation did not produce final output")
        return final

    def build_response(self, state: GraphState) -> GenerateResponse:
        latest = state.feedback_history[-1] if state.feedback_history else None
        return GenerateResponse(
            job_id=state.job_id,
            final_image=state.render_result.image_base64 if state.render_result else None,
            image_url=state.render_result.image_url if state.render_result else None,
            score=latest.score if latest else None,
            warnings=state.warnings,
            content_plan=state.content_plan,
            style=state.style,
            layout_tree=state.layout_tree,
            render_result=state.render_result,
            critiques=state.feedback_history,
        )

    def _finalize_response(self, best_response: GenerateResponse | None, state: GraphState) -> GenerateResponse:
        response = best_response or self.build_response(state)
        latest = state.feedback_history[-1] if state.feedback_history else None
        return response.model_copy(
            update={
                "warnings": list(state.warnings),
                "critiques": list(state.feedback_history),
                "score": response.score if response.score is not None else (latest.score if latest else None),
            }
        )
