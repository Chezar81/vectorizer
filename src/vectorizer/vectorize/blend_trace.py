"""Trace blended artwork with soft-coverage iso-contours.

Hard region labels still drive topology. Boundaries are the 0.5 isolevel of a
per-label coverage field (marching squares), optionally sampled from a soft
source so F6 retrace keeps anti-alias cues after the segmentation is edited.
"""

from __future__ import annotations

import math
import time

import numpy as np
from PIL import Image

from vectorizer.domain.settings import TraceSettings, normalize_hex
from vectorizer.errors import TraceError
from vectorizer.jobs.progress import STAGE_COLORS, STAGE_CONTOURS, STAGE_CURVES, ProgressCallback
from vectorizer.raster.color import (
    hex_to_rgb,
    nearest_oklab,
    project_coverage,
    rgb_to_hex,
    srgb_u8_to_oklab,
)
from vectorizer.svg.parse import parse_svg_document
from vectorizer.vectorize.backend import TraceResult
from vectorizer.vectorize.curves import fit_closed_contour, segments_to_path_d
from vectorizer.vectorize.iso_contour import (
    _dilate4,
    coverage_field,
    marching_squares,
    orient_clockwise,
)

_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))
_EMPTY = -1
# Megapixel cel scenes: trace at a capped working size, then scale paths back.
# Full-resolution iso-contours were 40s+ and often crunchier, not closer.
_MAX_WORKING_SIDE = 1280
# Cutout layers trace the source's own AA coverage, so only a light blur is
# needed; ≥1.5 px blur dropped 2 px ink strokes below the 0.5 isolevel.
_CUTOUT_SIGMA = 0.9
# Along-contour smoothing of cutout iso rings: removes residual pixel-stair
# wobble on long letter / shield edges without eroding thin strokes.
_CUTOUT_RING_PASSES = 8


