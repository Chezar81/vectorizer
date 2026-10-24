# Third-party licenses

This file is a notice, not legal advice. Read each project’s license text
before redistribution.

| Component | Use | License | Source |
| --- | --- | --- | --- |
| VTracer 0.6.15 | Raster-to-vector engine (Python wheels) | MIT | https://pypi.org/project/vtracer/0.6.15/ |
| Pillow | Raster I/O and preprocessing | HPND-style (Pillow) | https://pypi.org/project/Pillow/ |
| PySide6 / Qt for Python | Desktop GUI, SVG renderer | LGPL-3.0 **or** GPL-2.0 **or** GPL-3.0 | https://doc.qt.io/qtforpython-6/ |
| Qt (bundled with PySide wheels) | Widgets, SVG | LGPL-3.0 | The Qt Company |
| pytest | Tests only | MIT | https://pypi.org/project/pytest/ |
| Inkscape (optional) | EPS conversion only | GPL-2.0-or-later (Inkscape) | https://inkscape.org/ — not bundled; invoked if present |

## Application license

Vectorizer application code is MIT. See `LICENSE`.

## Qt / PySide6 redistribution

Shipping a binary that links PySide6 typically requires complying with LGPL-3.0
(dynamic linking via the official wheels is the intended path) **or** a Qt
commercial license. Do not statically link Qt without reviewing obligations.

## VTracer

VTracer is developed by the visioncortex project. Vectorizer wraps the public
Python API; it does not vendor VTracer sources.
