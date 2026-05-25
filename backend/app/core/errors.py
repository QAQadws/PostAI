class PostAIError(Exception):
    """Base application error."""


class LLMCallError(PostAIError):
    """Raised when a text model call fails."""


class SchemaParseError(PostAIError):
    """Raised when structured model output is invalid."""


class VisionCallError(PostAIError):
    """Raised when a vision model call fails."""


class RenderError(PostAIError):
    """Raised when rendering fails."""

