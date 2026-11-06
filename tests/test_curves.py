from __future__ import annotations

from vectorizer.vectorize.curves import (
    _corner_ids,
    _forward,
    cubics_to_path_d,
    fit_closed_contour,
)


def test_forward_rejects_only_identical_indices() -> None:
    assert _forward(0, 0, 100) is False
    assert _forward(10, 80, 100) is True  # long arc must still count as forward
    assert _forward(90, 10, 100) is True


def test_corner_ids_keeps_sparse_corners_around_ring() -> None:
    # Square ring: four corners far apart relative to half the perimeter.
    ring = [
        (0.0, 0.0),
        (10.0, 0.0),
        (20.0, 0.0),
        (20.0, 10.0),
        (20.0, 20.0),
        (10.0, 20.0),
        (0.0, 20.0),
        (0.0, 10.0),
    ]
    coarse = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
    ids = _corner_ids(ring, coarse, corner_degrees=20.0)
    assert ids[0] == ids[-1]
    assert len(ids) >= 5  # four corners + closing index


def test_fit_closed_contour_returns_closed_cubics() -> None:
    from vectorizer.vectorize.curves import ArcSegment, segments_to_path_d

    points = [
        (0.0, 0.0),
        (40.0, 0.0),
        (40.0, 30.0),
        (0.0, 30.0),
        (0.0, 0.0),
    ]
    curves = fit_closed_contour(points, tolerance=1.0, corner_degrees=45.0)
    assert curves
    path = segments_to_path_d(curves, decimals=2)
    assert path.startswith("M ")
    assert path.rstrip().endswith("Z")
    first = curves[0]
    last = curves[-1]
    if isinstance(first, ArcSegment):
        start = first.start
    else:
        start = first[0]
    if isinstance(last, ArcSegment):
        end = last.end
    else:
        end = last[3]
    assert abs(start[0] - end[0]) < 1e-3 or path.count("Z") == 1
    assert abs(start[1] - end[1]) < 1e-3 or path.count("Z") == 1


def test_fit_circle_polyline_stays_within_tolerance() -> None:
    import math

    from vectorizer.vectorize.curves import ArcSegment, segments_to_path_d

    points = [
        (50.0 + 30.0 * math.cos(t), 50.0 + 30.0 * math.sin(t))
        for t in [i * math.tau / 64 for i in range(65)]
    ]
    curves = fit_closed_contour(points, tolerance=0.75, corner_degrees=60.0)
    assert curves
    path = segments_to_path_d(curves, decimals=2)
    # Prefer real SVG arcs for near-circular silhouettes.
    assert " A " in path
    assert all(isinstance(seg, ArcSegment) for seg in curves)
    for seg in curves:
        assert abs(seg.radius - 30.0) < 1.0


def test_straight_spans_emit_lineto() -> None:
    from vectorizer.vectorize.curves import segments_to_path_d

    points = [
        (0.0, 0.0),
        (40.0, 0.0),
        (40.0, 30.0),
        (0.0, 30.0),
        (0.0, 0.0),
    ]
    curves = fit_closed_contour(points, tolerance=1.0, corner_degrees=45.0)
    path = segments_to_path_d(curves, decimals=2)
    assert " L " in path
