#!/usr/bin/env bash
# Build a wheel into dist/. Does not claim AppImage readiness.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip build
.venv/bin/python -m build --wheel
echo "Wheel(s) in dist/"
ls -la dist/
