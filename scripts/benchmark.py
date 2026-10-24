#!/usr/bin/env python3
"""Reproducible synthetic benchmark. Not a Vector Magic comparison."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from vectorizer.domain.settings import ColorMode, PathFitMode, TraceSettings
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.raster.loader import load_image
from vectorizer.raster.preprocess import preprocess_image
from vectorizer.segmentation.build import build_segmentation
from vectorizer.segmentation.ops import flood_fill, remove_small_regions
from vectorizer.vectorize.vtracer_backend import VTracerBackend
from tests.fixtures.generate import generate_fixtures

OUT_DIR = ROOT / "benchmark_results"


def _large_logo(size: tuple[int, int] = (1600, 1200)) -> Image.Image:
    image = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.ellipse((w * 0.15, h * 0.15, w * 0.7, h * 0.75), fill=(30, 90, 200, 255))
    draw.rectangle((w * 0.55, h * 0.2, w * 0.85, h * 0.55), fill=(200, 40, 40, 255))
    draw.polygon(
        [(w * 0.2, h * 0.8), (w * 0.45, h * 0.45), (w * 0.7, h * 0.8)],
        fill=(40, 160, 80, 255),
    )
    return image


def main() -> int:
    fixtures = generate_fixtures(ROOT / "tests" / "fixtures")
    backend = VTracerBackend()
    cases = [
        ("mono_logo.png", TraceSettings(colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON)),
        ("aa_logo.png", TraceSettings(colormode=ColorMode.COLOR, mode=PathFitMode.SPLINE)),
        ("transparent.png", TraceSettings()),
        ("thin_lines.png", TraceSettings(colormode=ColorMode.BINARY, filter_speckle=0)),
        ("nested_holes.png", TraceSettings(colormode=ColorMode.BINARY, mode=PathFitMode.POLYGON)),
        ("disconnected.png", TraceSettings(filter_speckle=0)),
        ("noisy.png", TraceSettings(filter_speckle=4)),
        ("gradient.png", TraceSettings(color_precision=5, filter_speckle=2)),
        ("photo_like.png", TraceSettings(filter_speckle=8, color_precision=5)),
    ]
    rows = []
    for name, settings in cases:
        image = load_image(fixtures[name]).image
        t0 = time.perf_counter()
        result = backend.trace(image, settings)
        elapsed = time.perf_counter() - t0
        rows.append(
            {
                "input": name,
                "settings": settings.to_json(),
                "seconds": round(elapsed, 4),
                "path_count": result.document.path_count,
                "svg_bytes": result.document.byte_size,
                "backend": result.backend_name,
            }
        )
        print(f"{name:28} {elapsed:7.3f}s  paths={result.document.path_count:4}  bytes={result.document.byte_size}")

    # Larger synthetic cases that exercise preprocess + segmentation hot paths.
    large = _large_logo()
    knock_settings = TraceSettings(
        remove_background=True,
        background_r=255,
        background_g=255,
        background_b=255,
        background_tolerance=8,
        target_colors=8,
        colormode=ColorMode.COLOR,
        mode=PathFitMode.SPLINE,
    ).validated()
    t0 = time.perf_counter()
    processed = preprocess_image(large, knock_settings)
    knock_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    result = backend.trace(processed, knock_settings)
    trace_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    sync = run_trace_sync(large, knock_settings)
    sync_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    seg = build_segmentation(large, knock_settings)
    build_s = time.perf_counter() - t0
    seed = next(
        (x, y)
        for y in range(0, seg.size[1], 17)
        for x in range(0, seg.size[0], 17)
        if seg.pixel(x, y)[3] > 0
    )
    t0 = time.perf_counter()
    flooded = flood_fill(seg, seed[0], seed[1], (255, 0, 0, 255))
    flood_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    remove_small_regions(flooded, min_pixels=32)
    clean_s = time.perf_counter() - t0

    heavy = {
        "input": "synthetic_1600x1200",
        "knockout_seconds": round(knock_s, 4),
        "trace_preprocessed_seconds": round(trace_s, 4),
        "run_trace_sync_seconds": round(sync_s, 4),
        "build_segmentation_seconds": round(build_s, 4),
        "flood_fill_seconds": round(flood_s, 4),
        "remove_small_seconds": round(clean_s, 4),
        "path_count": sync.document.path_count,
        "svg_bytes": sync.document.byte_size,
    }
    print(
        f"{'synthetic_1600x1200':28} knock={knock_s:.3f}s trace={trace_s:.3f}s "
        f"sync={sync_s:.3f}s seg={build_s:.3f}s flood={flood_s:.3f}s clean={clean_s:.3f}s "
        f"paths={sync.document.path_count}"
    )
    rows.append(heavy)

    OUT_DIR.mkdir(exist_ok=True)
    payload = {"suite": "synthetic-m1+hotpaths", "results": rows}
    (OUT_DIR / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = ["| Input | Seconds | Paths | SVG bytes |", "| --- | --- | --- | --- |"]
    for row in rows:
        if "seconds" in row:
            lines.append(f"| {row['input']} | {row['seconds']} | {row['path_count']} | {row['svg_bytes']} |")
        else:
            lines.append(
                f"| {row['input']} | sync {row['run_trace_sync_seconds']} "
                f"(knock {row['knockout_seconds']}, flood {row['flood_fill_seconds']}) | "
                f"{row['path_count']} | {row['svg_bytes']} |"
            )
    (OUT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_DIR / 'latest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
