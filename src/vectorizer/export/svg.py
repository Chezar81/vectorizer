"""SVG export writes backend geometry, not a rasterized preview."""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

from vectorizer.domain.document import VectorDocument
from vectorizer.domain.settings import HierarchyMode, SvgPaintStyle, TraceSettings
from vectorizer.errors import ExportError
from vectorizer.svg.edit import apply_paint_style

_DRAWABLE = {"path", "circle", "rect", "ellipse", "polygon", "polyline"}


def _local(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _ns_tag(name: str, namespace: str | None) -> str:
    if namespace:
        return f"{{{namespace}}}{name}"
    return name


def document_has_transparent_paint(document: VectorDocument) -> bool:
    """True when a fill uses partial alpha. Holes and `fill="none"` do not count.

    EPS, PDF, and DXF drop that alpha. Callers should suggest a PNG preview.
    """
    for group in document.groups:
        for path in group.paths:
            fill = path.fill
            if fill is None:
                continue
            if fill.opacity < 0.999:
                return True
            color = fill.color.strip().lower()
            if color in {"transparent"} or color.startswith("rgba("):
                return True
            if color.startswith("#") and len(color) >= 9 and color[7:9] != "ff":
                return True
    return False


def group_svg_by_fill(svg_text: str) -> str:
    """Wrap same-fill shapes in one `<g>` per color.

    In-memory groups from `svg.parse` are already keyed by fill, but blend and
    VTracer SVG is often a flat list of paths. Group order follows the first
    time each fill appears, and paths keep their relative order inside the
    group. Shapes that sit under a transformed `<g>` are left alone so a
    regroup does not drop that transform.
    """
    if not svg_text or not svg_text.strip():
        return svg_text
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return svg_text
    namespace = None
    if root.tag.startswith("{") and "}" in root.tag:
        namespace = root.tag[1:].split("}", 1)[0]
    parent_of: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in list(parent):
            parent_of[child] = parent

    def _transformed_ancestor(element: ET.Element) -> bool:
        current = parent_of.get(element)
        while current is not None and current is not root:
            if _local(current.tag) == "g" and (current.get("transform") or "").strip():
                return True
            current = parent_of.get(current)
        return False

    drawables: list[ET.Element] = []
    for parent in list(root.iter()):
        for child in list(parent):
            if _local(child.tag) not in _DRAWABLE:
                continue
            if _transformed_ancestor(child):
                return svg_text
            drawables.append(child)
    if not drawables:
        return svg_text
    for element in drawables:
        parent = parent_of.get(element)
        if parent is not None:
            parent.remove(element)
    removed = True
    while removed:
        removed = False
        for parent in list(root.iter()):
            for child in list(parent):
                if _local(child.tag) == "g" and len(child) == 0:
                    parent.remove(child)
                    removed = True
    buckets: dict[str, list[ET.Element]] = {}
    order: list[str] = []
    for element in drawables:
        fill = (element.get("fill") or "").strip()
        key = fill.lower() if fill else "(unfilled)"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(element)
    if namespace:
        ET.register_namespace("", namespace)
    for key in order:
        group = ET.Element(_ns_tag("g", namespace))
        safe = "".join(ch if ch.isalnum() else "-" for ch in key).strip("-") or "none"
        group.set("id", f"fill-{safe[:48]}")
        if key.startswith("#"):
            group.set("fill", key)
        for element in buckets[key]:
            group.append(element)
        root.append(group)
    svg = ET.tostring(root, encoding="unicode")
    if not svg.lstrip().startswith("<?xml"):
        svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg
    return svg


def export_svg(
    document: VectorDocument,
    destination: str | Path,
    *,
    paint_style: SvgPaintStyle | str = SvgPaintStyle.FILL,
    gap_filler_width: float = 2.0,
    gap_filler_non_scaling: bool = True,
    settings: TraceSettings | None = None,
) -> Path:
    path = Path(destination)
    if path.exists() and path.is_dir():
        raise ExportError(f"Refusing to overwrite a directory: {path}")
    style = SvgPaintStyle(paint_style)
    width = gap_filler_width
    non_scaling = gap_filler_non_scaling
    working = document
    if settings is not None:
        style = settings.svg_paint_style
        width = settings.gap_filler_width
        non_scaling = settings.gap_filler_non_scaling
        if HierarchyMode(settings.hierarchical) == HierarchyMode.CUTOUT:
            grouped = group_svg_by_fill(document.raw_svg)
            if grouped != document.raw_svg:
                working = replace(document, raw_svg=grouped)
    svg = apply_paint_style(
        working,
        style,
        gap_filler_width=width,
        gap_filler_non_scaling=non_scaling,
    ).raw_svg
    if not svg.strip():
        raise ExportError("There is no vector document to export.")
    payload = svg.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".vectorizer-", suffix=".svg", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception as exc:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
        raise ExportError(f"Could not write SVG: {exc}") from exc
    return path
