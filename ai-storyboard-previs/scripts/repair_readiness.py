"""Collect repair-evidence omissions before delivery; never infer a judgment."""
from collections import Counter
from math import isfinite

from validation import Report, text


def diagnose_damage(row, review, report=None, path='repair_assessment'):
    """Validate the optional one-shot corruption gate, not visual severity itself."""
    report = report if report is not None else Report()
    if 'severe_visual_damage' not in row:
        return report
    path += '.severe_visual_damage'
    damage = row['severe_visual_damage']
    if not report.kind(damage, dict, path):
        return report
    sid = row.get('shot_id')
    shot = next((v for v in review.get('shot_reviews', [])
                 if isinstance(v, dict) and v.get('shot_id') == sid), {})
    report.check(shot.get('verdict') == 'FAIL' and row.get('affects_story') is True,
                 path, 'severe damage needs a confirmed story-affecting FAIL, not absence/uncertainty')
    for field in ('damage_description', 'obscured_content'):
        report.check(text(damage.get(field)), path + '.' + field,
                     'describe visible corruption and the necessary content it obscures')
    span = damage.get('time_range')
    valid_span = (isinstance(span, list) and len(span) == 2 and
                  all(type(t) in (int, float) and isfinite(t) for t in span) and 0 <= span[0] < span[1])
    if report.check(valid_span, path + '.time_range', 'finite damaged interval with start < end required'):
        report.check(any(isinstance(e, dict) and type(e.get('time')) in (int, float) and
                         isfinite(e['time']) and e.get('shot_id') == sid and
                         e['time'] in (shot.get('evidence_times') or [])
                         and span[0] <= e['time'] <= span[1] for e in review.get('evidence', [])),
                     path + '.time_range', 'damaged interval needs same-shot timed frame evidence')
        refs = row.get('issue_ids')
        refs = refs if isinstance(refs, list) else []
        report.check(any(isinstance(i, dict) and i.get('id') in refs and
                         isinstance(i.get('shot_ids'), list) and sid in i['shot_ids'] and
                         isinstance(i.get('time_range'), list) and len(i['time_range']) == 2 and
                         all(type(t) in (int, float) and isfinite(t) for t in i['time_range']) and
                         i['time_range'][0] <= span[0] < span[1] <= i['time_range'][1]
                         for i in review.get('issues', [])),
                     path + '.time_range', 'damaged interval must be covered by a referenced same-shot issue')
    return report


def diagnose(p, review, report=None, prefix='repair_assessments'):
    report = report if report is not None else Report()
    rows = review.get('repair_assessments', [])
    if not report.kind(rows, list, prefix):
        return report
    problems = {v['shot_id']: v for v in review['shot_reviews']
                if isinstance(v.get('shot_id'), str) and v.get('verdict') in ('FAIL', 'absent')}
    valid = [r for r in rows if isinstance(r, dict) and isinstance(r.get('shot_id'), str)]
    counts = Counter(r['shot_id'] for r in valid)
    for sid in sorted(problems.keys() | counts.keys()):
        report.check(counts[sid] == (1 if sid in problems else 0), f'{prefix}[{sid}]',
                     'each confirmed FAIL/absent needs exactly one assessment; PASS/uncertain needs none')
    shots = {s['id']: s for s in p['shots']}
    issues = {i.get('id'): i for i in review.get('issues', []) if isinstance(i, dict) and text(i.get('id'))}
    for i, row in enumerate(rows):
        if not report.kind(row, dict, f'{prefix}[{i}]'):
            continue
        sid = row.get('shot_id')
        path = f'{prefix}[{sid}]' if isinstance(sid, str) else f'{prefix}[{i}]'
        if not report.check(isinstance(sid, str) and sid in problems and sid in shots,
                            path + '.shot_id', 'unknown or non-problem shot'):
            continue
        for field in ('critical', 'affects_story'):
            report.check(type(row.get(field)) is bool, path + '.' + field, 'explicit reviewer boolean required')
        quote = row.get('script_quote')
        report.check(text(quote) and quote in shots[sid]['script'], path + '.script_quote', 'exact same-shot script quote required')
        refs = row.get('issue_ids')
        good_refs = isinstance(refs, list) and bool(refs) and all(text(x) for x in refs)
        report.check(good_refs and len(refs) == len(set(refs)) and
                     all(x in issues and sid in issues[x].get('shot_ids', []) for x in refs),
                     path + '.issue_ids', 'unique same-shot issue references required')
        for field in ('impact', 'correction'):
            report.check(text(row.get(field)), path + '.' + field, 'specific reviewer rationale required')
        report.check(row.get('preserves_script') is True, path + '.preserves_script', 'confirm correction preserves original script')
        if row.get('critical') is True:
            report.check(row.get('affects_story') is True, path + '.affects_story', 'critical issue must affect story')
            report.check(row.get('critical_kind') in ('missing_key_node', 'wrong_actor', 'broken_causality',
                         'wrong_transfer_result', 'explicit_key_requirement'), path + '.critical_kind', 'concrete critical kind required')
        diagnose_damage(row, review, report, path)
    return report
