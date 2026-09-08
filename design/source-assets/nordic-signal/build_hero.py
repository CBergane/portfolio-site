"""Encode the approved master without cropping/upscaling (offline authoring only).

Requires Pillow and pillow-avif-plugin in the author's tool environment, not in
the website's runtime requirements. Run this file from any working directory.
"""
from pathlib import Path

import pillow_avif  # noqa: F401 -- registers the AVIF encoder with Pillow
from PIL import Image


def main():
    source = Path(__file__).with_name('home-hero-master.png')
    destination = source.parents[3] / 'app/static/images/nordic-signal'
    destination.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as master:
        master = master.convert('RGB')
        widths = sorted({min(width, master.width) for width in (960, 1600, 2400)})
        for width in widths:
            height = round(master.height * width / master.width)
            frame = master.resize((width, height), Image.Resampling.LANCZOS)
            for extension, options in (
                ('avif', {'quality': 65, 'speed': 6, 'subsampling': '4:4:4'}),
                ('webp', {'quality': 86, 'method': 6}),
            ):
                path = destination / f'home-hero-{width}.{extension}'
                frame.save(path, **options)
                print(f'{path.name}: {width} x {height}; {path.stat().st_size:,} bytes')


if __name__ == '__main__':
    main()
