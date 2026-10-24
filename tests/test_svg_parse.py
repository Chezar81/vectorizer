from __future__ import annotations

import pytest

from vectorizer.errors import SvgParseError
from vectorizer.svg.parse import parse_svg_document


def test_parse_paths_and_fills() -> None:
    svg = """<?xml version="1.0"?>
    <svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">
      <path d="M0,0 L10,0 L10,10 Z" fill="#ff0000" fill-opacity="0.5"/>
      <path d="M1,1 L2,1 L2,2 Z" fill="#00ff00"/>
    </svg>
    """
    doc = parse_svg_document(svg, backend_name="test")
    assert doc.path_count == 2
    assert doc.width == 10
    colors = {group.palette_key for group in doc.groups}
    assert "#ff0000" in colors
    red = next(g for g in doc.groups if g.palette_key == "#ff0000")
    assert red.paths[0].fill is not None
    assert red.paths[0].fill.opacity == 0.5


def test_rejects_empty() -> None:
    with pytest.raises(SvgParseError):
        parse_svg_document(" ", backend_name="test")
