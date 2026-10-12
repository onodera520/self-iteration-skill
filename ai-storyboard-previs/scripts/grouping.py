"""Narrative-first imported-video partitioning. No media or paid operations."""
from decimal import Decimal
import re

POLICY_VERSION = 4
MIN_SECONDS = Decimal('4')
MAX_SECONDS = Decimal('15')
SHORT_SECONDS = Decimal('8')
MAX_SHOTS = 12


def has_input_groups(p):
    return p.get('input_shot_groups') is not None


def parse_input_groups(value, shot_ids):
    """Normalize JSON, a two-column Markdown table, or A01: S01–S03 text.

    Parsing never repairs the user's partition. Unknown/reversed ranges remain
    visible to the conflict collector rather than being silently sorted.
    """
    import json
    if isinstance(value, str):
        value = value.strip()
        if value.startswith(('[', '{')):
            try:
                value = json.loads(value)
            except ValueError:
                return [dict(id='', shot_ids=[], parse_error='分组 JSON 无法解析')]
        else:
            rows = []
            for line in re.split(r'[;；\n]+', value):
                line = line.strip()
                if not line:
                    continue
                if line.startswith('|'):
                    cells = [c.strip() for c in line.strip('|').split('|')]
                    if len(cells) >= 2 and (re.fullmatch(r'[:\- ]+', cells[0]) or cells[0] in ('分组', '分组编号', 'Shot')):
                        continue
                    if len(cells) >= 2:
                        rows.append(dict(id=cells[0], shot_ids=cells[1]))
                        continue
                parts = re.split(r'[:：]', line, maxsplit=1)
                rows.append(dict(id=parts[0] if len(parts) == 2 else '',
                                 shot_ids=parts[1] if len(parts) == 2 else [],
                                 **({} if len(parts) == 2 else {'parse_error': '分组文字需写为 A01：S01–S03'})))
            value = rows
    if isinstance(value, dict):
        if 'input_shot_groups' in value:
            return parse_input_groups(value['input_shot_groups'], shot_ids)
        value = [value] if 'id' in value and 'shot_ids' in value else [dict(id=k, shot_ids=v) for k, v in value.items()]
    if not isinstance(value, list):
        return [dict(id='', shot_ids=[], parse_error='input_shot_groups 必须为分组列表、表格或文字')]
    result = []
    for row in value:
        if not isinstance(row, dict):
            result.append(dict(id='', shot_ids=[], parse_error='每个分组须有 id 和 shot_ids'))
            continue
        item = dict(id=row.get('id', ''), shot_ids=row.get('shot_ids', []))
        if row.get('parse_error'):
            item['parse_error'] = row['parse_error']
        seq = item['shot_ids']
        if isinstance(seq, str):
            seq = seq.strip()
            # A range follows the original script, not guessed numerical IDs.
            match = re.fullmatch(r'([\w]+)\s*[–—~～-]\s*([\w]+)', seq)
            if match:
                first, last = match.groups()
                if first in shot_ids and last in shot_ids:
                    a, b = shot_ids.index(first), shot_ids.index(last)
                    seq = shot_ids[a:b+1] if a <= b else list(reversed(shot_ids[b:a+1]))
                else:
                    seq = [first, last]
                    item['parse_error'] = '范围端点不是原脚本镜号'
            else:
                seq = [s for s in re.split(r'[\s,，、→]+', seq) if s]
        item['shot_ids'] = seq
        result.append(item)
    return result


