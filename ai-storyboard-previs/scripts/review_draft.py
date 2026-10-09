"""Evidence-bound review scaffolds and read-only batch diagnostics; never a visual judge."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import sys

import previs as core
from evidence_runtime import evidence_operation
from validation import Report, text


def from_context(ctx, shot_ids=None):
    from storyboard import CHECKS, has_frame_observation
    ids = shot_ids if shot_ids is not None else [s['shot_id'] for s in ctx['shots']]
    mapping = {s['shot_id']: s for s in ctx['mapping']['shots']}
    frames = {(f['sha256'], f['time']): f for f in ctx['extraction']['frames']}
    rows, references, evidence = [], [], []
    for shot in ctx['shots']:
        sid = shot['shot_id']
        if sid not in ids:
            continue
        selected = shot['selected_frame']
        shot_evidence = {}
        absent = mapping[sid]['status'] == 'absent'
        if selected and not absent:
            time = selected['source']['time']
            shot_evidence[selected['sha256'], time] = dict(
                shot_id=sid, path=selected['path'], sha256=selected['sha256'], time=time,
                observation='', visible_facts=[], interpretation='')
        if mapping[sid]['status'] == 'matched':
            for candidate in mapping[sid]['candidates']:
                if not has_frame_observation(candidate):
                    continue
                key = candidate['sha256'], candidate['time']
                frame = frames.get(key)
                core.require(frame is not None, 'candidate observation is not bound to current extraction')
                row = shot_evidence.setdefault(key, dict(
                    shot_id=sid, **{k: frame[k] for k in ('path', 'sha256', 'time')}, interpretation=''))
                # Copy only neutral single-frame notes. Interpretations and verdicts stay unapproved.
                row.update(observation=candidate['observation'], visible_facts=copy.deepcopy(candidate['visible_facts']))
        observed = sorted(shot_evidence.values(), key=lambda e: e['time'])
        evidence.extend(observed)
        times = [e['time'] for e in observed]
        rows.append(dict(shot_id=sid, verdict='absent' if absent else 'uncertain', reason='',
                         identity_reason='', evidence_times=times,
                         checks={k: 'uncertain' for k in sorted(CHECKS)}, followup=''))
        references.append(dict(shot_id=sid, decision='pending', derivable=None,
                               basis_shot_ids=[], evidence_times=list(times), reason=''))
    return dict(**{k: ctx[k] for k in ('group_id', 'version', 'video_sha256', 'context_fingerprint',
                                      'review_schema', 'reference_policy_version')},
                checks={k: 'uncertain' for k in ('shot', 'continuity', 'story')},
                grouping_checked=False, coverage=dict(shot_ids=list(ids), mapping_verified=False, limitations=[]),
                shot_reviews=rows, reference_assessments=references, evidence=evidence,
                issues=[], uncertainties=[], asset_comparisons=[], repair_assessments=[],
                boundary_checks=[dict(shot_id=b['shot_id'], verdict='uncertain', observation='')
                                 for b in ctx['boundaries']])


def worklist(draft, compact=False):
    """Editable semantic fields, keyed by shot ID; evidence bindings stay in the draft."""
    if compact:
        return compact_worklist(draft)
    result = dict(base_digest=core.digest(draft), shots={}, evidence=[], group={})
    references = {r['shot_id']: r for r in draft['reference_assessments']}
    assessments = {r['shot_id']: r for r in draft.get('repair_assessments', [])}
    for row in draft['shot_reviews']:
        sid = row['shot_id']
        result['shots'][sid] = dict(
            review={k: copy.deepcopy(v) for k, v in row.items() if k not in ('shot_id', 'evidence_times')},
            reference={k: copy.deepcopy(v) for k, v in references[sid].items() if k not in ('shot_id', 'evidence_times')},
            repair=copy.deepcopy(assessments.get(sid)) or dict(
                critical=None, critical_kind=None, affects_story=None, script_quote='', issue_ids=[],
                impact='', correction='', preserves_script=None))
        result['shots'][sid]['repair'].pop('shot_id', None)
    result['evidence'] = [{k: copy.deepcopy(e[k]) for k in
                          ('shot_id', 'sha256', 'time', 'observation', 'visible_facts', 'interpretation')}
                         for e in draft['evidence']]
    result['group'] = {k: copy.deepcopy(draft[k]) for k in
                       ('checks', 'grouping_checked', 'issues', 'uncertainties', 'asset_comparisons', 'boundary_checks')}
    result['group']['mapping_verified'] = draft['coverage']['mapping_verified']
    result['group']['limitations'] = copy.deepcopy(draft['coverage']['limitations'])
    return result


def compact_worklist(draft):
    """Explicit judgments plus evidence deltas; never infer PASS or a repair decision."""
    result = worklist(draft)
    result['format'] = 'review-worklist-2'
    for sid, values in result['shots'].items():
        if values['review']['verdict'] not in ('FAIL', 'absent'):
            del values['repair']
    result['evidence'] = []
    for i, row in enumerate(draft['evidence'], 1):
        value = dict(id=f'E{i:03d}', interpretation=row['interpretation'])
        if text(row['observation']) and row['visible_facts']:
            value['reuse_facts'] = True
        else:
            value.update(observation=row['observation'], visible_facts=copy.deepcopy(row['visible_facts']))
        result['evidence'].append(value)
    return result


def expand_worklist(draft, edits):
    """Resolve read-only IDs only against the exact, digest-bound source draft."""
    core.require(set(edits) == {'format', 'base_digest', 'shots', 'evidence', 'group'} and
                 edits['format'] == 'review-worklist-2', 'unexpected compact worklist format')
    expected = worklist(draft)
    core.require(isinstance(edits['shots'], dict) and set(edits['shots']) == set(expected['shots']),
                 'worklist must cover exact shot IDs')
    expanded = copy.deepcopy(edits)
    del expanded['format']
    for sid, values in expanded['shots'].items():
        core.require(isinstance(values, dict) and isinstance(values.get('review'), dict), 'invalid shot fields: ' + sid)
        problem = values['review'].get('verdict') in ('FAIL', 'absent')
        core.require(set(values) == ({'review', 'reference', 'repair'} if problem else {'review', 'reference'}),
                     'FAIL/absent require repair; non-problem shots omit repair: ' + sid)
        if not problem:
            values['repair'] = copy.deepcopy(expected['shots'][sid]['repair'])
    rows = edits['evidence']
    ids = [f'E{i:03d}' for i in range(1, len(draft['evidence']) + 1)]
    core.require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows) and
                 len(rows) == len(ids) and {r.get('id') for r in rows} == set(ids),
                 'evidence IDs must cover exact draft evidence once')
    originals = dict(zip(ids, draft['evidence']))
    expanded['evidence'] = []
    for row in rows:
        original = originals[row['id']]
        value = {k: copy.deepcopy(original[k]) for k in ('shot_id', 'sha256', 'time')}
        if 'reuse_facts' in row:
            core.require(set(row) == {'id', 'reuse_facts', 'interpretation'} and row['reuse_facts'] is True and
                         text(original['observation']) and bool(original['visible_facts']),
                         'reuse_facts requires recorded single-frame facts; do not rebind evidence')
            value.update(observation=original['observation'], visible_facts=copy.deepcopy(original['visible_facts']))
        else:
            core.require(set(row) == {'id', 'observation', 'visible_facts', 'interpretation'}, 'unexpected evidence delta fields')
            value.update(observation=row['observation'], visible_facts=copy.deepcopy(row['visible_facts']))
        value['interpretation'] = row['interpretation']
        expanded['evidence'].append(value)
    return expanded


def agent_view(ctx, context_file):
    """Normalize repeated frame bindings; keep every frame, candidate, state and boundary."""
    result = {k: copy.deepcopy(v) for k, v in ctx.items()
              if k not in ('previous_review', 'shots', 'mapping', 'extraction', 'boundaries', 'context_fingerprint')}
    result.update(format='review-view-1', context_fingerprint=ctx['context_fingerprint'],
                  full_context_file=str(Path(context_file).resolve()))
    frames = ctx['extraction']['frames']
    index = {(f['sha256'], f['time']): f'F{i:03d}' for i, f in enumerate(frames, 1)}
    core.require(len(index) == len(frames), 'duplicate frame binding in context')
    # Full SHA256 values remain in the frozen full context and draft; short IDs are reading aids.
    result['frames'] = [dict(id=index[f['sha256'], f['time']], **copy.deepcopy({k: v for k, v in f.items() if k != 'sha256'}))
                        for f in frames]
    result['extraction'] = {k: copy.deepcopy(v) for k, v in ctx['extraction'].items() if k != 'frames'}

    def selected(value):
        if not value:
            return None
        key = value['sha256'], value['source']['time']
        core.require(key in index, 'selected frame must belong to current extraction')
        return dict(frame_id=index[key], **copy.deepcopy({k: v for k, v in value.items()
                                                        if k not in ('path', 'sha256')}))

    result['shots'] = []
    for shot in ctx['shots']:
        row = copy.deepcopy(shot)
        row['selected_frame'] = selected(shot['selected_frame'])
        result['shots'].append(row)
    result['mapping'] = copy.deepcopy(ctx['mapping'])
    for row in result['mapping']['shots']:
        row['candidates'] = [dict(frame_id=index[c['sha256'], c['time']],
                                  **{k: v for k, v in c.items() if k not in ('path', 'sha256', 'time')})
                             for c in row['candidates']]
    # Boundary frames belong to other source videos; retain their complete independent bindings.
    result['boundaries'] = copy.deepcopy(ctx['boundaries'])
    result['evidence_ids'] = [dict(id=f'E{i:03d}', shot_id=e['shot_id'], frame_id=index[e['sha256'], e['time']])
                              for i, e in enumerate(from_context(ctx)['evidence'], 1)]
    result['view_digest'] = core.digest(result)
    return result


def fill(draft, edits):
    """Merge an explicit worklist, never rebind timestamps, hashes, or context."""
    core.require(edits.get('base_digest') == core.digest(draft), 'stale worklist; use the exact source draft')
    if 'format' in edits:
        edits = expand_worklist(draft, edits)
    expected = worklist(draft)
    core.require(set(edits) == set(expected) and set(edits['shots']) == set(expected['shots']), 'worklist must cover exact shot IDs')
    result = copy.deepcopy(draft)
    result['repair_assessments'] = []
    references = {r['shot_id']: r for r in result['reference_assessments']}
    for row in result['shot_reviews']:
        sid = row['shot_id']
        reference = references[sid]
        values = edits['shots'][sid]
        core.require(set(values) == set(expected['shots'][sid]), 'unexpected shot fields: ' + sid)
        for name, target in (('review', row), ('reference', reference)):
            core.require(set(values[name]) == set(expected['shots'][sid][name]), 'mechanical fields cannot be edited: ' + sid)
            target.update(copy.deepcopy(values[name]))
        core.require(set(values['repair']) == set(expected['shots'][sid]['repair']), 'unexpected repair fields: ' + sid)
        if row['verdict'] in ('FAIL', 'absent'):
            result['repair_assessments'].append(dict(shot_id=sid, **copy.deepcopy(values['repair'])))
        else:
            core.require(values['repair'] == expected['shots'][sid]['repair'] and
                         sid not in {a['shot_id'] for a in draft.get('repair_assessments', [])},
                         'non-problem shot must not carry a repair assessment: ' + sid)
    key = lambda e: (e['shot_id'], e['sha256'], e['time'])
    original = {key(e): e for e in result['evidence']}
    core.require(len(edits['evidence']) == len(original) and {key(e) for e in edits['evidence']} == set(original),
                 'evidence bindings changed; rebuild draft from actual evidence')
    for row in edits['evidence']:
        core.require(set(row) == {'shot_id', 'sha256', 'time', 'observation', 'visible_facts', 'interpretation'}, 'unexpected evidence fields')
        original[key(row)].update({k: copy.deepcopy(row[k]) for k in ('observation', 'visible_facts', 'interpretation')})
    core.require(set(edits['group']) == set(expected['group']), 'unexpected group fields')
    for k, v in edits['group'].items():
        (result['coverage'] if k in ('mapping_verified', 'limitations') else result)[k] = copy.deepcopy(v)
    return result


def prepare(project, gid, output, context_output=None, worklist_output=None, view_output=None, compact=False):
    output = Path(output).resolve()
    core.require(not output.exists(), 'use a new draft file; existing judgments must not be overwritten')
    if context_output is not None:
        context_output = Path(context_output).resolve()
        core.require(context_output != output and not context_output.exists(), 'use a distinct new context file')
    if worklist_output is not None:
        worklist_output = Path(worklist_output).resolve()
        core.require(worklist_output not in (output, context_output) and not worklist_output.exists(), 'use a distinct new worklist file')
    if view_output is not None:
        view_output = Path(view_output).resolve()
        core.require(context_output is not None, 'view requires a frozen full context file')
        core.require(view_output not in (output, context_output, worklist_output) and not view_output.exists(),
                     'use a distinct new view file')
    with evidence_operation():
        p = core.read(project)
        core.validate(p, project)
        core.require(p['config'].get('video_source') == 'imported', 'imported video required')
        ctx = core.video_context(p, project, gid)
        core.require(ctx.get('mapping') and ctx.get('extraction'), 'current batch mapping required')
        draft = from_context(ctx)
        # Full evidence/state context, without recycling a previous verdict as a new review.
        ctx.pop('previous_review', None)
        view = agent_view(ctx, context_output) if view_output is not None else None
    core.save(output, draft)
    if context_output is not None:
        core.save(context_output, ctx)
    if worklist_output is not None:
        core.save(worklist_output, worklist(draft, compact=compact))
    if view_output is not None:
        core.save(view_output, view)
    return draft


def check(project, review, delivery_only=False):
    """Collect independent mechanical mistakes, then retain the full original gate."""
    report = Report()
    with evidence_operation():
        p = core.read(project)
        core.validate(p, project)
        core.require(p['config'].get('video_source') == 'imported', 'imported video required')
        if not report.kind(review, dict, '$'):
            report.finish()
        core.require(any(g['id'] == review.get('group_id') for g in p['groups']), 'unknown group')
        ctx = core.video_context(p, project, review['group_id'])
        core.require(ctx.get('mapping') and ctx.get('extraction'), 'current batch mapping required')
        # Stale context is a dependency failure, not a draft that may be rebound silently.
        core.require(all(review.get(k) == ctx[k] for k in
                         ('version', 'video_sha256', 'context_fingerprint')), 'stale review context; rebuild from current evidence')
        ids = [s['shot_id'] for s in ctx['shots']]
        for name in ('shot_reviews', 'reference_assessments', 'evidence', 'issues', 'boundary_checks'):
            values = review.get(name)
            if not report.kind(values, list, name):
                continue
            for i, row in enumerate(values):
                report.kind(row, dict, f'{name}[{i}]')
        report.finish()  # Shape failures block dependent field access only.
        for name in ('shot_reviews', 'reference_assessments'):
            report.check([r.get('shot_id') for r in review[name]] == ids, name, 'cover all shots once in source order')
            for i, row in enumerate(review[name]):
                path = f'{name}[{i}]'
                report.check(text(row.get('reason')), path + '.reason', 'reviewer rationale required')
                report.kind(row.get('evidence_times'), list, path + '.evidence_times')
        frames = {str(core.resolve(project, f['path'])): f for f in ctx['extraction']['frames']}
        for i, row in enumerate(review['evidence']):
            path = f'evidence[{i}]'
            report.check(row.get('shot_id') in ids, path + '.shot_id', 'unknown evidence shot')
            report.check(text(row.get('observation')), path + '.observation', 'visible observation required')
            frame = frames.get(str(core.resolve(project, row['path']))) if text(row.get('path')) else None
            report.check(frame is not None, path + '.path', 'must reference a current extracted frame')
            if frame:
                report.check(row.get('time') == frame['time'], path + '.time', 'reuse exact extracted timestamp')
                report.check(row.get('sha256') == frame['sha256'], path + '.sha256', 'reuse current frame SHA256')
        from storyboard import CHECKS
        for i, row in enumerate(review['shot_reviews']):
            path = f'shot_reviews[{i}]'
            report.check(row.get('verdict') in ('PASS', 'FAIL', 'uncertain', 'absent'), path + '.verdict', 'invalid verdict')
            if row.get('verdict') != 'absent':
                checks = row.get('checks')
                report.check(isinstance(checks, dict) and set(checks) == CHECKS and
                             all(v in ('PASS', 'FAIL', 'uncertain') for v in checks.values()),
                             path + '.checks', 'all per-shot checks required')
            if row.get('verdict') == 'uncertain':
                report.check(text(row.get('followup')), path + '.followup', 'concrete evidence followup required')
        if not delivery_only:
            from repair_readiness import diagnose
            diagnose(p, review, report)
        # Run on a copy: even a valid draft must not register a review in this command.
        try:
            core.record_review(copy.deepcopy(p), project, copy.deepcopy(review))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            report.check(False, '$.full_review', str(exc))
        report.finish()
    return dict(valid=True, scope='structure_and_evidence_only', visual_quality_verified=False,
                repair_readiness_checked=not delivery_only)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    sub = commands.add_parser('prepare')
    for field in ('project', 'group', 'output'):
        sub.add_argument(field)
    sub.add_argument('--context-output', help='save the same full context without a second context operation')
    sub.add_argument('--worklist-output', help='save editable semantic fields keyed by shot ID')
    sub.add_argument('--view-output', help='save normalized agent reading view; requires --context-output')
    sub.add_argument('--legacy-worklist', action='store_true', help='write the previous full semantic form instead of evidence deltas')
    sub = commands.add_parser('check')
    sub.add_argument('project'); sub.add_argument('review')
    sub.add_argument('--delivery-only', action='store_true', help='legacy review only; not repair readiness')
    sub = commands.add_parser('fill')
    for field in ('project', 'draft', 'worklist', 'output'):
        sub.add_argument(field)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.project, args.group, args.output, args.context_output, args.worklist_output,
                args.view_output, compact=not args.legacy_worklist)
        print('draft only; verify frame notes and complete interpretations and judgments')
    elif args.command == 'fill':
        core.require(not Path(args.output).exists(), 'use a new completed draft file')
        completed = fill(core.read(args.draft), core.read(args.worklist))
        # Checking before writing also verifies live frame hashes and current context.
        check(args.project, completed)
        core.save(args.output, completed)
        print('checked draft only; next: previs.py review PROJECT OUTPUT')
    else:
        print(json.dumps(check(args.project, core.read(args.review), args.delivery_only)))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
