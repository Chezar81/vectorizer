"""Preprocessing applied to a copy of the source; never mutates the original."""

from __future__ import annotations

from PIL import Image, ImageFilter

from vectorizer.domain.settings import TraceSettings


def preprocess_image(image: Image.Image, settings: TraceSettings) -> Image.Image:
    """Return a working RGBA image for tracing.

    Original `image` is left unchanged. Operations (in order):
    - scrub chroma-key fringe (magenta/near-transparent junk)
    - solidify near-black transparent mattes (icon “black backgrounds”)
    - optional flattening of existing alpha when preserve_transparency is False
    - optional background removal by color + tolerance
    - optional light noise smoothing (median) while preserving alpha
    - optional color quantization (soft palette / target color count, no dither)
    """
    settings = settings.validated()
    working = image.convert("RGBA").copy()
    working = scrub_chroma_key_alpha(working)
    working = solidify_black_matte(working)

    if not settings.preserve_transparency:
        bg = (
            settings.background_r,
            settings.background_g,
            settings.background_b,
            255,
        )
        flat = Image.new("RGBA", working.size, bg)
        flat.paste(working, mask=working.split()[3])
        working = flat

    if settings.remove_background:
        working = _knock_out_color(
            working,
            (settings.background_r, settings.background_g, settings.background_b),
            settings.background_tolerance,
        )

    if settings.smooth_noise:
        working = _smooth_noise_rgba(working)

    if settings.target_colors and settings.target_colors > 0:
        working = _quantize_rgba(working, settings.target_colors)

    return working


def cel_stroke_mask(rgb: Image.Image | object, *, bleed_ink: bool = False) -> object:
    """Boolean mask of dark ink outlines abutting brighter fills.

    JPEG cel art browns true black; require local contrast so couch shadows are
    not treated as strokes.

    `bleed_ink` also accepts thin lines whose chroma was smeared in from a
    saturated fill (fold lines on a yellow curtain read as olive ~(108,80,6)).
    """
    import numpy as np

    if isinstance(rgb, Image.Image):
        arr = np.asarray(rgb.convert("RGB"), dtype=np.uint8)
    else:
        arr = np.asarray(rgb, dtype=np.uint8)
    gray = (
        0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    ).astype(np.float32)
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
    sat = arr.max(axis=2).astype(np.int16) - arr.min(axis=2).astype(np.int16)
    contrast = neigh_max - gray
    # Classic cel: dark ink against bright fills (Simpsons pink/orange).
    edge_ink = (gray <= 88.0) & (contrast >= 32.0) & (sat <= 95)
    # Dark-on-dark (Bar green feathers): near-black with modest local lift.
    dark_on_dark = (gray <= 42.0) & (contrast >= 14.0) & (sat <= 55)
    # Thin slate outlines (clouds, sails) are too light for the luma gate;
    # a black-hat (closing minus image) finds lines narrower than the kernel
    # while ignoring wide shadow bands.
    side = max(arr.shape[:2])
    kernel = 5 if side <= 2600 else 7
    gray_img = Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8), "L")
    closed = gray_img.filter(ImageFilter.MaxFilter(kernel)).filter(
        ImageFilter.MinFilter(kernel)
    )
    black_hat = np.asarray(closed, dtype=np.float32) - gray
    thin_ink = (black_hat >= 40.0) & (gray <= 125.0) & (sat <= 90)
    mask = edge_ink | dark_on_dark | thin_ink
    if bleed_ink:
        mask |= (black_hat >= 70.0) & (gray <= 105.0) & (sat <= 135)
    return mask


