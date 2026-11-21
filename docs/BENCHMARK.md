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

## Optional Vectorizer.AI oracle

`scripts/oracle_vectorizer_ai.py` can call Vectorizer.AI **test mode** (free,
watermarked) and write local vs remote SVG + a markdown table under
`benchmark_results/oracle/`. It is a quality reference only — the desktop app
stays offline and does not use the API.

```bash
export VECTORIZER_API_ID=...
export VECTORIZER_API_SECRET=...
python scripts/oracle_vectorizer_ai.py
# or local-only scaffolding:
python scripts/oracle_vectorizer_ai.py --skip-remote
```