def input_partition(p, blocked_starts=None):
    """Collect all fixed-partition conflicts; never mutate or fall back to auto.

    None means cross-video checks are deferred until evidence-bound reviews are
    available. An explicit collection contains boundaries not yet approved.
    """
    if not has_input_groups(p):
        return None
    shots = p['shots']
    ids = [s['id'] for s in shots]
    positions = {sid: i for i, sid in enumerate(ids)}
    groups = parse_input_groups(p['input_shot_groups'], ids)
    conflicts, ranges, owners = [], {}, {}

    def problem(code, message, indexes, shot_ids=()):
        conflicts.append(dict(code=code, message=message, group_indexes=sorted(set(indexes)), shot_ids=list(shot_ids)))

    for i, g in enumerate(groups):
        if g.get('parse_error'):
            problem('format', g['parse_error'], [i])
        if not isinstance(g['id'], str) or not g['id'].strip():
            problem('group_id', '分组编号不能为空', [i])
        seq = g['shot_ids']
        if not isinstance(seq, list) or not seq or any(not isinstance(s, str) for s in seq):
            problem('shot_ids', '分组须包含有序镜号列表', [i])
            g['shot_ids'] = []
            continue
        unknown = [s for s in seq if s not in positions]
        if unknown:
            problem('unknown', '未知镜号：' + '、'.join(unknown), [i], unknown)
        known = [s for s in seq if s in positions]
        for sid in known:
            owners.setdefault(sid, []).append(i)
        indexes = [positions[s] for s in known]
        if indexes and indexes != sorted(indexes):
            problem('order', '组内镜号乱序', [i], known)
        if indexes and indexes != list(range(indexes[0], indexes[0]+len(indexes))):
            problem('nonadjacent', '组内镜头必须连续相邻且原序排列', [i], known)
        if known and len(known) == len(seq) and indexes == list(range(indexes[0], indexes[0]+len(indexes))):
            ranges[i] = (indexes[0], indexes[-1]+1)
        if len(seq) > MAX_SHOTS:
            problem('shot_limit', '每组最多12镜', [i], known)
        durations = [shots[positions[s]].get('duration') for s in known]
        from previs import number
        duration_valid = all(number(d) and d > 0 for d in durations)
        if len(known) != len(seq) or not duration_valid:
            g['planned_duration'] = None
            if not duration_valid:
                problem('duration', '补齐脚本计划时长后才能批准省图', [i], known)
        else:
            total = sum((Decimal(str(d)) for d in durations), Decimal(0))
            g['planned_duration'] = float(total)
            if not MIN_SECONDS <= total <= MAX_SECONDS:
                problem('duration', '组总时长须为4–15秒', [i], known)
        unbound = [s for s in known if not shots[positions[s]].get('duration_source')]
        if unbound:
            problem('duration_source', '补齐计划时长及来源：' + '、'.join(unbound), [i], unbound)
        if len({shots[positions[s]].get('beat', {}).get('id') for s in known}) > 1:
            problem('beat', '不得跨 Beat 分组', [i], known)
        if blocked_starts is not None and indexes and any(min(indexes) < b <= max(indexes) for b in blocked_starts):
            problem('source_boundary', '跨来源视频边界尚未检验通过', [i], known)
    for gid in {g['id'] for g in groups if isinstance(g['id'], str)}:
        indexes = [i for i, g in enumerate(groups) if g['id'] == gid]
        if len(indexes) > 1:
            problem('duplicate_group', '重复分组编号：' + gid, indexes)
    for sid, indexes in owners.items():
        if len(indexes) > 1:
            problem('duplicate', '镜号重复：' + sid, indexes, [sid])
    missing = [sid for sid in ids if sid not in owners]
    if missing:
        problem('missing', '分组漏号：' + '、'.join(missing), [], missing)
    # A cut may be shifted, but supplied group order must never be sorted here.
    previous = None
    for i, g in enumerate(groups):
        indexes = [positions[s] for s in g['shot_ids'] if s in positions]
        if indexes:
            if previous and min(indexes) <= previous[1]:
                problem('group_order', '分组顺序与原脚本不一致', [previous[0], i])
            previous = (i, max(indexes))
    if not groups:
        problem('empty', '输入了空分组；不自动退回自动分组', [])
    invalid = {i for c in conflicts for i in c['group_indexes']}
    for i, g in enumerate(groups):
        g.update(planning_status='pending' if i in invalid else 'ready',
                 conflicts=[c['message'] for c in conflicts if i in c['group_indexes']])
    return dict(mode='input', feasible=not conflicts, groups=groups,
                # Public contexts must compare identically after a JSON round trip.
                valid_ranges={str(i): list(v) for i, v in ranges.items() if i not in invalid},
                conflicts=conflicts, unassigned_shot_ids=missing,
                limitations=[('、'.join(str(groups[i]['id']) for i in c['group_indexes']) + '：' if c['group_indexes'] else '') + c['message'] for c in conflicts],
                boundary_checks_deferred=blocked_starts is None)


