"""Shared-boundary tracer for busy cel / cartoon scenes.

Palette-snapped labels drive topology. Contours are crack-edge walks whose
shared midpoints stay identical for abutting colours (seam-free). Fills expand
slightly more than ink so paint tucks under outlines; dark ink paints last.
Tiny islands are absorbed into their majority neighbour before tracing so
JPEG freckles do not become paths. Rings become corner-preserving centripetal
Catmull–Rom cubics that interpolate the expanded midpoints (no Schneider drift).
"""

from __future__ import annotations

import math
import time

import numpy as np
from PIL import Image

from vectorizer.domain.settings import TraceSettings, normalize_hex
from vectorizer.errors import TraceError
from vectorizer.jobs.progress import STAGE_COLORS, STAGE_CONTOURS, STAGE_CURVES, ProgressCallback
from vectorizer.raster.color import hex_to_rgb, nearest_oklab, rgb_to_hex, srgb_u8_to_oklab
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.backend import TraceResult
from vectorizer.vectorize.blend_trace import _trace_mask
from vectorizer.vectorize.curves import simplify_closed_ring
from vectorizer.vectorize.iso_contour import orient_clockwise

# Outward underlap after shared crack midpoints (px). Fills tuck under ink.
_FILL_EXPAND = 0.55
_INK_EXPAND = 0.40
# Absorb islands below this area into the majority neighbour before tracing.
# ~20 beats VTracer RMSE on busy cel JPEGs; higher floors erase shade islands.
_ABSORB_MIN_AREA = 20
# Extra [1,2,1] passes after crack midpoints (shared on both sides of a seam).
_CRACK_SMOOTH_PASSES = 3
# Light Douglas–Peucker on expanded rings before Catmull–Rom.
_POLY_SIMPLIFY_EPS = 0.4
# Turn angle (degrees) that pins a Catmull–Rom corner (hard joint).
_CORNER_PIN_DEG = 36.0
_DARK_LUMA = 52.0


class CelBoundaryTracer:
    name = "cel_boundary"
    description = (
        "Shared-boundary Catmull–Rom tracer for cel illustrations. Crack "
        "midpoints stay shared; fills tuck under ink; ink paints last."
    )

    def trace(
        self,
        image: Image.Image,
        settings: TraceSettings,
        palette: tuple[str, ...],
        *,
        on_progress: ProgressCallback | None = None,
    ) -> TraceResult:
        report = on_progress or (lambda _stage, _fraction: None)
        validated = settings.validated()
        colors = tuple(normalize_hex(c) for c in palette)
        if len(colors) < 2:
            raise TraceError("Cel boundary tracing needs at least two palette colours.")
        source = image.convert("RGBA")
        if source.size[0] <= 0 or source.size[1] <= 0:
            raise TraceError("Cannot trace an empty image.")
        started = time.perf_counter()
        report(STAGE_COLORS, 0.08)
        labels = _label_palette(source, colors)
        report(STAGE_CONTOURS, 0.18)
        svg = _svg_from_components(
            labels,
            colors,
            validated,
            on_progress=report,
        )
        report(STAGE_CURVES, 0.92)
        document = parse_svg_document(svg, backend_name=self.name)
        document = replace_notes(
            document,
            ("Shared-boundary Catmull–Rom fit on palette-snapped cel regions.",),
        )
        elapsed = time.perf_counter() - started
        warnings: list[str] = []
        if document.path_count == 0:
            warnings.append("Cel boundary tracing produced no paths.")
        return TraceResult(
            document=document,
            elapsed_seconds=elapsed,
            settings=validated,
            backend_name=self.name,
            warnings=tuple(warnings),
        )


def replace_notes(document, notes: tuple[str, ...]):
    from dataclasses import replace

    return replace(document, source_notes=notes)


