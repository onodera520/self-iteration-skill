"""Source-bound prompt compilation and batch audit; no media or network actions.

The agent supplies the semantic judgments. These gates check coverage records,
exact source/output bindings and unresolved work, not the truth of prose claims.
Compact plans retain audited source bodies and record only edits and exceptions.
"""
import argparse
import copy
from pathlib import Path

import previs as core
import repair_prompt

CHECKS = ('story_coverage', 'actors_and_targets', 'objects_and_states',
          'action_order_and_phases', 'spatial_continuity', 'visible_evidence',
          'assets_and_style', 'timing_and_density', 'conflicts_and_repetition')


def sources(block):
    """Every input contribution must have an explicit semantic disposition."""
    result = {name: block[name] for name in ('generation_text', 'correction') if block.get(name)}
    for name in ('input_prompt_guidance', 'critical_changes', 'must_have', 'must_not_have'):
        result.update({f'{name}.{i}': value for i, value in enumerate(block.get(name, []))})
    if block.get('keyframe_target'):
        result['keyframe_target.description'] = block['keyframe_target']['description']
    return result


def template(request):
    """Legacy detailed plan; keep saved version-6 requests reproducible."""
    return dict(source_fingerprint=core.digest(request), preserves_story=False,
                shots=[dict(shot_id=b['shot_id'], content='', key_event='',
                            visibility_basis='', timing=dict(status='pending', basis=''),
                            coverage=[dict(source_path=path, output_excerpt='', basis='')
                                      for path in sources(b)]) for b in request['blocks']],
                checks={name: dict(status='pending', reason='') for name in CHECKS},
                unresolved=[], model_risks=[])


def _normalized(text):
    return ' '.join(text.split()).rstrip('。；; ')


def attention_shots(request):
    """Flag supplemental semantics that are not already copied verbatim.

    This is a reading/recording aid, never a semantic approval. All source
    contributions still appear in the view and require whole-batch review.
    """
    result = []
    for block in request['blocks']:
        retained = '\n'.join(_normalized(value) for value in
                             [block['generation_text'], block['design'],
                              *block.get('must_have', []), *block.get('must_not_have', [])])
        extra = [value for path, value in sources(block).items()
                 if path != 'generation_text' and not path.startswith(('must_have.', 'must_not_have.'))]
        if any(_normalized(value) not in retained for value in extra):
            result.append(block['shot_id'])
    return result


def compact_template(request):
    return dict(plan_version=2, source_fingerprint=core.digest(request), preserves_story=False,
                checks_passed=False,
                reviewed_shot_ids=[], edits=[], notes={},
                checks={name: '' for name in CHECKS}, unresolved=[], model_risks=[])


def reading_view(request, p):
    """One complete semantic view, without the redundant rendered source prompt.

    Exact duplicate contributions share an entry, with all source paths kept.
    Full hashes and raw reference provenance remain in the source snapshot.
    """
    blocks = []
    for block in request['blocks']:
        grouped = {}
        for path, value in sources(block).items():
            grouped.setdefault(value, []).append(path)
        row = dict(shot_id=block['shot_id'], design=block['design'],
                   sources=[dict(paths=paths, text=value) for value, paths in grouped.items()])
        if block.get('text') != block['generation_text']:
            row['original_text'] = block['text']
        if block.get('keyframe_target'):
            row['target_phase'] = block['keyframe_target']['phase']
        blocks.append(row)
    descriptions = {a['id']: a.get('description', '') for a in p['assets']}
    adaptations = request.get('visual_adaptations', {})

    def visual(path, value):
        return adaptations.get(path, {}).get('visual_text', value)

    assets = [dict(id=a['id'], description=visual(f'asset.{a["id"]}.description', descriptions[a['id']]))
              for a in request['assets']]
    style = [dict(asset_id=row['asset_id'], visible_style_facts=row.get('visible_style_facts', []),
                  guidance=visual(f'asset.{row["asset_id"]}.guidance', row['guidance']))
             for row in request['asset_style']['assets']]
    return dict(source_fingerprint=core.digest(request),
                fixed=dict(seconds_per_shot=1, duration_seconds=request['duration_seconds'],
                           aspect_ratio=request['aspect_ratio'],
                           previs_directive=request['previs_directive'],
                           silent_directive=repair_prompt.SILENT_DIRECTIVE,
                           format_requirements=request.get('format_requirements', []),
                           independent_hard_cuts=True,
                           asset_background_is_not_story_background=True),
                assets=assets, asset_style=style, blocks=blocks,
                required_note_shot_ids=attention_shots(request))


