import pytest
from pydantic import ValidationError

from app.schemas.api import GenerateRequest
from app.schemas.layout import Box, LayoutNode, LayoutTree
from app.schemas.state import GeneratedIllustration, GraphState


def test_graph_state_defaults_are_isolated():
    left = GraphState(user_prompt="a")
    right = GraphState(user_prompt="b")
    left.warnings.append("warning")
    assert right.warnings == []


def test_layout_tree_supports_nested_container():
    tree = LayoutTree(
        root=LayoutNode(
            node_type="container",
            box=Box(x=0, y=0, width=1, height=1),
            children=[
                LayoutNode(
                    node_type="container",
                    box=Box(x=0.1, y=0.1, width=0.8, height=0.8),
                    children=[
                        LayoutNode(element_id="title", box=Box(x=0.1, y=0.1, width=0.5, height=0.1))
                    ],
                )
            ],
        )
    )
    assert tree.root.children[0].children[0].element_id == "title"


def test_box_rejects_out_of_bounds_values():
    with pytest.raises(ValidationError):
        Box(x=0.8, y=0.1, width=0.3, height=0.2)


def test_generate_request_generated_illustration_defaults():
    request = GenerateRequest(prompt="海报")
    assert request.enable_generated_illustrations is True
    assert request.max_generated_illustrations == 3


def test_generate_request_rejects_too_many_generated_illustrations():
    with pytest.raises(ValidationError):
        GenerateRequest(prompt="海报", max_generated_illustrations=6)


def test_generated_illustration_accepts_failed_status():
    item = GeneratedIllustration(
        id="main-visual",
        source_visual_subject_id="main_visual",
        description="robot illustration",
        prompt="draw a robot",
        status="failed",
        error="provider unavailable",
    )
    assert item.status == "failed"
    assert item.url is None
