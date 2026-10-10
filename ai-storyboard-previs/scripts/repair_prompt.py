"""Source-bound visual generation views; never rewrite the frozen script."""
from decimal import Decimal, InvalidOperation
import hashlib
import re

VERSION = 4
SILENT_DIRECTIVE = ('只生成无声画面。人物不说话，不做说话口型；'
    '不得生成任何人声、对白、旁白、OS/VO、音乐或音效；'
    '不得出现字幕、对白文字、台词文字或其他新增屏幕文字。'
    '剧情仅由下列可见动作、表情、位置与道具关系表达。')
# These are a text gate, not a proof of model compliance or story fidelity.
SPEECH = re.compile(
    r'\{[^{}]*\}|(?<![A-Za-z])(?:OS|VO)(?![A-Za-z])|'
    r'\b(?:speech|dialogue|dialog|voiceover|voice-over|speaking|talking|narration|singing)\b|'
    r'对白|台词|旁白|独白|配音|字幕|屏幕文字|人声|音乐|音效|声音|声响|雨声|'
    r'开口|说话|讲话|说完|说着|说道|说出|问道|询问|解释|低语|耳语|呢喃|'
    r'低声|语速|语气|声线|呼喊|尖叫|唱歌|演唱|喊(?:道|出|话)|'
    r'(?:说|问|喊|叫|唱)\s*[:：{“‘\"「]', re.I)
NEGATIVE = re.compile(
    r'(?:没有|不要|不得|禁止|不输出|不出现|不添加|不生成|无)'
    r'(?:任何|出现|输出|生成|添加)?'
    r'(?:对白|台词|旁白|独白|配音|字幕|屏幕文字|人声|音乐|音效|声音|声响)'
    r'(?:(?:、|和|或|及)(?:对白|台词|旁白|独白|配音|字幕|屏幕文字|人声|音乐|音效|声音|声响))*')
TAGS = ('【时长】', '【生成时长】', '【镜头设计】', '【镜头内容】')
HEADER = re.compile(
    r'\A\s*镜头\s*(?P<number>\d+)\s*[,，：:]?\s*'
    r'【时长】\s*\d+(?:\.\d+)?\s*(?:秒|[sS])\s*[,，。;；]?\s*'
    r'【镜头设计】(?P<design>.*?)\s*【镜头内容】(?P<body>.*)\Z', re.S)


def finish(errors):
    if errors:
        raise ValueError('Repair prompt validation failed:\n' + '\n'.join(errors))


def speech_signals(text):
    """Ignore explicit prohibitions, never delete whole clauses or alter actions."""
    return list(dict.fromkeys(m.group() for m in SPEECH.finditer(NEGATIVE.sub('', text))))


class VisualOnly:
    """Collect all fields needing an agent-supplied, source-bound visual adaptation."""
    def __init__(self, adaptations):
        self.source = adaptations
        self.used, self.errors = {}, []
        if not isinstance(adaptations, dict):
            self.source = {}
            self.errors.append('repair_visual_adaptations must be an object')

    def text(self, path, source):
        signals = speech_signals(source)
        row = self.source.get(path)
        if not signals:
            if row is not None:
                self.errors.append(f'{path}: visual-only source must remain unchanged')
            return source
        if not isinstance(row, dict):
            self.errors.append(f'{path}: visual adaptation required for {signals}; preserve existing actions/plot, do not simply delete dialogue')
            return source
        if row.get('source_sha256') != hashlib.sha256(source.encode('utf-8')).hexdigest():
            self.errors.append(f'{path}: stale visual adaptation source_sha256')
        text = row.get('visual_text')
        if not isinstance(text, str) or not text.strip():
            self.errors.append(f'{path}: nonempty visual_text required; unresolved dialogue-only plot must stop before submission')
            text = source
        elif speech_signals(text) or any(tag in text for tag in TAGS):
            self.errors.append(f'{path}: visual_text still contains speech/audio/text or shot headers')
        if row.get('preserves_story') is not True or not isinstance(row.get('story_basis'), str) or not row['story_basis'].strip():
            self.errors.append(f'{path}: preserves_story=true and original-script story_basis required; no invented visual actions')
        self.used[path] = dict(row)
        return text

    def finish(self):
        finish(self.errors)


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
    if request.get('prompt_version') in (3, VERSION):
        if not prompt.startswith(SILENT_DIRECTIVE + '\n') or not prompt.endswith(SILENT_DIRECTIVE):
            errors.append('missing fixed visual-only directive at prompt beginning/end')
        signals = speech_signals(prompt.replace(SILENT_DIRECTIVE, ''))
        if signals:
            errors.append(f'speech/audio/text leaked into generation prompt: {signals}')
    finish(errors)