def main():
    """Import a fixed partition under the existing project lock; no media writes."""
    import argparse
    import json
    from pathlib import Path
    from previs import locked, read, save
    ap = argparse.ArgumentParser(description='检查或登记用户 Shot 分组；不自动修正冲突')
    ap.add_argument('project')
    ap.add_argument('input', help='UTF-8 分组文字、Markdown 表格或 JSON 文件')
    ap.add_argument('--apply', action='store_true', help='只保存 input_shot_groups；冲突也原样保留')
    args = ap.parse_args()
    with locked(args.project):
        p = read(args.project)
        raw = Path(args.input).read_text(encoding='utf-8-sig')
        p['input_shot_groups'] = parse_input_groups(raw, [s['id'] for s in p['shots']])
        report = input_partition(p)
        if args.apply:
            save(args.project, p)
        print(json.dumps(report, ensure_ascii=False, indent=2))


def validate_metadata(p, report=None):
    from previs import number
    from validation import Report, sourced, text, text_array, shot_path
    own = report is None
    report = report if report is not None else Report()
    has_beat = any('beat' in s for s in p['shots'])
    for i, s in enumerate(p['shots']):
        path = shot_path(s, i)
        if has_beat:
            beat = s.get('beat')
            if report.kind(beat, dict, path + '.beat'):
                report.check(text(beat.get('id')) and bool(re.fullmatch(r'[A-Za-z0-9_-]+', beat['id'])),
                             path + '.beat.id', 'beat needs a stable identifier')
                report.check(sourced(beat.get('source'), ('script', 'inference')),
                             path + '.beat.source', 'beat needs script/inference and ref')
        if 'duration_source' in s:
            report.check(sourced(s['duration_source'], ('script', 'inference')), path + '.duration_source', 'duration_source needs script/inference and ref')
            report.check(number(s.get('duration')) and s['duration'] > 0, path + '.duration', 'duration_source requires positive duration')
    data = p.get('narrative_plan')
    if not has_input_groups(p) and data is not None and report.kind(data, dict, 'narrative_plan'):
        report.check(sourced(data.get('source'), ('script', 'inference')), 'narrative_plan.source', 'narrative_plan source required')
        ids = [s['id'] for s in p['shots']]
        edges = data.get('boundaries')
        if report.kind(edges, list, 'narrative_plan.boundaries'):
            report.check(all(isinstance(e, dict) for e in edges) and [e.get('before_shot_id') for e in edges] == ids[1:],
                         'narrative_plan.boundaries', 'narrative boundaries must cover all adjacent shots in order')
            for i, edge in enumerate(edges):
                path = f'narrative_plan.boundaries[{i}]'
                if not report.kind(edge, dict, path):
                    continue
                report.check(type(edge.get('merge_allowed')) is bool, path + '.merge_allowed', 'boundary needs merge_allowed boolean')
                report.check(type(edge.get('strength')) is int and 0 <= edge['strength'] <= 3, path + '.strength', 'boundary needs strength 0..3')
                report.check(text(edge.get('reason')), path + '.reason', 'boundary reason required')
        spans = data.get('safe_spans')
        if report.kind(spans, list, 'narrative_plan.safe_spans'):
            for i, span in enumerate(spans):
                path = f'narrative_plan.safe_spans[{i}]'
                if not report.kind(span, dict, path):
                    continue
                seq = span.get('shot_ids')
                report.check(text(span.get('reason')), path + '.reason', 'safe span must explain whole-interval complexity')
                if report.check(text_array(seq) and bool(seq) and seq[0] in ids, path + '.shot_ids', 'invalid safe span'):
                    start = ids.index(seq[0])
                    report.check(ids[start:start+len(seq)] == seq, path + '.shot_ids', 'safe span must be contiguous and explain whole-interval complexity')
    if own:
        report.finish()


