"""Tests for HTMLPainter — Phase 1."""

import base64

import pytest

from app.core.errors import RenderError
from app.render.html_painter import HTMLPainter, _build_fallback_html

_MINIMAL_HTML = "<!DOCTYPE html><html><body>Hello</body></html>"
_STYLED_HTML = """<!DOCTYPE html>
<html><head><style>
  body { width:400px; height:600px; background:linear-gradient(180deg, #1a1a2e, #16213e); }
  h1 { color:white; font-family:sans-serif; text-align:center; padding-top:40%; }
</style></head><body><h1>AI Poster</h1></body></html>"""


# ── _build_fallback_html ──


def test_fallback_html_contains_expected_content():
    html = _build_fallback_html(
        width=400,
        height=600,
        title="Hello World",
        subtitle="A test poster",
        cta="Click Here",
    )
    assert "Hello World" in html
    assert "A test poster" in html
    assert "Click Here" in html
    assert "400px" in html
    assert "600px" in html


def test_fallback_html_uses_provided_colors():
    html = _build_fallback_html(
        width=400, height=600,
        primary="#FF0000", secondary="#00FF00", accent="#0000FF", text_color="#FFFFFF",
    )
    assert "#FF0000" in html
    assert "#00FF00" in html
    assert "#0000FF" in html


# ── HTMLPainter.render ──


async def test_render_minimal_html():
    """Basic HTML renders to a non-empty base64 PNG."""
    result = await HTMLPainter().render(_MINIMAL_HTML, width=400, height=600)
    assert result.image_base64
    assert result.width == 400
    assert result.height == 600
    assert result.mime_type == "image/png"
    # Decode to verify it's a real PNG.
    png_bytes = base64.b64decode(result.image_base64)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic header


async def test_render_styled_html():
    """CSS-styled HTML renders successfully."""
    result = await HTMLPainter().render(_STYLED_HTML, width=400, height=600)
    assert result.image_base64
    assert result.width == 400
    assert result.height == 600


async def test_render_respects_dimensions():
    """PNG dimensions match the requested width/height."""
    result = await HTMLPainter().render(_MINIMAL_HTML, width=800, height=1200)
    assert result.width == 800
    assert result.height == 1200


async def test_render_different_sizes_produce_different_output():
    """Two renders at different sizes should differ."""
    small = await HTMLPainter().render(_MINIMAL_HTML, width=200, height=300)
    large = await HTMLPainter().render(_MINIMAL_HTML, width=800, height=1200)
    assert small.image_base64 != large.image_base64


async def test_render_raises_on_empty_html():
    """Empty HTML must raise RenderError immediately."""
    with pytest.raises(RenderError, match="empty"):
        await HTMLPainter().render("", width=400, height=600)


async def test_render_raises_on_whitespace_only():
    with pytest.raises(RenderError, match="empty"):
        await HTMLPainter().render("   \n  ", width=400, height=600)
