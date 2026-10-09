"""Resolve a one-request repair aspect from the current source video's display shape."""
from fractions import Fraction

from media import probe
from previs import current_video, group, require, sha

POLICY = 1
# Exact ResolutionSelector values supported by workflow_bridge.ps1.
SUPPORTED = {'16:9': Fraction(16, 9), '9:16': Fraction(9, 16)}


def display_shape(info):
    stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'
                   and not s.get('disposition', {}).get('attached_pic')), None)
    require(stream is not None, 'Input video stream required for repair aspect')
    width, height = stream.get('width'), stream.get('height')
    require(type(width) is int and type(height) is int and width > 0 and height > 0,
            'Input video dimensions unavailable; probe before paid submission')
    raw_sar = stream.get('sample_aspect_ratio')
    try:
        sar = Fraction(str(raw_sar).replace(':', '/')) if raw_sar not in (None, '', 'N/A', '0:1') else Fraction(1)
        require(sar > 0, 'Invalid input pixel aspect ratio')
        rotation = next((s['rotation'] for s in stream.get('side_data_list', []) if 'rotation' in s),
                        stream.get('tags', {}).get('rotate', 0))
        rotation = Fraction(str(rotation)) % 360
    except (ValueError, ZeroDivisionError, TypeError):
        raise ValueError('Invalid input display metadata; probe before paid submission') from None
    require(rotation in (0, 90, 180, 270), 'Unsupported input rotation; do not guess repair aspect')
    ratio = Fraction(width, height) * sar
    if rotation in (90, 270):
        ratio = 1 / ratio
    aspect = min(SUPPORTED, key=lambda key: abs(ratio / SUPPORTED[key] - 1))
    # Resolution alignment can produce e.g. 1376x768 for nominal 16:9.
    require(abs(ratio / SUPPORTED[aspect] - 1) <= Fraction(1, 100),
            'Input aspect ratio unsupported by fixed workflow; do not crop or change the input')
    return dict(width=width, height=height, sample_aspect_ratio=f'{sar.numerator}:{sar.denominator}',
                rotation=int(rotation), aspect_ratio=aspect)


def source_aspect(p, project, gid, expected_sha256):
    task, path = current_video(p, project, group(p, gid))
    require(task and task['output_hashes'][0] == expected_sha256,
            'Current source video required for repair aspect')
    shape = display_shape(probe(path))
    require(sha(path) == expected_sha256, 'Input video changed while probing repair aspect')
    return dict(policy=POLICY, video_sha256=expected_sha256, **shape)
