"""Marching-squares iso-contours on soft coverage fields.

Each palette label gets a continuous coverage map (1 = solid ink, 0 = other).
The 0.5 isolevel is the sub-pixel boundary — smoother than crack-edge shifting.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

Point = tuple[float, float]

# Marching-squares edge midpoints for a unit cell with corners
# (0,0)=SW, (1,0)=SE, (1,1)=NE, (0,1)=NW in (x,y) with y down in image space
# but we use row/col with y increasing downward, so "south" is +y.
_EDGE_A = 0  # bottom (y+1 side): between SW-SE
_EDGE_B = 1  # right  (x+1 side): between SE-NE
_EDGE_C = 2  # top    (y side):   between NW-NE
_EDGE_D = 3  # left   (x side):   between SW-NW

# Case → list of edge-index pairs (each pair is one polyline segment).
# Corner bits: SW=1, SE=2, NE=4, NW=8.
_CASE_SEGMENTS: tuple[tuple[tuple[int, int], ...], ...] = (
    (),  # 0
    ((_EDGE_D, _EDGE_A),),  # 1 SW
    ((_EDGE_A, _EDGE_B),),  # 2 SE
    ((_EDGE_D, _EDGE_B),),  # 3 SW+SE
    ((_EDGE_B, _EDGE_C),),  # 4 NE
    ((_EDGE_D, _EDGE_A), (_EDGE_B, _EDGE_C)),  # 5 saddle SW+NE
    ((_EDGE_A, _EDGE_C),),  # 6 SE+NE
    ((_EDGE_D, _EDGE_C),),  # 7 SW+SE+NE
    ((_EDGE_C, _EDGE_D),),  # 8 NW
    ((_EDGE_C, _EDGE_A),),  # 9 NW+SW
    ((_EDGE_A, _EDGE_B), (_EDGE_C, _EDGE_D)),  # 10 saddle SE+NW
    ((_EDGE_C, _EDGE_B),),  # 11 NW+SW+SE
    ((_EDGE_B, _EDGE_D),),  # 12 NE+NW
    ((_EDGE_B, _EDGE_A),),  # 13 NE+NW+SW
    ((_EDGE_A, _EDGE_D),),  # 14 SE+NE+NW
    (),  # 15
)


def _dilate4(mask: np.ndarray, *, rings: int = 1) -> np.ndarray:
    """Grow a boolean mask by `rings` 4-connected steps."""
    out = mask
    for _ in range(max(1, rings)):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def coverage_field(
    labels: np.ndarray,
    label: int,
    pixels_lab: np.ndarray,
    palette_lab: np.ndarray,
    bg_lab: np.ndarray,
    *,
    soft_lab: np.ndarray | None = None,
    blur: float = 0.65,
) -> np.ndarray:
    """Float32 HxW coverage for `label`. Uses soft colours when provided."""
    height, width = labels.shape
    field = np.zeros((height, width), dtype=np.float32)
    lab = soft_lab if soft_lab is not None else pixels_lab
    ink = palette_lab[label]
    mask = labels == label
    empty = labels < 0
    # Only the ring around this label matters for the isolevel; interior
    # "other" pixels far from the boundary stay 0 and must not be visited.
    ring = _dilate4(mask, rings=2)
    other = ring & (~mask) & (~empty)
    empty_ring = ring & empty

    field[mask] = 1.0
    # Mixed / neighbour pixels: project onto the ink↔neighbour segment.
    if np.any(other):
        ys, xs = np.nonzero(other)
        pix = lab[ys, xs]
        neigh = labels[ys, xs].astype(np.intp)
        other_lab = palette_lab[neigh]
        ab = other_lab - ink
        denom = np.einsum("nc,nc->n", ab, ab, optimize=True)
        safe = denom > 1e-10
        along = np.zeros(ys.shape[0], dtype=np.float32)
        delta = pix - ink
        along[safe] = np.einsum("nc,nc->n", delta[safe], ab[safe], optimize=True) / denom[safe]
        # 1 = pure ink, 0 = pure neighbour.
        cov = np.clip(1.0 - along, 0.0, 1.0).astype(np.float32)
        # Only count coverage when the neighbour projection is meaningful;
        # far-away colours stay near 0 so the isolevel stays at the edge.
        field[ys, xs] = cov * 0.45
    if np.any(empty_ring):
        ys, xs = np.nonzero(empty_ring)
        pix = lab[ys, xs]
        ab = bg_lab - ink
        denom = float(np.dot(ab, ab))
        if denom > 1e-10:
            along = np.einsum("nc,c->n", pix - ink, ab, optimize=True) / denom
            cov = np.clip(1.0 - along, 0.0, 1.0).astype(np.float32)
            field[ys, xs] = np.maximum(field[ys, xs], cov * 0.35)

    if blur > 0:
        field = _box_blur(field, radius=max(0.5, float(blur)))
    # Reinforce solid cores so thin strokes do not dissolve.
    field = np.where(mask, np.maximum(field, 0.92), field)
    return field


def marching_squares(
    field: np.ndarray,
    *,
    level: float = 0.5,
) -> list[list[Point]]:
    """Closed contours of the `level` isolevel. Points are in pixel coordinates."""
    height, width = field.shape
    if height < 2 or width < 2:
        return []
    # Pad with zeros so shapes that touch the border still close.
    padded = np.pad(field, ((1, 1), (1, 1)), mode="constant", constant_values=0.0)
    above = padded >= level
    # Vectorized case codes — only boundary cells (not fully in/out) emit edges.
    sw = above[1:, :-1]
    se = above[1:, 1:]
    ne = above[:-1, 1:]
    nw = above[:-1, :-1]
    case = (
        sw.astype(np.uint8)
        | (se.astype(np.uint8) << 1)
        | (ne.astype(np.uint8) << 2)
        | (nw.astype(np.uint8) << 3)
    )
    active = (case > 0) & (case < 15)
    ys, xs = np.nonzero(active)
    segments: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for y, x in zip(ys.tolist(), xs.tolist()):
        code = int(case[y, x])
        pairs = _CASE_SEGMENTS[code]
        if code in (5, 10):
            # Ambiguous saddle: pick the average-centre disambiguation.
            centre = (
                float(padded[y, x])
                + float(padded[y, x + 1])
                + float(padded[y + 1, x])
                + float(padded[y + 1, x + 1])
            ) * 0.25
            # Centre inside joins the two inside corners; segments keep the
            # same winding as the single-outside-corner cases (7/13, 11/14).
            if centre >= level:
                if code == 5:
                    pairs = ((_EDGE_D, _EDGE_C), (_EDGE_B, _EDGE_A))
                else:
                    pairs = ((_EDGE_A, _EDGE_D), (_EDGE_C, _EDGE_B))
        corners = (
            float(padded[y + 1, x]),
            float(padded[y + 1, x + 1]),
            float(padded[y, x + 1]),
            float(padded[y, x]),
        )
        for a, b in pairs:
            p0 = _edge_point(x, y, a, corners, level)
            p1 = _edge_point(x, y, b, corners, level)
            # Undo the 1-pixel pad.
            p0 = (p0[0] - 1.0, p0[1] - 1.0)
            p1 = (p1[0] - 1.0, p1[1] - 1.0)
            if _key(p0) == _key(p1):
                # Crossing on a corner: zero-length segment would self-loop.
                continue
            segments.setdefault(_key(p0), []).append(p1)

    return _chain_segments(segments)


def _edge_point(
    x: int,
    y: int,
    edge: int,
    corners: tuple[float, float, float, float],
    level: float,
) -> Point:
    """Interpolate the isolevel crossing on one cell edge. corners: SW,SE,NE,NW."""
    sw, se, ne, nw = corners
    if edge == _EDGE_A:  # bottom SW-SE
        t = _interp(sw, se, level)
        return (x + t, y + 1.0)
    if edge == _EDGE_B:  # right SE-NE
        t = _interp(se, ne, level)
        return (x + 1.0, y + 1.0 - t)
    if edge == _EDGE_C:  # top NW-NE
        t = _interp(nw, ne, level)
        return (x + t, y)
    # left SW-NW
    t = _interp(sw, nw, level)
    return (x, y + 1.0 - t)


def _interp(a: float, b: float, level: float) -> float:
    denom = b - a
    if abs(denom) < 1e-12:
        return 0.5
    return max(0.0, min(1.0, (level - a) / denom))


def _key(point: Point) -> tuple[float, float]:
    return (round(point[0], 4), round(point[1], 4))


def _chain_segments(
    segments: dict[tuple[float, float], list[tuple[float, float]]],
) -> list[list[Point]]:
    contours: list[list[Point]] = []
    while segments:
        start_key, destinations = next(iter(segments.items()))
        if not destinations:
            del segments[start_key]
            continue
        nxt = destinations.pop()
        if not destinations:
            del segments[start_key]
        ring = [start_key, nxt]
        guard = 0
        limit = max(64, sum(len(v) for v in segments.values()) + 8)
        while guard < limit:
            guard += 1
            cur = _key(ring[-1])
            if cur == start_key and len(ring) > 2:
                ring[-1] = ring[0]
                break
            options = segments.get(cur)
            if not options:
                break
            nxt = options.pop()
            if not options:
                del segments[cur]
            ring.append(nxt)
        if len(ring) >= 4 and _key(ring[0]) == _key(ring[-1]):
            contours.append([(float(x), float(y)) for x, y in ring])
    return contours


def _box_blur(field: np.ndarray, *, radius: float) -> np.ndarray:
    """Separable box blur approximated with two passes. No SciPy dependency."""
    if radius <= 0:
        return field
    r = max(1, int(round(radius)))
    kernel = np.ones(2 * r + 1, dtype=np.float32) / float(2 * r + 1)
    # Pad reflect so border shapes do not shrink.
    padded = np.pad(field, ((0, 0), (r, r)), mode="edge")
    horiz = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="valid"), 1, padded)
    padded = np.pad(horiz, ((r, r), (0, 0)), mode="edge")
    vert = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="valid"), 0, padded)
    return vert.astype(np.float32)


def orient_clockwise(ring: Sequence[Point]) -> list[Point]:
    """Ensure clockwise winding (positive area in y-down image space is CW)."""
    pts = list(ring)
    if len(pts) < 4:
        return pts
    area = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        area += (x1 - x0) * (y1 + y0)
    # In y-down coordinates, positive shoelace means clockwise.
    if area < 0:
        pts = list(reversed(pts))
    return pts