class BlendTracer:
    name = "blend"
    description = (
        "Palette-constrained tracer. Soft coverage iso-contours place curves "
        "inside anti-aliased pixels; fills are exactly the chosen palette colors."
    )

    def trace(
        self,
        image: Image.Image,
        settings: TraceSettings,
        palette: tuple[str, ...],
        *,
        soft_source: Image.Image | None = None,
        label_override: np.ndarray | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> TraceResult:
        report = on_progress or (lambda _stage, _fraction: None)
        validated = settings.validated()
        colors = tuple(normalize_hex(color) for color in palette)
        if len(colors) < 1:
            raise TraceError("Blend tracing needs at least one palette color.")
        source = image.convert("RGBA")
        if source.size[0] <= 0 or source.size[1] <= 0:
            raise TraceError("Cannot trace an empty image.")
        started = time.perf_counter()
        out_w, out_h = source.size
        rgba = source
        scale_back = 1.0
        soft_for_labels = soft_source
        report(STAGE_COLORS, 0.05)
        if label_override is None:
            max_side = max(out_w, out_h)
            if max_side > _MAX_WORKING_SIDE:
                scale = _MAX_WORKING_SIDE / float(max_side)
                work_size = (
                    max(1, int(round(out_w * scale))),
                    max(1, int(round(out_h * scale))),
                )
                rgba = source.resize(work_size, Image.Resampling.BOX)
                scale_back = out_w / float(rgba.size[0])
                if soft_for_labels is not None:
                    soft_for_labels = soft_for_labels.convert("RGBA").resize(
                        work_size, Image.Resampling.BILINEAR
                    )
        if label_override is not None:
            if label_override.shape != (source.size[1], source.size[0]):
                raise TraceError("Label override size does not match the image.")
            labels = label_override.astype(np.int16, copy=True)
            rgba = source
            pixels_lab = srgb_u8_to_oklab(np.asarray(rgba, dtype=np.uint8)[..., :3])
            palette_lab = srgb_u8_to_oklab(
                np.asarray([hex_to_rgb(c) for c in colors], dtype=np.uint8)
            )
            bg = np.asarray(
                [[validated.background_r, validated.background_g, validated.background_b]],
                dtype=np.uint8,
            )
            bg_lab = srgb_u8_to_oklab(bg)[0]
        else:
            labels, pixels_lab, palette_lab, bg_lab = label_regions(rgba, colors, validated)
            labels = _drop_specks(labels, validated.filter_speckle)
            if validated.preserve_transparency and float((labels < 0).mean()) >= 0.02:
                _absorb_between_fringe(labels, pixels_lab, palette_lab)
        report(STAGE_CONTOURS, 0.22)
        soft_lab = None
        if soft_for_labels is not None:
            soft_rgba = soft_for_labels.convert("RGBA")
            if soft_rgba.size != rgba.size:
                soft_rgba = soft_rgba.resize(rgba.size, Image.Resampling.BILINEAR)
            soft_lab = srgb_u8_to_oklab(np.asarray(soft_rgba, dtype=np.uint8)[..., :3])
        elif soft_source is None and scale_back != 1.0:
            # Coverage from the working raster; geometry scales back to source.
            soft_lab = pixels_lab
        svg = _svg_from_labels(
            rgba,
            labels,
            colors,
            validated,
            pixels_lab=pixels_lab,
            palette_lab=palette_lab,
            bg_lab=bg_lab,
            soft_lab=soft_lab,
            output_size=(out_w, out_h),
            coordinate_scale=scale_back,
            on_progress=report,
        )
        document = parse_svg_document(svg, backend_name=self.name)
        elapsed = time.perf_counter() - started
        warnings: list[str] = []
        if document.path_count == 0:
            warnings.append("Tracing produced no paths.")
        return TraceResult(
            document=document,
            elapsed_seconds=elapsed,
            settings=validated,
            backend_name=self.name,
            warnings=tuple(warnings),
        )


def label_regions(
    image: Image.Image,
    palette: tuple[str, ...],
    settings: TraceSettings,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (labels, pixels_lab, palette_lab, bg_lab). Label -1 is empty."""
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    height, width = rgba.shape[:2]
    palette_rgb = np.asarray([hex_to_rgb(color) for color in palette], dtype=np.uint8)
    pixels_lab = srgb_u8_to_oklab(rgba[..., :3])
    palette_lab = srgb_u8_to_oklab(palette_rgb)
    # Mild chroma emphasis for illustration recipes (no posterize pass).
    chroma = 1.35 if settings.target_colors == 0 and settings.corner_threshold <= 45 else 1.0
    index, dist = nearest_oklab(pixels_lab, palette_lab, chroma_weight=chroma)
    labels = index.astype(np.int16)
    alpha = rgba[..., 3]
    labels[alpha < 8] = _EMPTY

    # True ink only: dark AND low-chroma. Chromatic dark fills (teal body,
    # navy logo) must not be treated as outline ink or they collapse to black.
    # Darkest first so stroke forcing prefers near-black over dark grey.
    dark_ids = sorted(
        (
            i
            for i, color in enumerate(palette_rgb)
            if (
                0.299 * int(color[0]) + 0.587 * int(color[1]) + 0.114 * int(color[2])
                <= 40
                and (int(color.max()) - int(color.min())) <= 48
            )
        ),
        key=lambda i: float(
            0.299 * int(palette_rgb[i][0])
            + 0.587 * int(palette_rgb[i][1])
            + 0.114 * int(palette_rgb[i][2])
        ),
    )
    # Bright palette slots (white letters, specular eye dots) must survive
    # stroke forcing and spatial majority — a 2×2 white eye highlight is
    # otherwise voted into black by its ink neighbourhood.
    bright_ids = [
        i
        for i, color in enumerate(palette_rgb)
        if (0.299 * int(color[0]) + 0.587 * int(color[1]) + 0.114 * int(color[2]))
        >= 200
    ]
    protect_ids = list(dict.fromkeys([*dark_ids, *bright_ids]))
    if dark_ids:
        # Reclaim flat chromatic darks first, then force strokes onto ink so
        # reclaim cannot undo the outline pass.
        _reclaim_chromatic_darks(labels, rgba[..., :3], palette_rgb, dark_ids)
        _force_stroke_ink(labels, rgba[..., :3], dark_ids, protect=bright_ids)
        _recover_dark_ink(labels, rgba[..., :3], palette_lab, dark_ids)

    # Cel outlines are thin; treat dark ink labels as stable so blend absorb
    # cannot erase them into neighbouring fills.
    stable_gate = 0.0016 * max(1.0, chroma)
    stable = (dist <= stable_gate) & (labels >= 0)
    if dark_ids:
        dark_mask = np.isin(labels, np.asarray(dark_ids, dtype=np.int16))
        stable |= dark_mask
    if bright_ids:
        bright_mask = np.isin(labels, np.asarray(bright_ids, dtype=np.int16))
        stable |= bright_mask
    unstable_fraction = float((~stable & (labels >= 0)).mean()) if height and width else 0.0
    if unstable_fraction <= 0.45:
        _absorb_blends(labels, stable, pixels_lab, palette_lab, protect=protect_ids)
    # Light spatial cleanup only — aggressive passes merged accents into fills.
    _spatial_clean_labels(labels, protect=protect_ids, passes=1, majority=7)
    # Final stroke pass after cleanup — outlines must win (bright stays bright).
    if dark_ids:
        _force_stroke_ink(labels, rgba[..., :3], dark_ids, protect=bright_ids)
    # Re-snap very bright source pixels to their bright palette slot after the
    # ink passes — eye speculars are 2–4 px and otherwise remain black.
    if bright_ids:
        _restore_bright_specks(labels, rgba[..., :3], palette_rgb, bright_ids)

    bg = np.asarray(
        [[settings.background_r, settings.background_g, settings.background_b]],
        dtype=np.uint8,
    )
    bg_lab = srgb_u8_to_oklab(bg)[0]
    if settings.remove_background:
        limit = (max(0, settings.background_tolerance) / 255.0) ** 2 * 0.25
        delta = pixels_lab - bg_lab
        bg_dist = np.einsum("hwc,hwc->hw", delta, delta, optimize=True)
        closer_than_ink = bg_dist + 1e-8 < dist
        labels[(bg_dist <= max(limit, 0.004)) & closer_than_ink] = _EMPTY
    return labels, pixels_lab, palette_lab, bg_lab


def _spatial_clean_labels(
    labels: np.ndarray,
    *,
    protect: list[int] | None = None,
    passes: int = 2,
    majority: int = 6,
) -> None:
    """Flip pixels that disagree with a strong 8-neighbour consensus."""
    height, width = labels.shape
    if height < 3 or width < 3:
        return
    protect_arr = (
        np.asarray(list(protect), dtype=np.int16) if protect else np.empty(0, dtype=np.int16)
    )
    for _ in range(passes):
        padded = np.pad(labels, 1, mode="edge")
        flat = np.stack(
            [
                padded[:-2, :-2],
                padded[:-2, 1:-1],
                padded[:-2, 2:],
                padded[1:-1, :-2],
                padded[1:-1, 2:],
                padded[2:, :-2],
                padded[2:, 1:-1],
                padded[2:, 2:],
            ],
            axis=0,
        ).reshape(8, -1)
        valid_flat = flat >= 0
        current = labels.reshape(-1)
        counts = np.zeros(current.shape[0], dtype=np.int16)
        winners = np.full(current.shape[0], -2, dtype=np.int16)
        for k in range(8):
            candidate = flat[k]
            usable = valid_flat[k]
            agree = np.zeros(candidate.shape[0], dtype=np.int16)
            for j in range(8):
                agree += (valid_flat[j] & usable & (flat[j] == candidate)).astype(np.int16)
            better = usable & (agree >= majority) & (agree > counts)
            winners[better] = candidate[better]
            counts[better] = agree[better]
        flip = (winners >= 0) & (winners != current) & (current >= 0)
        if protect_arr.size:
            flip &= ~np.isin(current, protect_arr)
        if not np.any(flip):
            return
        current[flip] = winners[flip]
        labels[:] = current.reshape(height, width)


def _force_stroke_ink(
    labels: np.ndarray,
    rgb: np.ndarray,
    dark_ids: list[int],
    *,
    protect: list[int] | None = None,
) -> None:
    """Hard-assign cel stroke pixels to the darkest ink label.

    JPEG browns sit nearer muddy palette slots than near-black; without a hard
    stroke pass the couch outlines dissolve into orange/brown fills.
    """
    if not dark_ids:
        return
    gray = (
        0.299 * rgb[..., 0].astype(np.float32)
        + 0.587 * rgb[..., 1].astype(np.float32)
        + 0.114 * rgb[..., 2].astype(np.float32)
    )
    padded = np.pad(gray, 1, mode="edge")
    neigh_max = np.maximum.reduce(
        [
            padded[:-2, 1:-1],
            padded[2:, 1:-1],
            padded[1:-1, :-2],
            padded[1:-1, 2:],
            padded[:-2, :-2],
            padded[:-2, 2:],
            padded[2:, :-2],
            padded[2:, 2:],
        ]
    )
    sat = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    contrast = neigh_max - gray
    # Tight stroke band: true cel ink, not couch shadow bowls.
    stroke = (
        (labels >= 0)
        & (gray <= 58.0)
        & (contrast >= 48.0)
        & (sat <= 58)
    )
    if protect:
        stroke &= ~np.isin(labels, np.asarray(protect, dtype=np.int16))
    if not np.any(stroke):
        return
    ink_id = int(dark_ids[0])
    labels[stroke] = ink_id
    # 1px bridge between broken stroke pixels so outlines stay continuous.
    ink = labels == ink_id
    padded = np.pad(ink, 1, mode="constant")
    near = (
        padded[:-2, 1:-1]
        | padded[2:, 1:-1]
        | padded[1:-1, :-2]
        | padded[1:-1, 2:]
    )
    bridge = (~ink) & near & (labels >= 0) & (gray <= 70.0) & (contrast >= 35.0) & (sat <= 65)
    if protect:
        bridge &= ~np.isin(labels, np.asarray(protect, dtype=np.int16))
        # Never bridge into bright source pixels (eye speculars).
        bridge &= gray < 180.0
    labels[bridge] = ink_id


def _restore_bright_specks(
    labels: np.ndarray,
    rgb: np.ndarray,
    palette_rgb: np.ndarray,
    bright_ids: list[int],
) -> None:
    """Force near-white source pixels onto the nearest bright palette slot."""
    if not bright_ids:
        return
    gray = (
        0.299 * rgb[..., 0].astype(np.float32)
        + 0.587 * rgb[..., 1].astype(np.float32)
        + 0.114 * rgb[..., 2].astype(np.float32)
    )
    sat = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    candidates = (labels >= 0) & (gray >= 210.0) & (sat <= 40)
    if not np.any(candidates):
        return
    bright = np.asarray(bright_ids, dtype=np.int16)
    # Nearest bright palette entry in RGB for those pixels.
    pix = rgb[candidates].astype(np.int16)
    best = np.full(pix.shape[0], bright[0], dtype=np.int16)
    best_d = np.full(pix.shape[0], np.inf, dtype=np.float32)
    for bid in bright_ids:
        center = palette_rgb[bid].astype(np.int16)
        d = ((pix - center) ** 2).sum(axis=1).astype(np.float32)
        take = d < best_d
        best[take] = bid
        best_d[take] = d[take]
    labels[candidates] = best


def _recover_dark_ink(
    labels: np.ndarray,
    rgb: np.ndarray,
    palette_lab: np.ndarray,
    dark_ids: list[int],
) -> None:
    """Assign dark palette labels to dark pixels abutting much brighter fills."""
    gray = (
        0.299 * rgb[..., 0].astype(np.float32)
        + 0.587 * rgb[..., 1].astype(np.float32)
        + 0.114 * rgb[..., 2].astype(np.float32)
    )
    padded = np.pad(gray, 1, mode="edge")
    neigh_max = np.maximum.reduce(
        [
            padded[:-2, 1:-1],
            padded[2:, 1:-1],
            padded[1:-1, :-2],
            padded[1:-1, 2:],
        ]
    )
    # Cel JPEG outlines are often luma 30–70 browns, not pure black. Catch
    # stroke-like pixels: dark enough + much brighter neighbour + low-ish sat.
    outline = (gray <= 72.0) & ((neigh_max - gray) >= 45.0) & (labels >= 0)
    if not np.any(outline):
        return
    already = np.isin(labels, np.asarray(dark_ids, dtype=np.int16))
    candidates = outline & ~already
    if not np.any(candidates):
        return
    ys, xs = np.nonzero(candidates)
    # Skip saturated colours (orange couch shading) even when luminance is low.
    sat = np.max(rgb[ys, xs], axis=1).astype(np.int16) - np.min(
        rgb[ys, xs], axis=1
    ).astype(np.int16)
    keep = sat <= 55
    if not np.any(keep):
        return
    ys, xs = ys[keep], xs[keep]
    pix = rgb[ys, xs].astype(np.uint8)
    pix_lab = srgb_u8_to_oklab(pix.reshape(ys.shape[0], 1, 3))[:, 0, :]
    best = np.full(ys.shape[0], dark_ids[0], dtype=np.int16)
    best_dist = np.full(ys.shape[0], np.inf, dtype=np.float32)
    for ink_id in dark_ids:
        delta = pix_lab - palette_lab[ink_id]
        dist = np.einsum("nc,nc->n", delta, delta, optimize=True)
        better = dist < best_dist
        best_dist[better] = dist[better]
        best[better] = int(ink_id)
    labels[ys, xs] = best


def _reclaim_chromatic_darks(
    labels: np.ndarray,
    rgb: np.ndarray,
    palette_rgb: np.ndarray,
    dark_ids: list[int],
) -> None:
    """Move saturated dark fills off near-black ink slots (teal body ≠ black stroke).

    Must NOT reclaim high-contrast stroke pixels — JPEG cel ink is often a dark
    brown with sat≈50, and reclaiming those erases every outline.
    """
    if not dark_ids:
        return
    ink = np.asarray(dark_ids, dtype=np.int16)
    ink_mask = np.isin(labels, ink)
    if not np.any(ink_mask):
        return
    sat = rgb.max(axis=2).astype(np.int16) - rgb.min(axis=2).astype(np.int16)
    gray = (
        0.299 * rgb[..., 0].astype(np.float32)
        + 0.587 * rgb[..., 1].astype(np.float32)
        + 0.114 * rgb[..., 2].astype(np.float32)
    )
    padded = np.pad(gray, 1, mode="edge")
    neigh_max = np.maximum.reduce(
        [
            padded[:-2, 1:-1],
            padded[2:, 1:-1],
            padded[1:-1, :-2],
            padded[1:-1, 2:],
        ]
    )
    contrast = neigh_max - gray
    # Flat chromatic fills only (teal body, navy logo). High local contrast =
    # stroke, leave on ink.
    bad = ink_mask & (sat >= 40) & (gray >= 22.0) & (contrast < 35.0)
    if not np.any(bad):
        return
    fill_ids = [i for i in range(len(palette_rgb)) if i not in set(dark_ids)]
    if not fill_ids:
        return
    ys, xs = np.nonzero(bad)
    pix = rgb[ys, xs].astype(np.int16)
    best = labels[ys, xs].astype(np.int16, copy=True)
    best_dist = np.full(ys.shape[0], np.inf, dtype=np.float32)
    for fid in fill_ids:
        color = palette_rgb[fid].astype(np.int16)
        dist = np.abs(pix - color).sum(axis=1).astype(np.float32)
        better = dist < best_dist
        best_dist[better] = dist[better]
        best[better] = int(fid)
    labels[ys, xs] = best


def _refine_palette_from_labels(
    rgb: np.ndarray,
    labels: np.ndarray,
    palette: tuple[str, ...],
    *,
    min_pixels: int = 32,
    drift_tol: int = 18,
) -> tuple[str, ...]:
    """Replace each used palette ink with the median RGB of its labeled pixels.

    Small AA fringe drift keeps the authored palette hex so logos stay exact;
    large corrections (wrong wall ink, etc.) adopt the true flat fill.
    """
    refined: list[str] = []
    for i, color in enumerate(palette):
        mask = labels == i
        count = int(mask.sum())
        if count < min_pixels:
            refined.append(color)
            continue
        median = np.median(rgb[mask], axis=0)
        new = (int(median[0]), int(median[1]), int(median[2]))
        old = hex_to_rgb(color)
        old_luma = 0.299 * old[0] + 0.587 * old[1] + 0.114 * old[2]
        new_luma = 0.299 * new[0] + 0.587 * new[1] + 0.114 * new[2]
        # Never lighten dedicated cel outline inks — JPEG fringe pulls them up.
        if old_luma <= 55 and new_luma > old_luma:
            refined.append(color)
            continue
        if (
            abs(new[0] - old[0]) + abs(new[1] - old[1]) + abs(new[2] - old[2])
            <= drift_tol
        ):
            refined.append(color)
            continue
        refined.append(normalize_hex(rgb_to_hex(new)))
    return tuple(refined)


def labels_to_image(labels: np.ndarray, palette: tuple[str, ...]) -> Image.Image:
    """RGBA segmentation: palette color, or transparent where the label is empty."""
    height, width = labels.shape
    out = np.zeros((height, width, 4), dtype=np.uint8)
    colors = np.asarray([hex_to_rgb(color) for color in palette], dtype=np.uint8)
    valid = labels >= 0
    if np.any(valid):
        out[valid, :3] = colors[labels[valid]]
        out[valid, 3] = 255
    return Image.fromarray(out, mode="RGBA")


def _absorb_blends(
    labels: np.ndarray,
    stable: np.ndarray,
    pixels_lab: np.ndarray,
    palette_lab: np.ndarray,
    *,
    protect: list[int] | None = None,
) -> None:
    """Give mixed edge pixels the neighboring solid color they belong to."""
    height, width = labels.shape
    unstable = ~stable & (labels >= 0)
    if protect:
        # Never dissolve protected ink labels into neighbouring fills.
        unstable &= ~np.isin(labels, np.asarray(protect, dtype=np.int16))
    count = int(np.count_nonzero(unstable))
    if count == 0 or count > 1_500_000:
        return
    ys, xs = np.nonzero(unstable)
    for _pass in range(3):
        active = ~stable[ys, xs] & (labels[ys, xs] >= 0)
        if protect:
            active &= ~np.isin(labels[ys, xs], np.asarray(protect, dtype=np.int16))
        if not np.any(active):
            break
        ay = ys[active]
        ax = xs[active]
        best_dist = np.full(ay.shape[0], np.inf, dtype=np.float32)
        best_label = labels[ay, ax].astype(np.int16, copy=True)
        found = np.zeros(ay.shape[0], dtype=bool)
        pix = pixels_lab[ay, ax]
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny = ay + dy
            nx = ax + dx
            inside = (ny >= 0) & (ny < height) & (nx >= 0) & (nx < width)
            if not np.any(inside):
                continue
            iy = ny[inside]
            ix = nx[inside]
            neighbor = labels[iy, ix]
            # `usable` is length n' = inside.sum(), matching flatnonzero(inside).
            usable = stable[iy, ix] & (neighbor >= 0)
            if not np.any(usable):
                continue
            idx = np.flatnonzero(inside)[usable]
            neigh = neighbor[usable].astype(np.intp, copy=False)
            delta = pix[idx] - palette_lab[neigh]
            dist = np.einsum("nc,nc->n", delta, delta, optimize=True)
            better = dist < best_dist[idx]
            if not np.any(better):
                continue
            take = idx[better]
            best_dist[take] = dist[better]
            best_label[take] = neigh[better].astype(np.int16, copy=False)
            found[take] = True
        if not np.any(found):
            break
        fy = ay[found]
        fx = ax[found]
        labels[fy, fx] = best_label[found]
        stable[fy, fx] = True


def _absorb_between_fringe(
    labels: np.ndarray,
    pixels_lab: np.ndarray,
    palette_lab: np.ndarray,
) -> None:
    """Fold thin AA slivers into the inks they blend between.

    The black↔olive ramp of a badge passes through charcoal, so a 1–2 px
    charcoal ribbon traces along every outline. A thin pixel whose colour lies
    on the segment between the labels on either side of it is fringe, not a
    feature; real thin ink (lion strokes, claw tips) is not "between" anything.
    """
    height, width = labels.shape
    if height < 5 or width < 5:
        return
    valid = labels >= 0
    padded = np.pad(labels, 1, mode="constant", constant_values=_EMPTY)
    # Opening residual: pixels with no same-label 3×3 core anywhere around them.
    core = np.ones_like(valid)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            core &= padded[dy : dy + height, dx : dx + width] == labels
    core_pad = np.pad(core, 1, mode="constant")
    covered = np.zeros_like(valid)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            covered |= core_pad[dy : dy + height, dx : dx + width] & (
                padded[dy : dy + height, dx : dx + width] == labels
            )
    thin = valid & ~covered
    if not np.any(thin):
        return
    ys, xs = np.nonzero(thin)
    current = labels[ys, xs]
    pix = pixels_lab[ys, xs]
    own = palette_lab[current]
    own_d = np.einsum("nc,nc->n", pix - own, pix - own)
    best_d = own_d * 0.5
    best_label = current.copy()
    pad2 = np.pad(labels, 2, mode="constant", constant_values=_EMPTY)
    for r in (1, 2):
        for dy, dx in ((0, r), (r, 0), (r, r), (r, -r)):
            a = pad2[ys + 2 - dy, xs + 2 - dx]
            b = pad2[ys + 2 + dy, xs + 2 + dx]
            ok = (a >= 0) & (b >= 0) & (a != b) & (a != current) & (b != current)
            if not np.any(ok):
                continue
            la = palette_lab[np.where(ok, a, 0)]
            lb = palette_lab[np.where(ok, b, 0)]
            ab = lb - la
            denom = np.maximum(np.einsum("nc,nc->n", ab, ab), 1e-10)
            t = np.clip(np.einsum("nc,nc->n", pix - la, ab) / denom, 0.0, 1.0)
            proj = la + ab * t[:, None]
            d = np.einsum("nc,nc->n", pix - proj, pix - proj)
            take = ok & (d < best_d)
            best_d = np.where(take, d, best_d)
            best_label = np.where(take, np.where(t < 0.5, a, b), best_label).astype(np.int16)
    labels[ys, xs] = best_label


def _drop_specks(labels: np.ndarray, min_pixels: int) -> np.ndarray:
    if min_pixels <= 1:
        return labels
    height, width = labels.shape
    out = labels.copy()
    flat = out.ravel()
    seen = flat < 0
    for start in np.flatnonzero(~seen):
        start_i = int(start)
        if seen[start_i]:
            continue
        color = int(flat[start_i])
        stack = [start_i]
        seen[start_i] = True
        cells: list[int] = [start_i]
        keep = False
        while stack:
            ci = stack.pop()
            cx = ci % width
            cy = ci // width
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if not (0 <= nx < width and 0 <= ny < height):
                    continue
                ni = ny * width + nx
                if seen[ni] or int(flat[ni]) != color:
                    continue
                seen[ni] = True
                stack.append(ni)
                if keep:
                    continue
                cells.append(ni)
                if len(cells) >= min_pixels:
                    keep = True
                    cells.clear()
        if keep or not cells:
            continue
        for ci in cells:
            cy, cx = divmod(ci, width)
            flat[ci] = _majority_neighbor(out, cy, cx, avoid=color)
    return out


def _majority_neighbor(labels: np.ndarray, y: int, x: int, *, avoid: int) -> int:
    height, width = labels.shape
    y0 = max(0, y - 1)
    y1 = min(height, y + 2)
    x0 = max(0, x - 1)
    x1 = min(width, x + 2)
    patch = labels[y0:y1, x0:x1]
    # Ignore the center and the avoided label; empty (-1) is a valid sink.
    flat = patch.ravel()
    cy = y - y0
    cx = x - x0
    center = cy * (x1 - x0) + cx
    candidates = [int(value) for i, value in enumerate(flat) if i != center and int(value) != avoid]
    if not candidates:
        return _EMPTY
    counts: dict[int, int] = {}
    for label in candidates:
        counts[label] = counts.get(label, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _svg_from_labels(
    image: Image.Image,
    labels: np.ndarray,
    palette: tuple[str, ...],
    settings: TraceSettings,
    *,
    pixels_lab: np.ndarray | None = None,
    palette_lab: np.ndarray | None = None,
    bg_lab: np.ndarray | None = None,
    soft_lab: np.ndarray | None = None,
    output_size: tuple[int, int] | None = None,
    coordinate_scale: float = 1.0,
    on_progress: ProgressCallback | None = None,
) -> str:
    report = on_progress or (lambda _stage, _fraction: None)
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    if pixels_lab is None:
        pixels_lab = srgb_u8_to_oklab(rgba[..., :3])
    if palette_lab is None:
        palette_lab = srgb_u8_to_oklab(
            np.asarray([hex_to_rgb(c) for c in palette], dtype=np.uint8)
        )
    if bg_lab is None:
        bg_lab = srgb_u8_to_oklab(
            np.asarray(
                [[settings.background_r, settings.background_g, settings.background_b]],
                dtype=np.uint8,
            )
        )[0]
    height, width = labels.shape
    out_w, out_h = output_size if output_size is not None else (width, height)
    coord_scale = float(coordinate_scale) if coordinate_scale else 1.0
    decimals = max(1, min(4, int(settings.path_precision)))
    # Fit tolerance scales gently with resolution so megapixel art does not
    # explode into thousands of tiny cubics, while small icons stay precise.
    geom_scale = max(1.0, math.sqrt((width * height) / 160_000.0))
    # Cel / illustration with ink: crack-edge contours keep thin outlines as
    # closed ribbons. Soft iso alone melted strokes into neighbouring fills.
    # Transparent cutouts use stacked Gaussian masks (not hard_cel): that
    # averages pixel stairs into smooth silhouettes and covers seams by
    # painting each fill under everything above it.
    cutout_precision = bool(
        settings.preserve_transparency and settings.automatic_quality.value != "fast"
    )
    hard_cel = (
        settings.target_colors == 0
        and settings.corner_threshold is not None
        and float(settings.corner_threshold) <= 45
        and not cutout_precision
    )
    if settings.automatic_quality.value == "high":
        tolerance = (1.15 if hard_cel else 0.55) * min(1.8, geom_scale)
        blur = 0.55
    elif settings.automatic_quality.value == "fast":
        tolerance = 1.35 * min(2.2, geom_scale)
        blur = 0.85
    else:
        tolerance = (1.35 if hard_cel else 0.95) * min(1.9, geom_scale)
        blur = 0.65
    cutout_sigma = _CUTOUT_SIGMA
    if cutout_precision:
        # Rings are already smooth and sit on the source edge; a loose fit
        # (≥1.2 px) let neighbouring layers drift apart into lumps and seams.
        tolerance = 0.9 if settings.automatic_quality.value == "high" else 1.1
        blur = min(blur, 0.40)
    corner = float(settings.corner_threshold) if settings.corner_threshold else 50.0
    if hard_cel and not cutout_precision:
        corner = max(corner, 50.0)
    elif cutout_precision:
        # Ignore High's corner−10 (that re-frayed cutout letters); keep smooth.
        corner = 50.0
    # Always evenodd: cel ink outlines are thin rings with holes. Nonzero fill
    # paints those holes solid and swallows teal/orange bodies into black.
    fill_rule = "evenodd"
    parts: list[str] = []
    # Full-bleed underlay: when the scene background stays, paint it first so
    # hairline gaps never show the canvas white through pink walls / skies.
    # Never invent an underlay from the largest subject colour — that turned
    # navy roosters into a solid blue rectangle when black matte was missing.
    empty_share = float((labels < 0).mean()) if labels.size else 0.0
    if (
        not settings.remove_background
        and palette
        and not (settings.preserve_transparency and empty_share >= 0.08)
    ):
        bg_hex = rgb_to_hex(
            (settings.background_r, settings.background_g, settings.background_b)
        )
        underlay = None
        for candidate in palette:
            if candidate == bg_hex or _colors_close(candidate, bg_hex, tol=18):
                underlay = candidate
                break
        if underlay is not None:
            parts.append(
                f'<path d="M 0 0 H {out_w} V {out_h} H 0 Z" fill="{underlay}"/>'
            )
    pad = max(3, int(math.ceil(blur)) + 2)
    if cutout_precision and not hard_cel:
        pad = max(pad, int(math.ceil(3.0 * cutout_sigma)) + 1)
    # Paint large fills first, dark ink last so cel outlines sit on top of
    # walls/furniture instead of being buried underneath.
    def _paint_key(label: int) -> tuple[int, int]:
        color = hex_to_rgb(palette[label])
        luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        area = int((labels == label).sum())
        dark = 1 if luma <= 70 else 0
        return (dark, -area)

    paint_order = sorted(range(len(palette)), key=_paint_key)
    # Tiny bright islands (lion eye specular, ~2–20 px) must paint after ink
    # or the solid black path covers them. Large white letter fills stay earlier.
    if cutout_precision:
        late_bright: list[int] = []
        for label in list(paint_order):
            color = hex_to_rgb(palette[label])
            luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            area = int((labels == label).sum())
            if luma >= 200 and 0 < area <= 64:
                late_bright.append(label)
        if late_bright:
            paint_order = [i for i in paint_order if i not in late_bright] + late_bright
    # Alpha cutouts: abutting paths each anti-alias their shared edge, so the
    # empty canvas shows through as pale hairlines. Draw outline ink last and
    # tuck every lower fill 1 px under the layers painted above it — fills grow
    # only underneath, never over ink.
    tuck: dict[int, np.ndarray] = {}
    if hard_cel and cutout_precision and empty_share >= 0.02:
        lumas = [
            sum(w * c for w, c in zip((0.299, 0.587, 0.114), hex_to_rgb(color)))
            for color in palette
        ]
        darkest = int(np.argmin(lumas))
        if lumas[darkest] <= 40:
            paint_order = [i for i in paint_order if i != darkest] + [darkest]
        above = np.zeros(labels.shape, dtype=bool)
        for label in reversed(paint_order):
            own = labels == label
            if not np.any(own):
                continue
            # Two rings: enough underlap so cubic wobble cannot open white
            # hairlines between black ink and yellow/olive fills.
            tuck[label] = _dilate4(own, rings=2) & above
            above |= own
    # Alpha cutouts: each fill underlaps only 2 px into layers painted above.
    # Full-union underlap closed seams but put white/red under the whole black
    # ring, so letter rims fringed white/pink. Local underlap keeps the true
    # neighbour colour at each ink edge.
    stacked: dict[int, np.ndarray] = {}
    cutout_lab = soft_lab if soft_lab is not None else pixels_lab
    cutout_alpha = rgba[..., 3].astype(np.float32) / 255.0
    if cutout_lab.shape[:2] != labels.shape:
        cutout_lab = pixels_lab
    if cutout_alpha.shape != labels.shape:
        cutout_alpha = (labels >= 0).astype(np.float32)
    if cutout_precision and not hard_cel:
        above = np.zeros(labels.shape, dtype=bool)
        for label in reversed(paint_order):
            own = labels == label
            if not np.any(own):
                continue
            # Up to 2 px underlap, but never within 1 px of anything painted
            # below (or transparency) — there it would peek past thin ink.
            exposed = _dilate4(~(above | own), rings=1)
            stacked[label] = _dilate4(own, rings=2) & above & ~own & ~exposed
            above = above | own
    total_labels = max(1, len(paint_order))
    for index, label in enumerate(paint_order):
        # Contours dominate runtime; keep fraction moving for the ETA display.
        report(
            STAGE_CONTOURS if index < total_labels // 2 else STAGE_CURVES,
            0.25 + 0.70 * (index / total_labels),
        )
        mask = labels == label
        if not np.any(mask):
            continue
        ys, xs = np.nonzero(mask)
        y0 = max(0, int(ys.min()) - pad)
        y1 = min(height, int(ys.max()) + pad + 1)
        x0 = max(0, int(xs.min()) - pad)
        x1 = min(width, int(xs.max()) + pad + 1)
        if label in stacked:
            underlap = stacked[label]
            field = _soft_cutout_field(
                labels[y0:y1, x0:x1],
                label,
                cutout_lab[y0:y1, x0:x1],
                cutout_alpha[y0:y1, x0:x1],
                palette_lab,
            )
            field = np.maximum(field, underlap[y0:y1, x0:x1].astype(np.float32))
            field = _gaussian_blur(field, sigma=cutout_sigma)
            # Keep bright holes (eye specular, letter counters) from being
            # filled in by the ink blur — force coverage to 0 there.
            color = hex_to_rgb(palette[label])
            luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
            if luma <= 40:
                sub = labels[y0:y1, x0:x1]
                bright_here = np.zeros(sub.shape, dtype=bool)
                for bi, bcol in enumerate(palette):
                    br, bg, bb = hex_to_rgb(bcol)
                    if 0.299 * br + 0.587 * bg + 0.114 * bb >= 200:
                        bright_here |= sub == bi
                if np.any(bright_here):
                    field = field.copy()
                    field[bright_here] = 0.0
            contours = marching_squares(field, level=0.5)
            # Marching squares samples pixel centres; shift back to pixel space.
            contours = [
                [(p[0] + x0 + 0.5, p[1] + y0 + 0.5) for p in contour]
                for contour in contours
            ]
            contours = [
                _smooth_iso_ring(c, passes=_CUTOUT_RING_PASSES) for c in contours
            ]
        elif hard_cel:
            # Crack-edge contours on the hard label mask. Marching-squares
            # chaining fragments complex cel flats so couch cushions etc. vanish.
            contours = _trace_mask(mask | tuck[label] if label in tuck else mask)
            if cutout_precision:
                # Crack stairs are ±0.5 px off the true edge; a sub-pixel fit
                # tolerance otherwise reproduces every stair as a wobble.
                contours = [_smooth_crack_ring(c) for c in contours]
        else:
            sub_labels = labels[y0:y1, x0:x1]
            sub_pixels = pixels_lab[y0:y1, x0:x1]
            sub_soft = soft_lab[y0:y1, x0:x1] if soft_lab is not None else None
            field = coverage_field(
                sub_labels,
                label,
                sub_pixels,
                palette_lab,
                bg_lab,
                soft_lab=sub_soft,
                blur=blur,
            )
            contours = marching_squares(field, level=0.5)
            if contours and (x0 or y0):
                contours = [
                    [(p[0] + x0, p[1] + y0) for p in contour] for contour in contours
                ]
            if not contours:
                contours = [
                    _shift_contour(
                        c, labels, label, rgba, pixels_lab, palette_lab, bg_lab
                    )
                    for c in _trace_mask(mask)
                ]
        if coord_scale != 1.0 and contours:
            contours = [
                [(p[0] * coord_scale, p[1] * coord_scale) for p in contour]
                for contour in contours
            ]
        subpaths: list[str] = []
        for contour in contours:
            ring = orient_clockwise(contour)
            if len(ring) < 4:
                continue
            segments = fit_closed_contour(
                ring,
                tolerance=tolerance * max(1.0, coord_scale),
                corner_degrees=max(22.0, corner),
            )
            path_d = segments_to_path_d(segments, decimals=decimals)
            if path_d:
                subpaths.append(path_d)
        if not subpaths:
            continue
        fill = rgb_to_hex(hex_to_rgb(palette[label]))
        parts.append(
            f'<path d="{" ".join(subpaths)}" fill="{fill}" fill-rule="{fill_rule}"/>'
        )
    body = "\n  ".join(parts)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{out_w}" height="{out_h}" '
        f'viewBox="0 0 {out_w} {out_h}">\n  {body}\n</svg>\n'
    )


def _smooth_iso_ring(
    contour: list[tuple[float, float]], *, passes: int
) -> list[tuple[float, float]]:
    """[1, 2, 1] passes along an iso ring; sharp turns (spike tips) stay pinned."""
    pts = np.asarray(contour, dtype=np.float64)
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    # Tiny islands (2×2 eye speculars) would shrink to nothing.
    if len(pts) < 40:
        return contour
    span = 3
    ahead = np.roll(pts, -span, axis=0) - pts
    behind = pts - np.roll(pts, span, axis=0)
    cross = behind[:, 0] * ahead[:, 1] - behind[:, 1] * ahead[:, 0]
    dot = np.einsum("nc,nc->n", behind, ahead)
    turn = np.abs(np.arctan2(cross, dot))
    pinned = turn >= math.radians(70.0)
    for _ in range(passes):
        smooth = 0.25 * np.roll(pts, 1, axis=0) + 0.5 * pts + 0.25 * np.roll(pts, -1, axis=0)
        pts = np.where(pinned[:, None], pts, smooth)
    out = [(float(x), float(y)) for x, y in pts]
    out.append(out[0])
    return out


def _soft_cutout_field(
    labels: np.ndarray,
    label: int,
    lab: np.ndarray,
    alpha: np.ndarray,
    palette_lab: np.ndarray,
) -> np.ndarray:
    """Per-pixel coverage of `label` read from the source anti-aliasing.

    Each pixel near the label boundary is unmixed against whichever nearby
    label (or transparency) explains its colour best, so the 0.5 isolevel
    lands on the source's sub-pixel edge instead of on binary pixel stairs.
    """
    height, width = labels.shape
    own = labels == label
    field = own.astype(np.float32)
    band = _dilate4(own, rings=2) & _dilate4(~own, rings=2)
    if not np.any(band):
        return field * np.minimum(1.0, alpha * 1.0)
    ys, xs = np.nonzero(band)
    pix = lab[ys, xs]
    ink = palette_lab[label]
    best_res = np.full(ys.shape[0], np.inf, dtype=np.float32)
    best_cov = np.where(own[ys, xs], 1.0, 0.0).astype(np.float32)
    padded = np.pad(labels, 2, mode="constant", constant_values=_EMPTY)
    offsets = [(0, 0)] + [
        (dy, dx) for dy in range(-2, 3) for dx in range(-2, 3) if (dy, dx) != (0, 0)
    ]
    for dy, dx in offsets:
        other = padded[ys + 2 + dy, xs + 2 + dx]
        ok = (other >= 0) & (other != label)
        if not np.any(ok):
            continue
        ab = palette_lab[np.where(ok, other, 0)] - ink
        denom = np.maximum(np.einsum("nc,nc->n", ab, ab), 1e-10)
        t = np.clip(np.einsum("nc,nc->n", pix - ink, ab) / denom, 0.0, 1.0)
        resid = pix - (ink + ab * t[:, None])
        res = np.einsum("nc,nc->n", resid, resid)
        take = ok & (res < best_res)
        best_res = np.where(take, res, best_res)
        best_cov = np.where(take, 1.0 - t, best_cov).astype(np.float32)
    field[ys, xs] = best_cov
    # Transparent neighbours: alpha is the coverage (colour is unpremultiplied).
    return field * np.clip(alpha, 0.0, 1.0)


def _gaussian_blur(field: np.ndarray, *, sigma: float) -> np.ndarray:
    """Separable Gaussian with zero padding (outside the crop is empty)."""
    radius = max(1, int(math.ceil(3.0 * sigma)))
    taps = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-0.5 * (taps / float(sigma)) ** 2)
    kernel /= kernel.sum()
    out = field.astype(np.float32)
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        padded = np.pad(out, pad, mode="constant")
        length = out.shape[axis]
        acc = np.zeros_like(out)
        for offset, weight in enumerate(kernel):
            window = [slice(None), slice(None)]
            window[axis] = slice(offset, offset + length)
            acc += weight * padded[tuple(window)]
        out = acc
    return out


def _colors_close(a: str, b: str, *, tol: int) -> bool:
    ar, ag, ab = hex_to_rgb(a)
    br, bg, bb = hex_to_rgb(b)
    return abs(ar - br) <= tol and abs(ag - bg) <= tol and abs(ab - bb) <= tol


def _shift_contour(
    contour: list[tuple[float, float]],
    labels: np.ndarray,
    label: int,
    rgba: np.ndarray,
    pixels_lab: np.ndarray,
    palette_lab: np.ndarray,
    bg_lab: np.ndarray,
) -> list[tuple[float, float]]:
    if len(contour) < 4:
        return contour
    shifts: list[tuple[float, float]] = []
    for start, end in zip(contour, contour[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        if abs(dx) >= abs(dy):
            direction = 0 if dx >= 0 else 2
        else:
            direction = 1 if dy >= 0 else 3
        inside = _side_pixel(int(round(start[0])), int(round(start[1])), direction, right=True)
        outside = _side_pixel(int(round(start[0])), int(round(start[1])), direction, right=False)
        inward = _inward(direction)
        coverage = _edge_coverage(
            inside,
            outside,
            label,
            labels,
            rgba,
            pixels_lab,
            palette_lab,
            bg_lab,
        )
        # Place the curve at the coverage isosurface, then bias slightly
        # outward (~0.18 px). Pure neighbors expand a hair so adjacent fills
        # overlap and hairline gaps disappear without a stroke workaround.
        amount = max(-0.22, min(0.48, (1.0 - coverage) - 0.18))
        shifts.append((inward[0] * amount, inward[1] * amount))
    if not shifts:
        return contour
    shifted: list[tuple[float, float]] = []
    count = len(contour) - 1
    for i, point in enumerate(contour[:-1]):
        prev_shift = shifts[(i - 1) % count]
        here = shifts[i % count]
        shifted.append(
            (point[0] + (prev_shift[0] + here[0]) * 0.5, point[1] + (prev_shift[1] + here[1]) * 0.5)
        )
    shifted.append(shifted[0])
    return shifted


def _edge_coverage(
    inside: tuple[int, int],
    outside: tuple[int, int],
    label: int,
    labels: np.ndarray,
    rgba: np.ndarray,
    pixels_lab: np.ndarray,
    palette_lab: np.ndarray,
    bg_lab: np.ndarray,
) -> float:
    height, width = labels.shape
    ix, iy = inside
    if not (0 <= ix < width and 0 <= iy < height):
        return 1.0
    alpha = int(rgba[iy, ix, 3])
    if alpha < 8:
        return 0.0
    ink = palette_lab[label]
    ox, oy = outside
    if 0 <= ox < width and 0 <= oy < height and int(labels[oy, ox]) >= 0:
        other_label = int(labels[oy, ox])
        other = palette_lab[other_label]
    else:
        other = bg_lab
        if alpha < 255:
            # Soft alpha edges: also peek at a second inside neighbor so thin
            # anti-aliased strokes don't collapse to binary cutouts.
            return _alpha_coverage(rgba, ix, iy, alpha)
    primary = project_coverage(pixels_lab[iy, ix], ink, other)
    # Average with the outside pixel's complementary coverage when both sides
    # are mixed. This stabilizes 3-way junctions and JPEG fringe.
    if 0 <= ox < width and 0 <= oy < height and int(rgba[oy, ox, 3]) >= 8:
        outside_cov = project_coverage(pixels_lab[oy, ox], ink, other)
        return 0.65 * primary + 0.35 * outside_cov
    return primary


def _alpha_coverage(rgba: np.ndarray, x: int, y: int, alpha: int) -> float:
    height, width = rgba.shape[:2]
    total = float(alpha)
    weight = 1.0
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            total += float(rgba[ny, nx, 3]) * 0.35
            weight += 0.35
    return max(0.0, min(1.0, (total / weight) / 255.0))


def _inward(direction: int) -> tuple[float, float]:
    # Interior sits on the right of the walk, which is clockwise in y-down space.
    return ((0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 0.0))[direction]


def _side_pixel(x: int, y: int, direction: int, *, right: bool) -> tuple[int, int]:
    """Pixel beside the crack that starts at (x, y) and leaves in `direction`.

    Pixel (c, r) covers corners (c, r) .. (c+1, r+1). Interior is kept on the right.
    """
    if direction == 0:  # east
        return (x, y) if right else (x, y - 1)
    if direction == 1:  # south
        return (x - 1, y) if right else (x, y)
    if direction == 2:  # west
        return (x - 1, y - 1) if right else (x - 1, y)
    return (x, y - 1) if right else (x - 1, y - 1)  # north


def _smooth_crack_ring(contour: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Unit-step crack polygon → edge midpoints with a few [1, 2, 1] passes.

    Both labels sharing a boundary walk the same unit edges, so they get the
    same smoothed points and stay seam-free. Extra passes knock down the
    pixel-stair fray that a single midpoint step still left on heraldic ink.
    """
    pts = np.asarray(contour, dtype=np.float64)
    if len(pts) < 5:
        return contour
    if np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    # Midpoints of each crack edge (shared by both abutting labels).
    smooth = 0.5 * (pts + np.roll(pts, -1, axis=0))
    for _ in range(3):
        smooth = (
            0.25 * np.roll(smooth, 1, axis=0)
            + 0.5 * smooth
            + 0.25 * np.roll(smooth, -1, axis=0)
        )
    out = [(float(x), float(y)) for x, y in smooth]
    out.append(out[0])
    return out


def _trace_mask(mask: np.ndarray) -> list[list[tuple[float, float]]]:
    """Clockwise crack contours of a boolean mask. Points are pixel corners."""
    height, width = int(mask.shape[0]), int(mask.shape[1])
    # Bool volume beats a Python set of (x, y, dir) triples on large regions.
    used = np.zeros((height + 1, width + 1, 4), dtype=bool)
    contours: list[list[tuple[float, float]]] = []
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if y > 0 and bool(mask[y - 1, x]):
            continue
        if used[y, x, 0]:
            continue
        contour = _walk(mask, x, y, used)
        if len(contour) >= 4:
            contours.append(contour)
    return contours


def _walk(
    mask: np.ndarray,
    sx: int,
    sy: int,
    used: np.ndarray,
) -> list[tuple[float, float]]:
    height, width = int(mask.shape[0]), int(mask.shape[1])
    x, y, direction = sx, sy, 0
    points = [(float(x), float(y))]
    start = (x, y, direction)
    limit = (height + 1) * (width + 1) * 4
    for _step in range(limit):
        moved = False
        for turn in (1, 0, 3, 2):
            new_dir = (direction + turn) % 4
            right = _side_pixel(x, y, new_dir, right=True)
            left = _side_pixel(x, y, new_dir, right=False)
            if not _inside(mask, right, width, height) or _inside(mask, left, width, height):
                continue
            if (x, y, new_dir) == start and len(points) > 2:
                points.append((float(sx), float(sy)))
                return points
            if used[y, x, new_dir]:
                return points
            used[y, x, new_dir] = True
            x += _DIRS[new_dir][0]
            y += _DIRS[new_dir][1]
            direction = new_dir
            points.append((float(x), float(y)))
            moved = True
            break
        if not moved or (x, y, direction) == start:
            break
    if points[0] != points[-1]:
        points.append(points[0])
    return points


def _inside(mask: np.ndarray, pixel: tuple[int, int], width: int, height: int) -> bool:
    x, y = pixel
    if not (0 <= x < width and 0 <= y < height):
        return False
    return bool(mask[y, x])