def validate_compact(plan, request):
    errors = []

    def check(ok, message):
        if not ok:
            errors.append(message)

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    check(plan.get('source_fingerprint') == core.digest(request),
          'stale prompt-plan source_fingerprint; regenerate the batch source')
    check(plan.get('preserves_story') is True, 'prompt plan must explicitly preserve the frozen script')
    check(plan.get('checks_passed') is True, 'explicitly confirm all nine semantic checks passed')
    ids = [block['shot_id'] for block in request['blocks']]
    check(plan.get('reviewed_shot_ids') == ids,
          'reviewed_shot_ids must cover the complete source exactly once in original order')
    edits = plan.get('edits')
    edits = edits if isinstance(edits, list) else []
    check(isinstance(plan.get('edits'), list) and all(isinstance(row, dict) for row in edits),
          'compact edits must be a list of objects')
    edited = []
    for row in edits:
        if not isinstance(row, dict):
            continue
        sid, content = row.get('shot_id'), row.get('content')
        check(isinstance(sid, str) and sid in ids and sid not in edited,
              'compact edits must reference source shot IDs at most once')
        if isinstance(sid, str):
            edited.append(sid)
        check(nonempty(content), f'{sid}: compiled visual content required')
        if nonempty(content):
            check(not repair_prompt.speech_signals(content), f'{sid}: speech/audio/text in compiled content')
            check('【' not in content, f'{sid}: compiled content must not contain extra headers/internal labels')
    notes = plan.get('notes')
    notes = notes if isinstance(notes, dict) else {}
    required = set(attention_shots(request)) | set(edited)
    check(isinstance(plan.get('notes'), dict) and set(notes) <= set(ids) and
          all(nonempty(note) for note in notes.values()), 'notes must map source shot IDs to concrete resolutions')
    check(required <= set(notes), 'supplemental-source/edited shots need a resolution note: ' +
          ', '.join(sid for sid in ids if sid in required and sid not in notes))
    checks = plan.get('checks')
    checks = checks if isinstance(checks, dict) else {}
    check(set(checks) == set(CHECKS), 'complete the nine batch semantic checks')
    for name in CHECKS:
        check(nonempty(checks.get(name)), f'{name}: a concrete batch judgment is required')
    check(plan.get('unresolved') == [], 'resolve prompt conflicts before export; do not relabel them as model risks')
    risks = plan.get('model_risks')
    check(isinstance(risks, list) and all(nonempty(risk) for risk in risks),
          'model_risks must be a list of specific residual generation uncertainties')
    repair_prompt.finish(errors)


def validate(plan, request):
    if isinstance(plan, dict) and 'plan_version' in plan:
        core.require(type(plan['plan_version']) is int and plan['plan_version'] == 2,
                     'Unsupported prompt plan_version')
        return validate_compact(plan, request)
    errors = []

    def check(ok, message):
        if not ok:
            errors.append(message)

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    if not isinstance(plan, dict):
        raise ValueError('Complete one source-bound repair_prompt_plans batch before exporting a new prompt')
    check(plan.get('source_fingerprint') == core.digest(request), 'stale prompt-plan source_fingerprint; regenerate the batch source')
    check(plan.get('preserves_story') is True, 'prompt plan must explicitly preserve the frozen script')
    rows = plan.get('shots')
    rows = rows if isinstance(rows, list) else []
    ids = [b['shot_id'] for b in request['blocks']]
    check(all(isinstance(row, dict) for row in rows), 'prompt-plan shots must be objects')
    check([row.get('shot_id') for row in rows if isinstance(row, dict)] == ids,
          'prompt-plan shots must cover the complete source exactly once in original order')
    # Resolve by id after checking order so omissions cannot accidentally shift bindings.
    blocks = {block['shot_id']: block for block in request['blocks']}
    for row in rows:
        if not isinstance(row, dict) or row.get('shot_id') not in blocks:
            continue
        sid = row['shot_id']
        block = blocks[sid]
        content = row.get('content')
        check(nonempty(content), f'{sid}: compiled visual content required')
        if not nonempty(content):
            continue
        check(not repair_prompt.speech_signals(content), f'{sid}: speech/audio/text in compiled content')
        check(not any(tag in content for tag in repair_prompt.TAGS) and '【' not in content,
              f'{sid}: compiled content must not contain extra headers/internal labels')
        delivered_content = ' '.join(content.split())
        check(nonempty(row.get('key_event')) and row['key_event'] in delivered_content,
              f'{sid}: key_event must quote the visible event from compiled content')
        check(nonempty(row.get('visibility_basis')), f'{sid}: explain how the key relation/result is visible')
        timing = row.get('timing')
        check(isinstance(timing, dict) and timing.get('status') == 'feasible' and nonempty(timing.get('basis')),
              f'{sid}: unresolved one-second action budget; preserve all required phases or report the conflict')
        coverage = row.get('coverage')
        coverage = coverage if isinstance(coverage, list) else []
        expected = sources(block)
        paths = [item.get('source_path') for item in coverage if isinstance(item, dict)]
        check(all(isinstance(item, dict) for item in coverage) and len(paths) == len(expected) and
              all(isinstance(path, str) for path in paths) and set(paths) == set(expected),
              f'{sid}: every source contribution needs exactly one coverage record')
        visible_text = '\n'.join(' '.join(value.split()) for value in
                                 [content, block['design'], *block.get('must_have', []), *block.get('must_not_have', [])])
        for item in coverage:
            if not isinstance(item, dict):
                continue
            check(nonempty(item.get('output_excerpt')) and item['output_excerpt'] in visible_text,
                  f'{sid}.{item.get("source_path")}: exact excerpt from delivered text required')
            check(nonempty(item.get('basis')), f'{sid}.{item.get("source_path")}: source-preservation explanation required')
    checks = plan.get('checks')
    checks = checks if isinstance(checks, dict) else {}
    check(set(checks) == set(CHECKS), 'complete the nine batch semantic checks')
    for name in CHECKS:
        item = checks.get(name)
        check(isinstance(item, dict) and item.get('status') == 'pass' and nonempty(item.get('reason')),
              f'{name}: a resolved batch judgment with a concrete reason is required')
    check(plan.get('unresolved') == [], 'resolve prompt conflicts before export; do not relabel them as model risks')
    risks = plan.get('model_risks')
    check(isinstance(risks, list) and all(nonempty(risk) for risk in risks), 'model_risks must be a list of specific residual generation uncertainties')
    repair_prompt.finish(errors)


