"""Corner-aware cubic fitting (Schneider) with circular-arc emission."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, Union

Point = tuple[float, float]
Cubic = tuple[Point, Point, Point, Point]


@dataclass(frozen=True)
class ArcSegment:
    """SVG elliptical arc from `start` to `end` (radii equal for circular arcs)."""

    start: Point
    end: Point
    radius: float
    large_arc: bool
    sweep: bool  # True = clockwise in SVG y-down space


PathSegment = Union[Cubic, ArcSegment]


def simplify_closed_ring(
    points: Sequence[Point], *, epsilon: float
) -> list[Point]:
    """Corner-preserving Douglas–Peucker on a closed ring (public helper)."""
    ring = _dedupe(_open_ring(points))
    if len(ring) < 3:
        return list(ring)
    return _douglas_peucker_closed(ring, max(0.25, float(epsilon)))


def fit_closed_contour(
    points: Sequence[Point], *, tolerance: float, corner_degrees: float
) -> list[PathSegment]:
    """Fit a closed polyline with cubics and circular arcs when they win."""
    ring = _dedupe(_open_ring(points))
    if len(ring) < 3:
        return []
    # Crack contours on megapixel art can be tens of thousands of points. Prefer
    # a corner-preserving Douglas–Peucker pass over uniform stride so diagonals
    # and sharp corners survive before the cubic fitter runs.
    ring = _preprocess_ring(ring, tolerance)
    # Whole-ring circular fit first — logos with round badges emit a single A.
    full = list(ring) + [ring[0]]
    closed_arc = _fit_arc_span(full, tolerance, closed=True)
    if closed_arc is not None:
        return list(closed_arc)
    coarse = _douglas_peucker_closed(ring, max(1.35, tolerance * 2.0))
    if len(coarse) < 3:
        coarse = ring
    split_ids = _corner_ids(ring, coarse, corner_degrees)
    corners = split_ids[:-1]
    # Smooth silhouettes (circles, ovals) may have no corner above the
    # threshold. Fit the whole ring as one open span that closes on itself.
    if len(corners) < 2:
        start = corners[0] if corners else 0
        span = list(ring[start:]) + list(ring[: start + 1])
        return _fit_span(span, tolerance)
    segments: list[PathSegment] = []
    for begin, end in zip(split_ids, split_ids[1:]):
        span = _slice_ring(ring, begin, end)
        segments.extend(_fit_span(span, tolerance))
    return segments


def _fit_span(points: Sequence[Point], tolerance: float) -> list[PathSegment]:
    # Prefer a true straight segment when the polyline hugs a chord — walls,
    # table edges, and picture frames stay crisp instead of wavy cubics.
    straight = _fit_straight_span(points, tolerance)
    if straight is not None:
        return [straight]
    arc = _fit_arc_span(points, tolerance, closed=False)
    if arc is not None:
        return list(arc)
    return list(_fit_open(points, tolerance))


def _fit_straight_span(points: Sequence[Point], tolerance: float) -> Cubic | None:
    """Return a line cubic when every sample stays within `tolerance` of the chord."""
    pts = _dedupe(points)
    if len(pts) < 2:
        return None
    start, end = pts[0], pts[-1]
    limit = max(0.35, float(tolerance) * 0.85)
    for point in pts[1:-1]:
        if _point_line_distance(point, start, end) > limit:
            return None
    # Reject near-zero chords; the cubic fitter handles degenerates better.
    if _hypot(end[0] - start[0], end[1] - start[1]) < 0.75:
        return None
    return _line_cubic(start, end)


def _preprocess_ring(ring: Sequence[Point], tolerance: float) -> list[Point]:
    count = len(ring)
    if count <= 2200:
        return list(ring)
    # First pass: keep geometry within ~half a pixel of the crack polyline.
    simplified = _douglas_peucker_closed(ring, max(0.35, tolerance * 0.45))
    if len(simplified) > 2200:
        # Extreme contours: Visvalingam-style area cull after the DP pass.
        simplified = _area_decimate_closed(simplified, max_points=2200)
    # Schneider only checks error at samples; long DP chords left the cubic
    # free to bulge 2–3 px between sparse vertices.
    return _densify_closed(_dedupe(simplified), spacing=2.0)


def _densify_closed(ring: Sequence[Point], *, spacing: float) -> list[Point]:
    out: list[Point] = []
    count = len(ring)
    for i in range(count):
        a = ring[i]
        b = ring[(i + 1) % count]
        out.append(a)
        steps = int(_hypot(b[0] - a[0], b[1] - a[1]) // spacing)
        for k in range(1, steps + 1):
            t = k / float(steps + 1)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _area_decimate_closed(ring: Sequence[Point], *, max_points: int) -> list[Point]:
    pts = list(ring)
    if len(pts) <= max_points:
        return pts
    # Iteratively drop the vertex whose removal changes the least area.
    while len(pts) > max_points and len(pts) > 3:
        best_i = 1
        best_area = float("inf")
        count = len(pts)
        for i in range(count):
            area = abs(_tri_area(pts[(i - 1) % count], pts[i], pts[(i + 1) % count]))
            if area < best_area:
                best_area = area
                best_i = i
        pts.pop(best_i)
    return _dedupe(pts)


def _tri_area(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _stride_decimate_closed(ring: Sequence[Point], *, max_points: int) -> list[Point]:
    """Legacy uniform stride. Kept for tests / call sites that still import it."""
    count = len(ring)
    if count <= max_points:
        return list(ring)
    step = count / float(max_points)
    reduced = [ring[min(count - 1, int(i * step))] for i in range(max_points)]
    return _dedupe(reduced)


def _slice_ring(ring: Sequence[Point], begin: int, end: int) -> list[Point]:
    if end >= begin:
        return list(ring[begin : end + 1])
    return list(ring[begin:]) + list(ring[: end + 1])


def _corner_ids(ring: Sequence[Point], coarse: Sequence[Point], corner_degrees: float) -> list[int]:
    """Indices into `ring`, including a repeated end so the loop closes."""
    index_of: list[int] = []
    cursor = 0
    ring_count = len(ring)
    for point in coarse:
        matched = False
        for _ in range(ring_count):
            if _same(ring[cursor], point):
                matched = True
                break
            cursor = (cursor + 1) % ring_count
        if not matched:
            # Douglas–Peucker can invent vertices; snap to the nearest ring point.
            cursor = _nearest_ring_index(ring, point)
        index_of.append(cursor)
        cursor = (cursor + 1) % ring_count
    limit = math.radians(corner_degrees)
    ids: list[int] = []
    count = len(coarse)
    for i, ring_i in enumerate(index_of):
        turn = _turn(coarse[(i - 1) % count], coarse[i], coarse[(i + 1) % count])
        if turn >= limit or not ids:
            ids.append(ring_i)
    if not ids:
        ids = [0]
    # Ensure the chain walks forward around the ring once, then closes.
    ordered = [ids[0]]
    for ring_i in ids[1:]:
        if ring_i == ordered[0]:
            break
        if _forward(ordered[-1], ring_i, ring_count):
            ordered.append(ring_i)
    ordered.append(ordered[0])
    return ordered


def _nearest_ring_index(ring: Sequence[Point], point: Point) -> int:
    best_i = 0
    best = float("inf")
    for i, candidate in enumerate(ring):
        dist = _hypot(candidate[0] - point[0], candidate[1] - point[1])
        if dist < best:
            best = dist
            best_i = i
    return best_i


def _forward(begin: int, end: int, count: int) -> bool:
    """True if `end` is a new ring index while walking the corner chain.

    Coarse corners are already ordered around the ring by Douglas–Peucker, so any
    distinct index is a valid forward step. A shorter-arc heuristic would drop
    legitimate corners that sit more than halfway around from the previous one.
    """
    if count <= 0:
        return False
    return begin != end


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
    """Back-compat emitter for cubic-only results."""
    return segments_to_path_d(curves, decimals=decimals)


def segments_to_path_d(segments: Sequence[PathSegment], *, decimals: int) -> str:
    if not segments:
        return ""
    places = max(0, min(4, int(decimals)))
    fmt = f"{{:.{places}f}}"

    def xy(point: Point) -> str:
        return f"{fmt.format(point[0])} {fmt.format(point[1])}"

    first = segments[0]
    start = first.start if isinstance(first, ArcSegment) else first[0]
    parts = [f"M {xy(start)}"]
    for segment in segments:
        if isinstance(segment, ArcSegment):
            # Always space-separate arc flags — packed flags break our DXF tokenizer.
            large = 1 if segment.large_arc else 0
            sweep = 1 if segment.sweep else 0
            radius = fmt.format(segment.radius)
            parts.append(
                f"A {radius} {radius} 0 {large} {sweep} {xy(segment.end)}"
            )
            continue
        if _is_nearly_linear(segment, places):
            parts.append(f"L {xy(segment[3])}")
        else:
            parts.append(f"C {xy(segment[1])} {xy(segment[2])} {xy(segment[3])}")
    parts.append("Z")
    return " ".join(parts)


def _fit_arc_span(
    points: Sequence[Point],
    tolerance: float,
    *,
    closed: bool,
) -> tuple[ArcSegment, ...] | None:
    """Return one or more circular arcs when the polyline is near-circular."""
    pts = _dedupe(points)
    if closed and len(pts) >= 2 and _same(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < (6 if closed else 5):
        return None
    centre, radius = _fit_circle(pts)
    if centre is None or radius < 1.5:
        return None
    # Residual must beat the cubic tolerance with a little headroom.
    # Closed whole-ring fits need a tighter residual — loose limits turned
    # curved feather blobs into solid filled circles.
    limit = max(0.35, tolerance * (0.45 if closed else 0.85))
    for point in pts:
        if abs(_hypot(point[0] - centre[0], point[1] - centre[1]) - radius) > limit:
            return None
    # Reject near-straight spans (huge radius relative to chord).
    chord = _hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    if not closed and radius > max(80.0, chord * 8.0):
        return None
    angles = [math.atan2(p[1] - centre[1], p[0] - centre[0]) for p in pts]
    # Unwrap so the walk is continuous.
    unwrapped = [angles[0]]
    for angle in angles[1:]:
        prev = unwrapped[-1]
        delta = angle - prev
        while delta > math.pi:
            delta -= 2.0 * math.pi
        while delta < -math.pi:
            delta += 2.0 * math.pi
        unwrapped.append(prev + delta)
    total = unwrapped[-1] - unwrapped[0]
    if closed:
        # Polygon area must match a filled disk — crescents / C-shapes that
        # merely hug a circle must not become a solid A-circle.
        poly_area = 0.0
        for a, b in zip(pts, pts[1:] + pts[:1]):
            poly_area += a[0] * b[1] - b[0] * a[1]
        poly_area = abs(poly_area) * 0.5
        disk = math.pi * radius * radius
        if disk < 1.0 or poly_area / disk < 0.82:
            return None
        # Prefer a full circle expressed as two half-arcs (SVG cannot close a
        # 360° arc from a point onto itself in one command).
        if abs(abs(total) - 2.0 * math.pi) > 0.35 and abs(total) < 0.35:
            # Angle wrap failed; force a full turn from winding of the ring.
            area = 0.0
            for a, b in zip(pts, pts[1:] + pts[:1]):
                area += (b[0] - a[0]) * (b[1] + a[1])
            total = 2.0 * math.pi if area >= 0 else -2.0 * math.pi
        sweep_cw = total > 0
        mid_angle = unwrapped[0] + total * 0.5
        mid = (
            centre[0] + radius * math.cos(mid_angle),
            centre[1] + radius * math.sin(mid_angle),
        )
        start = pts[0]
        return (
            ArcSegment(start=start, end=mid, radius=radius, large_arc=False, sweep=sweep_cw),
            ArcSegment(start=mid, end=start, radius=radius, large_arc=False, sweep=sweep_cw),
        )
    if abs(total) < math.radians(25):
        return None
    sweep_cw = total > 0
    large = abs(total) > math.pi
    return (
        ArcSegment(
            start=pts[0],
            end=pts[-1],
            radius=radius,
            large_arc=large,
            sweep=sweep_cw,
        ),
    )


def _fit_circle(points: Sequence[Point]) -> tuple[Point | None, float]:
    """Algebraic least-squares circle fit. Returns (centre, radius) or (None, 0)."""
    if len(points) < 3:
        return None, 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = float(len(points))
    mx = sum(xs) / n
    my = sum(ys) / n
    u = [x - mx for x in xs]
    v = [y - my for y in ys]
    suu = sum(a * a for a in u)
    svv = sum(a * a for a in v)
    suv = sum(a * b for a, b in zip(u, v))
    suuu = sum(a * a * a for a in u)
    svvv = sum(a * a * a for a in v)
    suuv = sum(a * a * b for a, b in zip(u, v))
    suvv = sum(a * b * b for a, b in zip(u, v))
    denom = 2.0 * (suu * svv - suv * suv)
    if abs(denom) < 1e-9:
        return None, 0.0
    uc = (svv * (suuu + suvv) - suv * (svvv + suuv)) / denom
    vc = (suu * (svvv + suuv) - suv * (suuu + suvv)) / denom
    centre = (mx + uc, my + vc)
    radius = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    return centre, radius


def _is_nearly_linear(curve: Cubic, places: int) -> bool:
    p0, p1, p2, p3 = curve
    # Slightly looser than pure decimal rounding so intentional straight fits
    # from `_fit_straight_span` emit as SVG `L` instead of shallow cubics.
    limit = max(10 ** (-places) * 2.0, 0.04)
    if _point_line_distance(p1, p0, p3) > limit:
        return False
    if _point_line_distance(p2, p0, p3) > limit:
        return False
    return True


def _fit_open(
    points: Sequence[Point],
    tolerance: float,
    *,
    left_tangent: Point | None = None,
    right_tangent: Point | None = None,
) -> list[Cubic]:
    pts = _dedupe(points)
    if len(pts) < 2:
        return []
    if len(pts) == 2:
        return [_line_cubic(pts[0], pts[1])]
    return _schneider(
        pts,
        tolerance,
        depth=0,
        left_tangent=left_tangent,
        right_tangent=right_tangent,
    )


def _schneider(
    points: Sequence[Point],
    tolerance: float,
    depth: int,
    *,
    left_tangent: Point | None = None,
    right_tangent: Point | None = None,
) -> list[Cubic]:
    if len(points) == 2 or depth > 12:
        return [_line_cubic(points[0], points[-1])]
    left = left_tangent or _tangent(points[0], points[min(2, len(points) - 1)])
    right = right_tangent or _tangent(points[-1], points[max(0, len(points) - 3)])
    params = _chord_params(points)
    curve = _generate_bezier(points, params, left, right)
    # Newton–Raphson reparameterization: walk each point to its nearest t on the
    # cubic so the least-squares fit converges the way Schneider described.
    for _ in range(6):
        params = _reparameterize(curve, points, params)
        curve = _generate_bezier(points, params, left, right)
        error, _split = _max_error(curve, points, params)
        if error <= tolerance:
            break
    error, split_at = _max_error(curve, points, params)
    if error <= tolerance:
        return [curve]
    if split_at <= 0 or split_at >= len(points) - 1:
        split_at = len(points) // 2
    # Shared unit tangent at the split for G1 continuity between the two halves.
    # Convention matches the top-level fitter: left tangents point forward along
    # the polyline, right tangents point backward (so p2 = end + alpha * right).
    split_forward = _unit(
        (
            points[min(split_at + 1, len(points) - 1)][0] - points[max(0, split_at - 1)][0],
            points[min(split_at + 1, len(points) - 1)][1] - points[max(0, split_at - 1)][1],
        )
    )
    split_backward = (
        (-split_forward[0], -split_forward[1]) if split_forward is not None else None
    )
    return _schneider(
        points[: split_at + 1],
        tolerance,
        depth + 1,
        left_tangent=left,
        right_tangent=split_backward,
    ) + _schneider(
        points[split_at:],
        tolerance,
        depth + 1,
        left_tangent=split_forward,
        right_tangent=right,
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
    fallback = dist / 3.0
    if abs(det) < 1e-9:
        alpha1 = alpha2 = fallback
    else:
        alpha1 = (x0 * c11 - x1 * c01) / det
        alpha2 = (x1 * c00 - x0 * c01) / det
    # Schneider: reject non-positive or runaway handles. Dist/3 is the safe
    # cubic heuristic and lets Newton–Raphson reparameterization converge.
    if alpha1 < 1e-4 or alpha2 < 1e-4 or alpha1 > dist or alpha2 > dist:
        alpha1 = alpha2 = fallback
    p1 = (p0[0] + tan1[0] * alpha1, p0[1] + tan1[1] * alpha1)
    p2 = (p3[0] + tan2[0] * alpha2, p3[1] + tan2[1] * alpha2)
    return (p0, p1, p2, p3)


def _reparameterize(
    curve: Cubic,
    points: Sequence[Point],
    params: Sequence[float],
) -> list[float]:
    updated: list[float] = []
    for point, t in zip(points, params):
        updated.append(_newton_raphson_root(curve, point, t))
    # Keep parameters strictly increasing so the least-squares matrix stays sane.
    cleaned = [0.0]
    for value in updated[1:-1]:
        cleaned.append(min(0.999, max(cleaned[-1] + 1e-6, value)))
    cleaned.append(1.0)
    return cleaned


def _newton_raphson_root(curve: Cubic, point: Point, t: float) -> float:
    """One Newton step of Q(t) · Q'(t) = 0 toward the nearest point on the cubic."""
    q = _bezier(curve, t)
    q1 = _bezier_derivative(curve, t)
    q2 = _bezier_second(curve, t)
    dx = q[0] - point[0]
    dy = q[1] - point[1]
    num = dx * q1[0] + dy * q1[1]
    den = q1[0] * q1[0] + q1[1] * q1[1] + dx * q2[0] + dy * q2[1]
    if abs(den) < 1e-12:
        return t
    return min(1.0, max(0.0, t - num / den))


