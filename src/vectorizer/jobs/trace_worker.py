"""Subprocess entry point for CPU-heavy tracing. No GUI imports."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from PIL import Image

from vectorizer.domain.settings import TraceSettings
from vectorizer.errors import VectorizerError
from vectorizer.jobs.progress import make_emitter
from vectorizer.raster.loader import load_image
from vectorizer.vectorize.dispatch import trace_prepared


def run_trace(
    input_path: Path,
    output_svg: Path,
    settings_path: Path,
    result_path: Path,
    *,
    soft_path: Path | None = None,
    meta_path: Path | None = None,
) -> int:
    try:
        settings = TraceSettings.from_mapping(json.loads(settings_path.read_text(encoding="utf-8")))
        loaded = load_image(input_path)
        soft_source = None
        if soft_path is not None and soft_path.is_file():
            soft_source = Image.open(soft_path)
            soft_source.load()
            soft_source = soft_source.convert("RGBA")
        content_kind = None
        if meta_path is not None and meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
            raw_kind = meta.get("content_kind") if isinstance(meta, dict) else None
            if isinstance(raw_kind, str) and raw_kind.strip():
                content_kind = raw_kind.strip()
        result = trace_prepared(
            loaded.image,
            settings,
            soft_source=soft_source,
            content_kind=content_kind,
            on_progress=make_emitter(True),
        )
        output_svg.write_text(result.document.raw_svg, encoding="utf-8")
        payload = {
            "ok": True,
            "elapsed_seconds": result.elapsed_seconds,
            "path_count": result.document.path_count,
            "byte_size": result.document.byte_size,
            "width": result.document.width,
            "height": result.document.height,
            "backend": result.backend_name,
            "warnings": list(result.warnings),
            "svg_path": str(output_svg),
        }
        result_path.write_text(json.dumps(payload), encoding="utf-8")
        return 0
    except VectorizerError as exc:
        result_path.write_text(json.dumps({"ok": False, "error": str(exc)}), encoding="utf-8")
        return 2
    except Exception as exc:
        result_path.write_text(
            json.dumps({"ok": False, "error": f"Unexpected tracer error: {exc}"}),
            encoding="utf-8",
        )
        traceback.print_exc(file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vectorizer tracing worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-svg", required=True)
    parser.add_argument("--settings", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--soft-source", default=None)
    parser.add_argument("--meta", default=None)
    args = parser.parse_args(argv)
    soft = Path(args.soft_source) if args.soft_source else None
    meta = Path(args.meta) if args.meta else None
    return run_trace(
        Path(args.input),
        Path(args.output_svg),
        Path(args.settings),
        Path(args.result),
        soft_path=soft,
        meta_path=meta,
    )


if __name__ == "__main__":
    sys.exit(main())
