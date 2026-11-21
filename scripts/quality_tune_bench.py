#!/usr/bin/env python3
"""Baseline / after metrics for Automatic mode on test_pictures/."""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vectorizer.raster.analyzer import analyze_image  # noqa: E402
from vectorizer.raster.loader import load_image  # noqa: E402
from vectorizer.vectorize.dispatch import trace_prepared  # noqa: E402

SRC = ROOT / "test_pictures"
OUT = ROOT / "benchmark_results" / "quality_tune"


def _files() -> list[Path]:
    return sorted(p for p in SRC.iterdir() if p.is_file() and not p.name.startswith("."))


def _rmse(original: Image.Image, svg: str, *, max_side: int = 512) -> float | None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtCore import QByteArray, QSize, Qt
        from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None
    if QApplication.instance() is None:
        QApplication([])
    w, h = original.size
    scale = min(1.0, max_side / float(max(w, h)))
    out_w = max(1, int(round(w * scale)))
    out_h = max(1, int(round(h * scale)))
    src = original.convert("RGBA")
    if (out_w, out_h) != (w, h):
        src = src.resize((out_w, out_h), Image.Resampling.BOX)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return None
    image = QImage(QSize(out_w, out_h), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    renderer.render(painter)
    painter.end()
    ptr = image.bits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((out_h, out_w, 4))
    # Qt ARGB32 premultiplied is BGRA in memory on little-endian.
    bgra = arr.copy()
    rendered = np.empty_like(bgra)
    rendered[..., 0] = bgra[..., 2]
    rendered[..., 1] = bgra[..., 1]
    rendered[..., 2] = bgra[..., 0]
    rendered[..., 3] = bgra[..., 3]
    src_arr = np.asarray(src, dtype=np.float32)
    ren = rendered.astype(np.float32)
    # Composite both on white so transparent logos compare fairly.
    def _over_white(rgba: np.ndarray) -> np.ndarray:
        a = rgba[..., 3:4] / 255.0
        return rgba[..., :3] * a + 255.0 * (1.0 - a)

    diff = _over_white(src_arr) - _over_white(ren)
    return float(np.sqrt((diff ** 2).mean()))


def main() -> None:
    trace = "--analyze-only" not in sys.argv
    tag = "after" if "--after" in sys.argv else "before"
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in _files():
        row: dict = {"file": path.name}
        try:
            loaded = load_image(path)
            image = loaded.image
            row["width"] = image.size[0]
            row["height"] = image.size[1]
            row["pixels"] = image.size[0] * image.size[1]
            t0 = time.perf_counter()
            analysis = analyze_image(image)
            row["analyze_s"] = round(time.perf_counter() - t0, 3)
            m = analysis.metrics
            s = analysis.suggested
            row.update(
                {
                    "content_kind": analysis.content_kind.value,
                    "edge_treatment": s.edge_treatment.value,
                    "photo_like": analysis.photo_like,
                    "palette_n": len(s.palette),
                    "palette": list(s.palette),
                    "target_colors": s.target_colors,
                    "remove_background": s.remove_background,
                    "preserve_transparency": s.preserve_transparency,
                    "filter_speckle": s.filter_speckle,
                    "corner_threshold": s.corner_threshold,
                    "layer_difference": s.layer_difference,
                    "color_precision": s.color_precision,
                    "colormode": s.colormode.value,
                    "mode": s.mode.value,
                    "smooth_noise": s.smooth_noise,
                    "unique_colors": m.unique_colors,
                    "flat_mass": round(m.flat_mass, 4),
                    "palette_estimate": m.palette_estimate,
                    "ink_outline_score": round(m.ink_outline_score, 5),
                    "edge_density": round(m.edge_density, 4),
                    "noise_score": round(m.noise_score, 4),
                    "fill_ratio": round(m.fill_ratio, 4),
                    "foreground_coverage": round(m.foreground_coverage, 4),
                    "corner_sharpness": round(m.corner_sharpness, 4),
                    "opaque_ratio": round(m.opaque_ratio, 4),
                    "has_alpha": m.has_alpha,
                    "minority_ratio": round(m.minority_ratio, 4),
                    "background_confidence": round(m.background_confidence, 3),
                    "notes": list(analysis.notes)[:3],
                }
            )
            print(
                f"ANALYZE {path.name:40} {analysis.content_kind.value:14} "
                f"{s.edge_treatment.value:8} pal={len(s.palette):2} "
                f"flat={m.flat_mass:.2f} ink={m.ink_outline_score:.4f} "
                f"edge={m.edge_density:.2f} cov={m.foreground_coverage:.2f} "
                f"sharp={m.corner_sharpness:.2f} uniq={m.unique_colors} "
                f"est={m.palette_estimate} {image.size[0]}x{image.size[1]}",
                flush=True,
            )
            if trace:
                t1 = time.perf_counter()
                result = trace_prepared(
                    image,
                    s,
                    content_kind=analysis.content_kind.value,
                )
                wall = time.perf_counter() - t1
                svg = result.document.raw_svg
                row["backend"] = result.backend_name
                row["path_count"] = result.document.path_count
                row["svg_bytes"] = len(svg.encode("utf-8"))
                row["wall_s"] = round(wall, 3)
                row["warnings"] = list(result.warnings)
                rmse = _rmse(image, svg)
                row["rmse"] = None if rmse is None else round(rmse, 3)
                svg_dir = OUT / tag / "svg"
                svg_dir.mkdir(parents=True, exist_ok=True)
                (svg_dir / f"{path.name}.svg").write_text(svg, encoding="utf-8")
                print(
                    f"  TRACE backend={result.backend_name} paths={result.document.path_count} "
                    f"svg={row['svg_bytes']} wall={wall:.2f}s rmse={row['rmse']} "
                    f"warn={result.warnings}",
                    flush=True,
                )
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["traceback"] = traceback.format_exc()
            print(f"FAIL {path.name}: {exc}", flush=True)
        rows.append(row)
        (OUT / f"{tag}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"WROTE {OUT / f'{tag}.json'} ({len(rows)} rows)", flush=True)


if __name__ == "__main__":
    main()
