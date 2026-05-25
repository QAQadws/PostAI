from app.render.pillow_renderer import PillowPosterRenderer


def test_renderer_font_candidates_include_linux_paths():
    candidates = PillowPosterRenderer()._font_candidates(bold=False)
    assert any("/usr/share/fonts" in candidate for candidate in candidates)