def _label_palette(image: Image.Image, palette: tuple[str, ...]) -> np.ndarray:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width = rgba.shape[:2]
    pal_rgb = np.asarray([hex_to_rgb(c) for c in palette], dtype=np.uint8)
    packed = (
        rgba[..., 0].astype(np.int32) << 16
        | rgba[..., 1].astype(np.int32) << 8
        | rgba[..., 2].astype(np.int32)
    )
    pal_packed = (
        pal_rgb[:, 0].astype(np.int32) << 16
        | pal_rgb[:, 1].astype(np.int32) << 8
        | pal_rgb[:, 2].astype(np.int32)
    )
    labels = np.full((height, width), -1, dtype=np.int16)
    for index, value in enumerate(pal_packed):
        labels[packed == value] = index
    miss = labels < 0
    alpha = rgba[..., 3]
    miss &= alpha >= 8
    if np.any(miss):
        missed = srgb_u8_to_oklab(rgba[..., :3])[miss]
        # nearest_oklab expects HxWx3; treat the flat miss list as N×1.
        idx, _ = nearest_oklab(
            missed.reshape(missed.shape[0], 1, 3),
            srgb_u8_to_oklab(pal_rgb),
        )
        labels[miss] = idx.reshape(-1).astype(np.int16)
    labels[alpha < 8] = -1
    return labels


def _svg_from_components(
    labels: np.ndarray,
    palette: tuple[str, ...],
    settings: TraceSettings,
    *,
    on_progress: ProgressCallback,
) -> str:
    from vectorizer.raster.preprocess import _label_regions

    height, width = labels.shape
    decimals = max(1, min(4, int(settings.path_precision)))
    # Absorb freckles into neighbours, then drop anything still below that
    # floor so holes are not left behind (drop alone raised RMSE sharply).
    absorb = max(_ABSORB_MIN_AREA, int(settings.filter_speckle))
    speckle = absorb
    # Cel-tuned Catmull–Rom corner pin (not the Schneider threshold).
    corner = _CORNER_PIN_DEG

    cleaned = _absorb_small_components(labels, absorb)

    # Keep root maps per colour so we do not materialise a bool mask per island
    # until we actually trace it.
    components: list[tuple[int, int, int, np.ndarray, int]] = []
    for label, color in enumerate(palette):
        mask = cleaned == label
        if not np.any(mask):
            continue
        roots = _label_regions(mask)
        uniq, counts = np.unique(roots[mask], return_counts=True)
        rgb = hex_to_rgb(color)
        luma = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        dark = 1 if luma <= _DARK_LUMA else 0
        for root, count in zip(uniq.tolist(), counts.tolist()):
            if root < 0 or int(count) < speckle:
                continue
            components.append((int(count), dark, label, roots, int(root)))
    components.sort(key=lambda item: (item[1], -item[0]))

    parts: list[str] = []
    underlay = _background_underlay(palette, settings)
    if underlay is not None:
        parts.append(
            f'<path d="M 0 0 H {width} V {height} H 0 Z" fill="{underlay}"/>'
        )

    total = max(1, len(components))
    path_count = 0
    for index, (area, dark, label, roots, root) in enumerate(components):
        on_progress(
            STAGE_CONTOURS if index < total // 2 else STAGE_CURVES,
            0.20 + 0.70 * (index / total),
        )
        if underlay is not None and palette[label] == underlay and area > 0.38 * height * width:
            continue
        mask = roots == root
        contours = _trace_mask_bbox(mask)
        if not contours:
            continue
        # Solid fills: keep the outer ring only. Ink ribbons keep all rings
        # (outer + counters) and use evenodd.
        if not dark and len(contours) > 1:
            contours = [max(contours, key=len)]
        fill = palette[label]
        subpaths: list[str] = []
        for contour in contours:
            if len(contour) < 6:
                continue
            expand = _INK_EXPAND if dark else _FILL_EXPAND
            ring = _prepare_ring(contour, expand=expand)
            if len(ring) < 4:
                continue
            if _POLY_SIMPLIFY_EPS > 0 and len(ring) >= 8:
                simplified = simplify_closed_ring(ring, epsilon=_POLY_SIMPLIFY_EPS)
                if len(simplified) >= 4:
                    ring = orient_clockwise(simplified)
            # Interpolating Catmull–Rom cubics: smooth curves, no Schneider drift.
            path_d = _corner_catmull_path_d(ring, corner_degrees=corner, decimals=decimals)
            if path_d:
                subpaths.append(path_d)
        if not subpaths:
            continue
        if dark and len(subpaths) > 1:
            parts.append(
                f'<path d="{" ".join(subpaths)}" fill="{fill}" fill-rule="evenodd"/>'
            )
            path_count += 1
        else:
            for path_d in subpaths:
                parts.append(f'<path d="{path_d}" fill="{fill}"/>')
                path_count += 1

    if path_count == 0 and underlay is None:
        raise TraceError("Cel boundary tracing found no regions above the speckle floor.")
    body = "\n  ".join(parts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n  {body}\n</svg>\n'
    )