def _bezier_derivative(curve: Cubic, t: float) -> Point:
    p0, p1, p2, p3 = curve
    u = 1.0 - t
    # Derivative of a cubic Bezier is a quadratic of the control differences.
    d0 = (3.0 * (p1[0] - p0[0]), 3.0 * (p1[1] - p0[1]))
    d1 = (3.0 * (p2[0] - p1[0]), 3.0 * (p2[1] - p1[1]))
    d2 = (3.0 * (p3[0] - p2[0]), 3.0 * (p3[1] - p2[1]))
    return (
        u * u * d0[0] + 2.0 * u * t * d1[0] + t * t * d2[0],
        u * u * d0[1] + 2.0 * u * t * d1[1] + t * t * d2[1],
    )


def _bezier_second(curve: Cubic, t: float) -> Point:
    p0, p1, p2, p3 = curve
    # Second derivative of the cubic Bezier.
    a = (
        6.0 * (p2[0] - 2.0 * p1[0] + p0[0]),
        6.0 * (p2[1] - 2.0 * p1[1] + p0[1]),
    )
    b = (
        6.0 * (p3[0] - 2.0 * p2[0] + p1[0]),
        6.0 * (p3[1] - 2.0 * p2[1] + p1[1]),
    )
    return (a[0] * (1.0 - t) + b[0] * t, a[1] * (1.0 - t) + b[1] * t)


def _max_error(
    curve: Cubic,
    points: Sequence[Point],
    params: Sequence[float] | None = None,
) -> tuple[float, int]:
    worst = 0.0
    index = len(points) // 2
    if params is None:
        params = _chord_params(points)
    for i, (point, t) in enumerate(zip(points, params)):
        sample = _bezier(curve, t)
        err = _hypot(point[0] - sample[0], point[1] - sample[1])
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
    return _unit((toward[0] - origin[0], toward[1] - origin[1])) or (1.0, 0.0)


def _unit(vector: Point) -> Point | None:
    length = _hypot(vector[0], vector[1])
    if length < 1e-9:
        return None
    return (vector[0] / length, vector[1] / length)


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
