"""VTracer 0.6.x adapter. APIs verified against the installed package."""

from __future__ import annotations

import io
import os
import re
import time
from typing import Any

from PIL import Image

from vectorizer.domain.settings import TraceSettings
from vectorizer.errors import TraceError
from vectorizer.jobs.progress import STAGE_CONTOURS, STAGE_SVG, ProgressCallback
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


_SUPERSAMPLE_MAX_PIXELS = 1_200_000
_PATH_RE = re.compile(
    r'<path d="([^"]*)"([^>]*?)transform="translate\(([-\d.]+),([-\d.]+)\)"'
)
_EMPTY_PATH_RE = re.compile(r'<path d="\s*(?:M\s*-?[\d.]+,-?[\d.]+\s*Z\s*)*"[^>]*/>\s*')


def supersample_factor(image: Image.Image, settings: TraceSettings) -> int:
    """2× nearest upsample so 1 px dots and diagonal hairlines survive.

    VTracer clusters 4-connected pixels and collapses every one-pixel cluster
    to a degenerate ``M0,0 Z``; diagonal 1 px strokes and dot grids vanish.
    Doubling the grid turns each pixel into a traceable 2×2 square.
    """
    override = os.environ.get("VECTORIZER_VTRACER_SUPERSAMPLE")
    if override is not None:
        try:
            return max(1, min(4, int(override)))
        except ValueError:
            return 1
    if settings.mode.value == "pixel":
        return 1
    if image.width * image.height > _SUPERSAMPLE_MAX_PIXELS:
        return 1
    return 2


def _scaled_kwargs(kwargs: dict[str, Any], factor: int) -> dict[str, Any]:
    out = dict(kwargs)
    # filter_speckle is a side length (area = speckle²) in source pixels.
    out["filter_speckle"] = int(kwargs.get("filter_speckle", 0)) * factor
    out["length_threshold"] = float(kwargs.get("length_threshold", 4.0)) * factor
    out["splice_threshold"] = int(kwargs.get("splice_threshold", 45))
    return out


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def _compact_path_data(d: str, inv: float) -> str:
    """Scale absolute M/L/C/Z data by `inv`; straight cubics become L.

    VTracer spline output spends a full cubic on every staircase step. Qt's
    SVG parser truncates paths beyond ~32k elements (a cubic costs three), so
    a large silhouette lost most of its outline in the preview.
    """
    tokens = re.findall(r"[MLCZmlcz]|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", d)
    out: list[str] = []
    i = 0
    cmd = ""
    cx = cy = sx = sy = 0.0
    n = len(tokens)
    try:
        while i < n:
            tok = tokens[i]
            if tok.isalpha():
                cmd = tok
                i += 1
                if cmd in "Zz":
                    out.append("Z")
                    cx, cy = sx, sy
                continue
            if cmd == "M":
                cx, cy = float(tokens[i]) * inv, float(tokens[i + 1]) * inv
                sx, sy = cx, cy
                out.append(f"M{_fmt(cx)} {_fmt(cy)}")
                i += 2
                cmd = "L"
            elif cmd == "L":
                cx, cy = float(tokens[i]) * inv, float(tokens[i + 1]) * inv
                out.append(f"L{_fmt(cx)} {_fmt(cy)}")
                i += 2
            elif cmd == "C":
                x1, y1, x2, y2, x, y = (float(t) * inv for t in tokens[i : i + 6])
                i += 6
                dx, dy = x - cx, y - cy
                length_sq = dx * dx + dy * dy
                straight = False
                if length_sq > 1e-12:
                    tol = 0.02
                    cross1 = abs((x1 - cx) * dy - (y1 - cy) * dx)
                    cross2 = abs((x2 - cx) * dy - (y2 - cy) * dx)
                    length = length_sq**0.5
                    if cross1 <= tol * length and cross2 <= tol * length:
                        t1 = ((x1 - cx) * dx + (y1 - cy) * dy) / length_sq
                        t2 = ((x2 - cx) * dx + (y2 - cy) * dy) / length_sq
                        straight = -1e-6 <= t1 <= 1 + 1e-6 and -1e-6 <= t2 <= 1 + 1e-6
                if straight:
                    out.append(f"L{_fmt(x)} {_fmt(y)}")
                else:
                    out.append(
                        f"C{_fmt(x1)} {_fmt(y1)} {_fmt(x2)} {_fmt(y2)} {_fmt(x)} {_fmt(y)}"
                    )
                cx, cy = x, y
            else:
                return d
    except (IndexError, ValueError):
        return d
    return " ".join(out)


