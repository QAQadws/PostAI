from __future__ import annotations

import base64
from io import BytesIO
import math
from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont

from app.core.errors import RenderError
from app.schemas.agents import ElementContent
from app.schemas.layout import ElementType, LayoutNode
from app.schemas.state import GraphState, RenderResult


class PillowPosterRenderer:
    async def render(self, state: GraphState) -> RenderResult:
        if state.style is None or state.layout_tree is None or state.content_plan is None:
            raise RenderError("style, layout_tree and content_plan are required")

        width = state.canvas.width
        height = state.canvas.height
        image = self._background(width, height, state.style.primary_color, state.style.secondary_color)
        draw = ImageDraw.Draw(image, "RGBA")
        elements = {element.id: element for element in state.content_plan.elements}

        for node in sorted(self._element_nodes(state.layout_tree.root), key=lambda item: item.z_index):
            if not node.element_id or node.element_id not in elements:
                continue
            element = elements[node.element_id]
            box = self._pixel_box(node, width, height)
            if element.type == ElementType.image:
                self._draw_visual(draw, box, state.style.accent_color, state.style.secondary_color)
            elif element.type == ElementType.shape:
                self._draw_shape(draw, box, node.style.background_color or state.style.accent_color)
            else:
                self._draw_text(draw, box, element, node, height, state)

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return RenderResult(image_base64=encoded, width=width, height=height, mime_type="image/png")

    def _background(self, width: int, height: int, top_hex: str, bottom_hex: str) -> Image.Image:
        top = self._hex_to_rgb(top_hex)
        bottom = self._hex_to_rgb(bottom_hex)
        image = Image.new("RGB", (width, height), top)
        pixels = image.load()
        for y in range(height):
            ratio = y / max(1, height - 1)
            color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
            for x in range(width):
                pixels[x, y] = color
        return image.convert("RGBA")

    def _element_nodes(self, node: LayoutNode) -> list[LayoutNode]:
        nodes = [node] if node.node_type == "element" else []
        for child in node.children:
            nodes.extend(self._element_nodes(child))
        return nodes

    def _pixel_box(self, node: LayoutNode, width: int, height: int) -> tuple[int, int, int, int]:
        box_h = node.box.height or 0.05
        x1 = int(node.box.x * width)
        y1 = int(node.box.y * height)
        x2 = int((node.box.x + node.box.width) * width)
        y2 = int((node.box.y + box_h) * height)
        return x1, y1, x2, y2

    def _draw_visual(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        accent_hex: str,
        secondary_hex: str,
    ) -> None:
        x1, y1, x2, y2 = box
        accent = self._hex_to_rgb(accent_hex)
        secondary = self._hex_to_rgb(secondary_hex)
        draw.rounded_rectangle(box, radius=max(16, (x2 - x1) // 18), fill=(*secondary, 85), outline=(*accent, 180), width=3)
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        radius = min(x2 - x1, y2 - y1) // 4
        for index in range(5):
            angle = index * math.tau / 5
            px = cx + int(math.cos(angle) * radius)
            py = cy + int(math.sin(angle) * radius)
            draw.line((cx, cy, px, py), fill=(*accent, 180), width=4)
            draw.ellipse((px - 12, py - 12, px + 12, py + 12), fill=(*accent, 220))
        draw.ellipse((cx - 28, cy - 28, cx + 28, cy + 28), fill=(*accent, 230))

    def _draw_shape(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], color_hex: str) -> None:
        color = self._hex_to_rgb(color_hex)
        draw.rounded_rectangle(box, radius=16, fill=(*color, 180))

    def _draw_text(
        self,
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        element: ElementContent,
        node: LayoutNode,
        canvas_height: int,
        state: GraphState,
    ) -> None:
        x1, y1, x2, y2 = box
        if node.style.background_color:
            bg = self._hex_to_rgb(node.style.background_color)
            radius = int((node.style.radius or 0.02) * canvas_height)
            draw.rounded_rectangle(box, radius=radius, fill=(*bg, 235))

        font_size = max(14, int((node.style.font_size or 0.026) * canvas_height))
        font, used_fallback = self._font(font_size, bold=node.style.font_weight in {"bold", "black"})
        if used_fallback and "Font fallback: using Pillow default font." not in state.warnings:
            state.warnings.append("Font fallback: using Pillow default font.")
        color = self._hex_to_rgb(node.style.color or "#FFFFFF")
        max_chars = max(4, int((x2 - x1) / max(1, font_size * 0.62)))
        lines = textwrap.wrap(element.content, width=max_chars) or [element.content]
        line_height = int(font_size * 1.18)
        total_height = line_height * len(lines)
        y = y1 + max(0, (y2 - y1 - total_height) // 2)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            if node.style.align == "center":
                x = x1 + max(0, (x2 - x1 - text_width) // 2)
            elif node.style.align == "right":
                x = x2 - text_width
            else:
                x = x1
            draw.text((x, y), line, font=font, fill=(*color, 255))
            y += line_height

    def _font(self, size: int, bold: bool = False) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
        for candidate in self._font_candidates(bold=bold):
            path = Path(candidate)
            if path.exists():
                return ImageFont.truetype(str(path), size=size), False
        return ImageFont.load_default(), True

    def _font_candidates(self, bold: bool = False) -> list[str]:
        return [
            "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]

    def _hex_to_rgb(self, value: str) -> tuple[int, int, int]:
        normalized = value.strip().lstrip("#")
        if len(normalized) != 6:
            return (255, 255, 255)
        return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))
