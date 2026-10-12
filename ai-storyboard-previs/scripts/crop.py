"""Create an internal crop for viewing; never replace bound evidence frames."""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image


def crop(source, output, box, scale=2):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.exists():
        raise ValueError('output must be a new file, distinct from the source')
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('scale must be finite and positive')
    if len(box) != 4 or any(not isinstance(n, int) for n in box):
        raise ValueError('box must contain four integer pixel coordinates')
    with Image.open(source) as image:
        left, top, right, bottom = box
        if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
            raise ValueError('box must lie within the source image')
        size = (max(1, round((right-left)*scale)), max(1, round((bottom-top)*scale)))
        view = image.crop(box).resize(size, Image.Resampling.LANCZOS)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        view.save(stream, format='PNG')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('--box', nargs=4, type=int, required=True, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'))
    parser.add_argument('--scale', type=float, default=2)
    parser.add_argument('--output', required=True, help='new internal viewing PNG, not an evidence path')
    args = parser.parse_args()
    try:
        print(crop(args.source, args.output, args.box, args.scale))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
