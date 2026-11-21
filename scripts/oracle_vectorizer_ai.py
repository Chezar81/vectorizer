#!/usr/bin/env python3
"""Optional quality oracle: compare local traces to Vectorizer.AI test mode.

This does **not** ship as a product dependency. It calls the public HTTP API in
`mode=test` (free, watermarked) when credentials are present, and writes a
side-by-side comparison for fixtures.

Credentials (either pair works):
  VECTORIZER_API_ID / VECTORIZER_API_SECRET
  VECTORIZER_AI_API_ID / VECTORIZER_AI_API_SECRET

Usage:
  python scripts/oracle_vectorizer_ai.py
  python scripts/oracle_vectorizer_ai.py --fixtures tests/fixtures/aa_logo.png
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vectorizer.domain.settings import TraceSettings, WorkflowMode
from vectorizer.jobs.runner import run_trace_sync
from vectorizer.raster.loader import load_image

OUT_DIR = ROOT / "benchmark_results" / "oracle"


def _credentials() -> tuple[str, str] | None:
    api_id = os.environ.get("VECTORIZER_API_ID") or os.environ.get("VECTORIZER_AI_API_ID")
    secret = os.environ.get("VECTORIZER_API_SECRET") or os.environ.get(
        "VECTORIZER_AI_API_SECRET"
    )
    if api_id and secret:
        return api_id, secret
    return None


def _multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"----vectorizer{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode(
                "utf-8"
            )
        )
    for name, (filename, data, content_type) in files.items():
        chunks.append(f"--{boundary}\r\n".encode("ascii"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _vectorizer_ai_svg(image_path: Path, api_id: str, secret: str, timeout: float) -> dict:
    payload, content_type = _multipart(
        {"mode": "test"},
        {
            "image": (
                image_path.name,
                image_path.read_bytes(),
                "application/octet-stream",
            )
        },
    )
    req = request.Request(
        "https://api.vectorizer.ai/api/v1/vectorize",
        data=payload,
        method="POST",
        headers={"Content-Type": content_type},
    )
    token = base64.b64encode(f"{api_id}:{secret}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", f"Basic {token}")
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = response.read()
            headers = {k.lower(): v for k, v in response.headers.items()}
            status = response.status
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Vectorizer.AI HTTP {exc.code}: {detail}") from exc
    elapsed = time.perf_counter() - started
    text = data.decode("utf-8", errors="replace")
    return {
        "ok": status == 200 and "<svg" in text.lower(),
        "seconds": round(elapsed, 4),
        "svg_bytes": len(data),
        "path_count": text.lower().count("<path"),
        "credits_calculated": headers.get("x-credits-calculated"),
        "svg": text if status == 200 else "",
        "status": status,
    }


def _local_trace(image_path: Path) -> dict:
    image = load_image(image_path).image
    settings = TraceSettings(workflow=WorkflowMode.AUTOMATIC).validated()
    started = time.perf_counter()
    result = run_trace_sync(image, settings)
    elapsed = time.perf_counter() - started
    return {
        "ok": True,
        "seconds": round(elapsed, 4),
        "svg_bytes": result.document.byte_size,
        "path_count": result.document.path_count,
        "backend": result.backend_name,
        "svg": result.document.raw_svg,
    }


def _default_fixtures() -> list[Path]:
    fixtures = ROOT / "tests" / "fixtures"
    names = [
        "mono_logo.png",
        "aa_logo.png",
        "nested_holes.png",
        "thin_lines.png",
        "gradient.png",
    ]
    return [fixtures / name for name in names if (fixtures / name).is_file()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        nargs="*",
        type=Path,
        help="Image files to compare (default: a small synthetic fixture set)",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--skip-remote",
        action="store_true",
        help="Only run the local tracer (still writes a local report)",
    )
    args = parser.parse_args(argv)

    creds = None if args.skip_remote else _credentials()
    if not args.skip_remote and creds is None:
        print(
            "No Vectorizer.AI credentials in the environment. "
            "Set VECTORIZER_API_ID and VECTORIZER_API_SECRET, or pass --skip-remote.",
            file=sys.stderr,
        )
        return 2

    paths = list(args.fixtures) if args.fixtures else _default_fixtures()
    if not paths:
        print("No fixtures found.", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in paths:
        path = path.resolve()
        print(f"Local: {path.name}")
        local = _local_trace(path)
        (OUT_DIR / f"{path.stem}.local.svg").write_text(local["svg"], encoding="utf-8")
        remote = None
        if creds is not None:
            print(f"Oracle: {path.name}")
            try:
                remote = _vectorizer_ai_svg(path, creds[0], creds[1], args.timeout)
                if remote.get("svg"):
                    (OUT_DIR / f"{path.stem}.oracle.svg").write_text(
                        remote["svg"], encoding="utf-8"
                    )
            except Exception as exc:  # noqa: BLE001 — report and continue suite
                remote = {"ok": False, "error": str(exc)}
                print(f"  oracle failed: {exc}", file=sys.stderr)
        row = {
            "input": path.name,
            "local": {k: v for k, v in local.items() if k != "svg"},
            "oracle": None
            if remote is None
            else {k: v for k, v in remote.items() if k != "svg"},
        }
        rows.append(row)
        if remote and remote.get("ok"):
            print(
                f"  local {local['seconds']:.3f}s paths={local['path_count']}  "
                f"oracle {remote['seconds']:.3f}s paths={remote['path_count']}"
            )
        else:
            print(f"  local {local['seconds']:.3f}s paths={local['path_count']}")

    payload = {
        "suite": "vectorizer-ai-oracle",
        "mode": "test" if creds else "local-only",
        "results": rows,
    }
    (OUT_DIR / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "| Input | Local s | Local paths | Oracle s | Oracle paths |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        local = row["local"]
        remote = row["oracle"] or {}
        lines.append(
            f"| {row['input']} | {local.get('seconds', '')} | {local.get('path_count', '')} | "
            f"{remote.get('seconds', '')} | {remote.get('path_count', remote.get('error', ''))} |"
        )
    (OUT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_DIR / 'latest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