def prepare_cel_ink(
    image: Image.Image,
    palette: tuple[str, ...],
    *,
    ink_rgb: tuple[int, int, int] = (20, 8, 0),
) -> Image.Image:
    """Inpaint outlines, snap fills, then bake pure ink back onto strokes.

    BlendTracer hard-cel paths collapse complex scenes to ~1 path per palette
    colour. VTracer on a stroke-solidified, palette-snapped raster keeps
    continuous black outlines and flat fills much closer to the source.
    """
    import numpy as np

    from vectorizer.raster.palette import snap_image_to_palette

    rgba = image.convert("RGBA")
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8).copy()
    stroke = cel_stroke_mask(rgb, bleed_ink=True)
    if not np.any(stroke):
        return snap_image_to_palette(rgba, palette)
    # Closing may only add mid/dark pixels: a bright 1px gap between two ink
    # lines is a real fill (outlet face, sink rim, chair texture between
    # comma strokes) and closing it welds detail into a black blob.
    gray = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    stroke = stroke | (_binary_close(stroke) & (gray <= 140.0))
    # Bridge 1px gaps between stroke pixels (JPEG breakups).
    stroke = _bridge_stroke_gaps(rgb, stroke)
    # Bake at true line width: AA shoulders lighter than the ink/fill midpoint
    # return to fill (they are re-inpainted with the fill ring below).
    stroke = _thin_stroke_shoulders(rgb, stroke, ink_rgb)
    # VTracer clusters are 4-connected: a 1px diagonal outline (sail edges)
    # otherwise traces as a dashed line with fill leaking through the gaps.
    stroke = _four_connect_strokes(rgb, stroke)
    # Clear AA brown/orange fringe from fills over a 2px ring, but bake ink
    # only at the closed stroke width — dilating the bake made Simpsons
    # outlines look like charcoal. (Ink/fill unmix on the stroke ring was
    # tried; it splintered flat fills into thousands of extra VTracer paths.)
    # Pale neutral fills (keypad buttons, white sails) are never AA fringe;
    # inside a dense ink grid the ring would swallow them whole and inpaint
    # falls back to ink, crushing a keypad to a black blob. Likewise any ring
    # pixel that already sits on a palette fill at its luma plateau: small
    # background objects (outlet, scale dial, faucet) are narrower than the
    # ring and were otherwise repainted from whatever lay 3px away.
    keep = _pale_neutral_fill(rgb, stroke) | _palette_plateau_fill(
        rgb, stroke, palette, ink_rgb
    )
    fill_hole = _binary_dilate(stroke, 2) & ~keep
    filled = _inpaint_masked(rgb, fill_hole, fallback=None)
    # Skip median on cel prep — it chews thin ink abutments into stair-steps.
    stroke_b = np.asarray(stroke, dtype=bool)
    snapped = snap_image_to_palette(
        Image.fromarray(filled, "RGB").convert("RGBA"),
        palette,
        chroma_weight=1.35,
    )
    out = np.asarray(snapped, dtype=np.uint8).copy()
    out[stroke_b, 0] = ink_rgb[0]
    out[stroke_b, 1] = ink_rgb[1]
    out[stroke_b, 2] = ink_rgb[2]
    # JPEG fringe along fold lines snaps to orange/brown freckles that VTracer
    # then turns into shards; majority-clean fills while leaving ink alone.
    out[..., :3] = _majority_clean_fills(out[..., :3], stroke_b, passes=2, majority=6)
    out[..., :3] = _despeckle_fills(out[..., :3], stroke_b)
    out[..., :3] = _flatten_enclosed_fills(out[..., :3], stroke_b)
    out[stroke_b, 0] = ink_rgb[0]
    out[stroke_b, 1] = ink_rgb[1]
    out[stroke_b, 2] = ink_rgb[2]
    out[..., 3] = np.asarray(rgba)[..., 3]
    return Image.fromarray(out, mode="RGBA")


def _majority_clean_fills(
    rgb: object,
    stroke: object,
    *,
    passes: int = 2,
    majority: int = 6,
) -> object:
    """Replace fill pixels that disagree with most neighbours (ink is frozen)."""
    import numpy as np

    out = np.asarray(rgb, dtype=np.uint8).copy()
    frozen = np.asarray(stroke, dtype=bool)
    if out.size == 0 or not np.any(~frozen):
        return out
    # Pack RGB into int32 so neighbour voting is a single channel.
    packed = (
        out[..., 0].astype(np.int32) << 16
        | out[..., 1].astype(np.int32) << 8
        | out[..., 2].astype(np.int32)
    )
    for _ in range(max(1, passes)):
        pad = np.pad(packed, 1, mode="edge")
        neigh = np.stack(
            [
                pad[:-2, 1:-1],
                pad[2:, 1:-1],
                pad[1:-1, :-2],
                pad[1:-1, 2:],
                pad[:-2, :-2],
                pad[:-2, 2:],
                pad[2:, :-2],
                pad[2:, 2:],
            ],
            axis=0,
        )
        # Mode of 8-neighbourhood via sort; ties keep the current pixel.
        ordered = np.sort(neigh, axis=0)
        # Count runs at the median of each sorted neighbourhood.
        mid = ordered[3]
        agree = (neigh == mid).sum(axis=0)
        # Prefer the true mode when the median slot is a weak tie.
        for candidate in (ordered[2], ordered[4], ordered[1], ordered[5]):
            cand_agree = (neigh == candidate).sum(axis=0)
            better = cand_agree > agree
            mid = np.where(better, candidate, mid)
            agree = np.where(better, cand_agree, agree)
        self_agree = (neigh == packed).sum(axis=0)
        flip = (~frozen) & (agree >= majority) & (agree > self_agree) & (mid != packed)
        if not np.any(flip):
            break
        packed = np.where(flip, mid, packed)
    out[..., 0] = (packed >> 16) & 255
    out[..., 1] = (packed >> 8) & 255
    out[..., 2] = packed & 255
    return out


