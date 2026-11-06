"""Pixel-aligned segmentation edits. All ops mutate a copy via SegmentationMap."""

from __future__ import annotations

from collections import deque

import numpy as np
from PIL import Image, ImageDraw

from vectorizer.errors import SegmentationError
from vectorizer.segmentation.map import SegmentationMap

Color = tuple[int, int, int, int]


def _same(a: Color, b: Color) -> bool:
    return a == b


def _finalize_edit(original: SegmentationMap, result: SegmentationMap) -> SegmentationMap:
    """Freeze soft-source AA cues on every pixel the edit changed."""
    if result.soft_source is not None:
        result.harden_soft_where_changed(original.image)
    return result


def flood_fill(
    map_: SegmentationMap,
    x: int,
    y: int,
    new_color: Color,
    *,
    contiguous: bool = True,
) -> SegmentationMap:
    """Flood-fill the region under (x, y). Returns a new map."""
    result = map_.copy()
    width, height = result.size
    if not (0 <= x < width and 0 <= y < height):
        raise SegmentationError("Flood fill seed is outside the image.")
    target = result.pixel(x, y)
    if _same(target, new_color):
        return result
    if not contiguous:
        result.image = _replace_color(result.image, target, new_color)
        return _finalize_edit(map_, result)

    arr = np.asarray(result.image, dtype=np.uint8).copy()
    packed = arr.view(np.uint32).reshape(height, width)
    old = np.asarray(target, dtype=np.uint8).view(np.uint32)[0]
    new = np.asarray(new_color, dtype=np.uint8).view(np.uint32)[0]
    if packed[y, x] != old:
        return result
    # Scanline fill: one seed per run instead of four neighbors per pixel.
    queue: deque[tuple[int, int]] = deque([(x, y)])
    while queue:
        cx, cy = queue.popleft()
        if not (0 <= cy < height and 0 <= cx < width) or packed[cy, cx] != old:
            continue
        left = cx
        while left > 0 and packed[cy, left - 1] == old:
            left -= 1
        right = left
        span_above = span_below = False
        while right < width and packed[cy, right] == old:
            packed[cy, right] = new
            if cy > 0:
                above = packed[cy - 1, right] == old
                if above and not span_above:
                    queue.append((right, cy - 1))
                    span_above = True
                elif not above:
                    span_above = False
            if cy + 1 < height:
                below = packed[cy + 1, right] == old
                if below and not span_below:
                    queue.append((right, cy + 1))
                    span_below = True
                elif not below:
                    span_below = False
            right += 1
    result.image = Image.fromarray(arr, mode="RGBA")
    return _finalize_edit(map_, result)


def _replace_color(image: Image.Image, target: Color, new_color: Color) -> Image.Image:
    """Exact RGBA replace via a packed uint32 mask."""
    arr = np.asarray(image, dtype=np.uint8).copy()
    packed = arr.view(np.uint32).reshape(arr.shape[0], arr.shape[1])
    old = np.asarray(target, dtype=np.uint8).view(np.uint32)[0]
    new = np.asarray(new_color, dtype=np.uint8).view(np.uint32)[0]
    packed[packed == old] = new
    return Image.fromarray(arr, mode="RGBA")


def recolor_region(map_: SegmentationMap, x: int, y: int, new_color: Color) -> SegmentationMap:
    """Alias for contiguous flood fill (region recoloring)."""
    return flood_fill(map_, x, y, new_color, contiguous=True)


def brush_stroke(
    map_: SegmentationMap,
    points: list[tuple[int, int]],
    color: Color,
    *,
    radius: int = 1,
) -> SegmentationMap:
    """Paint a polyline brush stroke in pixel space."""
    if not points:
        return map_.copy()
    result = map_.copy()
    draw = ImageDraw.Draw(result.image)
    r = max(0, int(radius))
    if len(points) == 1:
        x, y = points[0]
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
        return _finalize_edit(map_, result)
    width = max(1, r * 2 + 1)
    draw.line(points, fill=color, width=width, joint="curve")
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
    return _finalize_edit(map_, result)


def remove_small_regions(map_: SegmentationMap, min_pixels: int) -> SegmentationMap:
    """Remove connected opaque components smaller than min_pixels (set alpha 0)."""
    if min_pixels <= 1:
        return map_.copy()
    result = map_.copy()
    arr = np.array(result.image, dtype=np.uint8, copy=True)
    height, width = arr.shape[:2]
    # Pack RGBA into native uint32 so equality checks stay scalar-fast.
    packed = arr.view(np.uint32).reshape(height, width)
    flat = packed.ravel()
    # Alpha is not contiguous in HxWx4; keep a flat copy for the seen mask and
    # write clears back through 2D indexing so the image buffer is updated.
    alpha = np.ascontiguousarray(arr[..., 3])
    seen = (alpha == 0).ravel()
    # Only walk opaque pixels; large keepers stop collecting once past the threshold.
    for start in np.flatnonzero(~seen):
        start_i = int(start)
        if seen[start_i]:
            continue
        color = flat[start_i]
        stack = [start_i]
        seen[start_i] = True
        component: list[int] = [start_i]
        keep = False
        while stack:
            ci = stack.pop()
            cx = ci % width
            cy = ci // width
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                ni = ny * width + nx
                if seen[ni] or flat[ni] != color:
                    continue
                seen[ni] = True
                stack.append(ni)
                if keep:
                    continue
                component.append(ni)
                if len(component) >= min_pixels:
                    keep = True
                    component.clear()
        if not keep and component:
            ys, xs = np.divmod(np.asarray(component, dtype=np.intp), width)
            alpha[ys, xs] = 0
    arr[..., 3] = alpha
    result.image = Image.fromarray(arr, mode="RGBA")
    return _finalize_edit(map_, result)


