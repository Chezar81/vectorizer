"""SVG edits that do not refit curves: palette snap, shape delete, paint style."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace

from vectorizer.domain.document import VectorDocument
from vectorizer.domain.settings import SvgPaintStyle, normalize_hex
from vectorizer.errors import SvgParseError
from vectorizer.export.dxf import sample_path_points
from vectorizer.raster.color import hex_to_rgb, nearest_oklab, rgb_to_hex, srgb_u8_to_oklab
from vectorizer.svg.parse import parse_svg_document

import numpy as np


def snap_fills_to_palette(document: VectorDocument, palette: tuple[str, ...]) -> VectorDocument:
    """Force every path fill onto the nearest constrained palette color."""
    if not palette or document.path_count == 0:
        return document
    targets = tuple(normalize_hex(color) for color in palette)
    mapping: dict[str, str] = {}
    palette_lab = srgb_u8_to_oklab(_rgb_array(targets))
    for group in document.groups:
        key = group.palette_key
        if not key or not key.startswith("#"):
            continue
        try:
            source = normalize_hex(key)
        except ValueError:
            continue
        source_lab = srgb_u8_to_oklab(_rgb_array((source,)))
        index, _dist = nearest_oklab(source_lab.reshape(1, 1, 3), palette_lab)
        nearest = targets[int(index[0, 0])]
        if nearest != source:
            mapping[key] = nearest
            mapping[source] = nearest
    if not mapping:
        return document
    from vectorizer.svg.recolor import recolor_document

    return recolor_document(document, mapping)


def delete_shape_at(document: VectorDocument, x: float, y: float) -> VectorDocument | None:
    """Remove the topmost filled path that contains the image point. None if none hit."""
    hit = _hit_path_index(document, x, y)
    if hit is None:
        return None
    return _drop_path_indices(document, {hit})


def remove_background_shapes(
    document: VectorDocument,
    background: tuple[int, int, int],
    *,
    tolerance: int = 28,
) -> VectorDocument:
    """Drop paths whose fill is close to `background`. Fills and holes stay omitted from DXF later."""
    doomed: set[int] = set()
    order = 0
    bg = srgb_u8_to_oklab(_rgb_array((rgb_to_hex(background),)))[0]
    limit = (max(0, tolerance) / 255.0) ** 2 * 0.35
    for group in document.groups:
        for path in group.paths:
            color = path.fill.color if path.fill else ""
            if color.startswith("#"):
                try:
                    lab = srgb_u8_to_oklab(_rgb_array((normalize_hex(color),)))[0]
                except ValueError:
                    lab = None
                if lab is not None:
                    delta = lab - bg
                    if float(delta @ delta) <= max(limit, 0.003):
                        doomed.add(order)
            order += 1
    if not doomed:
        return document
    return _drop_path_indices(document, doomed)


def apply_paint_style(document: VectorDocument, style: SvgPaintStyle) -> VectorDocument:
    """Return a document whose SVG uses fill only, or fill plus a same-color hairline stroke."""
    if style != SvgPaintStyle.STROKE_FILL:
        return document
    try:
        root = ET.fromstring(document.raw_svg)
    except ET.ParseError as exc:
        raise SvgParseError(f"Cannot restyle SVG: {exc}") from exc
    changed = False
    for element in root.iter():
        if _local(element.tag) != "path":
            continue
        fill = element.get("fill")
        if not fill or fill.lower() == "none":
            continue
        element.set("stroke", fill)
        element.set("stroke-width", "1")
        element.set("stroke-linejoin", "round")
        changed = True
    if not changed:
        return document
    return replace(document, raw_svg=_serialize(root))


def _hit_path_index(document: VectorDocument, x: float, y: float) -> int | None:
    best: int | None = None
    for group in document.groups:
        for path in group.paths:
            if path.fill is None:
                continue
            points = sample_path_points(path.d, curve_segments=6)
            if _contains(points, x, y):
                best = path.source_order
    return best


def _contains(points: list[tuple[float, float]], x: float, y: float) -> bool:
    if len(points) < 3:
        return False
    inside = False
    x0, y0 = points[-1]
    for x1, y1 in points:
        if ((y1 > y) != (y0 > y)) and (x < (x0 - x1) * (y - y1) / ((y0 - y1) or 1e-12) + x1):
            inside = not inside
        x0, y0 = x1, y1
    return inside


def _drop_path_indices(document: VectorDocument, indices: set[int]) -> VectorDocument:
    try:
        root = ET.fromstring(document.raw_svg)
    except ET.ParseError as exc:
        raise SvgParseError(f"Cannot edit SVG: {exc}") from exc
    seen = 0
    for parent in root.iter():
        for child in list(parent):
            if _local(child.tag) != "path":
                continue
            d = (child.get("d") or "").strip()
            if not d:
                continue
            if seen in indices:
                parent.remove(child)
            seen += 1
    return parse_svg_document(_serialize(root), backend_name=document.backend_name)


def _serialize(root: ET.Element) -> str:
    svg_text = ET.tostring(root, encoding="unicode")
    if not svg_text.lstrip().startswith("<?xml"):
        svg_text = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg_text
    return svg_text


def _local(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _rgb_array(colors: tuple[str, ...]) -> np.ndarray:
    return np.asarray([hex_to_rgb(color) for color in colors], dtype=np.uint8)