def _despeckle_fills(
    rgb: object,
    stroke: object,
    *,
    passes: int = 2,
    max_self: int = 3,
) -> object:
    """Absorb fill specks of ≤ `max_self`+1 pixels into the dominant 5×5 fill.

    Painterly shading between two inks (salmon cabinet frame, mauve toaster)
    snaps to 2–4 pixel freckles that an 8-neighbour majority cannot reach.
    A 1px line keeps four same-colour pixels in its 5×5 window and survives.
    """
    import numpy as np

    out = np.asarray(rgb, dtype=np.uint8).copy()
    frozen = np.asarray(stroke, dtype=bool)
    packed = (
        out[..., 0].astype(np.int32) << 16
        | out[..., 1].astype(np.int32) << 8
        | out[..., 2].astype(np.int32)
    )
    h, w = packed.shape
    offsets = [(dy, dx) for dy in range(-2, 3) for dx in range(-2, 3) if dy or dx]
    for _ in range(max(1, passes)):
        pad = np.pad(packed, 2, mode="edge")
        ink = np.pad(frozen, 2, mode="edge")

        def _shift(arr, dy, dx):
            return arr[2 + dy : 2 + dy + h, 2 + dx : 2 + dx + w]

        self_count = np.zeros((h, w), dtype=np.int16)
        fill_count = np.zeros((h, w), dtype=np.int16)
        for dy, dx in offsets:
            nk = ~_shift(ink, dy, dx)
            self_count += (_shift(pad, dy, dx) == packed) & nk
            fill_count += nk
        cand_pix = (~frozen) & (self_count <= max_self) & (fill_count >= 12)
        if not np.any(cand_pix):
            break
        best = packed.copy()
        best_count = np.zeros((h, w), dtype=np.int16)
        # Candidates: every non-ink colour in the 3×3 ring.
        for cy, cx in offsets:
            if max(abs(cy), abs(cx)) > 1:
                continue
            cand = _shift(pad, cy, cx)
            usable = cand_pix & ~_shift(ink, cy, cx) & (cand != packed)
            if not np.any(usable):
                continue
            votes = np.zeros((h, w), dtype=np.int16)
            for dy, dx in offsets:
                votes += (_shift(pad, dy, dx) == cand) & ~_shift(ink, dy, dx)
            better = usable & (votes > best_count)
            best = np.where(better, cand, best)
            best_count = np.where(better, votes, best_count)
        flip = cand_pix & (best_count * 5 >= fill_count * 3)
        if not np.any(flip):
            break
        packed = np.where(flip, best, packed)
    out[..., 0] = (packed >> 16) & 255
    out[..., 1] = (packed >> 8) & 255
    out[..., 2] = packed & 255
    return out