def join_with_stroke(
    map_: SegmentationMap,
    points: list[tuple[int, int]],
    color: Color,
    *,
    radius: int = 1,
) -> SegmentationMap:
    """Connect separated regions by painting a bridge of `color`."""
    return brush_stroke(map_, points, color, radius=radius)


def separate_with_stroke(
    map_: SegmentationMap,
    points: list[tuple[int, int]],
    *,
    radius: int = 1,
) -> SegmentationMap:
    """Cut accidentally connected regions by painting transparent pixels."""
    return brush_stroke(map_, points, (0, 0, 0, 0), radius=radius)


def pick_color(map_: SegmentationMap, x: int, y: int) -> Color:
    return map_.pixel(x, y)


def zap_fringes(map_: SegmentationMap, *, max_pixels: int = 48) -> SegmentationMap:
    """Split thin leftover regions and merge each pixel into a neighboring color.

    Anti-aliased fringe is a small component sitting between two real colors.
    Deleting it would punch a hole. Zap assigns every pixel to the neighboring
    color that already surrounds it.
    """
    result = map_.copy()
    arr = np.asarray(result.image, dtype=np.uint8).copy()
    height, width = arr.shape[:2]
    packed = arr.view(np.uint32).reshape(height, width)
    flat = packed.ravel()
    alpha = np.ascontiguousarray(arr[..., 3])
    seen = (alpha == 0).ravel()
    for start in np.flatnonzero(~seen):
        start_i = int(start)
        if seen[start_i]:
            continue
        color = flat[start_i]
        stack = [start_i]
        seen[start_i] = True
        component: list[int] = [start_i]
        oversized = False
        while stack:
            ci = stack.pop()
            cx = ci % width
            cy = ci // width
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                ni = ny * width + nx
                if seen[ni] or flat[ni] != color:
                    continue
                seen[ni] = True
                stack.append(ni)
                if oversized:
                    continue
                component.append(ni)
                if len(component) > max_pixels:
                    oversized = True
                    component.clear()
        if oversized or not component:
            continue
        if not _is_fringe_packed(flat, component, width, height, color):
            continue
        for ci in component:
            cx = ci % width
            cy = ci // width
            flat[ci] = _neighbor_color_packed(
                flat, alpha.ravel(), cx, cy, width, height, avoid=int(color)
            )
    result.image = Image.fromarray(arr, mode="RGBA")
    return _finalize_edit(map_, result)


def find_problems(map_: SegmentationMap) -> list[tuple[int, int, str]]:
    """Mark one-pixel pinches and one-pixel gaps between the same color."""
    arr = np.asarray(map_.image, dtype=np.uint8)
    height, width = arr.shape[:2]
    if height < 3 or width < 3:
        return []
    packed = arr.view(np.uint32).reshape(height, width)
    alpha = arr[..., 3]
    center = packed[1:-1, 1:-1]
    left = packed[1:-1, :-2]
    right = packed[1:-1, 2:]
    up = packed[:-2, 1:-1]
    down = packed[2:, 1:-1]
    a_c = alpha[1:-1, 1:-1]
    a_left = alpha[1:-1, :-2]
    a_up = alpha[:-2, 1:-1]

    transparent = a_c == 0
    gap_h = transparent & (a_left > 0) & (left == right) & (left != center)
    gap_v = transparent & (a_up > 0) & (up == down) & (up != center)

    opaque = a_c > 0
    pinch_h = opaque & (left != center) & (right != center) & (up == center) & (down == center)
    pinch_v = opaque & (up != center) & (down != center) & (left == center) & (right == center)

    found: list[tuple[int, int, str]] = []
    for kind, mask in (
        ("gap", gap_h | gap_v),
        ("pinch", pinch_h | pinch_v),
    ):
        ys, xs = np.nonzero(mask)
        for y, x in zip(ys.tolist(), xs.tolist()):
            found.append((x + 1, y + 1, kind))
    return found


def _is_fringe_packed(
    flat: np.ndarray,
    component: list[int],
    width: int,
    height: int,
    color: np.uint32 | int,
) -> bool:
    if len(component) <= 12:
        return True
    # Thin: most pixels have a neighbor of a different color.
    touched = 0
    for ci in component:
        cx = ci % width
        cy = ci // width
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < width and 0 <= ny < height and flat[ny * width + nx] != color:
                touched += 1
                break
    return touched >= max(1, int(len(component) * 0.65))


def _neighbor_color_packed(
    flat: np.ndarray,
    alpha_flat: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    avoid: int,
) -> int:
    counts: dict[int, int] = {}
    for ny in range(y - 1, y + 2):
        for nx in range(x - 1, x + 2):
            if nx == x and ny == y:
                continue
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            ni = ny * width + nx
            if alpha_flat[ni] == 0:
                continue
            color = int(flat[ni])
            if color == avoid:
                continue
            counts[color] = counts.get(color, 0) + 1
    if not counts:
        # Clear alpha while keeping the avoided RGB (via the RGBA buffer).
        rgba = np.asarray([avoid], dtype=np.uint32).view(np.uint8).reshape(4)
        rgba[3] = 0
        return int(np.asarray(rgba, dtype=np.uint8).view(np.uint32)[0])
    return max(counts.items(), key=lambda item: item[1])[0]
