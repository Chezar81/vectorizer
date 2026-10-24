"""Pixel-aligned segmentation edits. All ops mutate a copy via SegmentationMap."""

from __future__ import annotations

from collections import deque

from PIL import Image, ImageDraw

from vectorizer.errors import SegmentationError
from vectorizer.segmentation.map import SegmentationMap

Color = tuple[int, int, int, int]


def _same(a: Color, b: Color) -> bool:
    return a == b


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
        return result

    pixels = result.image.load()
    assert pixels is not None
    queue: deque[tuple[int, int]] = deque([(x, y)])
    pixels[x, y] = new_color
    while queue:
        cx, cy = queue.popleft()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < width and 0 <= ny < height and pixels[nx, ny] == target:
                pixels[nx, ny] = new_color
                queue.append((nx, ny))
    return result


def _replace_color(image: Image.Image, target: Color, new_color: Color) -> Image.Image:
    """Exact RGBA replace via a flat byte scan (no nested x/y Python loops)."""
    raw = bytearray(image.tobytes())
    old = bytes(target)
    new = bytes(new_color)
    for i in range(0, len(raw), 4):
        if raw[i : i + 4] == old:
            raw[i : i + 4] = new
    return Image.frombytes("RGBA", image.size, bytes(raw))


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
        return result
    width = max(1, r * 2 + 1)
    draw.line(points, fill=color, width=width, joint="curve")
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
    return result


def remove_small_regions(map_: SegmentationMap, min_pixels: int) -> SegmentationMap:
    """Remove connected opaque components smaller than min_pixels (set alpha 0)."""
    if min_pixels <= 1:
        return map_.copy()
    result = map_.copy()
    width, height = result.size
    pixels = result.image.load()
    assert pixels is not None
    # Flat visited bitmap: far less allocation than list[list[bool]].
    visited = bytearray(width * height)

    for y in range(height):
        row = y * width
        for x in range(width):
            idx = row + x
            if visited[idx]:
                continue
            color = pixels[x, y]
            if color[3] == 0:
                visited[idx] = 1
                continue
            # DFS component of identical color.
            stack = [idx]
            visited[idx] = 1
            component: list[int] = []
            while stack:
                ci = stack.pop()
                component.append(ci)
                cx = ci % width
                cy = ci // width
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if not (0 <= nx < width and 0 <= ny < height):
                        continue
                    ni = ny * width + nx
                    if visited[ni]:
                        continue
                    if pixels[nx, ny] == color:
                        visited[ni] = 1
                        stack.append(ni)
            if len(component) < min_pixels:
                for ci in component:
                    cx = ci % width
                    cy = ci // width
                    r, g, b, _a = pixels[cx, cy]
                    pixels[cx, cy] = (r, g, b, 0)
    return result


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