def _thin_stroke_shoulders(
    rgb: object,
    stroke: object,
    ink_rgb: tuple[int, int, int],
) -> object:
    """Drop outer stroke pixels that are mostly fill (coverage below one half).

    Only the stroke's outer layer is judged, against the brightest adjacent
    non-ink pixel. A shoulder must sit closer to that fill than to ink and
    still be visibly darker than it; a fill barely above ink (dark pole
    shading on GolfCart) is not an AA partner. Line ridges stay so 1px fold
    lines keep their spine, and dark masses wider than ~5px are left whole.
    """
    import numpy as np

    arr = np.asarray(rgb, dtype=np.uint8)
    ink = np.asarray(stroke, dtype=bool)
    gray = (
        0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    ).astype(np.float32)
    ink_l = 0.299 * ink_rgb[0] + 0.587 * ink_rgb[1] + 0.114 * ink_rgb[2]
    fill_gray = np.where(ink, -1.0, gray).astype(np.float32)
    p = np.pad(fill_gray, 1, constant_values=-1.0)
    h, w = gray.shape
    adj_fill = np.maximum.reduce(
        [p[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w] for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    )
    shoulder = (
        ink
        & (adj_fill >= 0.0)
        & (adj_fill - ink_l >= 90.0)
        & (gray > (adj_fill + ink_l) * 0.5)
        & (adj_fill - gray >= 16.0)
    )
    g = np.pad(gray, 1, mode="edge")

    def _at(dy: int, dx: int):
        return g[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]

    ridge = np.zeros_like(ink)
    for (ay, ax), (by, bx) in (
        ((0, -1), (0, 1)),
        ((-1, 0), (1, 0)),
        ((-1, -1), (1, 1)),
        ((-1, 1), (1, -1)),
    ):
        ridge |= gray <= np.minimum(_at(ay, ax), _at(by, bx))
    dark = ink | (gray <= ink_l + 70.0)
    wide_dark = _binary_dilate(_binary_erode(dark, 2), 3)
    return ink & ~(shoulder & ~ridge & ~wide_dark)


def _label_regions(mask: object, values: object | None = None) -> object:
    """4-connected component labels (root pixel index; -1 outside `mask`).

    With `values`, neighbours only join when their values are equal.
    """
    import numpy as np

    m = np.asarray(mask, dtype=bool)
    h, w = m.shape
    idx = np.arange(h * w, dtype=np.int64).reshape(h, w)
    eh = m[:, :-1] & m[:, 1:]
    ev = m[:-1, :] & m[1:, :]
    if values is not None:
        v = np.asarray(values)
        eh &= v[:, :-1] == v[:, 1:]
        ev &= v[:-1, :] == v[1:, :]
    a = np.concatenate([idx[:, :-1][eh], idx[:-1, :][ev]])
    b = np.concatenate([idx[:, 1:][eh], idx[1:, :][ev]])
    lab = np.arange(h * w, dtype=np.int64)
    while a.size:
        la = lab[a]
        lb = lab[b]
        diff = la != lb
        if not np.any(diff):
            break
        a, b, la, lb = a[diff], b[diff], la[diff], lb[diff]
        # Hook the larger root onto the smaller, then compress fully so
        # every entry points at a root again.
        np.minimum.at(lab, np.maximum(la, lb), np.minimum(la, lb))
        while True:
            nxt = lab[lab]
            if np.array_equal(nxt, lab):
                break
            lab = nxt
    out = lab.reshape(h, w)
    out[~m] = -1
    return out


def _flatten_enclosed_fills(
    rgb: object,
    stroke: object,
    *,
    max_dist: float = 0.14,
    min_contact: float = 0.45,
    host_ratio: int = 3,
    passes: int = 2,
) -> object:
    """Fold small shading blotches into the fill that surrounds them.

    Painterly shading on small objects (toaster faces, cabinet frame) snaps to
    blotches of a neighbouring palette shade, too large for `_despeckle_fills`.
    A same-colour blob is merged into the non-ink neighbour blob it touches
    most when that host is OKLab-close, several times larger, and supplies
    most of the blob's boundary. Ink contacts count against the share, so
    outlined details (carrots on the curtain, keypad buttons) stay.
    """
    import numpy as np

    from vectorizer.raster.color import srgb_u8_to_oklab

    out = np.asarray(rgb, dtype=np.uint8).copy()
    fill = ~np.asarray(stroke, dtype=bool)
    if not np.any(fill):
        return out
    h, w = fill.shape
    max_blob = max(64, int(h * w * 6e-5))
    packed = (
        out[..., 0].astype(np.int64) << 16
        | out[..., 1].astype(np.int64) << 8
        | out[..., 2].astype(np.int64)
    )
    for _ in range(max(1, passes)):
        roots = _label_regions(fill, packed)
        _, blob = np.unique(roots[fill], return_inverse=True)
        n_blob = int(blob.max()) + 1
        blob_map = np.full((h, w), -1, dtype=np.int64)
        blob_map[fill] = blob.ravel()
        blob = blob_map
        area = np.bincount(blob[fill], minlength=n_blob)
        blob_color = np.zeros(n_blob, dtype=np.int64)
        blob_color[blob[fill]] = packed[fill]
        pairs = []
        for a, b in (
            (blob[:, :-1], blob[:, 1:]),
            (blob[:-1, :], blob[1:, :]),
        ):
            a = a.ravel()
            b = b.ravel()
            diff = a != b
            pairs.append((a[diff], b[diff]))
            pairs.append((b[diff], a[diff]))
        src = np.concatenate([p[0] for p in pairs])
        dst = np.concatenate([p[1] for p in pairs])
        keep = src >= 0
        src, dst = src[keep], dst[keep]
        small = area[src] <= max_blob
        src, dst = src[small], dst[small]
        if src.size == 0:
            break
        contacts = np.bincount(src, minlength=n_blob)
        fill_pair = dst >= 0
        keys, counts = np.unique(
            src[fill_pair] * n_blob + dst[fill_pair], return_counts=True
        )
        k_src = keys // n_blob
        k_dst = keys % n_blob
        order = np.lexsort((counts, k_src))
        last = np.r_[k_src[order][1:] != k_src[order][:-1], True]
        b_src = k_src[order][last]
        b_host = k_dst[order][last]
        b_cnt = counts[order][last]
        colors = np.unique(blob_color)
        rgb_u8 = np.stack(
            [(colors >> 16) & 255, (colors >> 8) & 255, colors & 255], axis=-1
        ).astype(np.uint8)
        lab_c = srgb_u8_to_oklab(rgb_u8[None])[0]
        ci = np.searchsorted(colors, blob_color[b_src])
        hi = np.searchsorted(colors, blob_color[b_host])
        dist = np.sqrt(((lab_c[ci] - lab_c[hi]) ** 2).sum(axis=1))
        # Thick elongated blobs are drawn shading (lampshade pleats, handset
        # shadow); only compact blotches and sub-3px AA slivers fold away.
        yy, xx = np.nonzero(fill)
        ids = blob[fill]
        sy = np.bincount(ids, yy, n_blob)
        sx = np.bincount(ids, xx, n_blob)
        n = np.maximum(area, 1)
        cyy = np.bincount(ids, yy.astype(np.float64) ** 2, n_blob) / n - (sy / n) ** 2
        cxx = np.bincount(ids, xx.astype(np.float64) ** 2, n_blob) / n - (sx / n) ** 2
        cxy = np.bincount(ids, yy.astype(np.float64) * xx, n_blob) / n - sy * sx / n**2
        tr = cxx + cyy
        disc = np.sqrt(np.maximum(((cxx - cyy) * 0.5) ** 2 + cxy**2, 0.0))
        major = tr * 0.5 + disc
        minor = np.maximum(tr * 0.5 - disc, 1e-3)
        p = np.pad(blob, 1, constant_values=-2)
        core = (
            (p[:-2, 1:-1] == blob)
            & (p[2:, 1:-1] == blob)
            & (p[1:-1, :-2] == blob)
            & (p[1:-1, 2:] == blob)
            & fill
        )
        has_core = np.bincount(blob[core], minlength=n_blob) > 0
        shape_ok = ~has_core | (major <= 16.0 * minor)
        merge = (
            (dist <= max_dist)
            & (b_cnt >= min_contact * contacts[b_src])
            & (area[b_host] >= host_ratio * area[b_src])
            & shape_ok[b_src]
        )
        if not np.any(merge):
            break
        new_color = blob_color.copy()
        new_color[b_src[merge]] = blob_color[b_host[merge]]
        packed = np.where(fill, new_color[np.maximum(blob, 0)], packed)
    out[..., 0] = (packed >> 16) & 255
    out[..., 1] = (packed >> 8) & 255
    out[..., 2] = packed & 255
    return out


def _binary_dilate(mask: object, iterations: int = 1) -> object:
    import numpy as np

    m = np.asarray(mask, dtype=bool)
    for _ in range(max(1, iterations)):
        p = np.pad(m, 1, constant_values=False)
        m = (
            p[:-2, 1:-1]
            | p[2:, 1:-1]
            | p[1:-1, :-2]
            | p[1:-1, 2:]
            | p[:-2, :-2]
            | p[:-2, 2:]
            | p[2:, :-2]
            | p[2:, 2:]
            | m
        )
    return m


def _binary_erode(mask: object, iterations: int = 1) -> object:
    import numpy as np

    m = np.asarray(mask, dtype=bool)
    for _ in range(max(1, iterations)):
        p = np.pad(m, 1, constant_values=False)
        m = (
            p[:-2, 1:-1]
            & p[2:, 1:-1]
            & p[1:-1, :-2]
            & p[1:-1, 2:]
            & p[:-2, :-2]
            & p[:-2, 2:]
            & p[2:, :-2]
            & p[2:, 2:]
            & m
        )
    return m


def _binary_close(mask: object) -> object:
    return _binary_erode(_binary_dilate(mask, 1), 1)


def _bridge_stroke_gaps(rgb: object, stroke: object) -> object:
    """Fill single-pixel gaps between stroke pixels with dark, low-sat candidates."""
    import numpy as np

    arr = np.asarray(rgb, dtype=np.uint8)
    ink = np.asarray(stroke, dtype=bool)
    gray = (
        0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    ).astype(np.float32)
    sat = arr.max(axis=2).astype(np.int16) - arr.min(axis=2).astype(np.int16)
    padded = np.pad(ink, 1, constant_values=False)
    near = (
        padded[:-2, 1:-1]
        | padded[2:, 1:-1]
        | padded[1:-1, :-2]
        | padded[1:-1, 2:]
    )
    bridge = (~ink) & near & (gray <= 95.0) & (sat <= 100)
    return ink | bridge


def _four_connect_strokes(rgb: object, stroke: object) -> object:
    """Fill one orthogonal corner wherever ink touches only diagonally."""
    import numpy as np

    arr = np.asarray(rgb, dtype=np.uint8)
    ink = np.asarray(stroke, dtype=bool).copy()
    gray = (
        0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    ).astype(np.float32)
    a = ink[:-1, :-1]
    b = ink[:-1, 1:]
    c = ink[1:, :-1]
    d = ink[1:, 1:]
    # Main diagonal a–d with b, c empty; anti-diagonal b–c with a, d empty.
    main = a & d & ~b & ~c
    anti = b & c & ~a & ~d
    g_a = gray[:-1, :-1]
    g_b = gray[:-1, 1:]
    g_c = gray[1:, :-1]
    g_d = gray[1:, 1:]
    ys, xs = np.nonzero(main)
    pick_b = g_b[ys, xs] <= g_c[ys, xs]
    ink[ys[pick_b], xs[pick_b] + 1] = True
    ink[ys[~pick_b] + 1, xs[~pick_b]] = True
    ys, xs = np.nonzero(anti)
    pick_a = g_a[ys, xs] <= g_d[ys, xs]
    ink[ys[pick_a], xs[pick_a]] = True
    ink[ys[~pick_a] + 1, xs[~pick_a] + 1] = True
    return ink


def _pale_neutral_fill(rgb: object, stroke: object) -> object:
    """Light low-chroma non-ink pixels at their local luma plateau."""
    import numpy as np

    arr = np.asarray(rgb, dtype=np.uint8)
    gray = (
        0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    ).astype(np.float32)
    sat = arr.max(axis=2).astype(np.int16) - arr.min(axis=2).astype(np.int16)
    gray_img = Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8), "L")
    local_max = np.asarray(gray_img.filter(ImageFilter.MaxFilter(3)), dtype=np.float32)
    return (
        ~np.asarray(stroke, dtype=bool)
        & (gray >= 170.0)
        & (sat <= 40)
        & (gray >= local_max - 25.0)
    )


