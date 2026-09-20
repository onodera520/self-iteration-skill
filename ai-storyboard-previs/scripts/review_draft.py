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
                issues=[], uncertainties=[], asset_comparisons=[],
                boundary_checks=[dict(shot_id=b['shot_id'], verdict='uncertain', observation='')
                                 for b in ctx['boundaries']])


def prepare(project, gid, output, context_output=None):
    output = Path(output).resolve()
    core.require(not output.exists(), 'use a new draft file; existing judgments must not be overwritten')
    if context_output is not None:
        context_output = Path(context_output).resolve()
        core.require(context_output != output and not context_output.exists(), 'use a distinct new context file')
    with evidence_operation():
        p = core.read(project)
        core.validate(p, project)
        core.require(p['config'].get('video_source') == 'imported', 'imported video required')
        ctx = core.video_context(p, project, gid)
        core.require(ctx.get('mapping') and ctx.get('extraction'), 'current batch mapping required')
        draft = from_context(ctx)
        # Full evidence/state context, without recycling a previous verdict as a new review.
        ctx.pop('previous_review', None)
    core.save(output, draft)
    if context_output is not None:
        core.save(context_output, ctx)
    return draft


def check(project, review):
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
        # Run on a copy: even a valid draft must not register a review in this command.
        try:
            core.record_review(copy.deepcopy(p), project, copy.deepcopy(review))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            report.check(False, '$.full_review', str(exc))
        report.finish()
    return dict(valid=True, scope='structure_and_evidence_only', visual_quality_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    sub = commands.add_parser('prepare')
    for field in ('project', 'group', 'output'):
        sub.add_argument(field)
    sub.add_argument('--context-output', help='save the same full context without a second context operation')
    sub = commands.add_parser('check')
    sub.add_argument('project'); sub.add_argument('review')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.project, args.group, args.output, args.context_output)
        print('draft only; verify frame notes and complete interpretations and judgments')
    else:
        print(json.dumps(check(args.project, core.read(args.review))))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
