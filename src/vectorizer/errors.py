"""Application errors that can be shown to the user."""


class VectorizerError(Exception):
    """Base class for expected, user-visible failures."""


class ImageLoadError(VectorizerError):
    """The raster file could not be opened or is outside supported limits."""


class ImageOversizeError(ImageLoadError):
    """The raster exceeds the working pixel cap. A smaller side is recommended.

    The original file is not modified. Callers may reload with `max_side` set
    to `recommended_max_side` to keep a shrunk working copy.
    """

    def __init__(
        self,
        message: str,
        *,
        width: int,
        height: int,
        recommended_max_side: int,
    ) -> None:
        super().__init__(message)
        self.width = int(width)
        self.height = int(height)
        self.recommended_max_side = int(recommended_max_side)


class TraceError(VectorizerError):
    """Vectorization failed."""


class ExportError(VectorizerError):
    """Writing an export file failed."""


class SvgParseError(VectorizerError):
    """Backend SVG could not be parsed into a document."""


class JobCancelled(VectorizerError):
    """A background job was cancelled before completion."""


class ProjectError(VectorizerError):
    """Project load/save validation failed."""


class SegmentationError(VectorizerError):
    """Segmentation edit or build failed."""
