#!/usr/bin/env python3
"""Build packaging/macos/Vectorizer.icns from the 512px PNG icon."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "packaging" / "icons" / "hicolor" / "512x512" / "apps" / "vectorizer.png"
OUT = ROOT / "packaging" / "macos" / "Vectorizer.icns"
SIZES = (16, 32, 64, 128, 256, 512)


def main() -> int:
    if not SRC.is_file():
        print(f"Missing source icon: {SRC}", file=sys.stderr)
        return 1
    base = Image.open(SRC).convert("RGBA")
    images = [base.resize((size, size), Image.Resampling.LANCZOS) for size in SIZES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images[-1].save(OUT, format="ICNS", append_images=images[:-1])
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