def _normalize_svg(svg_text: str, factor: int, size: tuple[int, int]) -> str:
    """Drop degenerate paths, map supersampled coordinates back, compact cubics."""
    svg_text = _EMPTY_PATH_RE.sub("", svg_text)
    inv = 1.0 / max(1, factor)

    def _path(match: re.Match[str]) -> str:
        d, middle, tx, ty = match.groups()
        return (
            f'<path d="{_compact_path_data(d, inv)}"{middle}'
            f'transform="translate({_fmt(float(tx) * inv)},{_fmt(float(ty) * inv)})"'
        )

    svg_text = _PATH_RE.sub(_path, svg_text)
    if factor > 1:
        w, h = size
        svg_text = re.sub(
            r'(<svg[^>]*?)width="\d+"', rf'\g<1>width="{w}"', svg_text, count=1
        )
        svg_text = re.sub(
            r'(<svg[^>]*?)height="\d+"', rf'\g<1>height="{h}"', svg_text, count=1
        )
    return svg_text


class VTracerBackend:
    name = "vtracer"
    description = (
        "visioncortex VTracer 0.6.x (MIT). Color clustering plus spline/polygon "
        "fitting. Stacked output overlaps shapes instead of using compound holes. "
        "No segmentation map is returned."
    )

    def trace(
        self,
        image: Image.Image,
        settings: TraceSettings,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> TraceResult:
        report = on_progress or (lambda _stage, _fraction: None)
        if _vtracer is None:
            raise TraceError(f"vtracer is not available: {_VTRACER_IMPORT_ERROR}")
        validated = settings.validated()
        if image.size[0] <= 0 or image.size[1] <= 0:
            raise TraceError("Cannot trace an empty image.")
        kwargs: dict[str, Any] = validated.to_backend_kwargs()
        started = time.perf_counter()
        # VTracer itself is opaque; park mid-range so the UI can show ETA from
        # prior jobs while the native call runs.
        report(STAGE_CONTOURS, 0.15)
        factor = supersample_factor(image, validated)
        source = image
        if factor > 1:
            source = image.convert("RGBA").resize(
                (image.width * factor, image.height * factor), Image.Resampling.NEAREST
            )
            kwargs = _scaled_kwargs(kwargs, factor)
        try:
            if hasattr(_vtracer, "convert_raw_image_to_svg"):
                svg_text = _vtracer.convert_raw_image_to_svg(
                    _image_png_bytes(source),
                    img_format="png",
                    **kwargs,
                )
            else:  # pragma: no cover - older wheels only
                svg_text = _vtracer.convert_pixels_to_svg(
                    _rgba_pixels(source),
                    source.size,
                    **kwargs,
                )
        except Exception as exc:
            raise TraceError(f"VTracer failed: {exc}") from exc
        report(STAGE_SVG, 0.85)
        elapsed = time.perf_counter() - started
        if not isinstance(svg_text, str) or "<svg" not in svg_text.lower():
            raise TraceError("VTracer did not return SVG markup.")
        svg_text = _normalize_svg(svg_text, factor, image.size)
        document = parse_svg_document(svg_text, backend_name=self.name)
        report(STAGE_SVG, 1.0)
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
