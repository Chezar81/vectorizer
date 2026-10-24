"""Recolor fill attributes in SVG XML. Geometry is preserved."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from vectorizer.domain.document import VectorDocument
from vectorizer.errors import SvgParseError
from vectorizer.svg.parse import parse_svg_document


def _local(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def recolor_document(document: VectorDocument, mapping: dict[str, str]) -> VectorDocument:
    """Replace fill colors using an exact string map (e.g. #ff0000 -> #00aa00)."""
    if not mapping:
        return document
    normalized = {k.lower(): v for k, v in mapping.items()}
    try:
        root = ET.fromstring(document.raw_svg)
    except ET.ParseError as exc:
        raise SvgParseError(f"Cannot recolor: SVG is not well-formed ({exc})") from exc
    changed = False
    for element in root.iter():
        if _local(element.tag) != "path":
            continue
        fill = element.get("fill")
        if fill is None:
            continue
        replacement = normalized.get(fill.lower())
        if replacement is not None and replacement != fill:
            element.set("fill", replacement)
            changed = True
    if not changed:
        return document
    svg_text = ET.tostring(root, encoding="unicode")
    if not svg_text.lstrip().startswith("<?xml"):
        svg_text = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg_text
    return parse_svg_document(svg_text, backend_name=document.backend_name)
