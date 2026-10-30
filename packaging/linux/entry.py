"""PyInstaller entry for the Linux onedir / .deb package."""

from __future__ import annotations

from vectorizer.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
