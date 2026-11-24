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

# Ink layer: sub-pixel ink coverage from the anti-aliased source, traced as
# marching-squares iso-contours and painted over fills that run under it.
_INK_LAYER = True
# Window radius (px) for the local paper colour an ink pixel blends against.
_INK_BG_RADIUS = 2
_INK_FILL_RADIUS = 3
# RGB distance to the ink colour that counts as solid ink (coverage 1).
_INK_SOLID_DIST = 48.0
# Max RGB distance off the paper↔ink mixing line before coverage is rejected.
_INK_MIX_RESIDUAL = 38.0
# Isolevel of the ink outline and the hysteresis core a component must hold.
_INK_LEVEL = 0.5
_INK_CORE = 0.55
_INK_MIN_CORE_PX = 6
# Hairlines peaking below full coverage get a lower, mass-preserving cut.
_INK_THIN_ADAPT = True
_INK_THIN_MIN_PEAK = 0.45
_INK_THIN_FLOOR = 0.3
_INK_MIN_AREA = 10
# Coverage above this hides the fill underneath, so fills are regrown there.
_INK_UNDER = 0.2
_INK_UNDER_GROW = 0
# Majority filter on fill labels once ink is lifted off. Radius scales with
# the long side: small cels have thin coloured glyphs a 5×5 vote would erase.
_FILL_MODE_STEPS = ((2000, 2), (1200, 1))
_FILL_MODE_PASSES = 1
# [1,2,1] passes on marching-squares ink rings before Catmull–Rom.
_INK_RING_PASSES = 1
_INK_SIMPLIFY_EPS = 0.35
# λ/μ (Taubin) passes on ink rings: straighter sides, no end shrinkage.
_INK_TAUBIN_PASSES = 4
# Strokes whose dark core is this far from the ink colour keep their own hue.
_STROKE_COLOR = True
_STROKE_COLOR_MIN_DIST = 60.0
# RGB radius that groups measured stroke colours into one family (0 = off).
_STROKE_FAMILY_DIST = 36.0
# Fold thin fill bands that are a mix of two neighbouring plateau fills.
_FRINGE_FOLD = True
_FRINGE_REACH = 4
_FRINGE_MIX_RESIDUAL = 30.0
# Re-pick fill labels with a local-dominance prior (window radius, OKLab
# bonus at 100 % share): mis-snapped shade stripes join the dominant fill.
_SPATIAL_RESNAP = True
_RESNAP_RADIUS = 10
_RESNAP_BONUS = 0.14
# Recentre each fill palette colour on the source pixels it finally labels.
_REFINE_FILL_COLORS = True
# Split large fill regions into 2–3 soft shade bands by smoothed source luma.
_SHADE_BANDS = True
_BAND_MIN_AREA = 4000
_BAND_MIN_STD = 6.0
_BAND_MIN_GAP = 8.0
_BAND_SMOOTH_RADIUS = 3
_BAND_MAX = 3
_BAND_MIN_SHARE = 0.06
# Band luma = 3×3 diffusion blocked by ink (0 = plain box mean). Ribs then
# separate pockets, so pleats between consecutive strokes get their own tone,
# and thin lines across narrow bars blur out instead of becoming strip bands.
_BAND_DIFFUSE_ITERS = 60
# Fill components whose own median colour is ≥ this far (OKLab) from their
# label's colour get a colour of their own (e.g. a sky-rim shadow sharing the
# floor-teal label); nearby outlier colours share one new label.
_OUTLIER_RECOLOR = True
_OUTLIER_MIN_AREA = 150
_OUTLIER_DIST = 0.04
# Smaller components (≥ this area) qualify only when far off (≥ this dist).
_OUTLIER_SMALL_AREA = 30
_OUTLIER_SMALL_DIST = 0.1
# Components below the outlier area (≥ min px) whose colour is off their
# label re-pick the best-matching label present within `reach` px, when it
# fits at most `ratio` × the own-label distance (0 = off).
_FLECK_MIN_AREA = 8
_FLECK_REACH = 10
_FLECK_RATIO = 0.6
# Flecks with no local match that touch ink (≥ this share of their rim) and
# sit on the ink↔fill mixing line of their main neighbour join that fill.
_FLECK_INK_RIM = 0.25
_FLECK_MIX_RESIDUAL = 18.0
# Fill parts thinner than 3 px join an adjacent fill of similar colour.
_SLIVER_MERGE = True
_SLIVER_MAX_DIST = 0.06


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
        soft_source: Image.Image | None = None,
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
        ink_index = _ink_label(colors)
        ink_field = None
        soft_rgb = None
        if _INK_LAYER and ink_index is not None:
            soft = soft_source if soft_source is not None else source
            if soft.size != source.size:
                soft = soft.resize(source.size, Image.Resampling.LANCZOS)
            soft_rgb = np.asarray(soft.convert("RGB"), dtype=np.float32)
            pal_rgb = np.asarray([hex_to_rgb(c) for c in colors], dtype=np.float32)
            ink_field = _ink_coverage_field(
                soft,
                hex_to_rgb(colors[ink_index]),
                alpha=np.asarray(source)[..., 3],
                labels=labels,
                palette_rgb=pal_rgb,
                ink_index=ink_index,
            )
            labels = _regrow_fills_under_ink(labels, ink_field, ink_index)
            if _SPATIAL_RESNAP:
                labels = _spatial_resnap(
                    labels,
                    soft_rgb,
                    pal_rgb,
                    frozen=ink_field >= _INK_UNDER,
                    ink_index=ink_index,
                    radius=_RESNAP_RADIUS,
                    bonus=_RESNAP_BONUS,
                )
            if _FRINGE_FOLD:
                labels = _fold_mix_fringes(labels, soft_rgb, pal_rgb, ink_index)
            radius = _fill_mode_radius(max(source.size))
            if radius > 0:
                labels = _mode_filter_labels(labels, radius=radius, passes=_FILL_MODE_PASSES)
            if _SLIVER_MERGE:
                labels = _merge_slivers(labels, pal_rgb, ink_index, max_dist=_SLIVER_MAX_DIST)
        if _SHADE_BANDS and soft_rgb is not None and ink_field is not None:
            labels, colors = _split_shade_bands(
                labels, soft_rgb, colors, ink_index=ink_index, under_ink=ink_field >= _INK_UNDER
            )
        if _OUTLIER_RECOLOR and soft_rgb is not None and ink_field is not None:
            labels, colors = _recolor_outliers(
                labels, soft_rgb, colors, ink_index=ink_index, sample=ink_field < _INK_UNDER
            )
            labels = _recolor_flecks(
                labels,
                soft_rgb,
                ink_index=ink_index,
                sample=ink_field < _INK_UNDER,
                ink_field=ink_field,
                ink_rgb=hex_to_rgb(colors[ink_index]) if ink_index is not None else None,
            )
        fill_colors = colors
        if _REFINE_FILL_COLORS and soft_rgb is not None and ink_field is not None:
            height, width = labels.shape
            pad = np.pad(labels, 1, constant_values=-1)
            interior = labels >= 0
            for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
                interior &= pad[dy : dy + height, dx : dx + width] == labels
            fill_colors = _refine_fill_colors(
                labels,
                soft_rgb,
                colors,
                ink_index=ink_index,
                sample=interior & (ink_field < _INK_UNDER),
            )
        report(STAGE_CONTOURS, 0.18)
        svg = _svg_from_components(
            labels,
            fill_colors,
            validated,
            ink_field=ink_field,
            ink_color=colors[ink_index] if ink_index is not None else None,
            stroke_rgb=soft_rgb if _STROKE_COLOR else None,
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
    ink_field: np.ndarray | None = None,
    ink_color: str | None = None,
    stroke_rgb: np.ndarray | None = None,
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
    components: list[tuple[int, int, int, np.ndarray, int, tuple[int, int, int, int]]] = []
    for label, color in enumerate(palette):
        mask = cleaned == label
        if not np.any(mask):
            continue
        roots = _label_regions(mask)
        rgb = hex_to_rgb(color)
        luma = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        dark = 1 if luma <= _DARK_LUMA else 0
        for root, count, bbox in _component_bboxes(roots):
            if count < speckle:
                continue
            components.append((count, dark, label, roots, root, bbox))
    components.sort(key=lambda item: (item[1], -item[0]))
    parts: list[str] = []
    underlay = _background_underlay(palette, settings)
    if underlay is not None:
        parts.append(
            f'<path d="M 0 0 H {width} V {height} H 0 Z" fill="{underlay}"/>'
        )

    total = max(1, len(components))
    traced: list[tuple[int, float, int, list]] = []
    for index, (area, dark, label, roots, root, bbox) in enumerate(components):
        on_progress(STAGE_CONTOURS, 0.20 + 0.35 * (index / total))
        if underlay is not None and palette[label] == underlay and area > 0.38 * height * width:
            continue
        contours = _trace_component(roots, root, bbox)
        if not contours:
            continue
        # The outer ring encloses every hole; a jagged hole can be longer.
        enclosed = max(abs(_ring_area(ring)) for ring in contours)
        # Solid fills: keep the outer ring only. Ink ribbons keep all rings
        # (outer + counters) and use evenodd.
        if not dark and len(contours) > 1:
            contours = [max(contours, key=lambda ring: abs(_ring_area(ring)))]
        traced.append((dark, enclosed, label, contours))
    # Fills paint as solid outer rings, so anything inside a ring must paint
    # after it: order by enclosed area, not pixel count (a bridged pair of
    # doors can out-count the frame around them).
    traced.sort(key=lambda item: (item[0], -item[1]))
    path_count = 0
    for index, (dark, _enclosed, label, contours) in enumerate(traced):
        on_progress(STAGE_CURVES, 0.55 + 0.35 * (index / max(1, len(traced))))
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

    if ink_field is not None and ink_color is not None:
        ink_rgb = hex_to_rgb(ink_color)
        strokes = _ink_layer_paths(ink_field, corner=corner, decimals=decimals)
        fills = [ink_color] * len(strokes)
        if stroke_rgb is not None:
            measured = [_stroke_color(stroke_rgb, mask, ink_rgb) for _d, mask in strokes]
            sizes = [int(mask[2].sum()) for _d, mask in strokes]
            fills = _stroke_families(measured, sizes, ink_color)
        for (path_d, _mask), fill in zip(strokes, fills):
            parts.append(f'<path d="{path_d}" fill="{fill}" fill-rule="evenodd"/>')
            path_count += 1

    if path_count == 0 and underlay is None:
        raise TraceError("Cel boundary tracing found no regions above the speckle floor.")
    body = "\n  ".join(parts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">\n  {body}\n</svg>\n'
    )


def _spatial_resnap(
    labels: np.ndarray,
    rgb: np.ndarray,
    palette_rgb: np.ndarray,
    *,
    frozen: np.ndarray,
    ink_index: int | None,
    radius: int,
    bonus: float,
) -> np.ndarray:
    """Re-pick fill labels with a local-dominance prior.

    Cost per label = OKLab distance of the source pixel to the palette colour
    minus ``bonus`` × that label's share of the (2r+1)² window. A pleat stripe
    that fits a muted mauve entry barely better than the surrounding orange
    joins the orange; a pixel clearly matching a small region keeps it.
    Only labels already present in the window compete. ``frozen`` pixels
    (under ink, transparent) keep their label.
    """
    from vectorizer.raster.color import srgb_u8_to_oklab

    height, width = labels.shape
    pix_lab = srgb_u8_to_oklab(np.clip(rgb, 0, 255).astype(np.uint8))
    pal_lab = srgb_u8_to_oklab(
        np.clip(palette_rgb, 0, 255).astype(np.uint8).reshape(-1, 1, 3)
    ).reshape(-1, 3)
    k = 2 * radius + 1
    norm = float(k * k)
    best_cost = np.full((height, width), np.inf, dtype=np.float32)
    best = labels.copy()
    for label in np.unique(labels[labels >= 0]).tolist():
        if ink_index is not None and label == ink_index:
            continue
        hits = (labels == label).astype(np.int32)
        integ = np.pad(hits, ((radius + 1, radius), (radius + 1, radius))).cumsum(0).cumsum(1)
        share = (integ[k:, k:] - integ[:-k, k:] - integ[k:, :-k] + integ[:-k, :-k]) / norm
        present = share > 0
        diff = pix_lab - pal_lab[label]
        cost = np.sqrt(np.einsum("hwc,hwc->hw", diff, diff)) - bonus * share
        cost = np.where(present, cost, np.inf).astype(np.float32)
        better = cost < best_cost
        best_cost = np.where(better, cost, best_cost)
        best = np.where(better, label, best)
    movable = (labels >= 0) & ~frozen
    if ink_index is not None:
        movable &= labels != ink_index
    return np.where(movable & np.isfinite(best_cost), best, labels).astype(labels.dtype)


def _box_mean(field: np.ndarray, weight: np.ndarray, radius: int) -> np.ndarray:
    """Normalised box mean of `field` over pixels where `weight` is set."""
    height, width = field.shape
    k = 2 * radius + 1

    def box(a: np.ndarray) -> np.ndarray:
        integ = np.pad(a, ((radius + 1, radius), (radius + 1, radius))).cumsum(0).cumsum(1)
        return integ[k:, k:] - integ[:-k, k:] - integ[k:, :-k] + integ[:-k, :-k]

    w = weight.astype(np.float64)
    num = box(field.astype(np.float64) * w)
    den = box(w)
    return np.where(den > 0, num / np.maximum(den, 1e-9), field).astype(np.float32)


def _blocked_diffuse(field: np.ndarray, weight: np.ndarray, iters: int) -> np.ndarray:
    """Iterated 3×3 weighted mean; zero-weight pixels receive but never pass on.

    Strokes wider than 2 px (the under-ink band is) therefore act as walls:
    each inter-rib pocket relaxes towards its own mean tone.
    """
    height, width = field.shape
    w = weight.astype(np.float32)
    v = field.astype(np.float32)

    def box3(a: np.ndarray) -> np.ndarray:
        p = np.pad(a, 1)
        acc = np.zeros_like(a)
        for dy in range(3):
            for dx in range(3):
                acc += p[dy : dy + height, dx : dx + width]
        return acc

    den = box3(w)
    reach = den > 0
    safe = np.maximum(den, 1e-6)
    for _ in range(max(0, iters)):
        v = np.where(reach, box3(v * w) / safe, v)
    return v


def _luma_bands(values: np.ndarray) -> np.ndarray:
    """1-D k-means centres (≤ `_BAND_MAX`), merging centres closer than the gap."""
    qs = np.linspace(0.15, 0.85, _BAND_MAX)
    centres = np.quantile(values, qs)
    for _ in range(12):
        idx = np.argmin(np.abs(values[:, None] - centres[None, :]), axis=1)
        new = np.array(
            [values[idx == i].mean() if np.any(idx == i) else centres[i] for i in range(len(centres))]
        )
        if np.allclose(new, centres, atol=0.05):
            break
        centres = new
    centres = np.sort(centres)
    merged = [float(centres[0])]
    for c in centres[1:]:
        if c - merged[-1] < _BAND_MIN_GAP:
            merged[-1] = 0.5 * (merged[-1] + float(c))
        else:
            merged.append(float(c))
    return np.asarray(merged)


def _split_shade_bands(
    labels: np.ndarray,
    rgb: np.ndarray,
    palette: tuple[str, ...],
    *,
    ink_index: int | None,
    under_ink: np.ndarray,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Split large shaded fills into a few coherent luma bands (new labels).

    Re-snapping folds pleat stripes into one flat orange. The soft source still
    carries the shading: a box-smoothed luma (ink pixels excluded) is cut into
    ≤3 levels per component, majority-cleaned, and each extra level becomes a
    new label so it traces as its own fill under the ink.
    """
    from vectorizer.raster.preprocess import _label_regions

    height, width = labels.shape
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    valid = (labels >= 0) & ~under_ink
    smooth = _box_mean(luma, valid, _BAND_SMOOTH_RADIUS)
    out = labels.copy()
    colors = list(palette)
    for label in np.unique(labels[labels >= 0]).tolist():
        if ink_index is not None and label == ink_index:
            continue
        mask = labels == label
        if int(mask.sum()) < _BAND_MIN_AREA:
            continue
        roots = _label_regions(mask)
        for root, count, (y0, x0, y1, x1) in _component_bboxes(roots):
            if count < _BAND_MIN_AREA:
                continue
            local = roots[y0:y1, x0:x1] == root
            seen = local & valid[y0:y1, x0:x1]
            field = smooth[y0:y1, x0:x1]
            vals = field[seen]
            if vals.size < _BAND_MIN_AREA // 2 or float(vals.std()) < _BAND_MIN_STD:
                continue
            if _BAND_DIFFUSE_ITERS > 0:
                field = _blocked_diffuse(luma[y0:y1, x0:x1], seen, _BAND_DIFFUSE_ITERS)
                vals = field[seen]
            sample = vals[:: max(1, vals.size // 20000)]
            centres = _luma_bands(sample)
            if len(centres) < 2:
                continue
            band = np.argmin(np.abs(field[..., None] - centres[None, None, :]), axis=2).astype(
                np.int16
            )
            band = np.where(local, band, -1).astype(np.int16)
            band = _mode_filter_labels(band, radius=2, passes=2)
            shares = np.bincount(band[local].astype(np.int64), minlength=len(centres)) / float(count)
            if np.count_nonzero(shares >= _BAND_MIN_SHARE) < 2:
                continue
            main = int(np.argmax(shares))
            region = out[y0:y1, x0:x1]
            src = rgb[y0:y1, x0:x1]
            for b in range(len(centres)):
                if b == main or shares[b] < _BAND_MIN_SHARE:
                    continue
                pick = local & (band == b)
                pix = src[pick & seen]
                if pix.shape[0] < 16:
                    continue
                med = np.clip(np.round(np.median(pix, axis=0)), 0, 255).astype(int)
                colors.append(rgb_to_hex((int(med[0]), int(med[1]), int(med[2]))))
                region[pick] = len(colors) - 1
    return out, tuple(colors)


def _recolor_outliers(
    labels: np.ndarray,
    rgb: np.ndarray,
    palette: tuple[str, ...],
    *,
    ink_index: int | None,
    sample: np.ndarray,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Give off-colour components of a shared label their own fill colour.

    One analyzer entry can serve far-apart regions with different real
    colours (floor teal and a cyan sky-rim shadow). Components whose median
    source colour sits ≥ `_OUTLIER_DIST` (OKLab) from the label's median move
    to a new label; outliers within half that distance of each other pool.
    """
    from vectorizer.raster.preprocess import _label_regions

    def oklab(c: np.ndarray) -> np.ndarray:
        return srgb_u8_to_oklab(
            np.clip(np.round(c), 0, 255).astype(np.uint8).reshape(-1, 1, 3)
        ).reshape(-1, 3)

    out = labels.copy()
    colors = list(palette)
    pooled: list[tuple[np.ndarray, int]] = []
    for label in np.unique(labels[labels >= 0]).tolist():
        if ink_index is not None and label == ink_index:
            continue
        mask = labels == label
        pix = rgb[mask & sample]
        if pix.shape[0] < 32:
            continue
        base = oklab(np.median(pix[:: max(1, pix.shape[0] // 20000)], axis=0))[0]
        roots = _label_regions(mask)
        comps = _component_bboxes(roots)
        if len(comps) < 2:
            continue
        for root, count, (y0, x0, y1, x1) in comps:
            small = count < _OUTLIER_MIN_AREA
            if small and (_OUTLIER_SMALL_AREA <= 0 or count < _OUTLIER_SMALL_AREA):
                continue
            local = roots[y0:y1, x0:x1] == root
            seen = local & sample[y0:y1, x0:x1]
            if int(seen.sum()) < (_OUTLIER_SMALL_AREA if small else _OUTLIER_MIN_AREA) // 3:
                continue
            med = np.median(rgb[y0:y1, x0:x1][seen], axis=0)
            lab = oklab(med)[0]
            gap = float(np.linalg.norm(lab - base))
            if gap < (_OUTLIER_SMALL_DIST if small else _OUTLIER_DIST):
                continue
            target = -1
            for ref, idx in pooled:
                if float(np.linalg.norm(ref - lab)) < 0.5 * _OUTLIER_DIST:
                    target = idx
                    break
            if target < 0:
                q = np.clip(np.round(med), 0, 255).astype(int)
                colors.append(rgb_to_hex((int(q[0]), int(q[1]), int(q[2]))))
                target = len(colors) - 1
                pooled.append((lab, target))
            out[y0:y1, x0:x1][local] = target
    return out, tuple(colors)


def _recolor_flecks(
    labels: np.ndarray,
    rgb: np.ndarray,
    *,
    ink_index: int | None,
    sample: np.ndarray,
    ink_field: np.ndarray | None = None,
    ink_rgb: tuple[int, int, int] | None = None,
) -> np.ndarray:
    """Re-label small off-colour components from their local label set.

    Rust pleat shading beside lamp ribs snaps to the frame-brown or a mauve
    entry whose colour is fixed elsewhere in the picture. Each component
    smaller than `_OUTLIER_MIN_AREA` whose median source colour is
    ≥ `_OUTLIER_DIST` from its label's median takes the label (present
    within `_FLECK_REACH` px) that matches it best, if that is clearly
    closer. Only local labels compete, so no fleck borrows a far-away colour.
    A fleck with no such match that touches a stroke and reads as ink mixed
    onto its main neighbour joins that neighbour (the ink layer covers it).
    """
    from vectorizer.raster.preprocess import _label_regions

    if _FLECK_MIN_AREA <= 0:
        return labels
    height, width = labels.shape
    lab_img = srgb_u8_to_oklab(np.clip(rgb, 0, 255).astype(np.uint8))
    base: dict[int, np.ndarray] = {}
    base_rgb: dict[int, np.ndarray] = {}
    for label in np.unique(labels[labels >= 0]).tolist():
        pick = (labels == label) & sample
        if int(pick.sum()) >= 32:
            step = max(1, int(pick.sum()) // 20000)
            base[label] = np.median(lab_img[pick][::step], axis=0)
            base_rgb[label] = np.median(rgb[pick][::step], axis=0)
    under = ink_field >= _INK_UNDER if ink_field is not None else None
    ink = np.asarray(ink_rgb, dtype=np.float32) if ink_rgb is not None else None
    out = labels.copy()
    reach = max(1, int(_FLECK_REACH))
    for label in list(base):
        if ink_index is not None and label == ink_index:
            continue
        roots = _label_regions(labels == label)
        for root, count, (y0, x0, y1, x1) in _component_bboxes(roots):
            if count < _FLECK_MIN_AREA or count >= _OUTLIER_MIN_AREA:
                continue
            local = roots[y0:y1, x0:x1] == root
            seen = local & sample[y0:y1, x0:x1]
            pix = lab_img[y0:y1, x0:x1][seen if seen.sum() >= 4 else local]
            med = np.median(pix, axis=0)
            own = float(np.linalg.norm(med - base[label]))
            if own < _OUTLIER_DIST:
                continue
            ya, xa = max(0, y0 - reach), max(0, x0 - reach)
            yb, xb = min(height, y1 + reach), min(width, x1 + reach)
            best, best_d = -1, own * _FLECK_RATIO
            for cand in np.unique(labels[ya:yb, xa:xb]).tolist():
                if cand < 0 or cand == label or cand == ink_index or cand not in base:
                    continue
                d = float(np.linalg.norm(med - base[cand]))
                if d < best_d:
                    best, best_d = cand, d
            if best < 0 and under is not None and ink is not None and _FLECK_INK_RIM > 0:
                best = _ink_mix_neighbour(
                    labels, under, rgb, base_rgb, ink, label, local, (y0, x0, y1, x1), seen
                )
            if best >= 0:
                out[y0:y1, x0:x1][local] = best
    return out


def _ink_mix_neighbour(
    labels: np.ndarray,
    under: np.ndarray,
    rgb: np.ndarray,
    base_rgb: dict[int, np.ndarray],
    ink: np.ndarray,
    label: int,
    local: np.ndarray,
    bbox: tuple[int, int, int, int],
    seen: np.ndarray,
) -> int:
    """Main neighbour label if the fleck touches ink and reads as ink on it."""
    height, width = labels.shape
    y0, x0, y1, x1 = bbox
    ya, xa = max(0, y0 - 1), max(0, x0 - 1)
    yb, xb = min(height, y1 + 1), min(width, x1 + 1)
    grown = np.zeros((yb - ya, xb - xa), dtype=bool)
    grown[y0 - ya : y1 - ya, x0 - xa : x1 - xa] = local
    rim = _dilate8(grown) & ~grown
    if not np.any(rim) or float(under[ya:yb, xa:xb][rim].mean()) < _FLECK_INK_RIM:
        return -1
    nb = labels[ya:yb, xa:xb][rim & ~under[ya:yb, xa:xb]]
    nb = nb[(nb >= 0) & (nb != label)]
    if nb.size == 0:
        return -1
    main = int(np.bincount(nb).argmax())
    if main not in base_rgb:
        return -1
    pix = rgb[y0:y1, x0:x1][seen if seen.sum() >= 4 else local]
    med = np.median(pix, axis=0).astype(np.float32)
    _cov, res = _mix_onto(med[None], base_rgb[main][None].astype(np.float32), ink)
    return main if float(res[0]) <= _FLECK_MIX_RESIDUAL else -1


def _refine_fill_colors(
    labels: np.ndarray,
    rgb: np.ndarray,
    palette: tuple[str, ...],
    *,
    ink_index: int | None,
    sample: np.ndarray,
) -> tuple[str, ...]:
    """Median source colour of each fill label's `sample` pixels.

    Analyzer palette entries are global cluster centres; after spatial
    re-snapping a label covers a different pixel set, so its colour drifts.
    Ink and unused labels keep their palette colour.
    """
    out = list(palette)
    flat_lab = labels[sample]
    flat_rgb = rgb[sample]
    for label in np.unique(flat_lab[flat_lab >= 0]).tolist():
        if ink_index is not None and label == ink_index:
            continue
        pix = flat_rgb[flat_lab == label]
        if pix.shape[0] < 32:
            continue
        if pix.shape[0] > 20000:
            pix = pix[:: pix.shape[0] // 20000]
        med = np.clip(np.round(np.median(pix, axis=0)), 0, 255).astype(int)
        out[label] = rgb_to_hex((int(med[0]), int(med[1]), int(med[2])))
    return tuple(out)


def _component_bboxes(
    roots: np.ndarray,
) -> list[tuple[int, int, tuple[int, int, int, int]]]:
    """(root, pixel count, (y0, x0, y1, x1) exclusive bbox) per component."""
    height, width = roots.shape
    flat = roots.ravel()
    pix = np.flatnonzero(flat >= 0)
    if pix.size == 0:
        return []
    ids = flat[pix]
    order = np.argsort(ids, kind="stable")
    ids = ids[order]
    pix = pix[order]
    ys = pix // width
    xs = pix % width
    uniq, start, counts = np.unique(ids, return_index=True, return_counts=True)
    y0 = np.minimum.reduceat(ys, start)
    y1 = np.maximum.reduceat(ys, start) + 1
    x0 = np.minimum.reduceat(xs, start)
    x1 = np.maximum.reduceat(xs, start) + 1
    return [
        (int(r), int(c), (int(a), int(b), int(e), int(f)))
        for r, c, a, b, e, f in zip(
            uniq.tolist(), counts.tolist(), y0.tolist(), x0.tolist(), y1.tolist(), x1.tolist()
        )
    ]


def _trace_component(
    roots: np.ndarray,
    root: int,
    bbox: tuple[int, int, int, int],
) -> list[list[tuple[float, float]]]:
    """Crack contours of one component, cropped to its padded bbox."""
    height, width = roots.shape
    y0, x0, y1, x1 = bbox
    y0 = max(0, y0 - 1)
    x0 = max(0, x0 - 1)
    y1 = min(height, y1 + 1)
    x1 = min(width, x1 + 1)
    local = roots[y0:y1, x0:x1] == root
    contours = _trace_mask(local)
    if y0 == 0 and x0 == 0:
        return contours
    return [[(x + x0, y + y0) for x, y in contour] for contour in contours]


def _ink_label(palette: tuple[str, ...]) -> int | None:
    """Index of the darkest neutral palette colour when it reads as cel ink."""
    best: int | None = None
    best_luma = 999.0
    for index, color in enumerate(palette):
        r, g, b = hex_to_rgb(color)
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        if luma < best_luma:
            best, best_luma = index, luma
    if best is None:
        return None
    r, g, b = hex_to_rgb(palette[best])
    if best_luma > 42 or max(r, g, b) - min(r, g, b) > 55:
        return None
    return best


def _ink_coverage_field(
    soft: Image.Image,
    ink_rgb: tuple[int, int, int],
    *,
    alpha: np.ndarray | None = None,
    labels: np.ndarray | None = None,
    palette_rgb: np.ndarray | None = None,
    ink_index: int | None = None,
) -> np.ndarray:
    """Float32 HxW ink coverage (0..1) of kept ink strokes.

    Each pixel is modelled as a mix of ink and the nearby fill it was
    anti-aliased against. Coverage is the position on that mixing line;
    colours far off every line are rejected. Components need a solid core so
    soft shade rims never become strokes.
    """
    from vectorizer.raster.preprocess import _label_regions

    rgb = np.asarray(soft.convert("RGB"), dtype=np.float32)
    height, width = rgb.shape[:2]
    ink = np.asarray(ink_rgb, dtype=np.float32)
    if labels is not None and palette_rgb is not None:
        cov, resid = _ink_mix_from_plateaus(rgb, ink, labels, palette_rgb, ink_index)
    else:
        cov, resid = _ink_mix_from_brightest(rgb, ink)
    cov = np.where(resid <= _INK_MIX_RESIDUAL, cov, 0.0)
    solid = np.sqrt(np.sum((rgb - ink) ** 2, axis=2)) <= _INK_SOLID_DIST
    cov = np.where(solid, 1.0, cov).astype(np.float32)
    if alpha is not None:
        cov[np.asarray(alpha) < 8] = 0.0

    mask = cov >= _INK_LEVEL
    if not np.any(mask):
        return np.zeros((height, width), dtype=np.float32)
    # Group through diagonal contacts so 1 px diagonal strokes stay whole.
    grouped = _dilate8(mask)
    roots = _label_regions(grouped)
    flat_roots = roots.ravel()
    area = np.bincount(flat_roots[mask.ravel()], minlength=height * width)
    core = np.bincount(flat_roots[(cov >= _INK_CORE).ravel()], minlength=height * width)
    keep_root = (area >= _INK_MIN_AREA) & (core >= _INK_MIN_CORE_PX)
    keep = grouped & keep_root[np.maximum(roots, 0)]
    # The AA rim just outside a kept stroke carries the sub-pixel isolevel.
    near = _dilate8(keep)
    cov = np.where(near, cov, 0.0).astype(np.float32)
    if _INK_THIN_ADAPT:
        cov = _thin_stroke_rescale(cov)
    return cov


def _fold_mix_fringes(
    labels: np.ndarray,
    rgb: np.ndarray,
    palette_rgb: np.ndarray,
    ink_index: int | None,
) -> np.ndarray:
    """Fold thin AA transition bands between two fills into the nearer fill.

    A JPEG edge between gold and pink snaps to an in-between palette brown,
    which traces as a crust along the seam. Pixels off any plateau whose
    colour sits on the segment between two different nearby plateau fills
    take the closer one. Thin real details are not mixes of their
    neighbours, so they keep their label.
    """
    height, width = labels.shape
    pad = np.pad(labels, 1, constant_values=-1)
    plateau = labels >= 0
    for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
        plateau &= pad[dy : dy + height, dx : dx + width] == labels
    if ink_index is not None:
        plateau &= labels != ink_index
    plat = np.where(plateau, labels, -1).astype(np.int32)
    target = (labels >= 0) & ~plateau
    if ink_index is not None:
        target &= labels != ink_index
    if not np.any(target):
        return labels
    reach = max(1, int(_FRINGE_REACH))
    # Nearest plateau label along each of the four axis directions.
    near: list[np.ndarray] = []
    padded = np.pad(plat, reach, constant_values=-1)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        found = np.full((height, width), -1, dtype=np.int32)
        for step in range(1, reach + 1):
            sy, sx = reach + dy * step, reach + dx * step
            cand = padded[sy : sy + height, sx : sx + width]
            fresh = (found < 0) & (cand >= 0)
            found[fresh] = cand[fresh]
        near.append(found)
    ys, xs = np.nonzero(target)
    pix = rgb[ys, xs]
    pal = np.asarray(palette_rgb, dtype=np.float32)
    best_res = np.full(ys.shape[0], np.float32(_FRINGE_MIX_RESIDUAL), dtype=np.float32)
    best_lab = np.full(ys.shape[0], -1, dtype=np.int32)
    cands = [n[ys, xs] for n in near]
    for i in range(4):
        for j in range(i + 1, 4):
            a, b = cands[i], cands[j]
            ok = (a >= 0) & (b >= 0) & (a != b)
            if not np.any(ok):
                continue
            ca = pal[np.maximum(a, 0)]
            cb = pal[np.maximum(b, 0)]
            seg = cb - ca
            denom = np.maximum(np.einsum("nc,nc->n", seg, seg), 1e-6)
            t = np.einsum("nc,nc->n", pix - ca, seg) / denom
            inner = (t > 0.08) & (t < 0.92)
            model = ca + np.clip(t, 0.0, 1.0)[:, None] * seg
            res = np.sqrt(np.einsum("nc,nc->n", pix - model, pix - model))
            better = ok & inner & (res < best_res)
            best_res = np.where(better, res, best_res)
            best_lab = np.where(better, np.where(t < 0.5, a, b), best_lab)
    take = best_lab >= 0
    out = labels.copy()
    out[ys[take], xs[take]] = best_lab[take].astype(labels.dtype)
    return out


def _box_and(mask: np.ndarray, radius: int) -> np.ndarray:
    """Binary erosion with a (2r+1)² square (outside counts as unset)."""
    out = mask
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        padded = np.pad(out, pad, constant_values=False)
        n = out.shape[axis]
        acc = np.ones_like(out)
        for s in range(2 * radius + 1):
            acc &= np.take(padded, np.arange(s, s + n), axis=axis)
        out = acc
    return out


def _box_or(mask: np.ndarray, radius: int) -> np.ndarray:
    """Binary dilation with a (2r+1)² square."""
    out = mask
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        padded = np.pad(out, pad, constant_values=False)
        n = out.shape[axis]
        acc = np.zeros_like(out)
        for s in range(2 * radius + 1):
            acc |= np.take(padded, np.arange(s, s + n), axis=axis)
        out = acc
    return out


def _merge_slivers(
    labels: np.ndarray,
    palette_rgb: np.ndarray,
    ink_index: int | None,
    *,
    max_dist: float,
    max_steps: int = 4,
) -> np.ndarray:
    """Fold fill parts thinner than 3 px into an adjacent similar fill.

    Thin strips of near-identical browns interleave along shaded bars and
    trace as crust. A 3×3 opening finds the strips; they regrow from
    neighbouring labels whose palette colour is within `max_dist` (OKLab)
    of their own. Thin details in a distinct colour have no such neighbour
    and stay.
    """
    pal_lab = srgb_u8_to_oklab(
        np.clip(np.asarray(palette_rgb), 0, 255).astype(np.uint8).reshape(-1, 1, 3)
    ).reshape(-1, 3)
    dist = np.sqrt(((pal_lab[:, None, :] - pal_lab[None, :, :]) ** 2).sum(axis=2))
    similar = dist <= max_dist
    np.fill_diagonal(similar, False)
    if ink_index is not None:
        similar[ink_index, :] = False
        similar[:, ink_index] = False
    thin = np.zeros(labels.shape, dtype=bool)
    for label in np.unique(labels[labels >= 0]).tolist():
        if not similar[label].any():
            continue
        mask = labels == label
        thin |= mask & ~_box_or(_box_and(mask, 1), 1)
    if not np.any(thin):
        return labels
    # A thin tongue touching its own thick body may simply stay.
    np.fill_diagonal(similar, True)
    if ink_index is not None:
        similar[ink_index, ink_index] = False
    height, width = labels.shape
    out = labels.copy()
    orig = labels.astype(np.int32)
    hole = thin.copy()
    out[hole] = -2
    for _ in range(max(1, max_steps)):
        if not np.any(hole):
            break
        prev = np.pad(out, 1, constant_values=-1)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nb = prev[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width].astype(np.int32)
            ok = hole & (nb >= 0)
            ok[ok] = similar[orig[ok], nb[ok]]
            out[ok] = nb[ok]
            hole &= ~ok
    out[hole] = labels[hole]
    return out


def _stroke_color(
    rgb: np.ndarray,
    stroke: tuple[int, int, np.ndarray],
    ink_rgb: tuple[int, int, int],
) -> str | None:
    """Measured colour of one stroke, or None when it reads as the ink colour."""
    y0, x0, local = stroke
    pix = rgb[y0 : y0 + local.shape[0], x0 : x0 + local.shape[1]][local]
    if pix.shape[0] < 4:
        return None
    luma = 0.299 * pix[:, 0] + 0.587 * pix[:, 1] + 0.114 * pix[:, 2]
    cut = np.quantile(luma, 0.25)
    dark = pix[luma <= cut]
    colour = np.median(dark, axis=0)
    ink = np.asarray(ink_rgb, dtype=np.float32)
    if float(np.linalg.norm(colour - ink)) <= _STROKE_COLOR_MIN_DIST:
        return None
    q = np.clip(np.round(colour / 8.0) * 8.0, 0, 255).astype(int)
    return rgb_to_hex((int(q[0]), int(q[1]), int(q[2])))


def _stroke_families(
    measured: list[str | None],
    sizes: list[int],
    ink_color: str,
) -> list[str]:
    """Group measured stroke colours into a few families (largest strokes seed).

    Each stroke keeps the pixel-weighted mean of its family, so near-duplicate
    dark browns collapse into one result colour.
    """
    if _STROKE_FAMILY_DIST <= 0:
        return [m or ink_color for m in measured]
    order = sorted(range(len(measured)), key=lambda i: -sizes[i])
    seeds: list[np.ndarray] = []
    sums: list[np.ndarray] = []
    weights: list[float] = []
    member = [-1] * len(measured)
    for i in order:
        if measured[i] is None:
            continue
        rgb = np.asarray(hex_to_rgb(measured[i]), dtype=np.float64)
        best, best_d = -1, _STROKE_FAMILY_DIST
        for f, seed in enumerate(seeds):
            d = float(np.linalg.norm(seed - rgb))
            if d < best_d:
                best, best_d = f, d
        if best < 0:
            seeds.append(rgb)
            sums.append(rgb * sizes[i])
            weights.append(float(sizes[i]))
            member[i] = len(seeds) - 1
        else:
            sums[best] = sums[best] + rgb * sizes[i]
            weights[best] += float(sizes[i])
            member[i] = best
    family_hex = []
    for total, weight in zip(sums, weights):
        c = np.clip(np.round(total / max(weight, 1.0)), 0, 255).astype(int)
        family_hex.append(rgb_to_hex((int(c[0]), int(c[1]), int(c[2]))))
    return [family_hex[m] if m >= 0 else ink_color for m in member]


def _mix_onto(
    rgb: np.ndarray, fill: np.ndarray, ink: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Coverage and residual of `rgb` on the fill↔ink line (per pixel)."""
    span = fill - ink
    denom = np.einsum("...c,...c->...", span, span)
    along = np.einsum("...c,...c->...", fill - rgb, span) / np.maximum(denom, 1e-6)
    cov = np.clip(along, 0.0, 1.0)
    model = fill - cov[..., None] * span
    diff = rgb - model
    resid = np.sqrt(np.einsum("...c,...c->...", diff, diff))
    # Fills close to ink carry no usable mixing line.
    resid = np.where(denom > 60.0 * 60.0, resid, np.float32(1e6))
    return cov.astype(np.float32), resid.astype(np.float32)


def _ink_mix_from_brightest(rgb: np.ndarray, ink: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mix against the brightest pixel within `_INK_BG_RADIUS` (no labels)."""
    height, width = rgb.shape[:2]
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    r = max(1, int(_INK_BG_RADIUS))
    pad_l = np.pad(luma, r, mode="edge")
    pad_c = np.pad(rgb, ((r, r), (r, r), (0, 0)), mode="edge")
    best = np.full((height, width), -1.0, dtype=np.float32)
    bg = np.zeros_like(rgb)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            shifted = pad_l[r + dy : r + dy + height, r + dx : r + dx + width]
            better = shifted > best
            best = np.where(better, shifted, best)
            bg[better] = pad_c[r + dy : r + dy + height, r + dx : r + dx + width][better]
    return _mix_onto(rgb, bg, ink)


def _ink_mix_from_plateaus(
    rgb: np.ndarray,
    ink: np.ndarray,
    labels: np.ndarray,
    palette_rgb: np.ndarray,
    ink_index: int | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Mix against the best-fitting clean fill colour within `_INK_FILL_RADIUS`.

    Candidates are palette colours of plateau pixels (all 4-neighbours share
    the label), so 1–2 px AA fringe labels never act as the paper. The
    candidate with the smallest residual wins; a pixel next to its own fill
    plateau therefore reads as that fill (coverage 0), not as faint ink.
    """
    height, width = labels.shape
    pad = np.pad(labels, 1, constant_values=-1)
    plateau = labels >= 0
    for dy, dx in ((0, 1), (2, 1), (1, 0), (1, 2)):
        plateau &= pad[dy : dy + height, dx : dx + width] == labels
    if ink_index is not None:
        plateau &= labels != ink_index
    plat = np.where(plateau, labels, -1).astype(np.int32)
    r = max(1, int(_INK_FILL_RADIUS))
    pad_p = np.pad(plat, r, constant_values=-1)
    pal = np.asarray(palette_rgb, dtype=np.float32)
    best_cov = np.zeros((height, width), dtype=np.float32)
    best_res = np.full((height, width), np.float32(1e6), dtype=np.float32)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            cand = pad_p[r + dy : r + dy + height, r + dx : r + dx + width]
            valid = cand >= 0
            if not np.any(valid):
                continue
            ys, xs = np.nonzero(valid & (best_res > 0.5))
            if ys.size == 0:
                continue
            cov, res = _mix_onto(rgb[ys, xs], pal[cand[ys, xs]], ink)
            better = res < best_res[ys, xs]
            best_res[ys[better], xs[better]] = res[better]
            best_cov[ys[better], xs[better]] = cov[better]
    # No plateau nearby (inside wide ink or busy texture): brightest fallback.
    lost = best_res >= 1e5
    if np.any(lost):
        cov_b, res_b = _ink_mix_from_brightest(rgb, ink)
        best_cov[lost] = cov_b[lost]
        best_res[lost] = res_b[lost]
    return best_cov, best_res


def _thin_stroke_rescale(cov: np.ndarray) -> np.ndarray:
    """Rescale so the fixed isolevel keeps the ink mass of sub-pixel strokes.

    A blurred hairline peaks at m < 1; cutting at 0.5 draws a sliver (or
    nothing). For a peak m the mass-preserving cut is m·(1 − m/2), so the
    field is scaled locally to put that cut at `_INK_LEVEL`. Solid strokes
    (m = 1) are unchanged.
    """
    peak = _local_max(cov, radius=2)
    m = np.clip(peak, 1e-3, 1.0)
    cut = np.maximum(m * (1.0 - 0.5 * m), _INK_THIN_FLOOR)
    scale = np.where(peak >= _INK_THIN_MIN_PEAK, _INK_LEVEL / cut, 1.0)
    return np.clip(cov * scale, 0.0, 1.0).astype(np.float32)


def _local_max(field: np.ndarray, *, radius: int) -> np.ndarray:
    height, width = field.shape
    padded = np.pad(field, radius, mode="constant")
    out = np.zeros_like(field)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            np.maximum(out, padded[dy : dy + height, dx : dx + width], out=out)
    return out


def _dilate8(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, constant_values=False)
    height, width = mask.shape
    out = np.zeros_like(mask)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            out |= padded[dy : dy + height, dx : dx + width]
    return out


def _regrow_fills_under_ink(
    labels: np.ndarray,
    ink_field: np.ndarray,
    ink_index: int,
    *,
    max_steps: int = 10,
) -> np.ndarray:
    """Replace ink and AA-fringe pixels with the nearest fill label.

    The ink layer paints over these pixels, so fills run continuously under
    every stroke and no seam can open between paint and ink.
    """
    under = ink_field >= _INK_UNDER
    for _ in range(max(0, _INK_UNDER_GROW)):
        under = _dilate8(under)
    unknown = (labels >= 0) & (under | (labels == ink_index))
    if not np.any(unknown):
        return labels
    out = labels.copy()
    out[unknown] = -2
    height, width = out.shape
    for _ in range(max(1, max_steps)):
        hole = out == -2
        if not np.any(hole):
            break
        prev = np.pad(out, 1, constant_values=-1)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nb = prev[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
            take = hole & (nb >= 0)
            out[take] = nb[take]
            hole &= ~take
    left = out == -2
    out[left] = labels[left]
    return out


def _fill_mode_radius(long_side: int) -> int:
    for min_side, radius in _FILL_MODE_STEPS:
        if long_side >= min_side:
            return radius
    return 0


def _mode_filter_labels(labels: np.ndarray, *, radius: int, passes: int) -> np.ndarray:
    """Majority vote in a (2r+1)² window: smooths JPEG-ragged fill seams.

    Only safe once ink lives on its own layer — a box majority would erase
    1–2 px strokes. Transparent pixels (-1) never vote or change.
    """
    out = labels
    size = (2 * radius + 1) ** 2
    for _ in range(max(0, passes)):
        height, width = out.shape
        best = np.zeros((height, width), dtype=np.int32)
        winner = out.copy()
        for label in np.unique(out[out >= 0]).tolist():
            hits = (out == label).astype(np.int32)
            padded = np.pad(hits, radius + 1)
            integ = padded.cumsum(0).cumsum(1)
            k = 2 * radius + 1
            box = integ[k:, k:] - integ[:-k, k:] - integ[k:, :-k] + integ[:-k, :-k]
            box = box[:height, :width]
            better = box > best
            best = np.where(better, box, best)
            winner = np.where(better, label, winner)
        change = (out >= 0) & (winner != out) & (2 * best > size)
        if not np.any(change):
            break
        out = np.where(change, winner, out).astype(labels.dtype)
    return out


def _ink_layer_paths(
    ink_field: np.ndarray,
    *,
    corner: float,
    decimals: int,
) -> list[tuple[str, tuple[int, int, np.ndarray]]]:
    """Marching-squares ink outlines → one evenodd path per stroke component.

    Each entry also carries the stroke's pixel mask as (y0, x0, local mask).
    """
    from vectorizer.raster.preprocess import _label_regions
    from vectorizer.vectorize.iso_contour import marching_squares

    mask = ink_field >= _INK_LEVEL
    if not np.any(mask):
        return []
    roots = _label_regions(_dilate8(mask))
    height, width = ink_field.shape
    out: list[tuple[str, tuple[int, int, np.ndarray]]] = []
    for root, count, (y0, x0, y1, x1) in _component_bboxes(roots):
        y0 = max(0, y0 - 1)
        x0 = max(0, x0 - 1)
        y1 = min(height, y1 + 1)
        x1 = min(width, x1 + 1)
        local = np.where(roots[y0:y1, x0:x1] == root, ink_field[y0:y1, x0:x1], 0.0)
        if float(local.max()) < _INK_LEVEL:
            continue
        subpaths: list[str] = []
        for contour in marching_squares(local, level=_INK_LEVEL):
            ring = [(x + x0 + 0.5, y + y0 + 0.5) for x, y in contour]
            if len(ring) < 5 or abs(_ring_area(ring)) < 1.5:
                continue
            ring = _smooth_iso_ring(ring, passes=_INK_RING_PASSES)
            if _INK_TAUBIN_PASSES > 0:
                ring = _taubin_ring(ring, passes=_INK_TAUBIN_PASSES)
            ring = orient_clockwise(ring)
            if _INK_SIMPLIFY_EPS > 0 and len(ring) >= 8:
                simplified = simplify_closed_ring(ring, epsilon=_INK_SIMPLIFY_EPS)
                if len(simplified) >= 4:
                    ring = orient_clockwise(simplified)
            path_d = _corner_catmull_path_d(ring, corner_degrees=corner, decimals=decimals)
            if path_d:
                subpaths.append(path_d)
        if subpaths:
            out.append((" ".join(subpaths), (y0, x0, local >= _INK_LEVEL)))
    return out


def _taubin_ring(
    ring: list[tuple[float, float]],
    *,
    passes: int,
    lam: float = 0.5,
    mu: float = -0.53,
) -> list[tuple[float, float]]:
    """λ/μ smoothing: flattens jitter on straight sides without shrinking ends."""
    pts = np.asarray(ring, dtype=np.float64)
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 6:
        return ring
    for _ in range(max(0, passes)):
        for factor in (lam, mu):
            lap = 0.5 * (np.roll(pts, 1, axis=0) + np.roll(pts, -1, axis=0)) - pts
            pts = pts + factor * lap
    out = [(float(x), float(y)) for x, y in pts]
    out.append(out[0])
    return out


def _ring_area(ring: list[tuple[float, float]]) -> float:
    pts = np.asarray(ring, dtype=np.float64)
    x = pts[:, 0]
    y = pts[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _smooth_iso_ring(
    ring: list[tuple[float, float]],
    *,
    passes: int,
) -> list[tuple[float, float]]:
    pts = np.asarray(ring, dtype=np.float64)
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 5:
        return ring
    for _ in range(max(0, passes)):
        pts = 0.25 * np.roll(pts, 1, axis=0) + 0.5 * pts + 0.25 * np.roll(pts, -1, axis=0)
    out = [(float(x), float(y)) for x, y in pts]
    out.append(out[0])
    return out


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


