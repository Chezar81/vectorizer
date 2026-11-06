"""Gradient / smooth-tone tracer: SVG mesh-like patches from planar OKLab fits.

Photographs still posterize through VTracer. Smooth gradients become layered
linearGradient fills over region silhouettes — editable and much lighter than
thousands of flat colour islands.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace

import numpy as np
from PIL import Image

from vectorizer.domain.settings import TraceSettings, normalize_hex
from vectorizer.errors import TraceError
from vectorizer.jobs.progress import STAGE_COLORS, STAGE_CONTOURS, STAGE_CURVES, ProgressCallback
from vectorizer.raster.color import rgb_to_hex
from vectorizer.raster.palette import suggest_palettes
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.backend import TraceResult
from vectorizer.vectorize.blend_trace import BlendTracer, _drop_specks, label_regions
from vectorizer.vectorize.curves import fit_closed_contour, segments_to_path_d
from vectorizer.vectorize.iso_contour import coverage_field, marching_squares, orient_clockwise
from vectorizer.vectorize.vtracer_backend import VTracerBackend


class GradientTracer:
    name = "gradient"
    description = (
        "Smooth-tone tracer. Large planar OKLab regions become SVG linear "
        "gradients; busy remainder falls back to posterized fills."
    )

    def trace(
        self,
        image: Image.Image,
        settings: TraceSettings,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> TraceResult:
        report = on_progress or (lambda _stage, _fraction: None)
        validated = settings.validated()
        rgba = image.convert("RGBA")
        width, height = rgba.size
        if width <= 0 or height <= 0:
            raise TraceError("Cannot trace an empty image.")
        started = time.perf_counter()

        report(STAGE_COLORS, 0.05)
        ignore = None
        if validated.remove_background:
            ignore = validated.background_rgb_tuple()
        suggestions = suggest_palettes(rgba, ignore_rgb=ignore)
        # Richer stop palette for gradients; keep it bounded for editability.
        count = min(12, max(4, suggestions.best))
        if count not in suggestions.palettes:
            count = min(suggestions.palettes, key=lambda n: abs(n - count))
        palette = suggestions.palettes.get(count) or suggestions.palettes[suggestions.best]
        palette = tuple(normalize_hex(c) for c in palette)

        labels, pixels_lab, palette_lab, bg_lab = label_regions(rgba, palette, validated)
        labels = _drop_specks(labels, max(2, validated.filter_speckle))
        report(STAGE_CONTOURS, 0.20)

        gradients: list[str] = []
        paths: list[str] = []
        flat_labels = labels.copy()
        next_id = 0
        active_labels = [label for label in range(len(palette)) if np.any(labels == label)]
        total_active = max(1, len(active_labels))
        for index, label in enumerate(active_labels):
            report(STAGE_CONTOURS, 0.20 + 0.45 * (index / total_active))
            mask = labels == label
            components = _connected_components(mask)
            for component in components:
                if int(component.sum()) < max(64, (width * height) // 400):
                    continue
                fit = _fit_planar_gradient(pixels_lab, component)
                if fit is None:
                    continue
                start_rgb, end_rgb, direction = fit
                field = coverage_field(
                    labels, label, pixels_lab, palette_lab, bg_lab, blur=0.9
                )
                # Restrict the field to this component so sibling islands stay flat.
                local = np.where(component, field, 0.0)
                contours = marching_squares(local, level=0.5)
                if not contours:
                    continue
                gid = f"g{next_id}"
                next_id += 1
                x1, y1, x2, y2 = _gradient_line(component, direction)
                gradients.append(
                    _linear_gradient_def(
                        gid,
                        start_rgb,
                        end_rgb,
                        x1,
                        y1,
                        x2,
                        y2,
                        width,
                        height,
                    )
                )
                decimals = max(1, min(4, int(validated.path_precision)))
                subpaths: list[str] = []
                for contour in contours:
                    ring = orient_clockwise(contour)
                    segs = fit_closed_contour(ring, tolerance=1.1, corner_degrees=55.0)
                    path_d = segments_to_path_d(segs, decimals=decimals)
                    if path_d:
                        subpaths.append(path_d)
                if not subpaths:
                    continue
                paths.append(
                    f'<path d="{" ".join(subpaths)}" fill="url(#{gid})" fill-rule="evenodd"/>'
                )
                # Remove the component from the flat leftover so it is not double-drawn.
                flat_labels = np.where(component, -1, flat_labels)

        # Leftover non-planar islands: blend-trace as flat palette fills.
        leftover_mask = flat_labels >= 0
        warnings: list[str] = []
        if np.any(leftover_mask):
            report(STAGE_CURVES, 0.72)
            # Build a flat RGBA from leftover labels and blend-trace it.
            from vectorizer.vectorize.blend_trace import labels_to_image

            flat_image = labels_to_image(flat_labels, palette)
            try:
                flat_result = BlendTracer().trace(
                    flat_image,
                    replace(validated, remove_background=False),
                    palette,
                    soft_source=rgba,
                    label_override=flat_labels,
                    on_progress=lambda stage, frac: report(
                        stage, 0.72 + 0.22 * max(0.0, min(1.0, frac))
                    ),
                )
                # Pull path elements out of the flat SVG body.
                body = flat_result.document.raw_svg
                for line in body.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("<path "):
                        paths.append(stripped)
            except Exception as exc:
                warnings.append(f"Flat leftover pass failed ({exc}).")

        if not paths and not gradients:
            # Absolute fallback: posterize through VTracer.
            fallback = VTracerBackend().trace(rgba, validated)
            warning = "Gradient analysis found no planar regions; used the standard tracer."
            return replace(fallback, warnings=fallback.warnings + (warning,))

        defs = "\n    ".join(gradients)
        body = "\n  ".join(paths)
        defs_block = f"<defs>\n    {defs}\n  </defs>\n  " if defs else ""
        svg = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">\n  {defs_block}{body}\n</svg>\n'
        )
        document = parse_svg_document(svg, backend_name=self.name)
        elapsed = time.perf_counter() - started
        if document.path_count == 0:
            warnings.append("Gradient tracing produced no paths.")
        notes = ("Smooth regions exported as SVG linear gradients.",)
        document = replace(document, source_notes=notes)
        return TraceResult(
            document=document,
            elapsed_seconds=elapsed,
            settings=validated,
            backend_name=self.name,
            warnings=tuple(warnings),
        )


def _connected_components(mask: np.ndarray) -> list[np.ndarray]:
    """4-connected components as boolean masks.

    Labels the whole mask once, then slices by id. Faster than allocating a
    fresh boolean array per flood fill on large photos.
    """
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    current = 0
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if labels[y0, x0]:
            continue
        current += 1
        stack = [(x0, y0)]
        labels[y0, x0] = current
        while stack:
            x, y = stack.pop()
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                if labels[ny, nx] or not mask[ny, nx]:
                    continue
                labels[ny, nx] = current
                stack.append((nx, ny))
    return [labels == index for index in range(1, current + 1)]


def _fit_planar_gradient(
    pixels_lab: np.ndarray,
    mask: np.ndarray,
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[float, float]] | None:
    """Fit L ≈ a + bx + cy. Return (start_rgb, end_rgb, direction) or None."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 64:
        return None
    # Subsample large regions.
    step = max(1, len(xs) // 4000)
    xs_s = xs[::step].astype(np.float64)
    ys_s = ys[::step].astype(np.float64)
    lab = pixels_lab[ys[::step], xs[::step]].astype(np.float64)
    # Fit each OKLab channel as a plane; use L for planarity score / direction.
    ones = np.ones_like(xs_s)
    A = np.column_stack((ones, xs_s, ys_s))
    try:
        coef_l, *_ = np.linalg.lstsq(A, lab[:, 0], rcond=None)
        coef_a, *_ = np.linalg.lstsq(A, lab[:, 1], rcond=None)
        coef_b, *_ = np.linalg.lstsq(A, lab[:, 2], rcond=None)
    except np.linalg.LinAlgError:
        return None
    pred = A @ coef_l
    residual = float(np.sqrt(np.mean((lab[:, 0] - pred) ** 2)))
    # Smooth gradients stay under ~0.04 OKLab L RMSE; textured photos do not.
    if residual > 0.045:
        return None
    direction = (float(coef_l[1]), float(coef_l[2]))
    length = math.hypot(direction[0], direction[1])
    if length < 1e-6:
        return None
    # Sample ends of the plane across the bounding box projected on direction.
    unit = (direction[0] / length, direction[1] / length)
    proj = xs_s * unit[0] + ys_s * unit[1]
    t0 = float(proj.min())
    t1 = float(proj.max())
    if abs(t1 - t0) < 4.0:
        return None
    def sample_at(t: float) -> tuple[int, int, int]:
        # Point on the line through the mean of the mask.
        mx = float(xs_s.mean())
        my = float(ys_s.mean())
        base = mx * unit[0] + my * unit[1]
        x = mx + (t - base) * unit[0]
        y = my + (t - base) * unit[1]
        L = float(coef_l[0] + coef_l[1] * x + coef_l[2] * y)
        a = float(coef_a[0] + coef_a[1] * x + coef_a[2] * y)
        b = float(coef_b[0] + coef_b[1] * x + coef_b[2] * y)
        return _oklab_to_srgb_u8(L, a, b)

    return sample_at(t0), sample_at(t1), unit


def _gradient_line(
    mask: np.ndarray,
    direction: tuple[float, float],
) -> tuple[float, float, float, float]:
    ys, xs = np.nonzero(mask)
    unit = direction
    proj = xs.astype(np.float64) * unit[0] + ys.astype(np.float64) * unit[1]
    t0 = float(proj.min())
    t1 = float(proj.max())
    mx = float(xs.mean())
    my = float(ys.mean())
    base = mx * unit[0] + my * unit[1]
    x1 = mx + (t0 - base) * unit[0]
    y1 = my + (t0 - base) * unit[1]
    x2 = mx + (t1 - base) * unit[0]
    y2 = my + (t1 - base) * unit[1]
    return x1, y1, x2, y2


def _linear_gradient_def(
    gid: str,
    start_rgb: tuple[int, int, int],
    end_rgb: tuple[int, int, int],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    _width: int,
    _height: int,
) -> str:
    # userSpaceOnUse keeps stop positions aligned with the fitted plane.
    return (
        f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" '
        f'x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}">'
        f'<stop offset="0%" stop-color="{rgb_to_hex(start_rgb)}"/>'
        f'<stop offset="100%" stop-color="{rgb_to_hex(end_rgb)}"/>'
        f"</linearGradient>"
    )


def _oklab_to_srgb_u8(L: float, a: float, b: float) -> tuple[int, int, int]:
    """Inverse OKLab → sRGB uint8. Public-domain OKLab (Ottosson)."""
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    def encode(channel: float) -> int:
        channel = max(0.0, min(1.0, channel))
        if channel <= 0.0031308:
            value = 12.92 * channel
        else:
            value = 1.055 * (channel ** (1.0 / 2.4)) - 0.055
        return int(round(max(0.0, min(1.0, value)) * 255.0))

    return encode(r), encode(g), encode(bl)
