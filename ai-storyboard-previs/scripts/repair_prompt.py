"""Deterministic generation view; never rewrite the original script or infer plot."""
from decimal import Decimal, InvalidOperation
import re

VERSION = 2
TAGS = ('【时长】', '【生成时长】', '【镜头设计】', '【镜头内容】')
HEADER = re.compile(
    r'\A\s*镜头\s*(?P<number>\d+)\s*[,，：:]?\s*'
    r'【时长】\s*\d+(?:\.\d+)?\s*(?:秒|[sS])\s*[,，。;；]?\s*'
    r'【镜头设计】(?P<design>.*?)\s*【镜头内容】(?P<body>.*)\Z', re.S)


def finish(errors):
    if errors:
        raise ValueError('Repair prompt validation failed:\n' + '\n'.join(errors))


def generation_view(shot, original, source_number):
    """Only remove an explicit, complete header; ambiguous text requires input repair."""
    raw = original['text']
    design, body = original['design'], raw
    match = HEADER.fullmatch(raw)
    if match:
        if int(match['number']) != source_number:
            raise ValueError('original header number disagrees with script order')
        extracted = match['design'].strip().rstrip('。')
        if not extracted:
            raise ValueError('empty original shot design')
        explicit = shot.get('shot_design')
        if explicit and explicit.strip().rstrip('。') != extracted:
            raise ValueError('shot_design conflicts with original header; resolve without rewriting baseline')
        design, body = extracted, match['body'].strip()
    elif raw.lstrip().startswith('【镜头内容】'):
        body = raw.lstrip()[len('【镜头内容】'):].strip()
    if not body.strip():
        raise ValueError('empty shot content')
    if any(tag in body or tag in design for tag in TAGS) or re.match(r'\s*镜头\s*\d+\s*[,，：:]', body):
        raise ValueError('ambiguous or duplicate shot header; supply an unambiguous original excerpt')
    return dict(generation_text=body, design=design)


def input_views(shots, original, resolved, source_numbers):
    views, errors = {}, []
    for shot in shots:
        sid = shot['id']
        try:
            views[sid] = generation_view(shot, original[sid], source_numbers[sid])
        except ValueError as exc:
            errors.append(f'{sid}: {exc}')
        req = resolved.get(sid) or {}
        if req and not req.get('ready'):
            errors.append(f'{sid}: Resolve provisional shot requirements before repair')
        if req.get('must_have') or req.get('must_not_have'):
            frame = req.get('keyframe') or {}
            if frame.get('phase') not in ('entry', 'action', 'exit') or not frame.get('description', '').strip():
                errors.append(f'{sid}: explicit keyframe phase and description required')
    finish(errors)
    return views


def validate(request, shot_ids):
    """Collect independent prompt errors before the immutable request/submit gate."""
    errors = []
    blocks, prompt = request.get('blocks', []), request.get('prompt', '')
    if [b.get('shot_id') for b in blocks] != shot_ids:
        errors.append('shot count/order differs from original group')
    headers = re.findall(r'^镜头(\d+),【生成时长】([^\n。]+)。', prompt, re.M)
    if [n for n, _ in headers] != [str(i) for i in range(1, len(shot_ids) + 1)]:
        errors.append('rendered shot count/order differs from original group')
    for tag in ('【生成时长】', '【镜头设计】', '【镜头内容】'):
        if prompt.count(tag) != len(shot_ids):
            errors.append(f'duplicate or missing {tag}')
    if '【时长】' in prompt:
        errors.append('original duration header leaked into generation prompt')
    if any(value != '1.0s' for _, value in headers):
        errors.append('conflicting generation duration')
    total = Decimal(0)
    for block in blocks:
        sid = block.get('shot_id', '?')
        body = block.get('generation_text', '')
        if not isinstance(body, str) or not body.strip():
            errors.append(f'{sid}: empty shot content')
        elif body not in prompt:
            errors.append(f'{sid}: shot content missing from prompt')
        if block.get('must_have') or block.get('must_not_have'):
            frame = block.get('keyframe_target') or {}
            if frame.get('phase') not in ('entry', 'action', 'exit') or not frame.get('description', '').strip():
                errors.append(f'{sid}: missing keyframe phase/description')
        try:
            duration = Decimal(str(block.get('duration')))
            if not duration.is_finite() or duration != Decimal('1'):
                raise ValueError()
            total += duration
        except (InvalidOperation, ValueError):
            errors.append(f'{sid}: invalid generation duration (expected 1.0s)')
    try:
        if total != Decimal(str(request.get('duration_seconds'))):
            errors.append('generation duration sum differs from request')
    except InvalidOperation:
        errors.append('invalid request duration')
    finish(errors)
