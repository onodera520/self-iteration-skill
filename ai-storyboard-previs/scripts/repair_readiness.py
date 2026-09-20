"""Collect repair-evidence omissions before delivery; never infer a judgment."""
from collections import Counter

from validation import Report, text


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
    return report
