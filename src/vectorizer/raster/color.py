"""Perceptual color helpers used by palette constraint and blend tracing."""

from __future__ import annotations

import numpy as np

from vectorizer.domain.settings import normalize_hex


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = normalize_hex(value)[1:]
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (int(c) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def srgb_u8_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """Convert uint8 sRGB (..., 3) to OKLab float32. Public-domain OKLab (Ottosson)."""
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    linear = np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
    r = linear[..., 0]
    g = linear[..., 1]
    b = linear[..., 2]
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_ = np.cbrt(np.clip(l, 0.0, None))
    m_ = np.cbrt(np.clip(m, 0.0, None))
    s_ = np.cbrt(np.clip(s, 0.0, None))
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    A = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return np.stack((L, A, B), axis=-1).astype(np.float32)


def nearest_oklab(
    pixels: np.ndarray,
    palette: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (index HxW int16, squared-distance HxW float32) to the nearest palette row."""
    height, width, _ = pixels.shape
    flat = np.ascontiguousarray(pixels, dtype=np.float32).reshape(-1, 3)
    pal = np.ascontiguousarray(palette, dtype=np.float32)
    index = np.empty(flat.shape[0], dtype=np.int16)
    dist = np.empty(flat.shape[0], dtype=np.float32)
    chunk = 200_000
    for start in range(0, flat.shape[0], chunk):
        block = flat[start : start + chunk]
        delta = block[:, None, :] - pal[None, :, :]
        squared = np.einsum("nkc,nkc->nk", delta, delta)
        index[start : start + chunk] = squared.argmin(axis=1).astype(np.int16)
        dist[start : start + chunk] = squared.min(axis=1)
    return index.reshape(height, width), dist.reshape(height, width)


def project_coverage(origin: np.ndarray, color_a: np.ndarray, color_b: np.ndarray) -> float:
    """Fraction of `color_a` in `origin` along the OKLab segment A→B. 1 means pure A."""
    ab = color_b - color_a
    denom = float(np.dot(ab, ab))
    if denom < 1e-10:
        return 1.0
    along = float(np.dot(origin - color_a, ab) / denom)
    return float(min(1.0, max(0.0, 1.0 - along)))
