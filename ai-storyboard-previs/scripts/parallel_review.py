"""Frozen read-only review tasks, deterministic collection, one validated writer.

This is orchestration bookkeeping, not a visual judge or an LLM/API client.
"""
from __future__ import annotations
import argparse
import copy
from pathlib import Path

import previs as core
from evidence_runtime import evidence_operation

ROWS = ('shot_reviews', 'reference_assessments', 'evidence',
        'asset_comparisons', 'repair_assessments', 'issues', 'uncertainties')
MAX_DISPUTES = 4


def fingerprint(data):
    return core.digest({k: v for k, v in data.items() if k != 'fingerprint'})


def schedule(ctx, units):
    """Keep adjacent event runs intact; balance whole units, never individual shots."""
    ids = [s['shot_id'] for s in ctx['shots']]
    core.require(units and [sid for u in units for sid in u['shot_ids']] == ids,
                 'units must cover every shot once in original order')
    owners = {sid: i for i, u in enumerate(units) for sid in u['shot_ids']}
    for u in units:
        core.require(isinstance(u.get('reason'), str) and u['reason'].strip(), 'unit event reason required')
        core.require(u['shot_ids'] and core.number(u.get('workload')) and u['workload'] > 0,
                     'unit workload must be positive')
    for left, right in zip(ctx['shots'], ctx['shots'][1:]):
        le, re = left.get('event'), right.get('event')
        core.require(le and re, 'event context required; use serial review for legacy projects')
        if le['id'] == re['id']:
            core.require(owners[left['shot_id']] == owners[right['shot_id']],
                         'cannot split a continuous event between review units')
    lanes, loads = [[], []], [0, 0]
    for i in sorted(range(len(units)), key=lambda i: (-units[i]['workload'], i)):
        lane = min(range(2), key=lambda j: (loads[j], j))
        lanes[lane].append(i)
        loads[lane] += units[i]['workload']
    return [dict(id=f'T{i+1:02}', unit_indices=sorted(lane),
                 shot_ids=[sid for j in sorted(lane) for sid in units[j]['shot_ids']], workload=loads[i])
            for i, lane in enumerate(lanes) if lane]


def prepare(project, gid, units, output):
    project, output = Path(project).resolve(), Path(output).resolve()
    core.require(not output.exists(), 'use a new bundle directory')
    with evidence_operation():
        p = core.read(project)
        core.require(p['config'].get('video_source') == 'imported', 'parallel review is imported-video only')
        ctx = core.video_context(p, project, gid)
        core.require(ctx.get('mapping') and ctx.get('extraction'), 'batch mapping required before dispatch')
        ctx.pop('previous_review', None)
        tasks = schedule(ctx, units)
        bundle = dict(schema=1, project=str(project), project_sha256=core.sha(project),
                      context=ctx, source_script=p['source_script'], units=units, tasks=tasks,
                      max_workers=2, max_disputes=MAX_DISPUTES, draft_only=True,
                      mode='parallel' if len(tasks) == 2 else 'serial')
        bundle['fingerprint'] = fingerprint(bundle)
    output.mkdir(parents=True)
    core.save(output / 'bundle.json', bundle)
    for task in tasks:
        owned = set(task['shot_ids'])
        ids = [s['shot_id'] for s in ctx['shots']]
        neighbors = {ids[j] for i, sid in enumerate(ids) if sid in owned
                     for j in (i-1, i+1) if 0 <= j < len(ids) and ids[j] not in owned}
        core.save(output / task['id'] / 'task.json', dict(
            task_id=task['id'], bundle_fingerprint=bundle['fingerprint'],
            shared_context=str(output / 'bundle.json'), shot_ids=task['shot_ids'],
            neighbor_shot_ids=[sid for sid in ids if sid in neighbors],
            output=str(output / task['id'] / 'draft.json'), draft_only=True,
            instruction='Read the full script and frozen state context. Review owned shots and their continuity; '
                        'neighbors are context only. Write only draft.json. Do not change shared files, '
                        'states or mappings, extract frames, approve final groups, call APIs or spawn agents.'))
    return bundle


def load_bundle(project, directory):
    directory = Path(directory).resolve()
    b = core.read(directory / 'bundle.json')
    core.require(b.get('schema') == 1 and b.get('fingerprint') == fingerprint(b), 'bundle changed')
    core.require(Path(b['project']) == Path(project).resolve(), 'wrong project')
    core.require(core.sha(project) == b['project_sha256'], 'project changed; prepare a fresh bundle')
    p = core.read(project)
    ctx = core.video_context(p, project, b['context']['group_id'])
    core.require(ctx['context_fingerprint'] == b['context']['context_fingerprint'],
                 'evidence/context changed; prepare a fresh bundle')
    return p, b


