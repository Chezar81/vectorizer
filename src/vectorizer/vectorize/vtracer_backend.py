"""VTracer 0.6.x adapter. APIs verified against the installed package."""

from __future__ import annotations

import io
import time
from typing import Any

from PIL import Image

from vectorizer.domain.settings import TraceSettings
from vectorizer.errors import TraceError
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.backend import TraceResult

_VTRACER_IMPORT_ERROR: str | None
try:
    import vtracer as _vtracer
except Exception as exc:  # pragma: no cover - environment-specific
    _vtracer = None
    _VTRACER_IMPORT_ERROR = str(exc)
else:
    _VTRACER_IMPORT_ERROR = None


def _image_png_bytes(image: Image.Image) -> bytes:
    """Encode RGBA as a fast PNG for VTracer's raw-bytes path.

    Avoids materializing a W×H list of Python tuples via convert_pixels_to_svg,
    which dominates RAM and CPU on multi-megapixel images.
    """
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    buffer = io.BytesIO()
    # compress_level=1 is much faster than the default 6 and still tiny vs a
    # pixel-tuple list (often tens of MB for the same image).
    rgba.save(buffer, format="PNG", compress_level=1, optimize=False)
    return buffer.getvalue()


def _rgba_pixels(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Fallback pixel list for older VTracer builds without the raw API."""
    rgba = image.convert("RGBA")
    if hasattr(rgba, "get_flattened_data"):
        return list(rgba.get_flattened_data())
    return list(rgba.getdata())


class VTracerBackend:
    name = "vtracer"
    description = (
        "visioncortex VTracer 0.6.x (MIT). Color clustering plus spline/polygon "
        "fitting. Stacked output overlaps shapes instead of using compound holes. "
        "No segmentation map is returned."
    )

    def trace(self, image: Image.Image, settings: TraceSettings) -> TraceResult:
        if _vtracer is None:
            raise TraceError(f"vtracer is not available: {_VTRACER_IMPORT_ERROR}")
        validated = settings.validated()
        if image.size[0] <= 0 or image.size[1] <= 0:
            raise TraceError("Cannot trace an empty image.")
        kwargs: dict[str, Any] = validated.to_backend_kwargs()
        started = time.perf_counter()
        try:
            if hasattr(_vtracer, "convert_raw_image_to_svg"):
                svg_text = _vtracer.convert_raw_image_to_svg(
                    _image_png_bytes(image),
                    img_format="png",
                    **kwargs,
                )
            else:  # pragma: no cover - older wheels only
                svg_text = _vtracer.convert_pixels_to_svg(
                    _rgba_pixels(image),
                    image.size,
                    **kwargs,
                )
        except Exception as exc:
            raise TraceError(f"VTracer failed: {exc}") from exc
        elapsed = time.perf_counter() - started
        if not isinstance(svg_text, str) or "<svg" not in svg_text.lower():
            raise TraceError("VTracer did not return SVG markup.")
        document = parse_svg_document(svg_text, backend_name=self.name)
        warnings: list[str] = []
        if validated.colormode.value == "color" and document.path_count == 0:
            warnings.append("Tracing produced no paths.")
        if image.mode == "RGBA":
            extrema = image.getchannel("A").getextrema()
            if extrema and extrema[0] < 255:
                warnings.append(
                    "The source has transparency. VTracer 0.6.x does not expose a "
                    "dedicated alpha-preserve switch; transparent pixels are traced "
                    "as they appear in the RGBA buffer."
                )
        return TraceResult(
            document=document,
            elapsed_seconds=elapsed,
            settings=validated,
            backend_name=self.name,
            warnings=tuple(warnings),
        )
