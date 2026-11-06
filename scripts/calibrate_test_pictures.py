#!/usr/bin/env python3
"""Calibrate Automatic vectorization against test_pictures/.

Traces each source, rasterizes the SVG back to the same size, and reports
mean absolute RGB error + structural agreement versus the original.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vectorizer.export.png import export_png_preview  # noqa: E402
from vectorizer.export.svg import export_svg  # noqa: E402
from vectorizer.jobs.runner import run_trace_sync  # noqa: E402
from vectorizer.raster.analyzer import analyze_image  # noqa: E402
from vectorizer.raster.preprocess import preprocess_image, solidify_black_matte  # noqa: E402


def _ensure_qt() -> QGuiApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app  # type: ignore[return-value]


def _resize_max(image: Image.Image, max_side: int) -> Image.Image:
    w, h = image.size
    if max(w, h) <= max_side:
        return image
    scale = max_side / float(max(w, h))
    return image.resize(
        (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
        Image.Resampling.LANCZOS,
    )


def _composite_on(rgb_bg: tuple[int, int, int], rgba: Image.Image) -> Image.Image:
    base = Image.new("RGB", rgba.size, rgb_bg)
    return Image.alpha_composite(base.convert("RGBA"), rgba.convert("RGBA")).convert("RGB")


def _metrics(original: Image.Image, rendered: Image.Image) -> dict[str, float]:
    a = np.asarray(original.convert("RGB"), dtype=np.float32)
    b = np.asarray(rendered.convert("RGB"), dtype=np.float32)
    if a.shape != b.shape:
        b_img = rendered.convert("RGB").resize(original.size, Image.Resampling.LANCZOS)
        b = np.asarray(b_img, dtype=np.float32)
    diff = np.abs(a - b)
    mae = float(diff.mean())
    rmse = float(np.sqrt((diff ** 2).mean()))
    # Fraction of pixels within a small tolerance (near-match).
    close = float((diff.max(axis=2) <= 18).mean())
    # Perceptual-ish: mean of per-channel correlation.
    corr = []
    for c in range(3):
        ac = a[..., c].ravel()
        bc = b[..., c].ravel()
        if ac.std() < 1e-3 or bc.std() < 1e-3:
            corr.append(1.0 if abs(ac.mean() - bc.mean()) < 5 else 0.0)
        else:
            corr.append(float(np.corrcoef(ac, bc)[0, 1]))
    return {
        "mae": mae,
        "rmse": rmse,
        "close_pct": close * 100.0,
        "corr": float(np.mean(corr)),
    }


def _side_by_side(original: Image.Image, rendered: Image.Image, label: str) -> Image.Image:
    o = original.convert("RGB")
    r = rendered.convert("RGB").resize(o.size, Image.Resampling.LANCZOS)
    gap = 8
    canvas = Image.new("RGB", (o.width * 2 + gap, o.height + 36), (32, 32, 36))
    canvas.paste(o, (0, 36))
    canvas.paste(r, (o.width + gap, 36))
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), f"Original | Vector  —  {label}", fill=(230, 230, 235))
    return canvas


def calibrate(max_side: int, out_dir: Path) -> list[dict]:
    _ensure_qt()
    src_dir = ROOT / "test_pictures"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "svg").mkdir(exist_ok=True)
    (out_dir / "png").mkdir(exist_ok=True)
    (out_dir / "compare").mkdir(exist_ok=True)

    rows: list[dict] = []
    files = sorted(
        p
        for p in src_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ""}
        or (p.is_file() and not p.name.startswith("."))
    )
    # Include extensionless PNG (GolfCart)
    files = sorted({p for p in src_dir.iterdir() if p.is_file()})

    for path in files:
        try:
            raw = Image.open(path)
            raw.load()
        except Exception as exc:
            print(f"SKIP {path.name}: {exc}")
            continue
        image = _resize_max(solidify_black_matte(raw.convert("RGBA")), max_side)
        t0 = time.perf_counter()
        analysis = analyze_image(image)
        settings = analysis.suggested
        prepared = preprocess_image(image, settings)
        result = run_trace_sync(prepared, settings)
        elapsed = time.perf_counter() - t0

        stem = path.name.replace(".", "_")
        svg_path = out_dir / "svg" / f"{stem}.svg"
        png_path = out_dir / "png" / f"{stem}.png"
        export_svg(result.document, svg_path)
        # Fair compare: same canvas colour the tracer used (black matte logos,
        # white paper cartoons, etc.).
        if analysis.metrics.background_rgb is not None:
            r, g, b = analysis.metrics.background_rgb
            bg = f"#{r:02x}{g:02x}{b:02x}"
        else:
            bg = "#808080"
        export_png_preview(
            result.document,
            png_path,
            width=image.size[0],
            height=image.size[1],
            background=bg,
        )
        rendered = Image.open(png_path).convert("RGBA")
        hexcol = bg.lstrip("#")
        rgb = tuple(int(hexcol[i : i + 2], 16) for i in (0, 2, 4))
        original_cmp = _composite_on(rgb, image)  # type: ignore[arg-type]
        rendered_cmp = _composite_on(rgb, rendered)  # type: ignore[arg-type]

        scores = _metrics(original_cmp, rendered_cmp)
        label = (
            f"{path.name}  {analysis.content_kind.name}/{settings.edge_treatment.name}  "
            f"pal={len(settings.palette)}  mae={scores['mae']:.1f}  "
            f"close={scores['close_pct']:.0f}%  t={elapsed:.1f}s"
        )
        compare = _side_by_side(original_cmp, rendered_cmp, label)
        compare.save(out_dir / "compare" / f"{stem}.png")

        row = {
            "file": path.name,
            "size": f"{image.size[0]}x{image.size[1]}",
            "kind": analysis.content_kind.name,
            "edge": settings.edge_treatment.name,
            "palette": len(settings.palette),
            "target_colors": settings.target_colors,
            "remove_bg": settings.remove_background,
            "smooth": settings.smooth_noise,
            "speckle": settings.filter_speckle,
            "paths": result.document.path_count,
            "seconds": round(elapsed, 2),
            **{k: round(v, 3) for k, v in scores.items()},
            "note": analysis.notes[0] if analysis.notes else "",
        }
        rows.append(row)
        print(
            f"{path.name:32} {row['kind']:12} {row['edge']:8} "
            f"mae={row['mae']:5.1f} close={row['close_pct']:5.1f}% "
            f"corr={row['corr']:.3f} paths={row['paths']:4} {row['seconds']:5.1f}s"
        )

    rows.sort(key=lambda r: r["mae"], reverse=True)
    with (out_dir / "scores.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    (out_dir / "scores.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("\nWorst by MAE:")
    for row in rows[:5]:
        print(f"  {row['file']:32} mae={row['mae']:.1f} close={row['close_pct']:.1f}%")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-side", type=int, default=900)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "benchmark_results" / "calib_test_pictures",
    )
    args = parser.parse_args()
    calibrate(args.max_side, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
