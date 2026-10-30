# DXF export notes

Vectorizer writes ASCII DXF from SVG `<path>` data. Lines mode uses AC1009
`LWPOLYLINE` entities. Spline mode uses AC1015 `SPLINE` entities for cubic
Bézier spans and `LINE` for straight spans.

| Topic | Behavior |
| --- | --- |
| Units | 1 DXF unit = 1 SVG pixel. `$INSUNITS` is 0 (unitless). |
| Y axis | Flipped so positive Y points up (SVG origin is top-left). |
| Lines mode | Cubic and quadratic Béziers and SVG elliptical arcs are sampled (default 8 segments) into `LWPOLYLINE`. |
| Spline mode | Cubic spans become degree-3 `SPLINE` (four controls, clamped knots). Straight spans become `LINE`. Arcs are still sampled into `LINE` segments. |
| Fills | Not exported. Only outlines. |
| Holes | Not compound regions; stacked SVG fills become separate outlines. |
| Transforms | `translate(x[,y])` applied; other transforms ignored. |
| Precision | Default 3 decimal places. |

For filled CAD artwork, prefer SVG/PDF and convert with a CAD-aware tool if
needed. Do not treat DXF output as a lossless Illustrator substitute.
