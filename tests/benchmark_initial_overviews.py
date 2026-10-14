"""Measure fresh CLI processes to first sheets; excludes agent reading and thinking."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repeats', type=int, default=3)
    args = ap.parse_args()
    if args.repeats < 1:
        ap.error('--repeats must be positive')
    parent = ROOT / 'test-tools'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='first-look-', dir=parent) as directory:
        root = Path(directory).resolve()
        assert root.is_relative_to(parent.resolve())
        paths = []
        for index in range(1, 15):
            path = root / f'{index}.png'
            Image.effect_noise((1920, 1080), 60).convert('RGB').save(path)
            paths.append(str(path))
        script = root / 'script.txt'
        script.write_text('\n'.join(f'镜头{i}，【时长】1s。【镜头设计】中景。'
                                    f'【镜头内容】男孩站在门边，第{i}镜。' for i in range(1, 15)),
                          encoding='utf-8')
        mapping = root / 'images.json'
        mapping.write_text(json.dumps(paths), encoding='utf-8')
        times = []
        for index in range(args.repeats):
            start = perf_counter()
            result = subprocess.run([sys.executable, '-X', 'utf8',
                                     str(ROOT / 'ai-storyboard-previs/scripts/prepare_storyboards.py'),
                                     'overview', str(script), '--images', str(mapping), '--output', str(root / f'run-{index}')],
                                    capture_output=True, text=True, encoding='utf-8', check=True)
            times.append(perf_counter() - start)
            data = json.loads(result.stdout)
            assert data['status'] == 'unreviewed' and len(data['pages']) == 2
            assert len(data['pages'][0]['shot_ids']) == 9 and len(data['pages'][1]['shot_ids']) == 5
        print(json.dumps(dict(scope='fresh CLI process to all first-look sheets; no agent timing',
                              images=14, dimensions=[1920, 1080], pages=2,
                              input_megabytes=round(sum(Path(p).stat().st_size for p in paths) / 1e6, 2),
                              seconds=times, median_seconds=statistics.median(times)), indent=2))


if __name__ == '__main__':
    main()
