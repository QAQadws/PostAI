from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


EventName = Literal[
    "job_started",
    "agent_start",
    "agent_complete",
    "render_preview",
    "critique",
    "warning",
    "final_output",
    "error",
    "job_finished",
]


class SSEEvent(BaseModel):
    event: EventName
    data: dict[str, Any] = Field(default_factory=dict)


def event(name: EventName, data: dict[str, Any] | BaseModel | None = None) -> SSEEvent:
    if data is None:
        payload: dict[str, Any] = {}
    elif isinstance(data, BaseModel):
        payload = data.model_dump(mode="json")
    else:
        payload = data
    return SSEEvent(event=name, data=payload)


def format_sse(sse_event: SSEEvent) -> str:
    data = json.dumps(sse_event.data, ensure_ascii=False)
    return f"event: {sse_event.event}\ndata: {data}\n\n"

