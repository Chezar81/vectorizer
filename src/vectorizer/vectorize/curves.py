"""Corner-aware cubic fitting (Schneider) for sub-pixel contours."""

from __future__ import annotations

import math
from typing import Sequence

Point = tuple[float, float]
Cubic = tuple[Point, Point, Point, Point]


def fit_closed_contour(points: Sequence[Point], *, tolerance: float, corner_degrees: float) -> list[Cubic]:
    """Fit a closed polyline with cubics. `points` may repeat the first point at the end."""
    ring = _dedupe(_open_ring(points))
    if len(ring) < 3:
        return []
    coarse = _douglas_peucker_closed(ring, max(1.35, tolerance * 2.0))
    if len(coarse) < 3:
        coarse = ring
    split_ids = _corner_ids(ring, coarse, corner_degrees)
    curves: list[Cubic] = []
    count = len(ring)
    for begin, end in zip(split_ids, split_ids[1:]):
        span = _slice_ring(ring, begin, end)
        curves.extend(_fit_open(span, tolerance))
    return curves


def _slice_ring(ring: Sequence[Point], begin: int, end: int) -> list[Point]:
    if end >= begin:
        return list(ring[begin : end + 1])
    return list(ring[begin:]) + list(ring[: end + 1])


def _corner_ids(ring: Sequence[Point], coarse: Sequence[Point], corner_degrees: float) -> list[int]:
    """Indices into `ring`, including a repeated end so the loop closes."""
    index_of = []
    cursor = 0
    for point in coarse:
        while not _same(ring[cursor], point):
            cursor = (cursor + 1) % len(ring)
            if cursor == 0 and not _same(ring[0], point):
                # Coarse point was produced by simplification and may not sit on a vertex.
                break
        index_of.append(cursor)
    limit = math.radians(corner_degrees)
    ids = []
    count = len(coarse)
    for i, ring_i in enumerate(index_of):
        turn = _turn(coarse[(i - 1) % count], coarse[i], coarse[(i + 1) % count])
        if turn >= limit or not ids:
            ids.append(ring_i)
    if not ids:
        ids = [0]
    if ids[-1] != ids[0]:
        ids.append(ids[0])
    else:
        ids.append(ids[0])
    # Ensure the chain walks forward around the ring once.
    ordered = [ids[0]]
    for ring_i in ids[1:]:
        if ring_i == ordered[0] and len(ordered) > 1:
            ordered.append(ring_i)
            break
        if _forward(ordered[-1], ring_i, len(ring)):
            ordered.append(ring_i)
    if ordered[-1] != ordered[0]:
        ordered.append(ordered[0])
    return ordered


def _forward(begin: int, end: int, count: int) -> bool:
    if begin == end:
        return False
    return ((end - begin) % count) <= count // 2 or True


def _douglas_peucker_closed(points: Sequence[Point], tolerance: float) -> list[Point]:
    if len(points) < 4:
        return list(points)
    start = _sharpest_corner(points, 35.0)
    rotated = list(points[start:]) + list(points[:start])
    simplified = _douglas_peucker(rotated, tolerance)
    if len(simplified) >= 2 and _same(simplified[0], simplified[-1]):
        simplified = simplified[:-1]
    return simplified


def _douglas_peucker(points: Sequence[Point], tolerance: float) -> list[Point]:
    if len(points) < 3:
        return list(points)
    worst = 0.0
    index = 0
    start, end = points[0], points[-1]
    for i in range(1, len(points) - 1):
        dist = _point_line_distance(points[i], start, end)
        if dist > worst:
            worst = dist
            index = i
    if worst <= tolerance or index == 0:
        return [points[0], points[-1]]
    left = _douglas_peucker(points[: index + 1], tolerance)
    right = _douglas_peucker(points[index:], tolerance)
    return left[:-1] + right


def _point_line_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = _hypot(dx, dy)
    if length < 1e-9:
        return _hypot(point[0] - start[0], point[1] - start[1])
    return abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0]) / length


def cubics_to_path_d(curves: Sequence[Cubic], *, decimals: int) -> str:
    if not curves:
        return ""
    places = max(0, min(4, int(decimals)))
    fmt = f"{{:.{places}f}}"

    def xy(point: Point) -> str:
        return f"{fmt.format(point[0])} {fmt.format(point[1])}"

    parts = [f"M {xy(curves[0][0])}"]
    for curve in curves:
        parts.append(f"C {xy(curve[1])} {xy(curve[2])} {xy(curve[3])}")
    parts.append("Z")
    return " ".join(parts)


def _fit_open(points: Sequence[Point], tolerance: float) -> list[Cubic]:
    pts = _dedupe(points)
    if len(pts) < 2:
        return []
    if len(pts) == 2:
        return [_line_cubic(pts[0], pts[1])]
    return _schneider(pts, tolerance, depth=0)


def _schneider(points: Sequence[Point], tolerance: float, depth: int) -> list[Cubic]:
    if len(points) == 2 or depth > 12:
        return [_line_cubic(points[0], points[-1])]
    left = _tangent(points[0], points[min(2, len(points) - 1)])
    right = _tangent(points[-1], points[max(0, len(points) - 3)])
    params = _chord_params(points)
    curve = _generate_bezier(points, params, left, right)
    error, split_at = _max_error(curve, points)
    if error <= tolerance:
        return [curve]
    if split_at <= 0 or split_at >= len(points) - 1:
        split_at = len(points) // 2
    return _schneider(points[: split_at + 1], tolerance, depth + 1) + _schneider(
        points[split_at:], tolerance, depth + 1
    )


