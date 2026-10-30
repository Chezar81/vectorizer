"""Subprocess entry point for CPU-heavy tracing. No GUI imports."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from vectorizer.domain.settings import TraceSettings
from vectorizer.errors import VectorizerError
from vectorizer.raster.loader import load_image
from vectorizer.vectorize.dispatch import trace_prepared


def run_trace(input_path: Path, output_svg: Path, settings_path: Path, result_path: Path) -> int:
    try:
        settings = TraceSettings.from_mapping(json.loads(settings_path.read_text(encoding="utf-8")))
        loaded = load_image(input_path)
        result = trace_prepared(loaded.image, settings)
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
    args = parser.parse_args(argv)
    return run_trace(Path(args.input), Path(args.output_svg), Path(args.settings), Path(args.result))


if __name__ == "__main__":
    sys.exit(main())