def collect(project, directory):
    """No approval is synthesized; coordinator completes checks and boundary/state audit."""
    p, b = load_bundle(project, directory)
    ctx = b['context']
    ids = [s['shot_id'] for s in ctx['shots']]
    combined = {key: [] for key in ROWS}
    hashes, limitations = {}, []
    for task in b['tasks']:
        path = Path(directory) / task['id'] / 'draft.json'
        d = core.read(path)
        hashes[task['id']] = core.sha(path)
        core.require(d.get('task_id') == task['id'] and d.get('bundle_fingerprint') == b['fingerprint'],
                     'wrong or stale task draft')
        core.require(set(d) <= set(ROWS) | {'task_id', 'bundle_fingerprint', 'limitations'},
                     'worker may only submit review rows, not state/mapping/group edits')
        owned = set(task['shot_ids'])
        for key in ROWS:
            rows = d.get(key, [])
            core.require(isinstance(rows, list), 'draft rows must be lists')
            if key in ('shot_reviews', 'reference_assessments'):
                core.require([r['shot_id'] for r in rows] == task['shot_ids'], 'missing/duplicate/out-of-order owned shots')
            for row in rows:
                if key == 'uncertainties':
                    core.require(isinstance(row, str) and row.strip(), 'uncertainty must describe the evidence gap')
                else:
                    affected = row['shot_ids'] if key == 'issues' else [row['shot_id']]
                    core.require(affected and set(affected) <= owned, 'worker row outside its ownership')
                combined[key].append(copy.deepcopy(row))
        core.require(isinstance(d.get('limitations', []), list), 'limitations must be a list')
        limitations.extend(d.get('limitations', []))
    for key in ('issues', 'asset_comparisons'):
        keys = [r['id'] for r in combined[key]]
        core.require(len(keys) == len(set(keys)), 'duplicate issue/comparison IDs; prefix task ID')
    for key in ROWS:
        if key not in ('issues', 'uncertainties'):
            combined[key].sort(key=lambda r: ids.index(r['shot_id']))
    # Optional repair records remain optional, just as in the serial validator.
    if not combined['repair_assessments']:
        combined.pop('repair_assessments')
    boundaries = []
    by_id = {s['shot_id']: s for s in ctx['shots']}
    for a, z in zip(b['units'], b['units'][1:]):
        left, right = a['shot_ids'][-1], z['shot_ids'][0]
        boundaries.append(dict(shot_ids=[left, right],
            exit_state=by_id[left]['requirements']['exit_state'],
            entry_state=by_id[right]['requirements']['entry_state']))
    unit_of = {sid: i for i, u in enumerate(b['units']) for sid in u['shot_ids']}
    cross_refs = [r['shot_id'] for r in combined['reference_assessments']
                  if any(unit_of[sid] != unit_of[r['shot_id']] for sid in r.get('basis_shot_ids', []) if sid in unit_of)]
    risks = [r['shot_id'] for r in combined['shot_reviews'] if r['verdict'] != 'PASS']
    draft = dict(group_id=ctx['group_id'], version=ctx['version'], video_sha256=ctx['video_sha256'],
                 context_fingerprint=ctx['context_fingerprint'], grouping_checked=False,
                 checks={k: 'uncertain' for k in ('shot', 'continuity', 'story')},
                 coverage=dict(shot_ids=ids, mapping_verified=False, limitations=limitations),
                 boundary_checks=[], **combined)
    return p, b, dict(review=draft, task_hashes=hashes, boundary_audit_required=boundaries,
                     cross_reference_audit_required=cross_refs, dispute_shot_ids=risks,
                     max_nonboundary_rechecks=MAX_DISPUTES, draft_only=True)


def assemble(project, directory, output):
    core.require(Path(output).resolve() != Path(project).resolve() and
                 not Path(output).resolve().is_relative_to(Path(directory).resolve()),
                 'collected output must be outside the frozen bundle and project')
    with evidence_operation():
        _, _, result = collect(project, directory)
    core.save(output, result)
    return result


