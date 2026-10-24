"""DXF export from SVG path data.

Limitations (documented, not hidden):
- Units are document pixels treated as DXF drawing units (1 unit = 1 px).
- Cubic/quadratic curves and elliptical arcs are linearized (default 8 segments).
- Fills are not represented; only path outlines / polylines are written.
- Compound holes and transforms other than simple translate are approximated.
- Precision is controlled by `decimals` (default 3).

This is a native ASCII DXF R12 writer — Inkscape is not required for DXF.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from pathlib import Path

from vectorizer.domain.document import VectorDocument, VectorPath
from vectorizer.errors import ExportError

_COMMANDS = set("MmLlHhVvCcSsQqTtAaZz")


def export_dxf(
    document: VectorDocument,
    destination: str | Path,
    *,
    curve_segments: int = 8,
    decimals: int = 3,
    flip_y: bool = True,
) -> Path:
    path = Path(destination)
    if path.exists() and path.is_dir():
        raise ExportError(f"Refusing to overwrite a directory: {path}")
    if not document.groups:
        raise ExportError("There is no vector geometry to export as DXF.")
    curve_segments = max(2, min(64, int(curve_segments)))
    decimals = max(0, min(8, int(decimals)))
    height = float(document.height) or 0.0

    entities: list[str] = []
    handle = 100
    for group in document.groups:
        for vp in group.paths:
            points = _path_to_points(vp, curve_segments=curve_segments)
            if len(points) < 2:
                continue
            if flip_y:
                points = [(x, height - y) for x, y in points]
            tx, ty = _parse_translate(vp.transform)
            if tx or ty:
                points = [(x + tx, y + (-ty if flip_y else ty)) for x, y in points]
            entities.append(_lwpolyline(points, handle=handle, decimals=decimals, closed=_is_closed(vp.d)))
            handle += 1

    if not entities:
        raise ExportError("No convertible path geometry was found for DXF.")

    payload = _wrap_dxf(entities)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".vectorizer-", suffix=".dxf", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle_f:
            handle_f.write(payload)
            handle_f.flush()
            os.fsync(handle_f.fileno())
        os.replace(tmp_name, path)
    except Exception as exc:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise ExportError(f"Could not write DXF: {exc}") from exc
    return path


def _parse_translate(transform: str | None) -> tuple[float, float]:
    if not transform:
        return 0.0, 0.0
    match = re.search(r"translate\(\s*([-\d.]+)(?:[,\s]+([-\d.]+))?\s*\)", transform)
    if not match:
        return 0.0, 0.0
    x = float(match.group(1))
    y = float(match.group(2) or 0.0)
    return x, y


def _is_closed(d: str) -> bool:
    return bool(re.search(r"[Zz]\s*$", d.strip()))


def _sample_curve(
    p0: tuple[float, float],
    controls: list[tuple[float, float]],
    p1: tuple[float, float],
    segments: int,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(1, segments + 1):
        t = i / segments
        if len(controls) == 2:
            c1, c2 = controls
            x = (
                (1 - t) ** 3 * p0[0]
                + 3 * (1 - t) ** 2 * t * c1[0]
                + 3 * (1 - t) * t**2 * c2[0]
                + t**3 * p1[0]
            )
            y = (
                (1 - t) ** 3 * p0[1]
                + 3 * (1 - t) ** 2 * t * c1[1]
                + 3 * (1 - t) * t**2 * c2[1]
                + t**3 * p1[1]
            )
        elif len(controls) == 1:
            c1 = controls[0]
            x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c1[0] + t**2 * p1[0]
            y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c1[1] + t**2 * p1[1]
        else:
            x = p0[0] + (p1[0] - p0[0]) * t
            y = p0[1] + (p1[1] - p0[1]) * t
        pts.append((x, y))
    return pts


def _sample_arc(
    p0: tuple[float, float],
    rx: float,
    ry: float,
    x_axis: float,
    large: bool,
    sweep: bool,
    p1: tuple[float, float],
    segments: int,
) -> list[tuple[float, float]]:
    """Sample an SVG elliptical arc (endpoint parameterization → polyline).

    Implements the W3C SVG center parameterization (implnote F.6). Degenerate
    radii fall back to a straight segment to the endpoint.
    """
    x1, y1 = p0
    x2, y2 = p1
    if abs(rx) < 1e-9 or abs(ry) < 1e-9 or (abs(x1 - x2) < 1e-12 and abs(y1 - y2) < 1e-12):
        return [p1]

    rx = abs(float(rx))
    ry = abs(float(ry))
    phi = math.radians(float(x_axis) % 360.0)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    # Step 1: compute (x1', y1')
    dx = (x1 - x2) / 2.0
    dy = (y1 - y2) / 2.0
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy

    # Step 2: ensure radii are large enough
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    rx_sq = rx * rx
    ry_sq = ry * ry
    x1p_sq = x1p * x1p
    y1p_sq = y1p * y1p
    denom = rx_sq * y1p_sq + ry_sq * x1p_sq
    if denom == 0.0:
        return [p1]
    num = rx_sq * ry_sq - denom
    coeff = math.sqrt(max(0.0, num / denom))
    if large == sweep:
        coeff = -coeff
    cxp = coeff * (rx * y1p) / ry
    cyp = coeff * (-(ry * x1p) / rx)

    # Step 3: center in original coords
    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

    def _angle(ux: float, uy: float, vx: float, vy: float) -> float:
        n = math.hypot(ux, uy) * math.hypot(vx, vy)
        if n == 0.0:
            return 0.0
        cos_a = max(-1.0, min(1.0, (ux * vx + uy * vy) / n))
        ang = math.acos(cos_a)
        if ux * vy - uy * vx < 0.0:
            ang = -ang
        return ang

    start_ang = _angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = _angle(
        (x1p - cxp) / rx,
        (y1p - cyp) / ry,
        (-x1p - cxp) / rx,
        (-y1p - cyp) / ry,
    )
    if not sweep and delta > 0.0:
        delta -= 2.0 * math.pi
    elif sweep and delta < 0.0:
        delta += 2.0 * math.pi

    pts: list[tuple[float, float]] = []
    for i in range(1, segments + 1):
        t = i / segments
        ang = start_ang + t * delta
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        x = cos_phi * rx * cos_a - sin_phi * ry * sin_a + cx
        y = sin_phi * rx * cos_a + cos_phi * ry * sin_a + cy
        pts.append((x, y))
    # Ensure the final sample lands exactly on the SVG endpoint.
    pts[-1] = p1
    return pts


def _path_d_to_points(d: str, *, curve_segments: int) -> list[tuple[float, float]]:
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", d)
    if not tokens:
        return []
    points: list[tuple[float, float]] = []
    cx = cy = 0.0
    start = (0.0, 0.0)
    last_ctrl: tuple[float, float] | None = None
    last_cmd = ""
    i = 0

    def take_float() -> float:
        nonlocal i
        value = float(tokens[i])
        i += 1
        return value

    while i < len(tokens):
        tok = tokens[i]
        if tok in _COMMANDS:
            cmd = tok
            i += 1
        else:
            cmd = last_cmd
            if not cmd:
                break
        absolute = cmd.isupper()
        op = cmd.upper()
        if op == "M":
            x, y = take_float(), take_float()
            if not absolute:
                x += cx
                y += cy
            cx, cy = x, y
            start = (cx, cy)
            points.append((cx, cy))
            last_cmd = "L" if absolute else "l"
            last_ctrl = None
            continue
        if op == "L":
            x, y = take_float(), take_float()
            if not absolute:
                x += cx
                y += cy
            cx, cy = x, y
            points.append((cx, cy))
            last_ctrl = None
        elif op == "H":
            x = take_float()
            if not absolute:
                x += cx
            cx = x
            points.append((cx, cy))
            last_ctrl = None
        elif op == "V":
            y = take_float()
            if not absolute:
                y += cy
            cy = y
            points.append((cx, cy))
            last_ctrl = None
        elif op == "C":
            x1, y1 = take_float(), take_float()
            x2, y2 = take_float(), take_float()
            x, y = take_float(), take_float()
            if not absolute:
                x1, y1, x2, y2, x, y = x1 + cx, y1 + cy, x2 + cx, y2 + cy, x + cx, y + cy
            points.extend(
                _sample_curve((cx, cy), [(x1, y1), (x2, y2)], (x, y), curve_segments)
            )
            last_ctrl = (x2, y2)
            cx, cy = x, y
        elif op == "S":
            x2, y2 = take_float(), take_float()
            x, y = take_float(), take_float()
            if not absolute:
                x2, y2, x, y = x2 + cx, y2 + cy, x + cx, y + cy
            if last_ctrl and last_cmd.upper() in {"C", "S"}:
                x1 = 2 * cx - last_ctrl[0]
                y1 = 2 * cy - last_ctrl[1]
            else:
                x1, y1 = cx, cy
            points.extend(
                _sample_curve((cx, cy), [(x1, y1), (x2, y2)], (x, y), curve_segments)
            )
            last_ctrl = (x2, y2)
            cx, cy = x, y
        elif op == "Q":
            x1, y1 = take_float(), take_float()
            x, y = take_float(), take_float()
            if not absolute:
                x1, y1, x, y = x1 + cx, y1 + cy, x + cx, y + cy
            points.extend(_sample_curve((cx, cy), [(x1, y1)], (x, y), curve_segments))
            last_ctrl = (x1, y1)
            cx, cy = x, y
        elif op == "T":
            x, y = take_float(), take_float()
            if not absolute:
                x, y = x + cx, y + cy
            if last_ctrl and last_cmd.upper() in {"Q", "T"}:
                x1 = 2 * cx - last_ctrl[0]
                y1 = 2 * cy - last_ctrl[1]
            else:
                x1, y1 = cx, cy
            points.extend(_sample_curve((cx, cy), [(x1, y1)], (x, y), curve_segments))
            last_ctrl = (x1, y1)
            cx, cy = x, y
        elif op == "A":
            rx, ry = take_float(), take_float()
            x_axis = take_float()
            large = bool(take_float())
            sweep = bool(take_float())
            x, y = take_float(), take_float()
            if not absolute:
                x, y = x + cx, y + cy
            points.extend(
                _sample_arc((cx, cy), rx, ry, x_axis, large, sweep, (x, y), curve_segments)
            )
            cx, cy = x, y
            last_ctrl = None
        elif op == "Z":
            points.append(start)
            cx, cy = start
            last_ctrl = None
        else:
            break
        last_cmd = cmd
    return points


def _path_to_points(path: VectorPath, *, curve_segments: int) -> list[tuple[float, float]]:
    return _path_d_to_points(path.d, curve_segments=curve_segments)


def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _lwpolyline(
    points: list[tuple[float, float]],
    *,
    handle: int,
    decimals: int,
    closed: bool,
) -> str:
    lines = [
        "0",
        "LWPOLYLINE",
        "5",
        f"{handle:X}",
        "8",
        "0",
        "90",
        str(len(points)),
        "70",
        "1" if closed else "0",
    ]
    for x, y in points:
        lines.extend(["10", _fmt(x, decimals), "20", _fmt(y, decimals)])
    return "\n".join(lines)


def _wrap_dxf(entities: list[str]) -> str:
    header = """0
SECTION
2
HEADER
9
$ACADVER
1
AC1009
9
$INSUNITS
70
0
0
ENDSEC
0
SECTION
2
TABLES
0
ENDSEC
0
SECTION
2
BLOCKS
0
ENDSEC
0
SECTION
2
ENTITIES
"""
    footer = """0
ENDSEC
0
EOF
"""
    return header + "\n".join(entities) + "\n" + footer