def compile_request(plan, source, p):
    validate(plan, source)
    result = copy.deepcopy(source)
    result['prompt_version'] = repair_prompt.VERSION
    result['prompt_plan'] = copy.deepcopy(plan)
    descriptions = {asset['id']: asset.get('description', '') for asset in p['assets']}
    result['asset_descriptions'] = [dict(id=asset['id'], description=descriptions[asset['id']])
                                    for asset in result['assets']]
    if plan.get('plan_version') == 2:
        edits = {row['shot_id']: row['content'] for row in plan['edits']}
        for block in result['blocks']:
            block['compiled_content'] = edits.get(block['shot_id'], block['generation_text'])
    else:
        for block, row in zip(result['blocks'], plan['shots']):
            block['compiled_content'] = row['content']
    # One canonical visual body per shot for both export and optional paid requests.
    from repair_export import render_prompt
    plain = render_prompt({}, result).strip()
    internal = plain.replace('【时长】1s。', '【生成时长】1.0s。')
    result['prompt'] = repair_prompt.SILENT_DIRECTIVE + '\n' + internal + '\n' + repair_prompt.SILENT_DIRECTIVE
    result['prompt_fingerprint'] = core.digest(dict(version=result['prompt_version'],
                                                   prompt=result['prompt'], blocks=result['blocks']))
    repair_prompt.validate(result, [block['shot_id'] for block in result['blocks']])
    return result


def source_request(p, project, gid):
    import repair_cycle
    return repair_cycle._compose_prompt(p, project, gid, 5, input_aspect=True)


def finish_plan(p, project, gid, plan, output):
    """Caller holds the project lock; build/validate once, then export/register.

    The supplied plan is untrusted. The source always comes from current project
    and evidence, never from an editable draft or the saved reading view.
    """
    from repair_export import _export_request
    request = compile_request(plan, source_request(p, project, gid), p)
    record = _export_request(p, project, gid, output, request)
    p.setdefault('repair_prompt_plans', {})[gid] = copy.deepcopy(plan)
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('prepare', 'check', 'finish'))
    ap.add_argument('project')
    ap.add_argument('group')
    ap.add_argument('plan_file')
    ap.add_argument('--apply', action='store_true', help='check and register the completed plan under the project lock')
    ap.add_argument('--detailed', action='store_true', help='prepare the legacy per-source-excerpt draft')
    ap.add_argument('--output', help='finish: separate user-facing Markdown output')
    args = ap.parse_args()
    core.require(args.action == 'check' or not args.apply, '--apply is only for check')
    core.require(args.action == 'prepare' or not args.detailed, '--detailed is only for prepare')
    core.require(bool(args.output) == (args.action == 'finish'), '--output is required only for finish')
    with core.locked(args.project):
        p = core.read(args.project)
        if args.action == 'finish':
            record = finish_plan(p, args.project, args.group, core.read(args.plan_file), args.output)
            core.save(args.project, p)
            print('Audited prompt exported: ' + record['path'])
            return
        request = source_request(p, args.project, args.group)
        if args.action == 'prepare':
            plan_file = Path(args.plan_file)
            source_file = plan_file.with_name(plan_file.stem + '.source.json')
            view_file = plan_file.with_name(plan_file.stem + '.view.json')
            core.require(not any(path.exists() for path in (plan_file, source_file, view_file)),
                         'use new internal draft/source paths')
            core.save(source_file, request)
            core.save(view_file, reading_view(request, p))
            core.save(plan_file, template(request) if args.detailed else compact_template(request))
            print(f'Batch prompt draft: {plan_file}\nReading view: {view_file}\nFull source: {source_file}')
        else:
            plan = core.read(args.plan_file)
            validate(plan, request)
            if args.apply:
                p.setdefault('repair_prompt_plans', {})[args.group] = plan
                core.save(args.project, p)
            print('Prompt-plan bindings and coverage records valid; semantic judgments remain the reviewer responsibility.')


if __name__ == '__main__':
    main()
