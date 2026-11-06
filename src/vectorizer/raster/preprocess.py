"""Preprocessing applied to a copy of the source; never mutates the original."""

from __future__ import annotations

from PIL import Image, ImageFilter

from vectorizer.domain.settings import TraceSettings


def preprocess_image(image: Image.Image, settings: TraceSettings) -> Image.Image:
    """Return a working RGBA image for tracing.

    Original `image` is left unchanged. Operations (in order):
    - solidify near-black transparent mattes (icon “black backgrounds”)
    - optional flattening of existing alpha when preserve_transparency is False
    - optional background removal by color + tolerance
    - optional light noise smoothing (median) while preserving alpha
    - optional color quantization (soft palette / target color count, no dither)
    """
    settings = settings.validated()
    working = image.convert("RGBA").copy()
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


def cel_stroke_mask(rgb: Image.Image | object) -> object:
    """Boolean mask of dark ink outlines abutting brighter fills.

    JPEG cel art browns true black; require local contrast so couch shadows are
    not treated as strokes.
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
    return edge_ink | dark_on_dark | thin_ink


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
    stroke = cel_stroke_mask(rgb)
    if not np.any(stroke):
        return snap_image_to_palette(rgba, palette)
    stroke = _binary_close(stroke)
    # Bridge 1px gaps between stroke pixels (JPEG breakups).
    stroke = _bridge_stroke_gaps(rgb, stroke)
    # Clear AA brown fringe from fills, but bake ink at the closed stroke
    # width — dilating the bake made Simpsons outlines look like charcoal.
    fill_hole = _binary_dilate(stroke, 1)
    filled = _inpaint_masked(rgb, fill_hole, fallback=ink_rgb)
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
    out[..., 3] = np.asarray(rgba)[..., 3]
    return Image.fromarray(out, mode="RGBA")


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


def _inpaint_masked(
    rgb: object,
    missing: object,
    *,
    fallback: tuple[int, int, int],
    passes: int = 10,
) -> object:
    """Propagate neighbouring known colours into `missing` pixels."""
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
    out[hole] = fallback
    return np.clip(out, 0, 255).astype(np.uint8)


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
