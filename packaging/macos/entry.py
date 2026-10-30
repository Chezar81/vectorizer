"""PyInstaller entry for the macOS .app bundle.

Kept free of Qt imports so ``--trace-worker`` re-invocations stay headless.
"""

from __future__ import annotations

import sys

from vectorizer.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