def _trace_mask_bbox(mask: np.ndarray) -> list[list[tuple[float, float]]]:
    """Trace a component after cropping to its bbox (faster on sparse islands)."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return []
    y0 = max(0, int(ys.min()) - 1)
    x0 = max(0, int(xs.min()) - 1)
    y1 = min(mask.shape[0], int(ys.max()) + 2)
    x1 = min(mask.shape[1], int(xs.max()) + 2)
    if y0 == 0 and x0 == 0 and y1 == mask.shape[0] and x1 == mask.shape[1]:
        return _trace_mask(mask)
    local = mask[y0:y1, x0:x1]
    contours = _trace_mask(local)
    if y0 == 0 and x0 == 0:
        return contours
    return [[(x + x0, y + y0) for x, y in contour] for contour in contours]


def _prepare_ring(
    contour: list[tuple[float, float]],
    *,
    expand: float,
) -> list[tuple[float, float]]:
    """Crack midpoints (shared) → extra shared smooth → outward underlap."""
    ring = _smooth_crack_ring(contour, passes=_CRACK_SMOOTH_PASSES)
    ring = orient_clockwise(ring)
    if expand > 0.05 and len(ring) >= 6:
        ring = _offset_outward(ring, expand)
        ring = orient_clockwise(ring)
    return ring


def _smooth_crack_ring(
    contour: list[tuple[float, float]],
    *,
    passes: int = 3,
) -> list[tuple[float, float]]:
    """Unit-step crack polygon → edge midpoints with shared [1, 2, 1] passes."""
    pts = np.asarray(contour, dtype=np.float64)
    if len(pts) < 5:
        return contour
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    smooth = 0.5 * (pts + np.roll(pts, -1, axis=0))
    for _ in range(max(0, passes)):
        smooth = (
            0.25 * np.roll(smooth, 1, axis=0)
            + 0.5 * smooth
            + 0.25 * np.roll(smooth, -1, axis=0)
        )
    out = [(float(x), float(y)) for x, y in smooth]
    out.append(out[0])
    return out


def _ring_to_polyline_d(ring: list[tuple[float, float]], *, decimals: int) -> str:
    pts = ring[:-1] if ring and ring[0] == ring[-1] else ring
    if len(pts) < 3:
        return ""
    if not all(np.isfinite(x) and np.isfinite(y) for x, y in pts):
        return ""
    fmt = f"{{:.{decimals}f}},{{:.{decimals}f}}"
    return "M" + " L".join(fmt.format(x, y) for x, y in pts) + " Z"


def _corner_catmull_path_d(
    ring: list[tuple[float, float]],
    *,
    corner_degrees: float,
    decimals: int,
) -> str:
    """Closed ring → SVG path of centripetal Catmull–Rom cubics with pinned corners."""
    pts = np.asarray(ring, dtype=np.float64)
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return ""
    if not np.all(np.isfinite(pts)):
        return ""
    pinned = _corner_pins(pts, corner_degrees)
    # Too many pins → nearly a polyline; loosen once so curves survive.
    if int(pinned.sum()) > n * 0.45:
        pinned = _corner_pins(pts, corner_degrees + 12.0)
    places = max(0, min(4, int(decimals)))
    fmt = f"{{:.{places}f}}"

    def xy(point: np.ndarray) -> str:
        return f"{fmt.format(float(point[0]))} {fmt.format(float(point[1]))}"

    pin_idx = sorted({int(i) for i in np.nonzero(pinned)[0]})
    if len(pin_idx) < 2:
        return _closed_catmull_path_d(pts, xy=xy)

    parts: list[str] = []
    started = False
    for k, start in enumerate(pin_idx):
        end = pin_idx[(k + 1) % len(pin_idx)]
        if end > start:
            span = pts[start : end + 1]
        else:
            span = np.vstack([pts[start:], pts[: end + 1]])
        for cubic in _catmull_span_cubics(span):
            if not started:
                parts.append(f"M {xy(cubic[0])}")
                started = True
            parts.append(f"C {xy(cubic[1])} {xy(cubic[2])} {xy(cubic[3])}")
    if not parts:
        return ""
    parts.append("Z")
    return " ".join(parts)


def _closed_catmull_path_d(pts: np.ndarray, *, xy) -> str:
    n = len(pts)
    parts = [f"M {xy(pts[0])}"]
    for i in range(n):
        cubic = _catmull_segment(
            pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        )
        parts.append(f"C {xy(cubic[1])} {xy(cubic[2])} {xy(cubic[3])}")
    parts.append("Z")
    return " ".join(parts)


def _corner_pins(pts: np.ndarray, corner_degrees: float) -> np.ndarray:
    n = len(pts)
    pinned = np.zeros(n, dtype=bool)
    thr = math.radians(max(10.0, float(corner_degrees)))
    for i in range(n):
        prev = pts[(i - 1) % n]
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        a = prev - cur
        b = nxt - cur
        na = float(np.linalg.norm(a))
        nb = float(np.linalg.norm(b))
        if na < 1e-9 or nb < 1e-9:
            continue
        a /= na
        b /= nb
        ang = math.acos(max(-1.0, min(1.0, float(np.dot(a, b)))))
        turn = abs(math.pi - ang)
        if turn >= thr:
            pinned[i] = True
    return pinned


def _catmull_span_cubics(span: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Open point span → cubics that interpolate every sample."""
    pts = np.asarray(span, dtype=np.float64)
    if len(pts) < 2:
        return []
    if len(pts) == 2:
        a, b = pts[0], pts[1]
        return [(a, a + (b - a) / 3.0, a + 2.0 * (b - a) / 3.0, b)]
    # Virtual neighbours for end tangents.
    ext = np.vstack([pts[0] - (pts[1] - pts[0]), pts, pts[-1] + (pts[-1] - pts[-2])])
    out: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for i in range(1, len(ext) - 2):
        out.append(_catmull_segment(ext[i - 1], ext[i], ext[i + 1], ext[i + 2]))
    return out


