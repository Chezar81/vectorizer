"""Qt helpers that stay out of image-processing modules."""

from __future__ import annotations

from io import BytesIO

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QPixmap


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    rgba = image if image.mode == "RGBA" else image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    # copy() so the QImage owns its buffer after `data` is freed.
    qimage = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888).copy()
    return QPixmap.fromImage(qimage)


def qimage_to_png_bytes(image: QImage) -> bytes:
    if image.isNull():
        return b""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def png_bytes_to_qbytearray(data: bytes) -> QByteArray:
    return QByteArray(data)


def qimage_to_pil(image: QImage) -> Image.Image:
    png = qimage_to_png_bytes(image)
    if not png:
        raise ValueError("Clipboard image is empty.")
    return Image.open(BytesIO(png)).convert("RGBA")
