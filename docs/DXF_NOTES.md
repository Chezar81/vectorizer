# DXF export notes

Vectorizer writes ASCII DXF (AC1009-style) with `LWPOLYLINE` entities derived
from SVG `<path>` data.

| Topic | Behavior |
| --- | --- |
| Units | 1 DXF unit = 1 SVG pixel. `$INSUNITS` is 0 (unitless). |
| Y axis | Flipped so positive Y points up (SVG origin is top-left). |
| Curves | Cubic/quadratic Beziers and SVG elliptical arcs sampled (default 8 segments). |
| Fills | Not exported. Only outlines / polylines. |
| Holes | Not compound regions; stacked SVG fills become separate polylines. |
| Transforms | `translate(x[,y])` applied; other transforms ignored. |
| Precision | Default 3 decimal places. |

For filled CAD artwork, prefer SVG/PDF and convert with a CAD-aware tool if
needed. Do not treat DXF output as a lossless Illustrator substitute.
