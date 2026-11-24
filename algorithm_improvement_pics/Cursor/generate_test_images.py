#!/usr/bin/env python3
"""Generate vectorization algorithm test images (1–10)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent
W, H = 800, 800


def save(img: Image.Image, name: str) -> Path:
    path = OUT / name
    img.convert("RGB").save(path, "PNG", optimize=True)
    print(f"wrote {path.name}")
    return path


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# 1  Black/white primitives with holes and fine lines
# ---------------------------------------------------------------------------
def img01() -> None:
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    # Outer frame
    d.rectangle([20, 20, W - 21, H - 21], outline="black", width=4)

    # Filled circle with triangular hole
    d.ellipse([60, 60, 320, 320], fill="black")
    d.polygon([(190, 120), (250, 260), (130, 260)], fill="white")

    # Annulus (ring)
    d.ellipse([380, 70, 620, 310], fill="black")
    d.ellipse([430, 120, 570, 260], fill="white")

    # Nested rectangles with corner cutouts
    d.rectangle([80, 380, 340, 640], fill="black")
    d.rectangle([120, 420, 300, 600], fill="white")
    d.rectangle([150, 450, 270, 570], fill="black")
    d.rectangle([180, 480, 240, 540], fill="white")

    # Star-like polygon with internal diamond hole
    cx, cy, r = 500, 510, 130
    outer = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        outer.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    d.polygon(outer, fill="black")
    d.polygon(
        [(cx, cy - 40), (cx + 40, cy), (cx, cy + 40), (cx - 40, cy)],
        fill="white",
    )

    # Fine lines of varying stroke width
    for i, width in enumerate([1, 2, 3, 4, 6, 8]):
        y = 680 + i * 16
        d.line([(60, y), (740, y)], fill="black", width=width)

    # Dense hatching / fine diagonal lines
    for i in range(0, 200, 6):
        d.line([(640, 60 + i), (760, 180 + i)], fill="black", width=1)

    # Thin concentric arcs
    for r in range(20, 90, 8):
        d.arc([650 - r, 650 - r, 650 + r, 650 + r], 200, 340, fill="black", width=1)

    # Small dots / stipple
    for x in range(360, 720, 10):
        for y in range(340, 370, 10):
            d.ellipse([x, y, x + 2, y + 2], fill="black")

    save(img, "01_bw_shapes_holes_lines.png")


# ---------------------------------------------------------------------------
# 2  Clearly separated saturated color regions
# ---------------------------------------------------------------------------
def img02() -> None:
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)

    colors = [
        ("#E53935", [40, 40, 390, 390]),  # red square
        ("#1E88E5", [410, 40, 760, 390]),  # blue square
        ("#43A047", [40, 410, 390, 760]),  # green square
        ("#FDD835", [410, 410, 760, 760]),  # yellow square
    ]
    for color, box in colors:
        d.rectangle(box, fill=color)

    # Center circle magenta + cyan triangle + orange ellipse
    d.ellipse([280, 280, 520, 520], fill="#D81B60")
    d.polygon([(400, 120), (520, 260), (280, 260)], fill="#00ACC1")
    d.ellipse([560, 560, 720, 700], fill="#FB8C00")
    d.rectangle([80, 560, 220, 700], fill="#8E24AA")

    save(img, "02_saturated_color_regions.png")


# ---------------------------------------------------------------------------
# 3  Adjacent very similar hues
# ---------------------------------------------------------------------------
def img03() -> None:
    img = Image.new("RGB", (W, H), "#F5F5F5")
    d = ImageDraw.Draw(img)

    # Horizontal strips: blues differing by ~8–12 RGB units
    blues = [
        (70, 130, 180),
        (78, 136, 186),
        (86, 142, 192),
        (94, 148, 198),
        (102, 154, 204),
        (110, 160, 210),
        (118, 166, 216),
        (126, 172, 222),
    ]
    strip_h = H // len(blues)
    for i, c in enumerate(blues):
        d.rectangle([0, i * strip_h, W, (i + 1) * strip_h], fill=c)

    # Vertical wedges with near-identical greens
    greens = [
        (46, 125, 50),
        (52, 130, 56),
        (58, 135, 62),
        (64, 140, 68),
        (70, 145, 74),
        (76, 150, 80),
    ]
    for i, c in enumerate(greens):
        x0 = 80 + i * 100
        d.polygon(
            [(x0, 120), (x0 + 90, 120), (x0 + 70, 360), (x0 + 20, 360)],
            fill=c,
        )

    # Checker of almost-matching warm greys
    a, b = (180, 160, 140), (188, 166, 146)
    for row in range(6):
        for col in range(8):
            x0, y0 = 80 + col * 80, 420 + row * 50
            d.rectangle([x0, y0, x0 + 78, y0 + 48], fill=a if (row + col) % 2 == 0 else b)

    save(img, "03_adjacent_similar_hues.png")


# ---------------------------------------------------------------------------
# 4  Different hues, similar luminance (isoluminant boundaries)
# ---------------------------------------------------------------------------
def img04() -> None:
    # Approximate equal perceived brightness via Rec.709 luma ~0.5
    # R*0.2126 + G*0.7152 + B*0.0722 ≈ 128
    pairs = [
        ((220, 90, 90), (90, 140, 200)),  # coral / steel blue
        ((200, 100, 180), (100, 160, 110)),  # magenta / green
        ((230, 150, 60), (80, 130, 210)),  # orange / blue
        ((180, 80, 200), (60, 170, 140)),  # purple / teal
        ((240, 120, 80), (70, 150, 180)),  # vermillion / cyan-ish
        ((160, 100, 220), (120, 160, 80)),  # violet / olive
    ]

    img = Image.new("RGB", (W, H), "#808080")
    d = ImageDraw.Draw(img)

    # Six side-by-side panels
    pw, ph = W // 3, H // 2
    for i, (c1, c2) in enumerate(pairs):
        col, row = i % 3, i // 3
        x0, y0 = col * pw, row * ph
        d.rectangle([x0, y0, x0 + pw // 2 - 1, y0 + ph - 1], fill=c1)
        d.rectangle([x0 + pw // 2, y0, x0 + pw - 1, y0 + ph - 1], fill=c2)
        # Soft-looking but hard geometric cut: circle of opposite color
        cx, cy = x0 + pw // 2, y0 + ph // 2
        r = min(pw, ph) // 5
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c1 if i % 2 else c2)

    save(img, "04_isoluminant_color_boundaries.png")


# ---------------------------------------------------------------------------
# 5  Overlapping colored shapes with translucent mixes
# ---------------------------------------------------------------------------
def img05() -> None:
    base = Image.new("RGBA", (W, H), (245, 245, 240, 255))
    layers = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    shapes = [
        ((255, 60, 60, 140), "ellipse", [80, 120, 480, 520]),
        ((40, 100, 255, 140), "ellipse", [320, 120, 720, 520]),
        ((40, 200, 80, 140), "ellipse", [200, 300, 600, 700]),
        ((255, 200, 40, 120), "rect", [140, 80, 360, 300]),
        ((180, 40, 220, 120), "polygon", [(500, 80), (720, 200), (560, 360), (420, 220)]),
        ((0, 180, 200, 130), "rect", [420, 480, 680, 720]),
    ]

    for color, kind, geom in shapes:
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if kind == "ellipse":
            d.ellipse(geom, fill=color)
        elif kind == "rect":
            d.rectangle(geom, fill=color)
        else:
            d.polygon(geom, fill=color)
        layers = Image.alpha_composite(layers, layer)

    out = Image.alpha_composite(base, layers)
    save(out, "05_overlapping_translucent_shapes.png")


# ---------------------------------------------------------------------------
# 6  Linear and radial gradients vs discrete flat regions
# ---------------------------------------------------------------------------
def img06() -> None:
    arr = np.zeros((H, W, 3), dtype=np.uint8)

    # Top-left: horizontal linear gradient red→blue
    for x in range(W // 2):
        t = x / (W // 2 - 1)
        arr[: H // 2, x] = (
            int(220 * (1 - t) + 40 * t),
            int(40 * (1 - t) + 80 * t),
            int(40 * (1 - t) + 220 * t),
        )

    # Top-right: vertical linear gradient yellow→green
    for y in range(H // 2):
        t = y / (H // 2 - 1)
        arr[y, W // 2 :] = (
            int(240 * (1 - t) + 30 * t),
            int(200 * (1 - t) + 180 * t),
            int(40 * (1 - t) + 60 * t),
        )

    # Bottom-left: radial gradient
    cy, cx = 3 * H // 4, W // 4
    yy, xx = np.ogrid[:H, :W]
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    max_r = math.hypot(W / 4, H / 4)
    t = np.clip(dist / max_r, 0, 1)
    # Only fill bottom-left quadrant
    mask = (yy >= H // 2) & (xx < W // 2)
    arr[..., 0][mask] = (255 * (1 - t) + 20 * t)[mask].astype(np.uint8)
    arr[..., 1][mask] = (80 * (1 - t) + 40 * t)[mask].astype(np.uint8)
    arr[..., 2][mask] = (200 * (1 - t) + 120 * t)[mask].astype(np.uint8)

    # Bottom-right: discrete flat color blocks for contrast
    flats = [
        ((220, 50, 50), [W // 2, H // 2, W, 5 * H // 8]),
        ((50, 180, 70), [W // 2, 5 * H // 8, W, 6 * H // 8]),
        ((50, 90, 220), [W // 2, 6 * H // 8, W, 7 * H // 8]),
        ((240, 200, 40), [W // 2, 7 * H // 8, W, H]),
    ]
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)
    for color, box in flats:
        d.rectangle(box, fill=color)

    # Thin black divider lines to mark regions
    d.line([(W // 2, 0), (W // 2, H)], fill=(0, 0, 0), width=2)
    d.line([(0, H // 2), (W, H // 2)], fill=(0, 0, 0), width=2)

    save(img, "06_linear_radial_gradients.png")


# ---------------------------------------------------------------------------
# 7  Colored text on variously colored backgrounds
# ---------------------------------------------------------------------------
def img07() -> None:
    backgrounds = [
        "#FFFFFF",
        "#212121",
        "#E53935",
        "#1E88E5",
        "#43A047",
        "#FDD835",
        "#8E24AA",
        "#FF7043",
        "#26A69A",
        "#78909C",
        "#FFF3E0",
        "#E8F5E9",
        "#E3F2FD",
        "#FCE4EC",
        "#263238",
        "#5D4037",
    ]
    fg_choices = [
        "#000000",
        "#FFFFFF",
        "#FFEB3B",
        "#00E5FF",
        "#FF1744",
        "#76FF03",
        "#FFFFFF",
        "#212121",
        "#FFEE58",
        "#FFFFFF",
        "#BF360C",
        "#1B5E20",
        "#0D47A1",
        "#880E4F",
        "#80D8FF",
        "#FFE082",
    ]
    words = [
        "Vector",
        "Kontur",
        "Edge",
        "Fläche",
        "Detail",
        "Glyph",
        "AaBb",
        "12345",
        "μm²",
        "QqPp",
        "Stroke",
        "Fill",
        "Contrast",
        "Hinten",
        "Klein",
        "GROSS",
    ]

    img = Image.new("RGB", (W, H), "#EEEEEE")
    d = ImageDraw.Draw(img)
    cols, rows = 4, 4
    cell_w, cell_h = W // cols, H // rows
    f_big = font(36)
    f_small = font(18)
    f_tiny = font(12)

    for i, (bg, fg, word) in enumerate(zip(backgrounds, fg_choices, words)):
        col, row = i % cols, i // cols
        x0, y0 = col * cell_w, row * cell_h
        d.rectangle([x0, y0, x0 + cell_w - 1, y0 + cell_h - 1], fill=bg)
        # Main word
        bbox = d.textbbox((0, 0), word, font=f_big)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text((x0 + (cell_w - tw) / 2, y0 + 40), word, fill=fg, font=f_big)
        # Secondary small text for fine detail
        d.text((x0 + 10, y0 + cell_h - 50), "abc xyz", fill=fg, font=f_small)
        d.text((x0 + 10, y0 + cell_h - 28), "iIl1 O0", fill=fg, font=f_tiny)

    save(img, "07_colored_text_on_backgrounds.png")


# ---------------------------------------------------------------------------
# 8  Flat landscape illustration with organic shapes
# ---------------------------------------------------------------------------
def img08() -> None:
    img = Image.new("RGB", (W, H), "#87CEEB")
    d = ImageDraw.Draw(img)

    # Sky gradient
    for y in range(0, 380):
        t = y / 380
        c = (
            int(135 + 40 * t),
            int(206 - 30 * t),
            int(235 - 20 * t),
        )
        d.line([(0, y), (W, y)], fill=c)

    # Sun
    d.ellipse([560, 60, 680, 180], fill="#FFE082")
    d.ellipse([575, 75, 665, 165], fill="#FFF59D")

    # Distant mountains (organic layered polygons)
    d.polygon(
        [
            (0, 380),
            (60, 300),
            (140, 340),
            (220, 260),
            (320, 320),
            (400, 240),
            (500, 300),
            (600, 220),
            (700, 290),
            (800, 250),
            (800, 420),
            (0, 420),
        ],
        fill="#5C6BC0",
    )
    d.polygon(
        [
            (0, 420),
            (80, 360),
            (180, 400),
            (280, 330),
            (380, 390),
            (480, 340),
            (580, 400),
            (680, 350),
            (800, 390),
            (800, 480),
            (0, 480),
        ],
        fill="#7986CB",
    )

    # Hills
    d.polygon(
        [
            (0, 480),
            (100, 450),
            (250, 500),
            (400, 440),
            (550, 510),
            (700, 460),
            (800, 500),
            (800, 620),
            (0, 620),
        ],
        fill="#66BB6A",
    )
    d.polygon(
        [
            (0, 580),
            (150, 540),
            (300, 590),
            (450, 530),
            (600, 600),
            (750, 550),
            (800, 580),
            (800, H),
            (0, H),
        ],
        fill="#43A047",
    )

    # Lake
    d.ellipse([180, 560, 520, 700], fill="#29B6F6")
    d.ellipse([220, 580, 480, 670], fill="#4FC3F7")

    # Trees (simple organic blobs + trunks)
    for tx, ty, s, leaf in [
        (120, 520, 1.0, "#2E7D32"),
        (680, 540, 0.85, "#388E3C"),
        (640, 500, 0.7, "#1B5E20"),
        (90, 560, 0.75, "#33691E"),
        (720, 600, 0.9, "#2E7D32"),
    ]:
        tw = int(18 * s)
        th = int(50 * s)
        d.rectangle([tx - tw // 2, ty, tx + tw // 2, ty + th], fill="#6D4C41")
        for ox, oy, r in [(-20, -10, 35), (15, -5, 30), (0, -35, 40), (-10, 10, 28)]:
            rr = int(r * s)
            d.ellipse(
                [tx + int(ox * s) - rr, ty + int(oy * s) - rr, tx + int(ox * s) + rr, ty + int(oy * s) + rr],
                fill=leaf,
            )

    # Path
    d.polygon(
        [(360, H), (420, H), (400, 640), (380, 640)],
        fill="#A1887F",
    )

    # Clouds
    for cx, cy in [(120, 100), (200, 90), (160, 120), (300, 70)]:
        d.ellipse([cx - 40, cy - 25, cx + 40, cy + 25], fill="#FFFFFF")
    for cx, cy in [(420, 110), (480, 100), (450, 125)]:
        d.ellipse([cx - 35, cy - 22, cx + 35, cy + 22], fill="#FAFAFA")

    save(img, "08_flat_landscape_organic.png")


# ---------------------------------------------------------------------------
# 9  Colored patterns, fine structures and textures
# ---------------------------------------------------------------------------
def img09() -> None:
    img = Image.new("RGB", (W, H), "#FAFAFA")
    d = ImageDraw.Draw(img)

    # Quadrant 1: striped pattern
    for i in range(0, 400, 8):
        color = "#E53935" if (i // 8) % 2 == 0 else "#FFCDD2"
        d.rectangle([i, 0, i + 7, 400], fill=color)

    # Quadrant 2: checkerboard fine
    for y in range(0, 400, 10):
        for x in range(400, 800, 10):
            color = "#1565C0" if ((x // 10) + (y // 10)) % 2 == 0 else "#90CAF9"
            d.rectangle([x, y, x + 9, y + 9], fill=color)

    # Quadrant 3: concentric rings
    cx, cy = 200, 600
    for r in range(190, 10, -8):
        color = "#2E7D32" if (r // 8) % 2 == 0 else "#A5D6A7"
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    # Quadrant 4: dense dots / stipple texture
    d.rectangle([400, 400, 800, 800], fill="#FFF8E1")
    rng = np.random.default_rng(42)
    for _ in range(9000):
        x = int(rng.integers(405, 795))
        y = int(rng.integers(405, 795))
        shade = int(rng.integers(0, 3))
        colors = [(255, 143, 0), (255, 193, 7), (191, 54, 12)]
        r = int(rng.integers(1, 3))
        d.ellipse([x - r, y - r, x + r, y + r], fill=colors[shade])

    # Cross-hatch band across center
    for i in range(-400, 900, 7):
        d.line([(i, 380), (i + 40, 420)], fill="#6A1B9A", width=1)
        d.line([(i, 420), (i + 40, 380)], fill="#AB47BC", width=1)

    # Fine zig-zag
    pts = []
    for i in range(0, 801, 10):
        pts.append((i, 390 + (8 if (i // 10) % 2 == 0 else -8)))
    if len(pts) >= 2:
        d.line(pts, fill="#212121", width=2)

    save(img, "09_patterns_textures_detail.png")


# ---------------------------------------------------------------------------
# 10 Realistic colorful still life (painted look via soft shading)
# ---------------------------------------------------------------------------
def img10() -> None:
    arr = np.zeros((H, W, 3), dtype=np.float32)
    yy, xx = np.mgrid[0:H, 0:W]

    # Table / background
    # Soft vertical backdrop gradient
    t = yy / (H - 1)
    arr[..., 0] = 210 - 40 * t
    arr[..., 1] = 200 - 30 * t
    arr[..., 2] = 185 - 20 * t

    # Table plane (lower third, warmer)
    table = yy > 520
    arr[table, 0] = 150
    arr[table, 1] = 110
    arr[table, 2] = 70
    # Soft perspective shading on table
    shade = np.clip((yy - 520) / 280, 0, 1)
    arr[table] *= (1 - 0.25 * shade[table])[:, None]

    def soft_disk(cx, cy, rx, ry, color, edge=12):
        dist = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        alpha = np.clip(1 - (dist - 1) * (edge / max(rx, ry)), 0, 1)
        alpha = np.where(dist <= 1, 1.0, np.clip(1 - (dist - 1) * edge, 0, 1))
        # Smooth falloff near edge
        alpha = np.clip((1.05 - dist) / 0.15, 0, 1)
        for c in range(3):
            arr[..., c] = arr[..., c] * (1 - alpha) + color[c] * alpha

    def shaded_sphere(cx, cy, r, base, light=(-0.45, -0.55)):
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        mask = dist <= 1.0
        # Fake normals on disk
        nx = (xx - cx) / r
        ny = (yy - cy) / r
        nz = np.sqrt(np.clip(1 - nx**2 - ny**2, 0, 1))
        lx, ly = light
        lz = math.sqrt(max(0.0, 1 - lx * lx - ly * ly))
        ndotl = np.clip(nx * lx + ny * ly + nz * lz, 0, 1)
        # Ambient + diffuse + rim
        intensity = 0.28 + 0.72 * ndotl
        # Specular highlight
        hx, hy, hz = (lx + 0) * 0.5, (ly - 1) * 0.5, (lz + 1) * 0.5
        hn = math.sqrt(hx * hx + hy * hy + hz * hz) or 1
        hx, hy, hz = hx / hn, hy / hn, hz / hn
        spec = np.clip(nx * hx + ny * hy + nz * hz, 0, 1) ** 24
        for c in range(3):
            col = base[c] * intensity + 255 * 0.55 * spec
            arr[..., c] = np.where(mask, col, arr[..., c])
        # Soft contact shadow under sphere
        shadow = np.exp(-(((xx - cx) / (r * 1.1)) ** 2 + ((yy - (cy + r * 0.85)) / (r * 0.28)) ** 2))
        shadow *= (yy > cy) * 0.35
        for c in range(3):
            arr[..., c] *= 1 - shadow

    # Cloth napkin (soft rectangle with folds suggestion)
    cloth = (xx > 120) & (xx < 520) & (yy > 500) & (yy < 720)
    fold = 0.85 + 0.15 * np.sin(xx / 18.0) * np.cos(yy / 25.0)
    arr[cloth, 0] = 230 * fold[cloth]
    arr[cloth, 1] = 235 * fold[cloth]
    arr[cloth, 2] = 245 * fold[cloth]

    # Fruits
    shaded_sphere(280, 430, 95, (210, 45, 40))  # red apple
    shaded_sphere(400, 450, 80, (240, 170, 40))  # orange
    shaded_sphere(500, 470, 55, (250, 220, 60))  # lemon
    shaded_sphere(210, 480, 48, (120, 180, 50))  # lime/green apple

    # Ceramic bowl (ellipse body + rim)
    # Bowl body
    bowl_mask = (((xx - 560) / 130) ** 2 + ((yy - 520) / 70) ** 2) <= 1
    bowl_mask &= yy >= 490
    base_col = np.array([235, 240, 245], dtype=np.float32)
    # shading: darker at bottom
    local = np.clip(1.0 - (yy - 490) / 100.0, 0.55, 1.0)
    for c in range(3):
        arr[..., c] = np.where(bowl_mask, base_col[c] * local * (0.9 + 0.1 * ((xx - 560) / 130)), arr[..., c])
    # Rim
    rim = (np.abs(np.sqrt(((xx - 560) / 130) ** 2 + ((yy - 495) / 28) ** 2) - 1) < 0.08) & (yy < 510)
    arr[rim] = (250, 252, 255)
    # Fruit in bowl
    shaded_sphere(540, 500, 42, (180, 40, 90))
    shaded_sphere(590, 505, 38, (60, 140, 200))

    # Soft vignette
    vignette = 1 - 0.25 * (((xx - W / 2) / (W * 0.7)) ** 2 + ((yy - H / 2) / (H * 0.7)) ** 2)
    arr *= vignette[..., None]

    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    # Mild blur for soft edges / natural look
    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))
    save(img, "10_realistic_still_life.png")


def main() -> None:
    img01()
    img02()
    img03()
    img04()
    img05()
    img06()
    img07()
    img08()
    img09()
    img10()
    print("done")


if __name__ == "__main__":
    main()
