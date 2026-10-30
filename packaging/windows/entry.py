"""PyInstaller entry for the Windows build."""

from __future__ import annotations

from vectorizer.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
