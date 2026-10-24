# Benchmarks

Pixel-wise comparison between a raster and a rasterized SVG is **one** signal.
It does not prove clean corners, correct topology, or editable paths.

## Run

```bash
source .venv/bin/activate
python scripts/benchmark.py
```

The script traces the synthetic fixtures with documented settings and writes
`benchmark_results/latest.json` plus a markdown table.

## Recorded fields

- input name and settings
- wall time
- path count
- SVG byte size
- optional raster reconstruction RMSE if Qt SVG rendering is available

## Comparison to Vector Magic

There is **no** Vector Magic comparison dataset in this repository and no
parity claim.
