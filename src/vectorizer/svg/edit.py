"""SVG edits that do not refit curves: palette snap, shape delete, paint style."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace

from vectorizer.domain.document import VectorDocument
from vectorizer.domain.settings import SvgPaintStyle, normalize_hex
from vectorizer.errors import SvgParseError
from vectorizer.raster.color import hex_to_rgb, nearest_oklab, rgb_to_hex, srgb_u8_to_oklab
from vectorizer.svg.edges import edge_to_path_d, find_shared_edges
from vectorizer.svg.parse import parse_svg_document

import numpy as np


def snap_fills_to_palette(
    document: VectorDocument,
    palette: tuple[str, ...],
    *,
    tolerance: int = 255,
    remaps: tuple[tuple[str, str], ...] = (),
) -> VectorDocument:
    """Snap path fills onto the palette, then apply optional remaps.

    `tolerance` is max sRGB channel-ish distance (0–255). At 255 every fill
    snaps to the nearest palette color (legacy behaviour). Lower values leave
    unmatched fills unchanged. Remap targets of `#00000000` drop those fills.
    """
    if document.path_count == 0:
        return document
    mapping: dict[str, str] = {}
    if palette:
        targets = tuple(normalize_hex(color) for color in palette)
        palette_lab = srgb_u8_to_oklab(_rgb_array(targets))
        # Approximate OKLab distance threshold from 0–255 sRGB tolerance.
        # Full snap (255) disables the gate. Empirically ~ (t/255)^2 * 0.45.
        limit = None if int(tolerance) >= 255 else (max(0, int(tolerance)) / 255.0) ** 2 * 0.45
        for group in document.groups:
            key = group.palette_key
            if not key or not key.startswith("#"):
                continue
            try:
                source = normalize_hex(key)
            except ValueError:
                continue
            source_lab = srgb_u8_to_oklab(_rgb_array((source,)))
            index, dist = nearest_oklab(source_lab.reshape(1, 1, 3), palette_lab)
            if limit is not None and float(dist[0, 0]) > limit:
                continue
            nearest = targets[int(index[0, 0])]
            if nearest != source:
                mapping[key] = nearest
                mapping[source] = nearest
    for source, target in remaps:
        try:
            src = normalize_hex(source)
        except ValueError:
            continue
        mapping[src] = target
        mapping[source] = target
    if not mapping:
        return document
    # Drop fills remapped to transparent by deleting those shapes.
    drop_colors = {src for src, dst in mapping.items() if dst == "#00000000"}
    working = document
    if drop_colors:
        doomed: set[int] = set()
        for group in working.groups:
            for path in group.paths:
                color = path.fill.color if path.fill else ""
                try:
                    hex_color = normalize_hex(color) if color.startswith("#") else ""
                except ValueError:
                    hex_color = ""
                if hex_color in drop_colors or color in drop_colors:
                    doomed.add(path.source_order)
        if doomed:
            working = _drop_path_indices(working, doomed)
        mapping = {k: v for k, v in mapping.items() if v != "#00000000"}
    if not mapping:
        return working
    from vectorizer.svg.recolor import recolor_document

    return recolor_document(working, mapping)


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


# Medium cluster radius, squared OKLab. palette.py treats ~0.012 as below a
# visible step; blend tracing treats ~0.06 (squared 0.0036) as one ramp.
# 0.03 sits between them: near-duplicate fills merge, distinct inks stay apart.
MEDIUM_CLUSTER_DIST2 = 0.03 * 0.03


def cluster_similar_fills(
    document: VectorDocument,
    *,
    max_dist2: float = MEDIUM_CLUSTER_DIST2,
) -> VectorDocument:
    """Merge near-duplicate fills onto the more common color.

    Intended for unlimited / empty-palette traces. A locked palette should
    not call this; the palette is already the color source of truth. The
    default radius is the medium OKLab step above. Returns the same document
    when nothing is close enough to merge.
    """
    counts: dict[str, int] = {}
    for group in document.groups:
        key = group.palette_key
        if not key or not key.startswith("#"):
            continue
        try:
            hex_color = normalize_hex(key)
        except ValueError:
            continue
        counts[hex_color] = counts.get(hex_color, 0) + len(group.paths)
    if len(counts) < 2:
        return document
    ordered = sorted(counts, key=lambda color: (-counts[color], color))
    labs = {color: srgb_u8_to_oklab(_rgb_array((color,)))[0] for color in ordered}
    mapping: dict[str, str] = {}
    kept: list[str] = []
    limit = float(max_dist2)
    for color in ordered:
        lab = labs[color]
        best: str | None = None
        best_dist: float | None = None
        for keeper in kept:
            delta = lab - labs[keeper]
            dist2 = float(delta @ delta)
            if best_dist is None or dist2 < best_dist:
                best = keeper
                best_dist = dist2
        if best is not None and best_dist is not None and best_dist <= limit and best != color:
            mapping[color] = best
        else:
            kept.append(color)
    if not mapping:
        return document
    from vectorizer.svg.recolor import recolor_document

    return recolor_document(document, mapping)


def apply_paint_style(
    document: VectorDocument,
    style: SvgPaintStyle,
    *,
    gap_filler_width: float = 2.0,
    gap_filler_non_scaling: bool = True,
) -> VectorDocument:
    """Apply SVG paint style: fill, same-color stroke, gap filler, or edge strokes."""
    style = SvgPaintStyle(style)
    if style == SvgPaintStyle.FILL:
        return document
    if style == SvgPaintStyle.STROKE_FILL:
        return _apply_stroke_fill(document)
    if style == SvgPaintStyle.GAP_FILLER:
        return _apply_gap_filler(
            document,
            width=gap_filler_width,
            non_scaling=gap_filler_non_scaling,
        )
    if style == SvgPaintStyle.STROKE_EDGES:
        return _apply_stroke_edges(
            document,
            width=gap_filler_width,
            non_scaling=gap_filler_non_scaling,
        )
    return document


def _apply_stroke_fill(document: VectorDocument) -> VectorDocument:
    try:
        root = ET.fromstring(document.raw_svg)
    except ET.ParseError as exc:
        raise SvgParseError(f"Cannot restyle SVG: {exc}") from exc
    changed = False
    for element in root.iter():
        if _local(element.tag) not in {"path", "circle", "rect", "ellipse", "polygon"}:
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


def _apply_gap_filler(
    document: VectorDocument,
    *,
    width: float,
    non_scaling: bool,
) -> VectorDocument:
    """Insert average-color understrokes along shared edges, keep fills on top."""
    edges = find_shared_edges(document)
    if not edges:
        return document
    try:
        root = ET.fromstring(document.raw_svg)
    except ET.ParseError as exc:
        raise SvgParseError(f"Cannot restyle SVG: {exc}") from exc
    ns = _svg_namespace(root)
    group = ET.Element(_tag("g", ns))
    group.set("id", "gap-filler")
    stroke_width = f"{max(0.0, min(5.0, float(width))):.3g}"
    for edge in edges:
        d = edge_to_path_d(edge.points)
        if not d:
            continue
        path = ET.Element(_tag("path", ns))
        path.set("d", d)
        path.set("fill", "none")
        path.set("stroke", edge.average_color)
        path.set("stroke-width", stroke_width)
        path.set("stroke-linecap", "round")
        path.set("stroke-linejoin", "round")
        if non_scaling:
            path.set("vector-effect", "non-scaling-stroke")
        group.append(path)
    if len(group) == 0:
        return document
    # Understrokes must paint before filled shapes.
    root.insert(0, group)
    return replace(document, raw_svg=_serialize(root))


def _apply_stroke_edges(
    document: VectorDocument,
    *,
    width: float,
    non_scaling: bool,
) -> VectorDocument:
    """Replace fills with one stroke per shared edge (cutting / engraving)."""
    edges = find_shared_edges(document)
    try:
        root = ET.fromstring(document.raw_svg)
    except ET.ParseError as exc:
        raise SvgParseError(f"Cannot restyle SVG: {exc}") from exc
    # Drop filled geometry; keep only edge strokes.
    for child in list(root):
        root.remove(child)
    ns = _svg_namespace(root)
    group = ET.Element(_tag("g", ns))
    group.set("id", "stroke-edges")
    stroke_width = f"{max(0.0, min(5.0, float(width))):.3g}"
    if edges:
        for edge in edges:
            d = edge_to_path_d(edge.points)
            if not d:
                continue
            path = ET.Element(_tag("path", ns))
            path.set("d", d)
            path.set("fill", "none")
            path.set("stroke", edge.average_color)
            path.set("stroke-width", stroke_width)
            path.set("stroke-linecap", "round")
            path.set("stroke-linejoin", "round")
            if non_scaling:
                path.set("vector-effect", "non-scaling-stroke")
            group.append(path)
    else:
        # Fallback: stroke every filled outline once when adjacency finds nothing.
        from vectorizer.svg.edges import iter_filled_paths

        for _order, path, color in iter_filled_paths(document):
            element = ET.Element(_tag("path", ns))
            element.set("d", path.d)
            element.set("fill", "none")
            element.set("stroke", color)
            element.set("stroke-width", stroke_width)
            if non_scaling:
                element.set("vector-effect", "non-scaling-stroke")
            group.append(element)
    if len(group) == 0:
        return document
    root.append(group)
    # Re-parse so groups/path_count match the new geometry.
    return parse_svg_document(_serialize(root), backend_name=document.backend_name)


def _svg_namespace(root: ET.Element) -> str | None:
    if root.tag.startswith("{") and "}" in root.tag:
        return root.tag[1:].split("}", 1)[0]
    return None


def _tag(name: str, namespace: str | None) -> str:
    if namespace:
        return f"{{{namespace}}}{name}"
    return name


def _hit_path_index(document: VectorDocument, x: float, y: float) -> int | None:
    # Lazy import: export.__init__ pulls export.svg → edit; a top-level dxf import cycles.
    from vectorizer.export.dxf import sample_path_subpaths

    # Groups are keyed by fill color, not paint order — pick the highest
    # source_order among hits so the visually topmost path is deleted.
    best: int | None = None
    for group in document.groups:
        for path in group.paths:
            if path.fill is None:
                continue
            rings = [ring for ring, _closed in sample_path_subpaths(path.d, curve_segments=6)]
            if not _contains_evenodd(rings, x, y):
                continue
            if best is None or path.source_order > best:
                best = path.source_order
    return best


def _contains_evenodd(rings: list[list[tuple[float, float]]], x: float, y: float) -> bool:
    """Even-odd fill: each closed subpath toggles inside, so holes stay hollow."""
    inside = False
    for points in rings:
        if _ring_contains(points, x, y):
            inside = not inside
    return inside


def _ring_contains(points: list[tuple[float, float]], x: float, y: float) -> bool:
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
