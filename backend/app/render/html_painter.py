"""HTMLPainter — render HTML+CSS to a PNG poster via headless Chromium.

Replaces the Pillow-based Painter.  The AI outputs a complete HTML document
with inline CSS; Playwright opens it in headless Chromium and captures a
pixel-perfect screenshot.  No more geometric-primitive limitations.

Uses Playwright's **synchronous** API inside ``asyncio.to_thread`` so that
browser launch runs via plain ``subprocess.Popen``, avoiding uv-managed
Python's broken ``asyncio.create_subprocess_exec`` on Windows.

Usage::

    result = await HTMLPainter().render("<h1>Hello</h1>", width=800, height=600)
"""

from __future__ import annotations

import asyncio
import base64

from playwright.sync_api import sync_playwright

from app.core.errors import RenderError
from app.schemas.state import RenderResult

# ═══════════════════════════════════════════════════════════════════════════════
# Fallback HTML template — used when the LLM fails to produce valid HTML.
# ═══════════════════════════════════════════════════════════════════════════════

_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  *, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ width:{width}px; height:{height}px; overflow:hidden; font-family:"Microsoft YaHei","PingFang SC",sans-serif; }}
  .bg {{ position:absolute; inset:0; background:linear-gradient(180deg, {primary}, {secondary}); }}
  .content {{ position:relative; display:flex; flex-direction:column; justify-content:center;
             align-items:center; height:100%; padding:8% 10%; color:{text_color}; }}
  .title {{ font-size:{title_size}px; font-weight:900; text-align:center; margin-bottom:3%; }}
  .subtitle {{ font-size:{subtitle_size}px; opacity:0.85; text-align:center; margin-bottom:8%; }}
  .visual {{ width:60%; aspect-ratio:1; border-radius:24px; background:rgba(255,255,255,0.08);
             border:2px solid rgba(255,255,255,0.15); display:flex; align-items:center; justify-content:center;
             margin-bottom:8%; }}
  .visual svg {{ width:40%; height:40%; opacity:0.5; }}
  .cta {{ font-size:{cta_size}px; font-weight:700; color:{primary}; background:{accent};
         padding:14px 48px; border-radius:16px; text-align:center; }}
</style>
</head>
<body>
<div class="bg"></div>
<div class="content">
  <div class="title">{title}</div>
  <div class="subtitle">{subtitle}</div>
  <div class="visual">
    <svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="none" stroke="white" stroke-width="2"/>
    <circle cx="35" cy="40" r="5" fill="white"/><circle cx="65" cy="40" r="5" fill="white"/>
    <path d="M35 65 Q50 80 65 65" fill="none" stroke="white" stroke-width="3" stroke-linecap="round"/></svg>
  </div>
  <div class="cta">{cta}</div>
</div>
</body>
</html>"""


def _build_fallback_html(
    *,
    width: int,
    height: int,
    primary: str = "#1a1a2e",
    secondary: str = "#16213e",
    accent: str = "#00d4ff",
    text_color: str = "#ffffff",
    title: str = "Poster Title",
    subtitle: str = "Subtitle goes here",
    cta: str = "Learn More",
) -> str:
    """Produce a simple fallback poster when the LLM is unavailable."""
    return _FALLBACK_HTML.format(
        width=width,
        height=height,
        primary=primary,
        secondary=secondary,
        accent=accent,
        text_color=text_color,
        title=title,
        subtitle=subtitle,
        cta=cta,
        title_size=int(height * 0.06),
        subtitle_size=int(height * 0.028),
        cta_size=int(height * 0.026),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HTMLPainter
# ═══════════════════════════════════════════════════════════════════════════════


class HTMLPainter:
    """Render an HTML string to a base64-encoded PNG via headless Chromium.

    The HTML must be self-contained (inline CSS or a ``<style>`` block).
    External resources like Google Fonts are supported — the painter waits
    for ``networkidle`` before capturing.
    """

    async def render(self, html: str, *, width: int, height: int) -> RenderResult:
        """Return a ``RenderResult`` containing the base64 PNG.

        Offloads Playwright's synchronous API to a thread so that the browser
        process is launched via ``subprocess.Popen`` instead of asyncio's
        (often broken on Windows) ``create_subprocess_exec``.

        Raises ``RenderError`` if the HTML is empty or the browser fails.
        """
        sanitised = html.strip()
        if not sanitised:
            raise RenderError("HTML string is empty — nothing to render")

        def _render_sync() -> RenderResult:
            console_errors: list[str] = []
            with sync_playwright() as p:
                browser = p.chromium.launch(args=["--disable-gpu", "--no-sandbox"])
                try:
                    page = browser.new_page(viewport={"width": width, "height": height})

                    def _on_console(msg):
                        if msg.type in {"error", "warning"}:
                            console_errors.append(f"[{msg.type}] {msg.text}")

                    page.on("console", _on_console)
                    page.set_content(sanitised, wait_until="networkidle")
                    screenshot = page.screenshot(full_page=False)
                except Exception as exc:
                    raise RenderError(f"Playwright rendering failed: {exc}") from exc
                finally:
                    browser.close()

            encoded = base64.b64encode(screenshot).decode("ascii")
            return RenderResult(
                image_base64=encoded,
                width=width,
                height=height,
                mime_type="image/png",
                console_errors=console_errors,
            )

        return await asyncio.to_thread(_render_sync)
