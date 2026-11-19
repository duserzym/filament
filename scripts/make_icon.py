"""Generate a neutral placeholder glyph; no final name or branding decision.

Uses Pillow already in the development venv. Does not install packages.
"""
from pathlib import Path

from PIL import Image, ImageDraw

from rawtims import branding

ROOT = Path(__file__).resolve().parents[1]


def main():
    image = Image.new('RGBA', (1024, 1024))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((32, 32, 992, 992), radius=210, fill='#526170')
    # A simple measurement pulse on a neutral slate tile.
    draw.line([(232, 610), (382, 610), (468, 356), (556, 672), (634, 498), (792, 498)],
              fill='#f3f5f7', width=56, joint='curve')
    for point in ((232, 610), (792, 498)):
        x, y = point
        draw.ellipse((x-28, y-28, x+28, y+28), fill='#f3f5f7')
    icon = ROOT / 'packaging' / branding.ICON_FILENAME
    image.save(icon, format='ICNS')
    asset = ROOT / 'src/rawtims_gui/assets' / branding.GUI_ICON_FILENAME
    asset.parent.mkdir(parents=True, exist_ok=True)
    image.resize((256, 256), Image.Resampling.LANCZOS).save(asset, optimize=True)
    print(icon)


if __name__ == '__main__':
    main()
