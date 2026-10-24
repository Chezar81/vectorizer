# Vectorizer

Independent, offline raster-to-vector desktop application for Linux Mint.
It imports a bitmap, traces it into editable SVG paths, lets you inspect and
correct segmentation, and exports SVG / PDF / PNG / DXF (plus optional EPS).

**Author:** Christoph Rupprich.

Current milestone: **4** — batch processing, optional EPS, native DXF, user packaging.

## Environment

Developed and tested on:

- Linux Mint 22.3 (Zena), Cinnamon, Ubuntu noble base
- Desktop theme: **Mint-Y-Aqua** (accent `#1f9ede`)
- Python 3.12.3 from the system interpreter
- CPU-only (no GPU required)
- No cloud APIs, accounts, telemetry, or runtime downloads

## Setup (project-local virtualenv)

Do not install into system Python.

```bash
cd "/path/to/Vectorizer"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Or install a user launcher, app icon, and menu/desktop starter (no sudo):

```bash
./scripts/install-user.sh
```

Afterwards open **Vectorizer** from the application menu (or the Desktop shortcut).
The shell command `vectorizer` works when `~/.local/bin` is on your `PATH`.

## Run

```bash
source .venv/bin/activate
vectorizer
```

Or without activating the venv (after `install-user.sh`):

```bash
vectorizer
```

Headless single file:

```bash
python -m vectorizer path/to/logo.png -o path/to/logo.svg
```

Batch (sequential):

```bash
python -m vectorizer --batch path/to/images --outdir path/to/out --formats svg,pdf,dxf
```

### GUI workflow

1. Open an image (or a `.vproj` project). **Automatic** mode classifies content
   (logo, line art, photo, …) and tunes tracing + preprocess for you.
2. Vectorize (F5); edit **Segmentation** and retrace (F6) if needed.
3. Export SVG / PDF / PNG / DXF; EPS if Inkscape is installed.
4. **File → Batch process…** for folders (shared settings, collision policy, summary).

## Optional system tools

| Tool | Purpose |
| --- | --- |
| Inkscape | EPS export only (detected at runtime; UI disables if missing) |

DXF does not need Inkscape. See `docs/DXF_NOTES.md`.

## Tests

```bash
source .venv/bin/activate
QT_QPA_PLATFORM=offscreen python -m pytest
```

## Packaging

See `docs/PACKAGING.md`. AppImage is **not** claimed ready.

## License

Application code: MIT (see `LICENSE`).
Third-party notices: `docs/THIRD_PARTY_LICENSES.md`.