def _palette_plateau_fill(
    rgb: object,
    stroke: object,
    palette: tuple[str, ...],
    ink_rgb: tuple[int, int, int],
    *,
    max_dist: float = 0.05,
) -> object:
    """Non-ink pixels already close to a non-ink palette fill at their luma plateau.

    AA fringe is a fill/ink mix: darker than its brightest neighbour and off
    every fill ink, so it still fails this test and gets inpainted.
    """
    import numpy as np

    from vectorizer.raster.color import hex_to_rgb, nearest_oklab, srgb_u8_to_oklab

    arr = np.asarray(rgb, dtype=np.uint8)
    fills = [hex_to_rgb(c) for c in palette if hex_to_rgb(c) != tuple(ink_rgb)]
    if not fills:
        return np.zeros(arr.shape[:2], dtype=bool)
    _idx, sq = nearest_oklab(
        srgb_u8_to_oklab(arr),
        srgb_u8_to_oklab(np.asarray(fills, dtype=np.uint8)),
        chroma_weight=1.35,
    )
    gray = (
        0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    ).astype(np.float32)
    gray_img = Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8), "L")
    local_max = np.asarray(gray_img.filter(ImageFilter.MaxFilter(3)), dtype=np.float32)
    return (
        ~np.asarray(stroke, dtype=bool)
        & (sq <= max_dist * max_dist)
        & (gray >= local_max - 25.0)
    )


