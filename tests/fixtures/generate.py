"""Create original synthetic rasters used by tests and benchmarks."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def generate_fixtures(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    mono = Image.new("RGB", (128, 128), "white")
    draw = ImageDraw.Draw(mono)
    draw.polygon([(20, 100), (64, 16), (108, 100)], fill="black")
    draw.rectangle((52, 72, 76, 100), fill="white")
    paths["mono_logo.png"] = _save(directory, "mono_logo.png", mono)

    aa = Image.new("RGBA", (160, 160), (255, 255, 255, 255))
    draw = ImageDraw.Draw(aa)
    draw.rounded_rectangle((18, 18, 142, 142), radius=28, fill=(32, 96, 180, 255))
    draw.ellipse((48, 48, 112, 112), fill=(240, 196, 48, 255))
    aa = aa.filter(ImageFilter.SMOOTH)
    paths["aa_logo.png"] = _save(directory, "aa_logo.png", aa)

    transparent = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(transparent)
    draw.ellipse((8, 8, 88, 88), fill=(200, 40, 40, 255))
    draw.ellipse((28, 28, 68, 68), fill=(0, 0, 0, 0))
    paths["transparent.png"] = _save(directory, "transparent.png", transparent)

    lines = Image.new("RGB", (160, 80), "white")
    draw = ImageDraw.Draw(lines)
    draw.line((8, 12, 152, 12), fill="black", width=1)
    draw.line((8, 40, 152, 68), fill="black", width=2)
    draw.line((80, 8, 80, 72), fill=(20, 20, 20), width=1)
    paths["thin_lines.png"] = _save(directory, "thin_lines.png", lines)

    nested = Image.new("RGB", (120, 120), "white")
    draw = ImageDraw.Draw(nested)
    draw.ellipse((10, 10, 110, 110), fill="black")
    draw.ellipse((35, 35, 85, 85), fill="white")
    draw.ellipse((50, 50, 70, 70), fill="black")
    paths["nested_holes.png"] = _save(directory, "nested_holes.png", nested)

    disconnected = Image.new("RGB", (140, 80), "white")
    draw = ImageDraw.Draw(disconnected)
    draw.rectangle((10, 20, 50, 60), fill=(16, 120, 64))
    draw.ellipse((90, 18, 130, 62), fill=(16, 120, 64))
    paths["disconnected.png"] = _save(directory, "disconnected.png", disconnected)

    noisy = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(noisy)
    draw.rectangle((15, 15, 65, 65), fill=(30, 30, 30))
    for x, y in ((4, 4), (12, 70), (74, 8), (60, 74), (3, 40)):
        draw.point((x, y), fill=(30, 30, 30))
        noisy.putpixel((x, y), (30, 30, 30))
    paths["noisy.png"] = _save(directory, "noisy.png", noisy)

    gradient = Image.new("RGB", (100, 40), "white")
    for x in range(100):
        value = int(255 * x / 99)
        for y in range(40):
            gradient.putpixel((x, y), (value, 40, 255 - value))
    paths["gradient.png"] = _save(directory, "gradient.png", gradient)

    photo = Image.new("RGB", (96, 64), "white")
    for y in range(64):
        for x in range(96):
            r = int(80 + 70 * (x / 95) + 20 * (y / 63))
            g = int(40 + 90 * (y / 63))
            b = int(30 + 100 * ((x + y) % 32) / 31)
            photo.putpixel((x, y), (min(r, 255), min(g, 255), min(b, 255)))
    photo = photo.filter(ImageFilter.GaussianBlur(radius=1.2))
    paths["photo_like.png"] = _save(directory, "photo_like.png", photo)

    jpeg = Image.new("RGB", (64, 48), (240, 240, 240))
    ImageDraw.Draw(jpeg).rectangle((10, 10, 54, 38), fill=(12, 12, 140))
    jpeg_path = directory / "simple.jpg"
    jpeg.save(jpeg_path, format="JPEG", quality=90)
    paths["simple.jpg"] = jpeg_path

    def _indexed_square(color_index: int) -> Image.Image:
        gif = Image.new("P", (32, 32))
        gif.putpalette([255, 255, 255, 0, 0, 0, 200, 0, 0] + [0] * (253 * 3))
        pixels = [0] * (32 * 32)
        for y in range(8, 24):
            for x in range(8, 24):
                pixels[y * 32 + x] = color_index
        gif.putdata(pixels)
        return gif

    frame_a = _indexed_square(1)
    frame_b = _indexed_square(2)
    gif_path = directory / "first_frame.gif"
    frame_a.save(
        gif_path,
        format="GIF",
        save_all=True,
        append_images=[frame_b],
        duration=100,
        loop=0,
    )
    paths["first_frame.gif"] = gif_path

    return paths


def _save(directory: Path, name: str, image: Image.Image) -> Path:
    path = directory / name
    fmt = "PNG" if path.suffix.lower() == ".png" else None
    image.save(path, format=fmt)
    return path


if __name__ == "__main__":
    generate_fixtures(Path(__file__).resolve().parent)