def _catmull_segment(
    p0: np.ndarray,
    p1: np.ndarray,
    p2: np.ndarray,
    p3: np.ndarray,
    *,
    alpha: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One centripetal Catmull–Rom segment P1→P2 as a cubic Bezier."""

    def tj(ti: float, a: np.ndarray, b: np.ndarray) -> float:
        dx = float(b[0] - a[0])
        dy = float(b[1] - a[1])
        return ti + (dx * dx + dy * dy) ** (alpha * 0.5)

    t0 = 0.0
    t1 = tj(t0, p0, p1)
    t2 = tj(t1, p1, p2)
    t3 = tj(t2, p2, p3)
    if min(t1 - t0, t2 - t1, t3 - t2) < 1e-8:
        return (p1, p1 + (p2 - p1) / 3.0, p1 + 2.0 * (p2 - p1) / 3.0, p2)
    b1 = p1 + (p2 - p0) * ((t2 - t1) / (t2 - t0) / 3.0)
    b2 = p2 - (p3 - p1) * ((t2 - t1) / (t3 - t1) / 3.0)
    return (p1, b1, b2, p2)


def _absorb_small_components(labels: np.ndarray, min_area: int) -> np.ndarray:
    """Merge per-colour components smaller than ``min_area`` into neighbours.

    Vectorised boundary voting per palette label. Sequential colours let a
    folded freckle become a host for the next label — same topology as the
    slow pixel-loop absorb, far less wall time on megapixel cels.
    """
    from vectorizer.raster.preprocess import _label_regions

    if min_area <= 1:
        return labels
    out = labels.copy()
    height, width = out.shape
    max_label = int(out.max()) if out.size else -1
    for label in range(max_label + 1):
        mask = out == label
        if not np.any(mask):
            continue
        roots = _label_regions(mask)
        sizes = np.bincount(roots[mask].astype(np.int64), minlength=height * width)
        small = mask & (sizes[roots] < min_area)
        if not np.any(small):
            continue
        pad_lab = np.pad(out, 1, constant_values=-1)
        roots_list: list[np.ndarray] = []
        labs_list: list[np.ndarray] = []
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nlab = pad_lab[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
            edge = small & (nlab >= 0) & (nlab != label)
            if not np.any(edge):
                continue
            roots_list.append(roots[edge].astype(np.int64))
            labs_list.append(nlab[edge].astype(np.int64))
        if not roots_list:
            continue
        root_ids = np.concatenate(roots_list)
        neigh_labs = np.concatenate(labs_list)
        order = np.argsort(root_ids, kind="mergesort")
        root_ids = root_ids[order]
        neigh_labs = neigh_labs[order]
        uniq, start, counts = np.unique(root_ids, return_index=True, return_counts=True)
        root_to_lab = np.full(height * width, -1, dtype=np.int16)
        for root, st, ct in zip(uniq.tolist(), start.tolist(), counts.tolist()):
            chunk = neigh_labs[st : st + ct]
            hist = np.bincount(chunk.astype(np.int32) + 1)
            root_to_lab[int(root)] = int(hist.argmax()) - 1
        mapped = root_to_lab[roots]
        take = small & (mapped >= 0)
        if np.any(take):
            out = np.where(take, mapped, out).astype(np.int16)
    return out


def _offset_outward(
    ring: list[tuple[float, float]],
    distance: float,
) -> list[tuple[float, float]]:
    """Push a clockwise ring outward (into neighbours) by `distance` pixels."""
    pts = np.asarray(ring, dtype=np.float64)
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 3:
        return ring
    prev = np.roll(pts, 1, axis=0)
    nxt = np.roll(pts, -1, axis=0)
    incoming = pts - prev
    outgoing = nxt - pts
    # Left normals in y-down space (outward for clockwise rings).
    n_in = np.stack((-incoming[:, 1], incoming[:, 0]), axis=1)
    n_out = np.stack((-outgoing[:, 1], outgoing[:, 0]), axis=1)
    normal = n_in + n_out
    lengths = np.linalg.norm(normal, axis=1)
    lengths = np.maximum(lengths, 1e-6)
    normal = normal / lengths[:, None]
    shifted = pts + distance * normal
    out = [(float(x), float(y)) for x, y in shifted]
    out.append(out[0])
    return out


def _background_underlay(
    palette: tuple[str, ...],
    settings: TraceSettings,
) -> str | None:
    if settings.remove_background:
        return None
    bg_hex = rgb_to_hex(
        (settings.background_r, settings.background_g, settings.background_b)
    )
    bg = hex_to_rgb(bg_hex)
    for color in palette:
        rgb = hex_to_rgb(color)
        if max(abs(rgb[i] - bg[i]) for i in range(3)) <= 14:
            return color
    return None