def _inpaint_masked(
    rgb: object,
    missing: object,
    *,
    fallback: tuple[int, int, int] | None,
    passes: int = 10,
) -> object:
    """Propagate neighbouring known colours into `missing` pixels.

    Pixels still unreached after `passes` take `fallback`, or keep their own
    colour when `fallback` is None.
    """
    import numpy as np

    out = np.asarray(rgb, dtype=np.float32).copy()
    hole = np.asarray(missing, dtype=bool).copy()
    for _ in range(passes):
        if not np.any(hole):
            break
        padded = np.pad(out, ((1, 1), (1, 1), (0, 0)), mode="edge")
        known = np.pad(~hole, 1, constant_values=False)
        acc = np.zeros_like(out)
        weight = np.zeros(hole.shape, dtype=np.float32)
        for dy, dx in (
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ):
            k = known[1 + dy : 1 + dy + out.shape[0], 1 + dx : 1 + dx + out.shape[1]]
            vals = padded[
                1 + dy : 1 + dy + out.shape[0], 1 + dx : 1 + dx + out.shape[1]
            ]
            acc += vals * k[..., None]
            weight += k.astype(np.float32)
        can = hole & (weight > 0)
        out[can] = acc[can] / weight[can, None]
        hole[can] = False
    if fallback is not None:
        out[hole] = fallback
    return np.clip(out, 0, 255).astype(np.uint8)


