#!/usr/bin/env bash
# Launch Vectorizer on X11. Uses a project-local libxcb-cursor if present
# (avoids needing sudo apt install libxcb-cursor0).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIBDIR="${ROOT}/.local-libs/extracted/usr/lib/x86_64-linux-gnu"
if [[ -d "${LIBDIR}" ]]; then
  export LD_LIBRARY_PATH="${LIBDIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi
export DISPLAY="${DISPLAY:-:0}"
exec "${ROOT}/.venv/bin/vectorizer" "$@"