def validate_partition(p, ranges):
    """Audit coverage/order and duration conservation independently of the solver."""
    ss = p['shots']
    ids = [s['id'] for s in ss]
    if len(ids) != len(set(ids)):
        raise ValueError('Clip identifiers must be unique')
    cursor, totals = 0, []
    for a, b in ranges:
        if a != cursor or not a < b <= len(ss):
            raise ValueError('partition must cover every Clip exactly once in original order')
        total = sum((Decimal(str(s['duration'])) for s in ss[a:b]), Decimal(0))
        if not MIN_SECONDS <= total <= MAX_SECONDS or b-a > MAX_SHOTS:
            raise ValueError('each group requires 4..15 seconds and at most 12 Clips')
        if len({s.get('beat', {}).get('id') for s in ss[a:b]}) != 1:
            raise ValueError('a group cannot cross Beat boundaries')
        totals.append(total)
        cursor = b
    if cursor != len(ss) or not ranges:
        raise ValueError('partition must cover every Clip exactly once in original order')
    if sum(totals, Decimal(0)) != sum((Decimal(str(s['duration'])) for s in ss), Decimal(0)):
        raise ValueError('partition must conserve total duration')
    return totals


def clip_group_list(p, ranges):
    """JSON-ready internal Clip -> Shot view; no second LLM transformation."""
    totals = validate_partition(p, ranges)
    result = []
    for n, ((a, b), total) in enumerate(zip(ranges, totals), 1):
        used = {aid for s in p['shots'][a:b] for aid in s['asset_ids']}
        result.append(dict(shotId=f'shot_{n}', originClipIdList=[s['id'] for s in p['shots'][a:b]],
                           totalDuration=float(total),
                           assetIdList=[asset['id'] for asset in p['assets'] if asset['id'] in used]))
    return result


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
            if ss[j].get('beat', {}).get('id') != ss[j-1].get('beat', {}).get('id'):
                return '不同 Beat，不跨段聚合'
            if not edges[j-1]['merge_allowed']:
                return edges[j-1]['reason']
        if b-a > 1 and not any(x <= a and b <= y for x, y in spans):
            return '整段生成复杂度未获支持，不能由两两可合并外推'
        return None

    # Natural events first; oversized/complex events split at the weakest
    # continuation available within their feasible prefix.
    natural = [0] + [i for i in range(1, len(ss)) if
        ss[i]['event']['id'] != ss[i-1]['event']['id'] or
        not edges[i-1]['merge_allowed'] or i in blocked or
        ss[i].get('beat', {}).get('id') != ss[i-1].get('beat', {}).get('id') or
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
    if any(length(a, b) < MIN_SECONDS for a, b in groups):
        # Moving a cut can avoid a short tail (e.g. 12+1 -> 9+4 Clips).
        # Repartition only when necessary; never relax a narrative/evidence gate.
        best = {0: ((0, 0, ()), [])}
        for b in range(1, len(ss)+1):
            choices = []
            for a in range(max(0, b-MAX_SHOTS), b):
                if a not in best or length(a, b) < MIN_SECONDS or obstacle(a, b):
                    continue
                score, prefix = best[a]
                cut_cost = edges[a-1]['strength'] if a else 0
                # Fewer groups; weaker cuts; longer earlier group on ties.
                key = (score[0]+1, score[1]+cut_cost, score[2]+(-b,))
                choices.append((key, prefix+[(a, b)]))
            if choices:
                best[b] = min(choices)
        if len(ss) not in best:
            return dict(feasible=False, ranges=[], reasons=[], trace=trace,
                        limitations=['无法同时满足每组4–15秒、12镜上限及剧情/Beat/来源证据边界；需补充连续内容、拆分或调整计划时长，不能自动改时长或跨边界合并。'])
        groups[:] = best[len(ss)][1]
        trace.append(dict(stage='minimum_repartition', ranges=list(groups),
                          reason='重排相邻切分位置以满足4秒下限，原镜序及计划时长不变'))
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
    validate_partition(p, groups)
    return dict(feasible=True, ranges=groups, reasons=reasons, trace=trace, limitations=[])


if __name__ == '__main__':
    main()
