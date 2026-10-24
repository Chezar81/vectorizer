"""Application errors that can be shown to the user."""


class VectorizerError(Exception):
    """Base class for expected, user-visible failures."""


class ImageLoadError(VectorizerError):
    """The raster file could not be opened or is outside supported limits."""


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
