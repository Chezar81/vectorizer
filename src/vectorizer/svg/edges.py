"""Shared-edge detection for gap fillers and stroke-edge export."""

from __future__ import annotations

import math
from dataclasses import dataclass

from vectorizer.domain.document import VectorDocument, VectorPath
from vectorizer.domain.settings import normalize_hex
from vectorizer.raster.color import hex_to_rgb, rgb_to_hex


@dataclass(frozen=True)
class SharedEdge:
    """One shared boundary between two filled shapes."""

    path_a: int
    path_b: int
    color_a: str
    color_b: str
    points: tuple[tuple[float, float], ...]

    @property
    def average_color(self) -> str:
        ra, ga, ba = hex_to_rgb(self.color_a)
        rb, gb, bb = hex_to_rgb(self.color_b)
        return rgb_to_hex(((ra + rb) // 2, (ga + gb) // 2, (ba + bb) // 2))


def iter_filled_paths(document: VectorDocument) -> list[tuple[int, VectorPath, str]]:
    """Return (source_order, path, normalized fill) for filled paths."""
    out: list[tuple[int, VectorPath, str]] = []
    for group in document.groups:
        for path in group.paths:
            if path.fill is None:
                continue
            color = path.fill.color
            if not color or color.lower() == "none" or not color.startswith("#"):
                continue
            try:
                hex_color = normalize_hex(color)
            except ValueError:
                continue
            out.append((path.source_order, path, hex_color))
    out.sort(key=lambda item: item[0])
    return out


def find_shared_edges(
    document: VectorDocument,
    *,
    sample_spacing: float = 2.0,
    max_gap: float = 1.35,
    min_hits: int = 3,
) -> list[SharedEdge]:
    """Find adjacent filled paths and sample points along their shared boundaries."""
    filled = iter_filled_paths(document)
    if len(filled) < 2:
        return []

    samples: list[tuple[int, str, list[tuple[float, float]]]] = []
    for order, path, color in filled:
        points = _resample_outline(path.d, spacing=sample_spacing)
        if len(points) >= 2:
            samples.append((order, color, points))

    # Spatial hash: cell -> list of (sample_index, point_index)
    cell = max(1.0, float(max_gap))
    buckets: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for si, (_order, _color, points) in enumerate(samples):
        for pi, (x, y) in enumerate(points):
            key = (int(math.floor(x / cell)), int(math.floor(y / cell)))
            buckets.setdefault(key, []).append((si, pi))

    pair_hits: dict[tuple[int, int], list[tuple[float, float]]] = {}
    gap2 = float(max_gap) ** 2
    for si, (_order_a, color_a, points_a) in enumerate(samples):
        for pi, (x, y) in enumerate(points_a):
            gx, gy = int(math.floor(x / cell)), int(math.floor(y / cell))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for sj, pj in buckets.get((gx + dx, gy + dy), ()):
                        if sj <= si:
                            continue
                        _order_b, color_b, points_b = samples[sj]
                        if color_a == color_b:
                            continue
                        bx, by = points_b[pj]
                        dist2 = (x - bx) ** 2 + (y - by) ** 2
                        if dist2 > gap2:
                            continue
                        key = (si, sj)
                        # Midpoint sits on the shared seam.
                        pair_hits.setdefault(key, []).append(((x + bx) * 0.5, (y + by) * 0.5))

    edges: list[SharedEdge] = []
    for (si, sj), hits in pair_hits.items():
        if len(hits) < min_hits:
            continue
        ordered = _order_polyline(hits)
        if len(ordered) < 2:
            continue
        order_a, color_a, _ = samples[si]
        order_b, color_b, _ = samples[sj]
        edges.append(
            SharedEdge(
                path_a=order_a,
                path_b=order_b,
                color_a=color_a,
                color_b=color_b,
                points=tuple(ordered),
            )
        )
    return edges


def edge_to_path_d(points: tuple[tuple[float, float], ...] | list[tuple[float, float]], *, decimals: int = 2) -> str:
    if len(points) < 2:
        return ""
    places = max(0, min(4, int(decimals)))
    fmt = f"{{:.{places}f}}"

    def xy(point: tuple[float, float]) -> str:
        return f"{fmt.format(point[0])} {fmt.format(point[1])}"

    parts = [f"M {xy(points[0])}"]
    for point in points[1:]:
        parts.append(f"L {xy(point)}")
    return " ".join(parts)


def _resample_outline(d: str, *, spacing: float) -> list[tuple[float, float]]:
    # Lazy import: export.svg → edit → edges must not import export.dxf at module load.
    from vectorizer.export.dxf import sample_path_subpaths

    rings = sample_path_subpaths(d, curve_segments=8)
    out: list[tuple[float, float]] = []
    step = max(0.75, float(spacing))
    for ring, _closed in rings:
        if len(ring) < 2:
            continue
        out.extend(_resample_polyline(ring, step))
    return out


def _resample_polyline(points: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return list(points)
    out = [points[0]]
    carry = 0.0
    for start, end in zip(points, points[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            continue
        dist = spacing - carry
        while dist <= length:
            t = dist / length
            out.append((start[0] + dx * t, start[1] + dy * t))
            dist += spacing
        carry = length - (dist - spacing)
    if math.hypot(out[-1][0] - points[-1][0], out[-1][1] - points[-1][1]) > 0.25:
        out.append(points[-1])
    return out


def _order_polyline(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Greedy nearest-neighbour order so gap strokes follow the seam."""
    if len(points) <= 2:
        return list(points)
    # Deduplicate near-identical hits first.
    unique: list[tuple[float, float]] = []
    for point in points:
        if not unique or math.hypot(point[0] - unique[-1][0], point[1] - unique[-1][1]) > 0.4:
            # Also skip if close to any earlier point (spatial clutter).
            if any(math.hypot(point[0] - u[0], point[1] - u[1]) < 0.45 for u in unique):
                continue
            unique.append(point)
    if len(unique) <= 2:
        return unique
    remaining = set(range(1, len(unique)))
    order = [0]
    while remaining:
        last = unique[order[-1]]
        best = min(
            remaining,
            key=lambda i: (unique[i][0] - last[0]) ** 2 + (unique[i][1] - last[1]) ** 2,
        )
        remaining.remove(best)
        order.append(best)
    return [unique[i] for i in order]
