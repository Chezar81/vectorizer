"""Parse backend SVG into the canonical document using XML, not regex."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict

from vectorizer.domain.document import FillStyle, VectorDocument, VectorGroup, VectorPath
from vectorizer.errors import SvgParseError

SVG_NS = "http://www.w3.org/2000/svg"


def _local(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_length(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    for suffix in ("px", "pt", "mm", "cm", "in"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    try:
        return float(text)
    except ValueError as exc:
        raise SvgParseError(f"Invalid SVG length: {value!r}") from exc


def _parse_view_box(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    parts = value.replace(",", " ").split()
    if len(parts) != 4:
        raise SvgParseError(f"Invalid viewBox: {value!r}")
    try:
        nums = tuple(float(p) for p in parts)
    except ValueError as exc:
        raise SvgParseError(f"Invalid viewBox: {value!r}") from exc
    return nums[0], nums[1], nums[2], nums[3]


def _parse_opacity(value: str | None) -> float:
    if value is None or value == "":
        return 1.0
    try:
        opacity = float(value)
    except ValueError as exc:
        raise SvgParseError(f"Invalid opacity: {value!r}") from exc
    return max(0.0, min(1.0, opacity))


def _fill_from_attrib(attrib: dict[str, str]) -> FillStyle | None:
    fill = attrib.get("fill")
    if fill is None or fill.lower() == "none":
        return None
    opacity = _parse_opacity(attrib.get("fill-opacity", attrib.get("opacity")))
    return FillStyle(color=fill, opacity=opacity)


def parse_svg_document(svg_text: str, *, backend_name: str) -> VectorDocument:
    if not svg_text or not svg_text.strip():
        raise SvgParseError("Backend returned empty SVG.")
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise SvgParseError(f"Backend SVG is not well-formed XML: {exc}") from exc

    if _local(root.tag) != "svg":
        raise SvgParseError(f"Expected an <svg> root, got <{_local(root.tag)}>.")

    view_box = _parse_view_box(root.get("viewBox"))
    width = _parse_length(root.get("width"))
    height = _parse_length(root.get("height"))
    if width is None and view_box is not None:
        width = view_box[2]
    if height is None and view_box is not None:
        height = view_box[3]
    if width is None or height is None:
        raise SvgParseError("SVG is missing width/height and viewBox.")

    grouped: dict[str, list[VectorPath]] = defaultdict(list)
    order = 0
    for element in root.iter():
        if _local(element.tag) != "path":
            continue
        d = (element.get("d") or "").strip()
        if not d:
            continue
        fill = _fill_from_attrib(element.attrib)
        path = VectorPath(
            d=d,
            fill=fill,
            fill_rule=element.get("fill-rule"),
            transform=element.get("transform"),
            source_order=order,
        )
        key = fill.color if fill else "(unfilled)"
        grouped[key].append(path)
        order += 1

    groups = tuple(
        VectorGroup(name=f"fill:{key}", palette_key=None if key == "(unfilled)" else key, paths=tuple(paths))
        for key, paths in grouped.items()
    )
    notes = ()
    if order == 0:
        notes = ("SVG parsed but contained no <path> elements.",)

    return VectorDocument(
        width=width,
        height=height,
        view_box=view_box,
        groups=groups,
        raw_svg=svg_text,
        backend_name=backend_name,
        path_count=order,
        source_notes=notes,
    )
