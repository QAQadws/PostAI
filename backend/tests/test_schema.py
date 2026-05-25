import pytest
from pydantic import ValidationError

from app.schemas.layout import Box, LayoutNode, LayoutTree
from app.schemas.state import GraphState


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
