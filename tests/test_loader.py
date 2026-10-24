from __future__ import annotations

from pathlib import Path

import pytest

from vectorizer.errors import ImageLoadError
from vectorizer.raster.loader import load_image, load_image_from_bytes


def test_load_png_and_jpeg(fixtures: dict[str, Path]) -> None:
    png = load_image(fixtures["mono_logo.png"])
    assert png.image.mode == "RGBA"
    assert png.image.size == (128, 128)
    assert png.source_format in {"PNG"}
    jpeg = load_image(fixtures["simple.jpg"])
    assert jpeg.source_format == "JPEG"
    assert jpeg.image.mode == "RGBA"


def test_gif_uses_first_frame(fixtures: dict[str, Path]) -> None:
    loaded = load_image(fixtures["first_frame.gif"])
    assert loaded.frame_index == 0
    assert any("first frame" in note.lower() for note in loaded.notes)
    # First frame is the black square, not the later red frame.
    corner = loaded.image.getpixel((16, 16))
    assert corner[0] < 40 and corner[1] < 40 and corner[2] < 40


def test_transparency_preserved(fixtures: dict[str, Path]) -> None:
    loaded = load_image(fixtures["transparent.png"])
    extrema = loaded.image.getchannel("A").getextrema()
    assert extrema is not None and extrema[0] == 0


def test_corrupt_file(tmp_path: Path) -> None:
    bogus = tmp_path / "broken.png"
    bogus.write_bytes(b"this is not an image")
    with pytest.raises(ImageLoadError):
        load_image(bogus)


def test_oversize_rejected(fixtures: dict[str, Path]) -> None:
    with pytest.raises(ImageLoadError):
        load_image(fixtures["mono_logo.png"], max_pixels=10)


def test_unicode_and_spaces(tmp_path: Path, fixtures: dict[str, Path]) -> None:
    dest = tmp_path / "logo 测试 & file.png"
    dest.write_bytes(fixtures["mono_logo.png"].read_bytes())
    loaded = load_image(dest)
    assert loaded.image.size == (128, 128)


def test_load_from_bytes(fixtures: dict[str, Path]) -> None:
    data = fixtures["aa_logo.png"].read_bytes()
    loaded = load_image_from_bytes(data)
    assert loaded.file_size == len(data)
    assert loaded.image.size[0] > 0
