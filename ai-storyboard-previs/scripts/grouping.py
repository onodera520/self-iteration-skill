"""Narrative-first imported-video partitioning. No media or paid operations."""
from decimal import Decimal

POLICY_VERSION = 2
MAX_SECONDS = Decimal('15')
SHORT_SECONDS = Decimal('8')
MAX_SHOTS = 12


def validate_metadata(p):
    from previs import require, number
    def source(value):
        return (isinstance(value, dict) and value.get('kind') in ('script', 'inference')
                and isinstance(value.get('ref'), str) and bool(value['ref'].strip()))
    for s in p['shots']:
        if 'duration_source' in s:
            require(source(s['duration_source']), 'duration_source needs script/inference and ref')
            require(number(s.get('duration')) and s['duration'] > 0, 'duration_source requires positive duration')
    data = p.get('narrative_plan')
    if data is None:
        return
    require(isinstance(data, dict) and source(data.get('source')), 'narrative_plan source required')
    ids = [s['id'] for s in p['shots']]
    edges = data.get('boundaries')
    require(isinstance(edges, list) and all(isinstance(e, dict) for e in edges)
            and [e.get('before_shot_id') for e in edges] == ids[1:],
            'narrative boundaries must cover all adjacent shots in order')
    for edge in edges:
        require(type(edge.get('merge_allowed')) is bool and type(edge.get('strength')) is int
                and 0 <= edge['strength'] <= 3 and isinstance(edge.get('reason'), str) and edge['reason'].strip(),
                'boundary needs merge_allowed, strength 0..3 and reason')
    spans = data.get('safe_spans')
    require(isinstance(spans, list), 'whole-interval complexity safe_spans required')
    for span in spans:
        require(isinstance(span, dict), 'safe span must be an object')
        seq = span.get('shot_ids')
        require(isinstance(seq, list) and seq and seq[0] in ids, 'invalid safe span')
        i = ids.index(seq[0])
        require(ids[i:i+len(seq)] == seq and isinstance(span.get('reason'), str) and span['reason'].strip(),
                'safe span must be contiguous and explain whole-interval complexity')


def partition(p, blocked_starts=()):
    """Semantic annotations come from one batch judgment; all arithmetic is exact.

    A safe span certifies its whole interval and contained subintervals only.
    Overlapping spans never imply that their union is safe.
    """
    validate_metadata(p)
    ss = p['shots']
    missing = [s['id'] for s in ss if s.get('duration') is None or not s.get('duration_source')]
    problems = []
    if missing:
        problems.append('补齐脚本计划时长及来源；未给时长须提出并标注建议值：' + '、'.join(missing))
    if not p.get('narrative_plan') or any('event' not in s for s in ss):
        problems.append('补齐自然事件、相邻承接及整段生成复杂度依据。')
    too_long = [s['id'] for s in ss if s.get('duration') is not None and Decimal(str(s['duration'])) > MAX_SECONDS]
    if too_long:
        problems.append('单镜超过15秒，需拆分或调整计划时长：' + '、'.join(too_long))
    if problems:
        return dict(feasible=False, ranges=[], reasons=[], trace=[], limitations=problems)
    ids = [s['id'] for s in ss]
    edges = p['narrative_plan']['boundaries']
    spans = [(ids.index(r['shot_ids'][0]), ids.index(r['shot_ids'][-1])+1) for r in p['narrative_plan']['safe_spans']]
    durations = [Decimal(str(s['duration'])) for s in ss]
    blocked = set(blocked_starts)

    def length(a, b):
        return sum(durations[a:b], Decimal(0))

    def obstacle(a, b):
        if b-a > MAX_SHOTS:
            return '每组12镜上限'
        if length(a, b) > MAX_SECONDS:
            return '合并将超过15秒'
        for j in range(a+1, b):
            if j in blocked:
                return '跨来源视频边界尚未检验通过'
            if ss[j]['continuity_id'] != ss[j-1]['continuity_id']:
                return '明确时空或连续性边界'
            if not edges[j-1]['merge_allowed']:
                return edges[j-1]['reason']
        if b-a > 1 and not any(x <= a and b <= y for x, y in spans):
            return '整段生成复杂度未获支持，不能由两两可合并外推'
        return None

    # Natural events first; oversized/complex events split at the strongest cut
    # available within their feasible prefix (weaker continuation cuts first).
    natural = [0] + [i for i in range(1, len(ss)) if
        ss[i]['event']['id'] != ss[i-1]['event']['id'] or
        not edges[i-1]['merge_allowed'] or i in blocked or
        ss[i]['continuity_id'] != ss[i-1]['continuity_id']] + [len(ss)]
    groups = []
    for a, end in zip(natural, natural[1:]):
        while a < end:
            candidates = [b for b in range(a+1, min(end, a+MAX_SHOTS)+1) if not obstacle(a, b)]
            # Keep a complete natural event whenever possible. Otherwise prefer
            # the weakest internal continuation, then the longest legal prefix.
            b = end if end in candidates else min(candidates, key=lambda b: (edges[b-1]['strength'] if b < end else -1, -b))
            groups.append((a, b))
            a = b
    trace = [dict(stage='natural', ranges=list(groups))]

    def merge_pass(short_only=False):
        changed = False
        while True:
            choices = []
            for i, ((a, b), (_, c)) in enumerate(zip(groups, groups[1:])):
                if short_only and min(length(a, b), length(b, c)) >= SHORT_SECONDS:
                    continue
                if not obstacle(a, c):
                    # Stronger narrative continuation first; ties merge left.
                    choices.append((-edges[b-1]['strength'], i))
            if not choices:
                return changed
            _, i = min(choices)
            a, b = groups[i]
            _, c = groups[i+1]
            groups[i:i+2] = [(a, c)]
            trace.append(dict(stage='short_merge' if short_only else 'adjacent_merge',
                              shot_ids=ids[a:c], reason=edges[b-1]['reason']))
            changed = True

    merge_pass()
    merge_pass(short_only=True)
    reasons = []
    for i, (a, b) in enumerate(groups):
        summaries = list(dict.fromkeys(s['event']['summary'] for s in ss[a:b]))
        reason = '；'.join(summaries)
        if len(summaries) > 1:
            reason += '；自然承接合并。'
        if length(a, b) < SHORT_SECONDS:
            limits = []
            if i:
                limits.append(obstacle(groups[i-1][0], b))
            if i+1 < len(groups):
                limits.append(obstacle(a, groups[i+1][1]))
            note = '；'.join(dict.fromkeys(x for x in limits if x)) or '全段内容已完整，无相邻段可合并'
            reason += '；短段已复核：' + note + '。'
            trace.append(dict(stage='short_review', shot_ids=ids[a:b], reason=note))
        reasons.append(reason)
    return dict(feasible=True, ranges=groups, reasons=reasons, trace=trace, limitations=[])
