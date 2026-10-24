# Packaging

## Ready now (user-local)

### Virtualenv + editable install

```bash
cd "/path/to/Vectorizer"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
vectorizer
```

### One-shot user launcher + icon + menu starter

```bash
./scripts/install-user.sh
```

This writes:

- `~/.local/bin/vectorizer` → project `.venv` (also sets `LD_LIBRARY_PATH` for bundled libs)
- `~/.local/share/applications/vectorizer.desktop` (Cinnamon / Mint menu)
- `~/.local/share/icons/hicolor/*/apps/vectorizer.png` (+ scalable SVG)
- `~/Desktop/vectorizer.desktop` when a Desktop folder exists

No administrator privileges. Ensure `~/.local/bin` is on your `PATH` for the
shell command; the menu entry uses an absolute path and does not need that.

### Wheel

```bash
./scripts/build-wheel.sh
# or: python -m build --wheel
```

Install the resulting `dist/vectorizer-*.whl` into a venv with `pip install`.

## Optional system dependency

| Tool | Used for | Required? |
| --- | --- | --- |
| Inkscape | EPS export | Optional. Detected at runtime; EPS UI disabled if missing. |

DXF export is native and does **not** require Inkscape.

## AppImage / Flatpak

**Not claimed ready.** Do not publish an AppImage until an actual artifact is built
**and launched** on Linux Mint, then re-tested for open → trace → SVG/PDF export.

Checklist before claiming AppImage readiness:

1. Bundle Python 3.12+, PySide6-Essentials, Pillow, VTracer.
2. Launch on Mint 22.x Cinnamon (`xcb`; may need `libxcb-cursor0`).
3. Verify tracing, SVG preview, PDF, batch, and project round-trip.
4. Document bundled third-party licenses.

## What not to do

- Do not `sudo pip install`.
- Do not rename SVG/PDF to `.ai`.
- Do not ship without `docs/THIRD_PARTY_LICENSES.md`.
