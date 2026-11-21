"""Raster import. The original bitmap is never mutated after load."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from vectorizer.errors import ImageLoadError, ImageOversizeError

SUPPORTED_FORMATS = ("PNG", "JPEG", "BMP", "GIF", "TIFF", "WEBP")
OPEN_EXTENSIONS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".jpe": "JPEG",
    ".jfif": "JPEG",
    ".bmp": "BMP",
    ".gif": "GIF",
    ".tif": "TIFF",
    ".tiff": "TIFF",
    ".webp": "WEBP",
}

DEFAULT_MAX_PIXELS = 25_000_000
DEFAULT_MAX_BYTES = 80_000_000


@dataclass(frozen=True)
class LoadedImage:
    image: Image.Image
    source_path: Path | None
    source_format: str
    notes: tuple[str, ...]
    file_size: int | None
    original_mode: str
    frame_index: int
    # Pixel size before any working-copy shrink. Equal to image.size when
    # the file already fit.
    original_width: int = 0
    original_height: int = 0


def recommend_max_side(
    width: int,
    height: int,
    *,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> int:
    """Longest side of a working copy that stays within `max_pixels`.

    Returns 0 when the image already fits. This is a suggestion for a
    shrunk working copy; the source file is not modified.
    """
    width = int(width)
    height = int(height)
    limit = int(max_pixels)
    if width <= 0 or height <= 0 or limit <= 0:
        return 0
    if width * height <= limit:
        return 0
    scale = math.sqrt(limit / float(width * height))
    new_w = max(1, math.floor(width * scale))
    new_h = max(1, math.floor(height * scale))
    while new_w * new_h > limit and (new_w > 1 or new_h > 1):
        if new_w >= new_h and new_w > 1:
            new_w -= 1
        elif new_h > 1:
            new_h -= 1
        else:
            break
    return max(new_w, new_h)


def shrink_to_max_side(
    image: Image.Image,
    max_side: int,
    *,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> Image.Image:
    """Return a copy whose long side is at most `max_side` and pixel count fits.

    The input image is not mutated. A `max_side` that would still exceed
    `max_pixels` is clamped to `recommend_max_side`.
    """
    width, height = image.size
    longest = max(width, height)
    side = int(max_side)
    if side <= 0 or longest <= side:
        recommended = recommend_max_side(width, height, max_pixels=max_pixels)
        if recommended <= 0:
            return image
        side = recommended
    recommended = recommend_max_side(width, height, max_pixels=max_pixels)
    if recommended and side > recommended:
        side = recommended
    if side >= longest:
        return image
    scale = side / float(longest)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    limit = int(max_pixels)
    while new_w * new_h > limit and max(new_w, new_h) > 1:
        if new_w >= new_h and new_w > 1:
            new_w -= 1
        elif new_h > 1:
            new_h -= 1
        else:
            break
    if (new_w, new_h) == (width, height):
        return image
    return image.resize((new_w, new_h), Image.Resampling.LANCZOS)


def _target_long_side(
    width: int,
    height: int,
    *,
    max_pixels: int,
    max_side: int,
    shrink: bool,
) -> int:
    """Longest side to resize to, or 0 to keep the original pixels.

    Raises ImageOversizeError when the pixel cap is exceeded and the caller
    did not ask to shrink.
    """
    recommended = recommend_max_side(width, height, max_pixels=max_pixels)
    longest = max(int(width), int(height))
    target = 0
    if int(max_side) > 0 and longest > int(max_side):
        target = int(max_side)
    if recommended and (target == 0 or target > recommended):
        if shrink or int(max_side) > 0:
            target = recommended if target == 0 else min(target, recommended)
        else:
            pixels = int(width) * int(height)
            raise ImageOversizeError(
                f"Image is {width}×{height} ({pixels} pixels), which exceeds the "
                f"{max_pixels} pixel safety limit. Recommended max side is "
                f"{recommended}. Pass --max-side {recommended} to shrink the "
                "working copy (the original file is not modified).",
                width=int(width),
                height=int(height),
                recommended_max_side=recommended,
            )
    if target <= 0 or target >= longest:
        return 0
    return target


def _check_file_size(path: Path, max_bytes: int) -> int:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ImageLoadError(f"Could not read file size: {exc}") from exc
    if size <= 0:
        raise ImageLoadError("The file is empty.")
    if size > max_bytes:
        raise ImageLoadError(
            f"File is {size} bytes, which exceeds the {max_bytes} byte safety limit."
        )
    return size


def _finalize(
    image: Image.Image,
    *,
    source_path: Path | None,
    source_format: str | None,
    notes: list[str],
    file_size: int | None,
    original_mode: str,
    frame_index: int,
    max_pixels: int,
    max_side: int = 0,
    shrink: bool = False,
) -> LoadedImage:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ImageLoadError("Image has invalid dimensions.")
    original_width, original_height = width, height
    target = _target_long_side(
        width,
        height,
        max_pixels=max_pixels,
        max_side=max_side,
        shrink=shrink,
    )
    if target:
        image = shrink_to_max_side(image, target, max_pixels=max_pixels)
        notes.append(
            f"Shrunk working copy from {original_width}×{original_height} to "
            f"{image.size[0]}×{image.size[1]} (original dimensions kept in metadata)."
        )
        width, height = image.size
    pixels = width * height
    if pixels > max_pixels:
        raise ImageLoadError(
            f"Image is {width}×{height} ({pixels} pixels), which exceeds the "
            f"{max_pixels} pixel safety limit."
        )
    rgba = image.convert("RGBA")
    fmt = (source_format or "PNG").upper()
    if fmt not in SUPPORTED_FORMATS:
        notes.append(f"Loaded as {fmt}; treating as a generic raster.")
    return LoadedImage(
        image=rgba,
        source_path=source_path,
        source_format=fmt,
        notes=tuple(notes),
        file_size=file_size,
        original_mode=original_mode,
        frame_index=frame_index,
        original_width=original_width,
        original_height=original_height,
    )


def _open_pil(source: Path | io.BytesIO, notes: list[str]) -> tuple[Image.Image, int]:
    try:
        image = Image.open(source)
        image.load()
    except UnidentifiedImageError as exc:
        raise ImageLoadError("The file is not a supported image, or it is corrupt.") from exc
    except OSError as exc:
        raise ImageLoadError(f"Could not decode the image: {exc}") from exc

    frame_index = 0
    n_frames = int(getattr(image, "n_frames", 1) or 1)
    image_format = (image.format or "").upper()
    if n_frames > 1 or image_format == "GIF":
        try:
            image.seek(0)
            image.load()
        except EOFError as exc:
            raise ImageLoadError("Could not read the first frame of the animated image.") from exc
        if n_frames > 1:
            notes.append(
                f"Animated image has {n_frames} frames; only the first frame is used."
            )
        else:
            notes.append("GIF loaded using the first frame only.")
        frame_index = 0

    original_mode = image.mode
    try:
        oriented = ImageOps.exif_transpose(image)
        if oriented is not None and oriented is not image:
            notes.append("Applied EXIF orientation.")
            image = oriented
    except Exception:
        notes.append("EXIF orientation could not be applied; using stored pixels.")

    return image, frame_index


def load_image(
    path: str | Path,
    *,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_side: int = 0,
    shrink: bool = False,
) -> LoadedImage:
    file_path = Path(path)
    if not file_path.is_file():
        raise ImageLoadError(f"File not found: {file_path}")
    file_size = _check_file_size(file_path, max_bytes)
    notes: list[str] = []
    image, frame_index = _open_pil(file_path, notes)
    original_mode = image.mode
    fmt = (image.format or OPEN_EXTENSIONS.get(file_path.suffix.lower()) or "PNG")
    return _finalize(
        image,
        source_path=file_path,
        source_format=fmt,
        notes=notes,
        file_size=file_size,
        original_mode=original_mode,
        frame_index=frame_index,
        max_pixels=max_pixels,
        max_side=max_side,
        shrink=shrink,
    )


def load_image_from_bytes(
    data: bytes,
    *,
    source_path: Path | None = None,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_side: int = 0,
    shrink: bool = False,
) -> LoadedImage:
    if not data:
        raise ImageLoadError("No image data was provided.")
    if len(data) > max_bytes:
        raise ImageLoadError(
            f"Image data is {len(data)} bytes, which exceeds the {max_bytes} byte safety limit."
        )
    notes: list[str] = []
    buffer = io.BytesIO(data)
    image, frame_index = _open_pil(buffer, notes)
    original_mode = image.mode
    fmt = image.format or "PNG"
    return _finalize(
        image,
        source_path=source_path,
        source_format=fmt,
        notes=notes,
        file_size=len(data),
        original_mode=original_mode,
        frame_index=frame_index,
        max_pixels=max_pixels,
        max_side=max_side,
        shrink=shrink,
    )