def _generate_bezier(
    points: Sequence[Point],
    params: Sequence[float],
    tan1: Point,
    tan2: Point,
) -> Cubic:
    p0 = points[0]
    p3 = points[-1]
    c00 = c01 = c11 = 0.0
    x0 = x1 = 0.0
    for point, t in zip(points, params):
        u = 1.0 - t
        b1 = 3.0 * u * u * t
        b2 = 3.0 * u * t * t
        b0 = u * u * u
        b3 = t * t * t
        a1 = (tan1[0] * b1, tan1[1] * b1)
        a2 = (tan2[0] * b2, tan2[1] * b2)
        tmp = (
            point[0] - (p0[0] * b0 + p3[0] * b3),
            point[1] - (p0[1] * b0 + p3[1] * b3),
        )
        c00 += a1[0] * a1[0] + a1[1] * a1[1]
        c01 += a1[0] * a2[0] + a1[1] * a2[1]
        c11 += a2[0] * a2[0] + a2[1] * a2[1]
        x0 += a1[0] * tmp[0] + a1[1] * tmp[1]
        x1 += a2[0] * tmp[0] + a2[1] * tmp[1]
    det = c00 * c11 - c01 * c01
    dist = _hypot(p3[0] - p0[0], p3[1] - p0[1])
    if abs(det) < 1e-9:
        alpha1 = alpha2 = dist / 3.0
    else:
        alpha1 = (x0 * c11 - x1 * c01) / det
        alpha2 = (x1 * c00 - x0 * c01) / det
    if alpha1 < 1e-4 or alpha2 < 1e-4:
        alpha1 = alpha2 = dist / 3.0
    p1 = (p0[0] + tan1[0] * alpha1, p0[1] + tan1[1] * alpha1)
    p2 = (p3[0] + tan2[0] * alpha2, p3[1] + tan2[1] * alpha2)
    return (p0, p1, p2, p3)


def _max_error(curve: Cubic, points: Sequence[Point]) -> tuple[float, int]:
    worst = 0.0
    index = len(points) // 2
    steps = max(8, len(points))
    # Compare each polyline vertex to its nearest sample on the cubic.
    samples = [_bezier(curve, i / steps) for i in range(steps + 1)]
    for i, point in enumerate(points):
        err = min(_hypot(point[0] - s[0], point[1] - s[1]) for s in samples)
        if err > worst:
            worst = err
            index = i
    return worst, index


def _bezier(curve: Cubic, t: float) -> Point:
    u = 1.0 - t
    p0, p1, p2, p3 = curve
    return (
        u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
    )


def _chord_params(points: Sequence[Point]) -> list[float]:
    lengths = [0.0]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1] + _hypot(b[0] - a[0], b[1] - a[1]))
    total = lengths[-1] or 1.0
    return [length / total for length in lengths]


def _corner_indices(points: Sequence[Point], corner_degrees: float) -> list[int]:
    limit = math.radians(corner_degrees)
    indices = [0]
    for i in range(1, len(points) - 1):
        if _turn(points[i - 1], points[i], points[i + 1]) >= limit:
            indices.append(i)
    indices.append(len(points) - 1)
    return indices


def _sharpest_corner(ring: Sequence[Point], corner_degrees: float) -> int:
    best_i = 0
    best = -1.0
    limit = math.radians(corner_degrees)
    count = len(ring)
    for i in range(count):
        turn = _turn(ring[(i - 1) % count], ring[i], ring[(i + 1) % count])
        if turn > best:
            best = turn
            best_i = i
    if best < limit:
        return 0
    return best_i


def _turn(a: Point, b: Point, c: Point) -> float:
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = _hypot(v1[0], v1[1])
    n2 = _hypot(v2[0], v2[1])
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cos_a = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.acos(cos_a)


def _tangent(origin: Point, toward: Point) -> Point:
    dx = toward[0] - origin[0]
    dy = toward[1] - origin[1]
    length = _hypot(dx, dy)
    if length < 1e-9:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def _line_cubic(a: Point, b: Point) -> Cubic:
    p1 = (a[0] + (b[0] - a[0]) / 3.0, a[1] + (b[1] - a[1]) / 3.0)
    p2 = (a[0] + 2.0 * (b[0] - a[0]) / 3.0, a[1] + 2.0 * (b[1] - a[1]) / 3.0)
    return (a, p1, p2, b)


def _open_ring(points: Sequence[Point]) -> list[Point]:
    pts = list(points)
    if len(pts) >= 2 and _same(pts[0], pts[-1]):
        pts = pts[:-1]
    return pts


def _dedupe(points: Sequence[Point]) -> list[Point]:
    cleaned: list[Point] = []
    for point in points:
        if not cleaned or not _same(cleaned[-1], point):
            cleaned.append((float(point[0]), float(point[1])))
    return cleaned


def _same(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) < 1e-4 and abs(a[1] - b[1]) < 1e-4


def _hypot(dx: float, dy: float) -> float:
    return math.hypot(dx, dy)
