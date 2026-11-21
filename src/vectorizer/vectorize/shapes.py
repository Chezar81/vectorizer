"""Detect parameterized primitives (circle, axis-aligned rectangle) from rings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

Point = tuple[float, float]


@dataclass(frozen=True)
class CircleShape:
    cx: float
    cy: float
    radius: float

    def to_svg(self, *, fill: str, decimals: int = 3) -> str:
        places = max(0, min(4, int(decimals)))
        fmt = f"{{:.{places}f}}"
        return (
            f'<circle cx="{fmt.format(self.cx)}" cy="{fmt.format(self.cy)}" '
            f'r="{fmt.format(self.radius)}" fill="{fill}"/>'
        )

    def to_path_d(self, *, decimals: int = 3) -> str:
        """Two half-arcs — keeps path-only pipelines working."""
        places = max(0, min(4, int(decimals)))
        fmt = f"{{:.{places}f}}"
        x0 = self.cx - self.radius
        x1 = self.cx + self.radius
        y = self.cy
        r = fmt.format(self.radius)
        return (
            f"M {fmt.format(x0)} {fmt.format(y)} "
            f"A {r} {r} 0 0 1 {fmt.format(x1)} {fmt.format(y)} "
            f"A {r} {r} 0 0 1 {fmt.format(x0)} {fmt.format(y)} Z"
        )


@dataclass(frozen=True)
class RectShape:
    x: float
    y: float
    width: float
    height: float

    def to_svg(self, *, fill: str, decimals: int = 3) -> str:
        places = max(0, min(4, int(decimals)))
        fmt = f"{{:.{places}f}}"
        return (
            f'<rect x="{fmt.format(self.x)}" y="{fmt.format(self.y)}" '
            f'width="{fmt.format(self.width)}" height="{fmt.format(self.height)}" '
            f'fill="{fill}"/>'
        )

    def to_path_d(self, *, decimals: int = 3) -> str:
        places = max(0, min(4, int(decimals)))
        fmt = f"{{:.{places}f}}"
        x0, y0 = self.x, self.y
        x1, y1 = self.x + self.width, self.y + self.height
        return (
            f"M {fmt.format(x0)} {fmt.format(y0)} "
            f"L {fmt.format(x1)} {fmt.format(y0)} "
            f"L {fmt.format(x1)} {fmt.format(y1)} "
            f"L {fmt.format(x0)} {fmt.format(y1)} Z"
        )


ParameterizedShape = CircleShape | RectShape


def try_parameterized_shape(
    points: Sequence[Point],
    *,
    tolerance: float,
) -> ParameterizedShape | None:
    """Return a circle or axis-aligned rectangle when the ring fits cleanly."""
    ring = _open_ring(points)
    if len(ring) < 4:
        return None
    circle = _fit_circle_shape(ring, tolerance)
    rect = _fit_rect_shape(ring, tolerance)
    if circle is None:
        return rect
    if rect is None:
        return circle
    # Prefer the tighter residual.
    c_err = _circle_error(ring, circle)
    r_err = _rect_error(ring, rect)
    return circle if c_err <= r_err else rect


def _fit_circle_shape(ring: list[Point], tolerance: float) -> CircleShape | None:
    centre, radius = _fit_circle(ring)
    if centre is None or radius < 1.5:
        return None
    limit = max(0.35, float(tolerance) * 0.45)
    for point in ring:
        if abs(math.hypot(point[0] - centre[0], point[1] - centre[1]) - radius) > limit:
            return None
    poly_area = abs(_shoelace(ring))
    disk = math.pi * radius * radius
    if disk < 1.0 or poly_area / disk < 0.82:
        return None
    return CircleShape(cx=centre[0], cy=centre[1], radius=radius)


def _fit_rect_shape(ring: list[Point], tolerance: float) -> RectShape | None:
    # Corners via coarse Douglas–Peucker; need exactly four.
    corners = _douglas_peucker_closed(ring, max(0.8, float(tolerance)))
    if len(corners) != 4:
        # Try a slightly looser / tighter pass.
        for eps in (tolerance * 0.6, tolerance * 1.4, 1.5, 2.5):
            corners = _douglas_peucker_closed(ring, max(0.5, float(eps)))
            if len(corners) == 4:
                break
        else:
            return None
    # Axis-aligned: each edge nearly horizontal or vertical.
    for a, b in zip(corners, corners[1:] + corners[:1]):
        dx = abs(b[0] - a[0])
        dy = abs(b[1] - a[1])
        length = math.hypot(dx, dy)
        if length < 1.0:
            return None
        # Allow a few degrees of tilt.
        if min(dx, dy) / length > 0.08:
            return None
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    width = x1 - x0
    height = y1 - y0
    if width < 1.5 or height < 1.5:
        return None
    # Opposite sides should be comparable (already AA, so just area sanity).
    limit = max(0.45, float(tolerance) * 0.9)
    for point in ring:
        dist = min(abs(point[0] - x0), abs(point[0] - x1), abs(point[1] - y0), abs(point[1] - y1))
        # Interior points of a filled rect ring should sit on the boundary.
        inside_x = x0 - limit <= point[0] <= x1 + limit
        inside_y = y0 - limit <= point[1] <= y1 + limit
        if not (inside_x and inside_y):
            return None
        on_v = abs(point[0] - x0) <= limit or abs(point[0] - x1) <= limit
        on_h = abs(point[1] - y0) <= limit or abs(point[1] - y1) <= limit
        if not (on_v or on_h):
            # Allow mild corner chamfer only when both coords are near a corner.
            near_corner = (
                (abs(point[0] - x0) <= limit * 2 or abs(point[0] - x1) <= limit * 2)
                and (abs(point[1] - y0) <= limit * 2 or abs(point[1] - y1) <= limit * 2)
            )
            if not near_corner and dist > limit:
                return None
    poly_area = abs(_shoelace(ring))
    box = width * height
    if box < 1.0 or poly_area / box < 0.88:
        return None
    return RectShape(x=x0, y=y0, width=width, height=height)


def _circle_error(ring: list[Point], shape: CircleShape) -> float:
    return sum(
        abs(math.hypot(p[0] - shape.cx, p[1] - shape.cy) - shape.radius) for p in ring
    ) / len(ring)


def _rect_error(ring: list[Point], shape: RectShape) -> float:
    x0, y0 = shape.x, shape.y
    x1, y1 = shape.x + shape.width, shape.y + shape.height
    total = 0.0
    for point in ring:
        total += min(
            abs(point[0] - x0),
            abs(point[0] - x1),
            abs(point[1] - y0),
            abs(point[1] - y1),
        )
    return total / len(ring)


def _open_ring(points: Sequence[Point]) -> list[Point]:
    ring = [(float(x), float(y)) for x, y in points]
    if len(ring) >= 2 and _same(ring[0], ring[-1]):
        ring = ring[:-1]
    # Deduplicate consecutive points.
    out: list[Point] = []
    for point in ring:
        if not out or not _same(out[-1], point):
            out.append(point)
    return out


def _same(a: Point, b: Point, eps: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) <= eps and abs(a[1] - b[1]) <= eps


def _shoelace(ring: list[Point]) -> float:
    area = 0.0
    for a, b in zip(ring, ring[1:] + ring[:1]):
        area += a[0] * b[1] - b[0] * a[1]
    return area * 0.5


def _fit_circle(points: list[Point]) -> tuple[Point | None, float]:
    """Algebraic circle fit (Kåsa). Returns (centre, radius) or (None, 0)."""
    if len(points) < 3:
        return None, 0.0
    sx = sy = sxx = syy = sxy = sx3 = sy3 = 0.0
    for x, y in points:
        sx += x
        sy += y
        sxx += x * x
        syy += y * y
        sxy += x * y
        sx3 += x * (x * x + y * y)
        sy3 += y * (x * x + y * y)
    n = float(len(points))
    a = n * sxx - sx * sx
    b = n * sxy - sx * sy
    c = n * syy - sy * sy
    d = 0.5 * (n * sx3 - sx * (sxx + syy))
    e = 0.5 * (n * sy3 - sy * (sxx + syy))
    det = a * c - b * b
    if abs(det) < 1e-9:
        return None, 0.0
    cx = (d * c - b * e) / det
    cy = (a * e - b * d) / det
    radius = math.sqrt(
        max(0.0, (sxx + syy) / n - 2.0 * (cx * sx + cy * sy) / n + cx * cx + cy * cy)
    )
    return (cx, cy), radius


def _douglas_peucker_closed(points: list[Point], epsilon: float) -> list[Point]:
    if len(points) < 3:
        return list(points)
    # Rotate so we start at an extreme point (more stable corners).
    start = min(range(len(points)), key=lambda i: (points[i][0], points[i][1]))
    ring = points[start:] + points[:start]
    simplified = _douglas_peucker(ring + [ring[0]], epsilon)
    if len(simplified) >= 2 and _same(simplified[0], simplified[-1]):
        simplified = simplified[:-1]
    return simplified


def _douglas_peucker(points: list[Point], epsilon: float) -> list[Point]:
    if len(points) < 3:
        return list(points)
    start, end = points[0], points[-1]
    index = 0
    max_dist = 0.0
    for i in range(1, len(points) - 1):
        dist = _point_line_distance(points[i], start, end)
        if dist > max_dist:
            index = i
            max_dist = dist
    if max_dist > epsilon:
        left = _douglas_peucker(points[: index + 1], epsilon)
        right = _douglas_peucker(points[index:], epsilon)
        return left[:-1] + right
    return [start, end]


def _point_line_distance(point: Point, start: Point, end: Point) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    return abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0]) / length
