"""Trace blended artwork by placing edges from anti-alias coverage.

Hard region labels still drive the segmentation. Curve vertices then move
inside the boundary pixel by the mix between the two colors that meet there.
Output fills are exactly the chosen palette.
"""

from __future__ import annotations

import time

import numpy as np
from PIL import Image

from vectorizer.domain.settings import TraceSettings, normalize_hex
from vectorizer.errors import TraceError
from vectorizer.raster.color import (
    hex_to_rgb,
    nearest_oklab,
    project_coverage,
    rgb_to_hex,
    srgb_u8_to_oklab,
)
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.backend import TraceResult
from vectorizer.vectorize.curves import cubics_to_path_d, fit_closed_contour

_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))
_EMPTY = -1


class BlendTracer:
    name = "blend"
    description = (
        "Palette-constrained tracer. Anti-aliased edge pixels place the curve "
        "inside the pixel; fills are exactly the chosen palette colors."
    )

    def trace(
        self,
        image: Image.Image,
        settings: TraceSettings,
        palette: tuple[str, ...],
    ) -> TraceResult:
        validated = settings.validated()
        colors = tuple(normalize_hex(color) for color in palette)
        if len(colors) < 1:
            raise TraceError("Blend tracing needs at least one palette color.")
        rgba = image.convert("RGBA")
        if rgba.size[0] <= 0 or rgba.size[1] <= 0:
            raise TraceError("Cannot trace an empty image.")
        started = time.perf_counter()
        labels = label_regions(rgba, colors, validated)
        labels = _drop_specks(labels, validated.filter_speckle)
        svg = _svg_from_labels(rgba, labels, colors, validated)
        document = parse_svg_document(svg, backend_name=self.name)
        elapsed = time.perf_counter() - started
        warnings: list[str] = []
        if document.path_count == 0:
            warnings.append("Tracing produced no paths.")
        return TraceResult(
            document=document,
            elapsed_seconds=elapsed,
            settings=validated,
            backend_name=self.name,
            warnings=tuple(warnings),
        )


