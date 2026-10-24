# Project format (`.vproj`)

A Vectorizer project is a ZIP archive (not pickle) with a fixed member set.

## Members

| Path | Required | Content |
| --- | --- | --- |
| `manifest.json` | yes | Schema, settings, asset names |
| `source.png` | yes | Original RGBA source (immutable copy) |
| `segmentation.png` | no | Working segmentation RGBA |
| `result.svg` | no | Current vector SVG |

## Manifest

```json
{
  "schema": 1,
  "format": "vectorizer-project",
  "source_name": "logo.png",
  "source": "source.png",
  "segmentation": "segmentation.png",
  "result": "result.svg",
  "settings": { "...": "TraceSettings.to_json()" },
  "notes": [],
  "dimensions": { "width": 128, "height": 128 }
}
```

## Safety

- Archive members must be basename-only (`source.png`, not `../x`).
- Unknown members are rejected.
- Uncompressed payload is capped (200 MiB).
- Schema mismatches raise a clear error.

## Distinctions

- **Source** is never overwritten by segmentation edits.
- **Segmentation** is what Retrace (F6) feeds to VTracer with preprocess off.
- **Result SVG** is the last successful vector document.