def scrub_chroma_key_alpha(image: Image.Image) -> Image.Image:
    """Force chroma-key / junk fringe pixels to fully transparent.

    Exports often store the area outside a badge as magenta (#ff00ff) with
    alpha 1–16. Palette quantization then treats that as a real fill, so
    VTracer paints a neon-pink rectangle behind the crest. Clear those pixels
    (and any near-invisible alpha) before analysis and tracing.
    """
    import numpy as np

    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[..., 3]
    r = rgba[..., 0].astype(np.int16)
    g = rgba[..., 1].astype(np.int16)
    b = rgba[..., 2].astype(np.int16)
    # Classic chroma keys + near-transparent anything.
    magenta = (r >= 200) & (b >= 200) & (g <= 80) & (alpha < 250)
    near_invisible = alpha < 16
    kill = magenta | near_invisible
    out = rgba.copy()
    # Cleared pixels keep their matte RGB: zeroing it would turn a transparent
    # white matte into a "black matte" that solidify_black_matte then bakes
    # opaque. Only the chroma key itself is neutralised.
    if np.any(kill):
        out[kill, 3] = 0
        out[magenta, :3] = 255
    # Soft cutout fringe (alpha 16–96): mid-greys along the silhouette become
    # pale soft-iso labels and show as white slivers outside the black outline.
    # Clear low coverage; promote denser fringe to fully opaque so labels snap
    # to a real fill instead of a translucent ghost.
    alpha2 = out[..., 3]
    soft = (alpha2 >= 16) & (alpha2 < 96)
    if np.any(soft):
        promote = soft & (alpha2 >= 48)
        clear = soft & ~promote
        out[clear, 3] = 0
        out[promote, 3] = 255
    # Light AA halo outside dark ink rings (e.g. grey ~142 at alpha ~190 on
    # crest exports). Those pixels are closer to "empty" than to any fill and
    # otherwise become white/grey soft-iso ribbons around the badge.
    alpha3 = out[..., 3]
    rgb3 = out[..., :3].astype(np.int16)
    luma = 0.299 * rgb3[..., 0] + 0.587 * rgb3[..., 1] + 0.114 * rgb3[..., 2]
    sat = rgb3.max(axis=2) - rgb3.min(axis=2)
    pale = (alpha3 >= 96) & (alpha3 < 250) & (luma >= 90) & (sat <= 40)
    if np.any(pale):
        empty = alpha3 < 16
        padded = np.pad(empty, 1, constant_values=False)
        near_empty = (
            padded[:-2, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
            | padded[2:, 1:-1]
            | padded[:-2, :-2]
            | padded[:-2, 2:]
            | padded[2:, :-2]
            | padded[2:, 2:]
        )
        halo = pale & near_empty
        if np.any(halo):
            out[halo, 3] = 0
    if not np.any(kill) and not np.any(soft) and not np.any(pale):
        return image.convert("RGBA")
    return Image.fromarray(out, mode="RGBA")


def solidify_black_matte(image: Image.Image) -> Image.Image:
    """Bake near-black transparent pixels to opaque black.

    Many app icons store a black canvas as RGBA(0,0,0,0). Viewers show black;
    tracers saw empty labels and painted a white underlay instead. When most
    transparent pixels are near-black, treat them as an intentional black matte.
    """
    import numpy as np

    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    alpha = rgba[..., 3]
    transparent = alpha < 128
    if not np.any(transparent):
        return image.convert("RGBA")
    trans_rgb = rgba[transparent, :3].astype(np.int16)
    near_black = (trans_rgb[:, 0] <= 28) & (trans_rgb[:, 1] <= 28) & (trans_rgb[:, 2] <= 28)
    # Also accept very dark cool mattes (Gockl-style blue-black holes).
    luma = (
        0.299 * trans_rgb[:, 0] + 0.587 * trans_rgb[:, 1] + 0.114 * trans_rgb[:, 2]
    )
    dark_matte = near_black | (luma <= 55)
    # Icons often put the subject on a fully transparent canvas that is meant
    # to read as black; if opaque coverage is sparse, solidify the rest too.
    opaque_ratio = float((alpha >= 128).mean())
    threshold = 0.55 if opaque_ratio <= 0.35 else 0.70
    if float(dark_matte.mean()) < threshold:
        return image.convert("RGBA")
    # Cutout badges/crests (colourful opaque subject + empty corners) must keep
    # real transparency. Only solidify when the mark is sparse or itself mostly
    # near-black (ChatGPT / Brave style black mattes).
    opaque = rgba[alpha >= 128, :3].astype(np.int16)
    if opaque_ratio >= 0.50 and len(opaque):
        opaque_luma = (
            0.299 * opaque[:, 0] + 0.587 * opaque[:, 1] + 0.114 * opaque[:, 2]
        )
        if float((opaque_luma <= 55).mean()) < 0.55:
            return image.convert("RGBA")
    out = rgba.copy()
    ys, xs = np.nonzero(transparent)
    keep = dark_matte
    out[ys[keep], xs[keep], 0] = 0
    out[ys[keep], xs[keep], 1] = 0
    out[ys[keep], xs[keep], 2] = 0
    out[ys[keep], xs[keep], 3] = 255
    return Image.fromarray(out, mode="RGBA")


def _knock_out_color(
    image: Image.Image,
    color: tuple[int, int, int],
    tolerance: int,
) -> Image.Image:
    """Fade alpha where RGB is near `color`, using OKLab distance.

    Hard sRGB box knock-out left anti-aliased halos (partially mixed edge
    pixels kept full opacity). A soft ramp unmixed those fringes instead.
    """
    import numpy as np

    from vectorizer.raster.color import srgb_u8_to_oklab

    rgba = np.asarray(image, dtype=np.uint8)
    pixels_lab = srgb_u8_to_oklab(rgba[..., :3])
    bg_lab = srgb_u8_to_oklab(np.asarray([[color]], dtype=np.uint8))[0, 0]
    delta = pixels_lab - bg_lab
    dist = np.sqrt(np.einsum("hwc,hwc->hw", delta, delta, optimize=True))
    # Map the legacy 0..255 channel tolerance onto an OKLab radius. Empirically
    # ~0.25 OKLab ≈ full sRGB cube diagonal; scale linearly with tolerance.
    hard = max(0.004, (max(0, int(tolerance)) / 255.0) * 0.22)
    soft = hard * 1.65
    # 1 = keep, 0 = fully transparent.
    fade = (dist - hard) / max(1e-6, (soft - hard))
    fade = np.clip(fade, 0.0, 1.0).astype(np.float32)
    out = rgba.copy()
    out[..., 3] = np.minimum(out[..., 3], np.round(out[..., 3] * fade).astype(np.uint8))
    return Image.fromarray(out, mode="RGBA")


def _smooth_noise_rgba(image: Image.Image) -> Image.Image:
    """3×3 median on RGB; keep the original alpha channel untouched."""
    alpha = image.getchannel("A")
    rgb = image.convert("RGB").filter(ImageFilter.MedianFilter(size=3))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def _quantize_rgba(image: Image.Image, colors: int) -> Image.Image:
    """Palette-reduce RGB without dithering (dither creates fake speckles for tracers)."""
    colors = max(2, min(256, int(colors)))
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    # MAXCOVERAGE tends to keep saturated brand colors better than median-cut alone
    # on logos; fall back if the Pillow build lacks the enum member.
    method = getattr(Image.Quantize, "MAXCOVERAGE", Image.Quantize.MEDIANCUT)
    try:
        quantized = rgb.quantize(colors=colors, method=method, dither=Image.Dither.NONE)
    except Exception:
        quantized = rgb.quantize(
            colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
        )
    restored = quantized.convert("RGBA")
    restored.putalpha(alpha)
    return restored


def extract_palette_hex(image: Image.Image, max_colors: int = 32) -> list[str]:
    """Unique opaque colors from an RGBA image, capped for UI display."""
    rgba = image.convert("RGBA")
    colors = rgba.getcolors(maxcolors=max_colors * 8)
    if colors is None:
        quantized = _quantize_rgba(rgba, max_colors)
        colors = quantized.getcolors(maxcolors=max_colors * 4)
    if not colors:
        return []
    hexes: list[str] = []
    for _count, pixel in sorted(colors, key=lambda item: -item[0]):
        if len(pixel) == 4:
            r, g, b, a = pixel
            if a < 16:
                continue
        else:
            r, g, b = pixel[:3]
        hexes.append(f"#{r:02x}{g:02x}{b:02x}")
        if len(hexes) >= max_colors:
            break
    return hexes