def audit_final(b, collected, final, audit):
    for field in ('group_id', 'version', 'video_sha256', 'context_fingerprint'):
        core.require(final.get(field) == b['context'][field], 'final review must use the frozen group context')
    core.require(audit.get('task_hashes') == collected['task_hashes'], 'task drafts changed after coordination')
    ids = [s['shot_id'] for s in b['context']['shots']]
    boundaries = collected['boundary_audit_required']
    rows = audit.get('boundaries', [])
    core.require([r.get('shot_ids') for r in rows] == [r['shot_ids'] for r in boundaries], 'boundary audit incomplete')
    shot_reviews = {r['shot_id']: r for r in final['shot_reviews']}
    for row, expected in zip(rows, boundaries):
        core.require(row.get('exit_state') == expected['exit_state'] and row.get('entry_state') == expected['entry_state'],
                     'boundary state must use frozen computed state')
        for field in ('visual_reason', 'state_reason'):
            core.require(isinstance(row.get(field), str) and row[field].strip(), 'visual and state boundary reasons required')
        core.require(row.get('verdict') in ('PASS', 'FAIL', 'uncertain'), 'boundary verdict required')
        if row['verdict'] != 'PASS':
            core.require(final['checks']['continuity'] == row['verdict'] or final['checks']['continuity'] == 'FAIL',
                         'boundary problem cannot be marked globally passed')
            affected = row.get('affected_shot_ids', [])
            core.require(affected and set(affected) <= set(row['shot_ids']) and
                         all(shot_reviews[s]['verdict'] in ('FAIL', 'uncertain', 'absent') for s in affected),
                         'boundary problem must remain localized')
    edge = {sid for row in boundaries for sid in row['shot_ids']}
    rechecked = audit.get('rechecked_shot_ids', [])
    deferred = audit.get('deferred_shot_ids', [])
    accepted = audit.get('accepted_shot_ids', [])
    core.require(len(rechecked) == len(set(rechecked)) and set(rechecked) <= set(ids), 'invalid recheck list')
    core.require(len(set(rechecked) - edge) <= MAX_DISPUTES, 'nonboundary dispute recheck cap exceeded')
    core.require(set(deferred) <= set(ids) - set(rechecked), 'invalid deferred list')
    core.require(set(accepted) <= set(ids) - set(rechecked) - set(deferred), 'invalid accepted list')
    originals = {r['shot_id']: r for r in collected['review']['shot_reviews']}
    for sid in accepted:
        core.require(shot_reviews[sid] == originals[sid], 'accepted finding must remain unchanged')
    for sid, original in originals.items():
        if shot_reviews.get(sid) != original and sid not in edge:
            core.require(sid in rechecked or sid in deferred, 'changed shot must be rechecked or deferred')
    for sid in deferred:
        core.require(shot_reviews[sid]['verdict'] == 'uncertain' and shot_reviews[sid].get('followup'),
                     'deferred dispute must remain uncertain with followup')
    core.require(set(collected['dispute_shot_ids']) <= edge | set(rechecked) | set(deferred) | set(accepted),
                 'dispute must be checked or explicitly deferred')
    cross = audit.get('cross_references', [])
    unit_of = {sid: i for i, u in enumerate(b['units']) for sid in u['shot_ids']}
    cross_ids = set(collected['cross_reference_audit_required'])
    for row in final['reference_assessments']:
        if any(unit_of.get(sid) != unit_of.get(row['shot_id']) for sid in row.get('basis_shot_ids', [])):
            cross_ids.add(row['shot_id'])
    core.require([r.get('shot_id') for r in cross] == [sid for sid in ids if sid in cross_ids] and
                 all(isinstance(r.get('reason'), str) and r['reason'].strip() for r in cross),
                 'cross-unit reference audit incomplete')
    # Any discarded or edited worker conclusion needs a traceable, explicit resolution.
    resolutions = audit.get('resolutions', [])
    acknowledged = {r.get('record_hash') for r in resolutions
                    if isinstance(r.get('reason'), str) and r['reason'].strip()}
    for field in ROWS:
        remaining = [core.digest(r) for r in final.get(field, [])]
        for record in collected['review'].get(field, []):
            key = core.digest(record)
            if key in remaining:
                remaining.remove(key)
            else:
                core.require(key in acknowledged, 'worker finding changed/dropped without resolution')
    for limitation in collected['review']['coverage']['limitations']:
        core.require(limitation in final['coverage']['limitations'] or core.digest(limitation) in acknowledged,
                     'worker limitation dropped without resolution')


def commit(project, directory, review_file, audit_file):
    """Single writer; no worker writes project state, and no API is called."""
    project = Path(project).resolve()
    with core.locked(project):
        with evidence_operation():
            p, b, collected = collect(project, directory)
            final, audit = core.read(review_file), core.read(audit_file)
            audit_final(b, collected, final, audit)
            core.record_review(p, project, final)
            p['reviews'][-1]['parallel_audit'] = dict(bundle_fingerprint=b['fingerprint'], **audit)
        # Exit the evidence transaction before the deliberate project mutation.
        core.save(project, p)
    return p['reviews'][-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('project'); p.add_argument('group'); p.add_argument('units'); p.add_argument('output')
    p = sub.add_parser('assemble')
    p.add_argument('project'); p.add_argument('bundle'); p.add_argument('output')
    p = sub.add_parser('commit')
    p.add_argument('project'); p.add_argument('bundle'); p.add_argument('review'); p.add_argument('audit')
    a = parser.parse_args()
    if a.command == 'prepare':
        result = prepare(a.project, a.group, core.read(a.units), a.output)
        print(result['mode'], len(result['tasks']))
    elif a.command == 'assemble':
        assemble(a.project, a.bundle, a.output)
        print('draft only; coordinator review required')
    else:
        result = commit(a.project, a.bundle, a.review, a.audit)
        print(result['verdict'])


if __name__ == '__main__':
    main()
