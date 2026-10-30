"""Headless tracing and batch for tests and scripts. Does not start the GUI by default."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vectorizer import __version__
from vectorizer.batch.engine import (
    BatchJob,
    CollisionPolicy,
    ExportFormat,
    collect_inputs,
    run_batch,
)
from vectorizer.domain.settings import (
    AutomaticQuality,
    ColorMode,
    PathFitMode,
    TraceSettings,
)
from vectorizer.export.svg import export_svg
from vectorizer.jobs.runner import TRACE_WORKER_FLAG, run_trace_sync
from vectorizer.presets import load_preset
from vectorizer.raster.analyzer import analyze_image
from vectorizer.raster.loader import load_image


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # Frozen macOS/Windows builds re-invoke the bundled binary as the worker.
    if raw and raw[0] == TRACE_WORKER_FLAG:
        from vectorizer.jobs.trace_worker import main as worker_main

        return worker_main(raw[1:])

    parser = argparse.ArgumentParser(
        prog="vectorizer",
        description="Offline raster-to-vector conversion. GUI is the default; "
        "use --output or --batch for headless work.",
    )
    parser.add_argument("image", nargs="?", help="Input raster path (GUI if no --output/--batch)")
    parser.add_argument("-o", "--output", help="Write SVG here and exit (no GUI)")
    parser.add_argument("--binary", action="store_true", help="Force black-and-white tracing")
    parser.add_argument("--polygon", action="store_true", help="Use polygon fitting instead of splines")
    parser.add_argument(
        "--quality",
        choices=[q.value for q in AutomaticQuality],
        default=AutomaticQuality.BALANCED.value,
        help="Automatic analyzer quality when no --preset/--settings-json is given",
    )
    parser.add_argument("--batch", metavar="DIR", help="Batch-convert images from DIR (or use --inputs)")
    parser.add_argument("--inputs", nargs="+", help="Explicit input files for batch mode")
    parser.add_argument("--outdir", help="Batch output directory (required with --batch/--inputs)")
    parser.add_argument(
        "--formats",
        default="svg",
        help="Comma list: svg,pdf,png,dxf,eps (default: svg)",
    )
    parser.add_argument(
        "--collision",
        choices=[p.value for p in CollisionPolicy],
        default=CollisionPolicy.RENAME.value,
    )
    parser.add_argument("--preset", help="Named preset for settings")
    parser.add_argument("--settings-json", help="Path to TraceSettings JSON")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(raw)

    if args.version:
        print(__version__)
        return 0

    if args.batch or args.inputs:
        return _run_batch_cli(args)

    if args.output:
        if not args.image:
            parser.error("an input image is required with --output")
        loaded = load_image(args.image)
        settings = _settings_from_args(args, loaded)
        result = run_trace_sync(loaded.image, settings)
        dest = export_svg(result.document, Path(args.output))
        print(
            f"Wrote {dest} ({result.document.path_count} paths, "
            f"{result.elapsed_seconds:.2f}s, {result.document.byte_size} bytes)"
        )
        return 0

    from vectorizer.gui.app import run_app

    initial = Path(args.image) if args.image else None
    return run_app(initial_image=initial)


def _settings_from_args(args: argparse.Namespace, loaded=None) -> TraceSettings:
    if args.settings_json:
        data = json.loads(Path(args.settings_json).read_text(encoding="utf-8"))
        settings = TraceSettings.from_mapping(data)
    elif args.preset:
        settings = load_preset(args.preset)
    elif loaded is not None:
        quality = AutomaticQuality(getattr(args, "quality", AutomaticQuality.BALANCED.value))
        settings = analyze_image(loaded.image, quality=quality).suggested
    else:
        settings = TraceSettings().validated()
    payload = settings.to_json()
    if args.binary:
        payload["colormode"] = ColorMode.BINARY.value
    if args.polygon:
        payload["mode"] = PathFitMode.POLYGON.value
    return TraceSettings.from_mapping(payload)


def _run_batch_cli(args: argparse.Namespace) -> int:
    if not args.outdir:
        raise SystemExit("--outdir is required for batch mode")
    paths: list[Path] = []
    if args.batch:
        paths.extend(collect_inputs(Path(args.batch)))
    if args.inputs:
        paths.extend(collect_inputs([Path(p) for p in args.inputs]))
    if not paths:
        print("No input images found.")
        return 2
    formats = tuple(ExportFormat(part.strip().lower()) for part in args.formats.split(",") if part.strip())
    settings = _settings_from_args(args)
    job = BatchJob(
        inputs=tuple(paths),
        output_dir=Path(args.outdir),
        settings=settings,
        formats=formats,
        collision=CollisionPolicy(args.collision),
        continue_on_error=not args.stop_on_error,
    )
    summary = run_batch(job)
    print(
        f"Batch done: ok={summary.ok_count} failed={summary.fail_count} "
        f"skipped={summary.skip_count}"
    )
    print(f"Summary: {job.output_dir / 'batch_summary.json'}")
    return 0 if summary.fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
