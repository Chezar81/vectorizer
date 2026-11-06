"""Optional GPU acceleration for dense raster colour maths.

Path topology (marching squares, curve fit, VTracer) always stays on the CPU so
results remain consistent. When CuPy + CUDA are ready and the active plan allows
GPU raster work, nearest-OKLab assignment can run on the device for large images.
"""

from __future__ import annotations

import numpy as np

from vectorizer.hardware.policy import active_plan, ensure_compute_plan, gpu_raster_worthwhile


def nearest_oklab_accelerated(
    pixels: np.ndarray,
    palette: np.ndarray,
    *,
    chroma_weight: float = 1.0,
) -> tuple[np.ndarray, np.ndarray] | None:
    """GPU nearest-OKLab if worthwhile; otherwise None (caller uses CPU)."""
    ensure_compute_plan()
    height, width, _ = pixels.shape
    if not gpu_raster_worthwhile(height * width):
        return None
    try:
        import cupy as cp  # type: ignore
    except Exception:
        return None

    plan = active_plan()
    if plan is None or not plan.use_gpu_raster:
        return None

    flat = np.ascontiguousarray(pixels, dtype=np.float32).reshape(-1, 3)
    pal = np.ascontiguousarray(palette, dtype=np.float32)
    if pal.shape[0] == 0:
        index = np.zeros((height, width), dtype=np.int16)
        dist = np.zeros((height, width), dtype=np.float32)
        return index, dist

    weight = np.asarray(
        [1.0, max(1.0, float(chroma_weight)), max(1.0, float(chroma_weight))],
        dtype=np.float32,
    )
    try:
        d_flat = cp.asarray(flat)
        d_pal = cp.asarray(pal)
        d_weight = cp.asarray(weight)
        # Chunk to keep the (pixels × palette × 3) temporary bounded on VRAM.
        n_pixels = flat.shape[0]
        n_palette = pal.shape[0]
        chunk = max(1, min(200_000, (4_000_000 // max(1, n_palette))))
        index = cp.empty(n_pixels, dtype=cp.int16)
        dist = cp.empty(n_pixels, dtype=cp.float32)
        for start in range(0, n_pixels, chunk):
            block = d_flat[start : start + chunk]
            delta = (block[:, None, :] - d_pal[None, :, :]) * d_weight
            squared = cp.sum(delta * delta, axis=2)
            best = squared.argmin(axis=1)
            rows = cp.arange(best.shape[0])
            index[start : start + chunk] = best.astype(cp.int16)
            dist[start : start + chunk] = squared[rows, best]
        cp.cuda.Stream.null.synchronize()
        return (
            cp.asnumpy(index).reshape(height, width),
            cp.asnumpy(dist).reshape(height, width),
        )
    except Exception:
        return None
