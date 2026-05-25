from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.events import format_sse
from app.orchestration.graph_runner import GraphRunner
from app.schemas.api import GenerateRequest, GenerateResponse
from app.schemas.layout import CanvasSpec
from app.schemas.state import GraphState


router = APIRouter(tags=["generate"])


def _state_from_request(request: GenerateRequest) -> GraphState:
    return GraphState(
        user_prompt=request.prompt,
        canvas=CanvasSpec(width=request.width, height=request.height),
        max_iterations=request.max_iterations,
        target_score=request.target_score,
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest) -> GenerateResponse:
    runner = GraphRunner()
    try:
        return await runner.run(_state_from_request(request))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/generate/stream")
async def generate_stream(request: GenerateRequest) -> StreamingResponse:
    runner = GraphRunner()
    state = _state_from_request(request)

    async def stream() -> AsyncIterator[str]:
        async for sse_event in runner.run_events(state):
            yield format_sse(sse_event)

    return StreamingResponse(stream(), media_type="text/event-stream")