def label_regions(
    image: Image.Image,
    palette: tuple[str, ...],
    settings: TraceSettings,
) -> np.ndarray:
    """Return an int16 label image. -1 is transparent / removed background."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width = rgba.shape[:2]
    palette_rgb = np.asarray([hex_to_rgb(color) for color in palette], dtype=np.uint8)
    pixels_lab = srgb_u8_to_oklab(rgba[..., :3])
    palette_lab = srgb_u8_to_oklab(palette_rgb)
    index, dist = nearest_oklab(pixels_lab, palette_lab)
    labels = index.astype(np.int16)
    alpha = rgba[..., 3]
    labels[alpha < 8] = _EMPTY

    stable = (dist <= 0.0016) & (labels >= 0)
    unstable_fraction = float((~stable & (labels >= 0)).mean()) if height and width else 0.0
    if unstable_fraction <= 0.45:
        _absorb_blends(labels, stable, pixels_lab, palette_lab)

    bg = np.asarray(
        [[settings.background_r, settings.background_g, settings.background_b]],
        dtype=np.uint8,
    )
    bg_lab = srgb_u8_to_oklab(bg)[0]
    if settings.remove_background:
        limit = (max(0, settings.background_tolerance) / 255.0) ** 2 * 0.25
        delta = pixels_lab - bg_lab
        bg_dist = np.einsum("hwc,hwc->hw", delta, delta)
        closer_than_ink = bg_dist + 1e-8 < dist
        labels[(bg_dist <= max(limit, 0.004)) & closer_than_ink] = _EMPTY
    return labels


def labels_to_image(labels: np.ndarray, palette: tuple[str, ...]) -> Image.Image:
    """RGBA segmentation: palette color, or transparent where the label is empty."""
    height, width = labels.shape
    out = np.zeros((height, width, 4), dtype=np.uint8)
    colors = np.asarray([hex_to_rgb(color) for color in palette], dtype=np.uint8)
    valid = labels >= 0
    if np.any(valid):
        out[valid, :3] = colors[labels[valid]]
        out[valid, 3] = 255
    return Image.fromarray(out, mode="RGBA")


def _absorb_blends(
    labels: np.ndarray,
    stable: np.ndarray,
    pixels_lab: np.ndarray,
    palette_lab: np.ndarray,
) -> None:
    """Give mixed edge pixels the neighboring solid color they belong to."""
    height, width = labels.shape
    unstable = np.argwhere(~stable & (labels >= 0))
    if unstable.shape[0] == 0 or unstable.shape[0] > 1_500_000:
        return
    for _pass in range(3):
        changed = False
        for y, x in unstable:
            y = int(y)
            x = int(x)
            if stable[y, x]:
                continue
            best_label = int(labels[y, x])
            best_dist = 1e9
            found = False
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if not (0 <= ny < height and 0 <= nx < width):
                    continue
                if not stable[ny, nx]:
                    continue
                neighbor = int(labels[ny, nx])
                if neighbor < 0:
                    continue
                delta = pixels_lab[y, x] - palette_lab[neighbor]
                dist = float(delta @ delta)
                if dist < best_dist:
                    best_dist = dist
                    best_label = neighbor
                    found = True
            if found:
                labels[y, x] = best_label
                stable[y, x] = True
                changed = True
        if not changed:
            break


def _drop_specks(labels: np.ndarray, min_pixels: int) -> np.ndarray:
    if min_pixels <= 1:
        return labels
    height, width = labels.shape
    out = labels.copy()
    seen = np.zeros((height, width), dtype=bool)
    for y in range(height):
        for x in range(width):
            if seen[y, x] or out[y, x] < 0:
                continue
            color = int(out[y, x])
            stack = [(y, x)]
            seen[y, x] = True
            cells: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and not seen[ny, nx] and int(out[ny, nx]) == color:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(cells) >= min_pixels:
                continue
            for cy, cx in cells:
                replacement = _majority_neighbor(out, cy, cx, avoid=color)
                out[cy, cx] = replacement
    return out


def _majority_neighbor(labels: np.ndarray, y: int, x: int, *, avoid: int) -> int:
    height, width = labels.shape
    counts: dict[int, int] = {}
    for ny in range(y - 1, y + 2):
        for nx in range(x - 1, x + 2):
            if ny == y and nx == x:
                continue
            if not (0 <= ny < height and 0 <= nx < width):
                continue
            label = int(labels[ny, nx])
            if label == avoid:
                continue
            counts[label] = counts.get(label, 0) + 1
    if not counts:
        return _EMPTY
    return max(counts.items(), key=lambda item: item[1])[0]


def _svg_from_labels(
    image: Image.Image,
    labels: np.ndarray,
    palette: tuple[str, ...],
    settings: TraceSettings,
) -> str:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    pixels_lab = srgb_u8_to_oklab(rgba[..., :3])
    palette_lab = srgb_u8_to_oklab(np.asarray([hex_to_rgb(c) for c in palette], dtype=np.uint8))
    bg_lab = srgb_u8_to_oklab(
        np.asarray(
            [[settings.background_r, settings.background_g, settings.background_b]],
            dtype=np.uint8,
        )
    )[0]
    height, width = labels.shape
    decimals = max(1, min(4, int(settings.path_precision)))
    if settings.automatic_quality.value == "high":
        tolerance = 0.75
    elif settings.automatic_quality.value == "fast":
        tolerance = 1.6
    else:
        tolerance = 1.15
    corner = float(settings.corner_threshold) if settings.corner_threshold else 50.0
    parts: list[str] = []
    for label in range(len(palette)):
        mask = labels == label
        if not np.any(mask):
            continue
        subpaths: list[str] = []
        for contour in _trace_mask(mask):
            shifted = _shift_contour(
                contour,
                labels,
                label,
                rgba,
                pixels_lab,
                palette_lab,
                bg_lab,
            )
            curves = fit_closed_contour(shifted, tolerance=tolerance, corner_degrees=max(20.0, corner))
            path_d = cubics_to_path_d(curves, decimals=decimals)
            if path_d:
                subpaths.append(path_d)
        if not subpaths:
            continue
        fill = rgb_to_hex(hex_to_rgb(palette[label]))
        parts.append(
            f'<path d="{" ".join(subpaths)}" fill="{fill}" fill-rule="evenodd"/>'
        )
    body = "\n  ".join(parts)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n  {body}\n</svg>\n'
    )


def _shift_contour(
    contour: list[tuple[float, float]],
    labels: np.ndarray,
    label: int,
    rgba: np.ndarray,
    pixels_lab: np.ndarray,
    palette_lab: np.ndarray,
    bg_lab: np.ndarray,
) -> list[tuple[float, float]]:
    if len(contour) < 4:
        return contour
    shifts: list[tuple[float, float]] = []
    for start, end in zip(contour, contour[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if abs(dx) >= abs(dy):
            direction = 0 if dx >= 0 else 2
        else:
            direction = 1 if dy >= 0 else 3
        inside = _side_pixel(int(round(start[0])), int(round(start[1])), direction, right=True)
        outside = _side_pixel(int(round(start[0])), int(round(start[1])), direction, right=False)
        inward = _inward(direction)
        coverage = _edge_coverage(
            inside,
            outside,
            label,
            labels,
            rgba,
            pixels_lab,
            palette_lab,
            bg_lab,
        )
        amount = min(0.45, max(0.0, 1.0 - coverage))
        shifts.append((inward[0] * amount, inward[1] * amount))
    if not shifts:
        return contour
    shifted: list[tuple[float, float]] = []
    count = len(contour) - 1
    for i, point in enumerate(contour[:-1]):
        prev_shift = shifts[(i - 1) % count]
        here = shifts[i % count]
        shifted.append(
            (point[0] + (prev_shift[0] + here[0]) * 0.5, point[1] + (prev_shift[1] + here[1]) * 0.5)
        )
    shifted.append(shifted[0])
    return shifted


def _edge_coverage(
    inside: tuple[int, int],
    outside: tuple[int, int],
    label: int,
    labels: np.ndarray,
    rgba: np.ndarray,
    pixels_lab: np.ndarray,
    palette_lab: np.ndarray,
    bg_lab: np.ndarray,
) -> float:
    height, width = labels.shape
    ix, iy = inside
    if not (0 <= ix < width and 0 <= iy < height):
        return 1.0
    alpha = int(rgba[iy, ix, 3])
    if alpha < 8:
        return 0.0
    ink = palette_lab[label]
    ox, oy = outside
    if 0 <= ox < width and 0 <= oy < height and int(labels[oy, ox]) >= 0:
        other = palette_lab[int(labels[oy, ox])]
    else:
        other = bg_lab
        if alpha < 255:
            return alpha / 255.0
    return project_coverage(pixels_lab[iy, ix], ink, other)


def _inward(direction: int) -> tuple[float, float]:
    # Interior sits on the right of the walk, which is clockwise in y-down space.
    return ((0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 0.0))[direction]


def _side_pixel(x: int, y: int, direction: int, *, right: bool) -> tuple[int, int]:
    """Pixel beside the crack that starts at (x, y) and leaves in `direction`.

    Pixel (c, r) covers corners (c, r) .. (c+1, r+1). Interior is kept on the right.
    """
    if direction == 0:  # east
        return (x, y) if right else (x, y - 1)
    if direction == 1:  # south
        return (x - 1, y) if right else (x, y)
    if direction == 2:  # west
        return (x - 1, y - 1) if right else (x - 1, y)
    return (x, y - 1) if right else (x - 1, y - 1)  # north


def _trace_mask(mask: np.ndarray) -> list[list[tuple[float, float]]]:
    """Clockwise crack contours of a boolean mask. Points are pixel corners."""
    height, width = int(mask.shape[0]), int(mask.shape[1])
    used: set[tuple[int, int, int]] = set()
    contours: list[list[tuple[float, float]]] = []
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if y > 0 and bool(mask[y - 1, x]):
            continue
        if (x, y, 0) in used:
            continue
        contour = _walk(mask, x, y, used)
        if len(contour) >= 4:
            contours.append(contour)
    return contours


def _walk(
    mask: np.ndarray,
    sx: int,
    sy: int,
    used: set[tuple[int, int, int]],
) -> list[tuple[float, float]]:
    height, width = int(mask.shape[0]), int(mask.shape[1])
    x, y, direction = sx, sy, 0
    points = [(float(x), float(y))]
    start = (x, y, direction)
    limit = (height + 1) * (width + 1) * 4
    for _step in range(limit):
        moved = False
        for turn in (1, 0, 3, 2):
            new_dir = (direction + turn) % 4
            right = _side_pixel(x, y, new_dir, right=True)
            left = _side_pixel(x, y, new_dir, right=False)
            if not _inside(mask, right, width, height) or _inside(mask, left, width, height):
                continue
            key = (x, y, new_dir)
            if key == start and len(points) > 2:
                points.append((float(sx), float(sy)))
                return points
            if key in used:
                return points
            used.add(key)
            x += _DIRS[new_dir][0]
            y += _DIRS[new_dir][1]
            direction = new_dir
            points.append((float(x), float(y)))
            moved = True
            break
        if not moved or (x, y, direction) == start:
            break
    if points[0] != points[-1]:
        points.append(points[0])
    return points


def _inside(mask: np.ndarray, pixel: tuple[int, int], width: int, height: int) -> bool:
    x, y = pixel
    if not (0 <= x < width and 0 <= y < height):
        return False
    return bool(mask[y, x])

