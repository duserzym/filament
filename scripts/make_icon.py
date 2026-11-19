"""Verify the curated ribbon assets and export the Windows icon.

Artwork and small-size strategy credited to IDTIMS_UPbRPy/tools/make_app_icon.py.
The copied SVG, PNGs and Apple ICNS are the source of truth; do not re-render.
See docs/icon-provenance.json for source commit, original paths and SHA-256.
Uses existing Pillow only; no application bundle is built.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from rawtims import branding

ROOT = Path(__file__).resolve().parents[1]
ICO_SIZES = (16, 32, 48, 64, 128, 256)


def main():
    provenance = json.loads((ROOT / "docs/icon-provenance.json").read_text())
    for relative, record in provenance["files"].items():
        path = ROOT / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Curated icon changed: {path}")
    assets = ROOT / "src/rawtims_gui/assets"
    images = {
        size: Image.open(assets / name).convert("RGBA")
        for size, name in branding.GUI_ICON_FILENAMES.items()
        if size <= 256
    }
    # Only 48 px needs resampling; preserve the curated 16/32 px artwork.
    images[48] = images[64].resize((48, 48), Image.Resampling.LANCZOS)
    target = ROOT / "packaging" / branding.ICO_FILENAME
    images[256].save(
        target,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=[images[s] for s in ICO_SIZES if s != 256],
    )
    print(target)


if __name__ == "__main__":
    main()
