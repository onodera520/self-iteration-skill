"""Image-error thresholds, frozen review delivery and source-bound prompt export."""
from __future__ import annotations
import argparse
import copy
from decimal import Decimal
from pathlib import Path
import previs as core
import planner
import repair_prompt
import repair_reference

_CURRENT_REFERENCE = object()
_CURRENT_PLAN = object()
POLICY = 3
PREVIS_DIRECTIVE = '严格按照分镜脚本生成一段快速切镜的视频，每个分镜不需要很大的动作幅度。没有台词，没有音乐，不要出现字幕。每个分镜硬切转场。'
DECISION_STATE = ('fingerprint',)


def baseline(p):
    """Call during initial extraction; script is original text, never a synopsis."""
    rows = [dict(shot_id=s['id'], text=s['script'], design=s.get('shot_design') or s.get('shot_size') or
                 '按原脚本，未指定的机位与运镜不补设') for s in p['shots']]
    core.require(all(r['text'] and r['text'] in p['source_script'] for r in rows),
                 'Each shot script must be an exact excerpt of source_script; recover original text first')
    core.require(all(isinstance(r['design'], str) and r['design'].strip() for r in rows), 'Shot design text required')
    formats = p.get('video_format_requirements', [])
    core.require(isinstance(formats, list) and all(isinstance(x, str) and x.strip() and x in p['source_script'] for x in formats),
                 'Global format requirements must quote the original script, not introduce new requirements')
    value = dict(source_script=p['source_script'], shots=rows, format_requirements=formats)
    previous = p.get('repair_baseline')
    if previous:
        core.require(previous == value, 'Original script baseline changed; do not rewrite a repair lineage')
    else:
        p['repair_baseline'] = copy.deepcopy(value)
    return value


def validate_assessments(p, r):
    """Optional review extension; mandatory before a repair-prompt decision."""
    rows = r.get('repair_assessments', [])
    problems = {v['shot_id']: v for v in r['shot_reviews'] if v['verdict'] == 'FAIL'}
    core.require(len(rows) == len(problems) and {a.get('shot_id') for a in rows} == set(problems),
                 'repair_assessments must cover each confirmed FAIL once')
    shots = {s['id']: s for s in p['shots']}
    issues = {i['id']: i for i in r['issues']}
    from repair_readiness import diagnose_damage
    for a in rows:
        sid = a['shot_id']
        core.require(type(a.get('critical')) is bool and type(a.get('affects_story')) is bool,
                     'Explicit critical and affects_story judgments required')
        quote = a.get('script_quote', '')
        core.require(isinstance(quote, str) and quote.strip() and quote in shots[sid]['script'],
                     'repair script_quote must be an exact same-shot script excerpt')
        refs = a.get('issue_ids', [])
        core.require(refs and len(refs) == len(set(refs)) and
                     all(i in issues and sid in issues[i]['shot_ids'] for i in refs),
                     'Repair needs same-shot issue references')
        core.require(isinstance(a.get('impact'), str) and a['impact'].strip(), 'Specific narrative impact required')
        core.require(isinstance(a.get('correction'), str) and a['correction'].strip() and
                     a.get('preserves_script') is True, 'Script-preserving correction required')
        core.require(not a['critical'] or a['affects_story'], 'Critical issue must affect narrative')
        if a['critical']:
            core.require(a.get('critical_kind') in ('missing_key_node', 'wrong_actor', 'broken_causality',
                         'wrong_transfer_result', 'explicit_key_requirement'), 'Concrete critical issue kind required')
        core.require(any(e['shot_id'] == sid and e['sha256'] in problems[sid].get('evidence_sha256', [])
                         for e in r['evidence']), 'Repair FAIL needs the same-shot original image')
        diagnose_damage(a, r, path='repair_assessments[' + sid + ']').finish()


def threshold(total, eligible, critical, severe_visual_damage=()):
    ids = list(dict.fromkeys(eligible))
    keys = list(dict.fromkeys(critical))
    damaged = list(dict.fromkeys(severe_visual_damage))
    core.require(type(total) is int and total > 0 and len(ids) <= total and
                 set(keys) <= set(ids) and set(damaged) <= set(ids), 'Invalid repair counts')
    ratio = Decimal(len(ids)) / Decimal(total)
    critical_trigger = bool(keys)
    damage_trigger = bool(damaged)
    cumulative = len(ids) >= 2 and ratio >= Decimal('0.2')
    return dict(triggered=critical_trigger or damage_trigger or cumulative,
                error_count=len(ids), total=total, ratio=float(ratio), critical_shot_ids=keys,
                severe_visual_damage_shot_ids=damaged,
                problem_shot_ids=ids,
                trigger=('critical' if critical_trigger else 'severe_visual_damage' if damage_trigger
                         else 'cumulative' if cumulative else 'below_threshold'))


def binding(p, project, gid):
    g = core.group(p, gid)
    r = core.review_current(p, project, gid)
    a = planner.current_aggregation(p, project)
    core.require(r and a, 'Current group review and final aggregation required')
    b = baseline(p)
    assets = [dict(id=x['id'], path=str(core.resolve(project, x['path'])), sha256=core.sha(core.resolve(project, x['path'])))
              for x in p['assets']]
    source = dict(source_kind='provided', source_fingerprint=r['source_fingerprint'])
    return dict(policy=POLICY, source_group_id=gid, version=g['version'], **source,
                review_fingerprint=core.digest(r),
                context_fingerprint=r['context_fingerprint'], aggregation_fingerprint=core.digest(a),
                script_fingerprint=core.digest(b), assets=assets,
                style_fingerprint=core.digest(p.get('repair_asset_style')),
                group_fingerprint=core.group_fingerprint(p, project, g))


def decide(p, project, gid):
    bound = binding(p, project, gid)
    review = core.review_current(p, project, gid)
    validate_assessments(p, review)
    assessments = {a['shot_id']: a for a in review.get('repair_assessments', [])}
    eligible = [v['shot_id'] for v in review['shot_reviews'] if v['verdict'] == 'FAIL']
    critical = [sid for sid in eligible if assessments[sid]['critical']]
    damaged = [sid for sid in eligible if 'severe_visual_damage' in assessments[sid]]
    result = dict(binding=bound, **threshold(len(core.shots(p, core.group(p, gid))), eligible, critical,
                  severe_visual_damage=damaged), allowed_correction_shot_ids=eligible,
                  assessments=list(assessments.values()), review_verdict=review['verdict'])
    result['fingerprint'] = core.digest({k: v for k, v in result.items() if k not in DECISION_STATE})
    p.setdefault('repair_decisions', {})[gid] = result
    return result


def current_decision(p, project, gid):
    d = p.get('repair_decisions', {}).get(gid)
    core.require(d and d['binding'] == binding(p, project, gid), 'Repair decision stale; re-evaluate changed inputs')
    core.require(d['fingerprint'] == core.digest({k: v for k, v in d.items() if k not in DECISION_STATE}),
                 'Repair decision was modified')
    return d


def refresh_prompt_style(p, project, gid):
    """Prepare may refresh style-only bindings; changed review evidence still stops.

    Style is supplied after the threshold is known. Updating that preparation
    data does not change image judgments or the set of allowed corrections.
    Legacy plan finish never refreshes. The one-work finish may refresh only
    after verifying its complete pre-preparation input fingerprint.
    """
    d = p.get('repair_decisions', {}).get(gid)
    if not d:
        return False
    core.require(d.get('fingerprint') == core.digest({k: v for k, v in d.items() if k not in DECISION_STATE}),
                 'Repair decision was modified')
    fresh = binding(p, project, gid)
    if d['binding'] == fresh:
        return False
    core.require({k: v for k, v in d['binding'].items() if k != 'style_fingerprint'} ==
                 {k: v for k, v in fresh.items() if k != 'style_fingerprint'},
                 'Repair decision stale; re-evaluate changed inputs')
    decide(p, project, gid)
    return True


def asset_style(p, assets):
    """Agent supplies grounded observations once; tool binds them to original assets."""
    from validation import Report, style_shape
    report = Report()
    style_shape(p, report)
    report.finish()
    profile = p.get('repair_asset_style', {})
    rows = profile.get('assets', [])
    core.require(isinstance(rows, list) and len(rows) == len(assets) and
                 [r.get('asset_id') for r in rows] == [a['id'] for a in assets],
                 'Asset style analysis must cover the original assets in order')
    for row, asset in zip(rows, assets):
        core.require(row.get('sha256') == asset['sha256'], 'Asset style evidence is stale')
        facts = row.get('visible_style_facts')
        core.require(isinstance(facts, list) and facts and all(isinstance(f, str) and f.strip() for f in facts),
                     'Visible asset style facts required; do not infer style from the failed reference image')
        core.require(isinstance(row.get('guidance'), str) and row['guidance'].strip(), 'Grounded asset style guidance required')
    core.require(profile.get('preserves_story') is True, 'Style guidance must preserve script and narrative-first tolerance')
    return profile


def _compose_prompt(p, project, gid, version, input_aspect=False, reference_snapshot=_CURRENT_REFERENCE,
                    stored_decision=None, plan_snapshot=_CURRENT_PLAN):
    if version == 6:
        import repair_quality
        source = _compose_prompt(p, project, gid, 5, input_aspect=input_aspect,
                                 reference_snapshot=reference_snapshot, stored_decision=stored_decision)
        plan = p.get('repair_prompt_plans', {}).get(gid) if plan_snapshot is _CURRENT_PLAN else plan_snapshot
        return repair_quality.compile_request(plan, source, p)
    core.require(version == 5, 'Only current source and audited prompt formats are supported')
    d = current_decision(p, project, gid) if stored_decision is None else stored_decision
    core.require(d['triggered'], 'Repair threshold not reached')
    preparation_errors = []

    def prepare_value(fn):
        try:
            return fn()
        except (ValueError, OSError, UnicodeError) as exc:
            preparation_errors.append(str(exc))
            return None

    if (stored_decision is None and reference_snapshot is _CURRENT_REFERENCE
            and gid in p.get('deferred_storyboard_prompts', {})):
        from prepare_storyboards import load_original_prompt
        prepare_value(lambda: load_original_prompt(p, project, gid))
    from requirements import contexts
    resolved = contexts(p)
    original = {s['shot_id']: s for s in baseline(p)['shots']}
    assessment = {s['shot_id']: s for s in d['assessments']}
    ss = core.shots(p, core.group(p, gid))
    views = repair_prompt.input_views(ss, original, resolved,
        {s['id']: i for i, s in enumerate(p['shots'], 1)})
    visual = repair_prompt.VisualOnly(p.get('repair_visual_adaptations', {}))
    reference, guidance = None, {}
    reference = repair_reference.current(p, gid) if reference_snapshot is _CURRENT_REFERENCE else reference_snapshot
    guidance = prepare_value(lambda: repair_reference.validate(reference, d['binding'], original,
                             [s['id'] for s in ss])) or {}
    def render_text(path, text):
        return visual.text(path, text) if visual else text
    assets = d['binding']['assets']
    style = prepare_value(lambda: asset_style(p, assets))
    descriptions = {a['id']: a.get('description', '') for a in p['assets']}
    from storyboard_inputs import source_aspect
    shape = prepare_value(lambda: source_aspect(p, project, d['binding']['source_fingerprint'])) if input_aspect else None
    aspect = shape['aspect_ratio'] if shape else p['config'].get('aspect_ratio', '')
    lines = ['按下列完整脚本生成视频，保留镜号、镜序、剧情及必要切镜。',
             '资产图顺序：' + '；'.join(f"图{i}: {a['id']} {render_text('asset.' + a['id'] + '.description', descriptions[a['id']])}" for i, a in enumerate(assets, 1)),
             '画幅：' + str(aspect)]
    if visual:
        lines.insert(0, repair_prompt.SILENT_DIRECTIVE)
    if reference is not None:
        lines.append('原提示词参考仅补充与本镜脚本相容的视觉细节；剧情、行动主体、镜序和结果以本镜正文及约束为准，生成时长、画幅与固定预演要求以本次请求为准。')
    format_requirements = [render_text(f'format.{i}', text) for i, text in enumerate(baseline(p)['format_requirements'])]
    lines.extend(format_requirements)
    if shape:
        lines.append(f'本次生成采用画幅 {aspect}，保留全部分镜图原图。')
    lines += ['镜号对应：' + '；'.join(f"镜头{i}={s['id']}" for i, s in enumerate(ss, 1)),
              '返修快速预演每镜固定1.0秒，此处生成时长安排不改写原始脚本文字。']
    blocks, corrections = [], []
    for i, s in enumerate(ss, 1):
        block = dict(shot_id=s['id'], text=original[s['id']]['text'], design=original[s['id']]['design'], duration=1.0)
        if views:
            block.update(views[s['id']])
        if s['id'] in d['allowed_correction_shot_ids']:
            block['correction'] = assessment[s['id']]['correction']
            corrections.append((i, s['id']))
        # Script-derived keyframe requirements only; they add no new story content.
        requirement = resolved.get(s['id']) or {}
        core.require(not requirement or requirement['ready'],
                     'Resolve provisional shot requirements before repair: ' + s['id'])
        must = [x for x in (requirement.get('must_have') or []) if x]
        must_not = [x for x in (requirement.get('must_not_have') or []) if x]
        changes = [f"{c['entity']}.{c['attribute']} 由 {c['before']} 变为 {c['after']}"
                   for c in s.get('state_changes', []) if c.get('authorized') and c.get('critical')]
        if must:
            block['must_have'] = must
        if must_not:
            block['must_not_have'] = must_not
        if (must or must_not):
            frame = requirement['keyframe']
            block['keyframe_target'] = dict(phase=frame['phase'], description=frame['description'])
        if changes:
            block['critical_changes'] = changes
        if visual:
            sid = s['id']
            for name in ('design', 'generation_text', 'correction'):
                if name in block:
                    block[name] = render_text(f'{sid}.{name}', block[name])
            for name in ('must_have', 'must_not_have', 'critical_changes'):
                if name in block:
                    block[name] = [render_text(f'{sid}.{name}.{j}', value) for j, value in enumerate(block[name])]
            if 'keyframe_target' in block:
                target = block['keyframe_target']
                target['description'] = render_text(f'{sid}.keyframe_target.description', target['description'])
            must, must_not, changes = (block.get(name, []) for name in ('must_have', 'must_not_have', 'critical_changes'))
        blocks.append(block)
        duration_tag = '生成时长' if views else '时长'
        line = f"镜头{i},【{duration_tag}】1.0s。【镜头设计】{block['design']}。【镜头内容】{block.get('generation_text', block['text'])}"
        if 'keyframe_target' in block:
            target = block['keyframe_target']
            phase = {'entry': '起态', 'action': '动作中', 'exit': '终态'}[target['phase']]
            line += f"【目标静帧】{phase}：{target['description']}。以下必须/不得出现仅约束该时刻，完整动作仍按原脚本先后呈现。"
        if must:
            line += '【本镜必须出现】' + '；'.join(must)
        if must_not:
            line += '【本镜不得出现】' + '；'.join(must_not)
        if changes:
            line += '【本镜关键变化】' + '；'.join(changes)
        if 'correction' in block:
            line += '【仅本镜返修补充】' + block['correction']
        if s['id'] in guidance:
            block['input_prompt_guidance'] = guidance[s['id']]
            line += '【原提示词参考】' + '；'.join(guidance[s['id']])
        lines += [line]
    lines += ['\n【固定预演要求】', PREVIS_DIRECTIVE,
              ('小幅运动仍须清楚呈现原脚本的关键动作和结果，保留所有镜头与硬切。' if visual else
               '小幅运动仍须清楚呈现原脚本的关键动作和结果。对白、OS、VO仅用于理解剧情，不输出声音或屏幕文字。')]
    if corrections:
        lines += ['【必须独立成镜的镜头】',
                  '以下为本次需修正的镜头，必须各自单独成一个硬切镜头，不得省略、不得与相邻镜合并：'
                  + '、'.join(f"镜头{i}={sid}" for i, sid in corrections)]
    lines += ['【原始资产风格】', '以下风格仅约束视觉表现，不改变原脚本人物关系、动作、场景与时空；资产展示背景不替代剧情背景。']
    if style:
        lines.extend(f"图{i}（{row['asset_id']}）：{render_text('asset.' + row['asset_id'] + '.guidance', row['guidance'])}" for i, row in enumerate(style['assets'], 1))
    if visual:
        preparation_errors.extend(visual.errors)
        lines.append(repair_prompt.SILENT_DIRECTIVE)
    if preparation_errors:
        # Internal work data only: no guessed style or automatic semantic approval.
        inputs = dict(input_preparation_version=1, source_group_id=gid,
            visual_story_rule=repair_prompt.VISUAL_STORY_RULE,
            errors=preparation_errors,
            source_fingerprint=d['binding']['source_fingerprint'],
            script_fingerprint=d['binding']['script_fingerprint'],
            assets=[dict(a, description=descriptions[a['id']]) for a in assets],
            repair_asset_style=copy.deepcopy(p.get('repair_asset_style')) or dict(preserves_story=False,
                assets=[dict(asset_id=a['id'], sha256=a['sha256'], visible_style_facts=[], guidance='') for a in assets]),
            visual_sources=visual.source_fields,
            repair_visual_adaptations=copy.deepcopy(p.get('repair_visual_adaptations', {})))
        if reference is not None:
            inputs['original_prompt'] = copy.deepcopy(reference)
        if gid in p.get('deferred_storyboard_prompts', {}):
            inputs['deferred_original_prompt'] = copy.deepcopy(p['deferred_storyboard_prompts'][gid])
        if input_aspect:
            from storyboard_inputs import inputs as image_inputs
            inputs['input_ratios'] = list(dict.fromkeys(row['aspect_ratio'] for row in image_inputs(p, project)))
            inputs['storyboard_target_aspect'] = p.get('storyboard_target_aspect')
            if shape:
                inputs['input_aspect'] = copy.deepcopy(shape)
        # A complete reading context lets one submission resolve preparation and
        # compile the batch without another prepare/read/fill round.
        inputs['prompt_context'] = dict(source_group_id=gid, decision_fingerprint=d['fingerprint'],
            binding=copy.deepcopy(d['binding']), blocks=copy.deepcopy(blocks), assets=copy.deepcopy(assets),
            asset_style=copy.deepcopy(style) if style else dict(assets=[dict(asset_id=a['id'],
                visible_style_facts=[], guidance='') for a in assets]),
            previs_directive=PREVIS_DIRECTIVE, duration_seconds=float(len(ss)), aspect_ratio=aspect,
            input_aspect=copy.deepcopy(shape), format_requirements=copy.deepcopy(format_requirements),
            visual_adaptations=copy.deepcopy(visual.used), source_prompt_reference=copy.deepcopy(reference))
        raise repair_prompt.PreparationError(preparation_errors, inputs)
    seconds = len(ss)
    result = dict(source_group_id=gid,
                decision_fingerprint=d['fingerprint'], binding=copy.deepcopy(d['binding']),
                prompt='\n'.join(lines), blocks=blocks, assets=copy.deepcopy(assets),
                asset_style=copy.deepcopy(style), previs_directive=PREVIS_DIRECTIVE,
                duration_seconds=float(seconds), aspect_ratio=aspect)
    if shape:
        result['input_aspect'] = shape
    if reference is not None:
        result['source_prompt_reference'] = copy.deepcopy(reference)
    result['format_requirements'] = format_requirements
    result['prompt_version'] = version
    if visual:
        result['visual_adaptations'] = visual.used
    result['prompt_fingerprint'] = core.digest(dict(version=version, prompt=result['prompt'], blocks=blocks))
    repair_prompt.validate(result, [s['id'] for s in ss])
    return result


def make_prompt(p, project, gid):
    return _compose_prompt(p, project, gid, repair_prompt.VERSION, input_aspect=True)


def save_prompt(path, request, explicit=False):
    """Never overwrite an older request when previewing a new prompt version."""
    path = Path(path)
    if path.exists() and core.read(path) != request:
        core.require(not explicit, 'Prompt output already exists with different content; choose a new output path')
        path = path.with_name(f'{path.stem}-v{request["prompt_version"]}-{core.digest(request)[:12]}{path.suffix}')
    core.require(not path.exists() or core.read(path) == request, 'Versioned prompt output already differs')
    if not path.exists():
        core.save(path, request)
    return path


def snapshot(p, project, out, stage='original'):
    import storyboard
    core.require(stage == 'original', 'Only the current image review can be delivered')
    core.require(planner.current_aggregation(p, project), 'Current aggregation required before delivery')
    core.require(all(core.review_current(p, project, g['id']) for g in p['groups']), 'All source/boundary reviews must be current')
    out = Path(out).resolve()
    records = p.setdefault('repair_deliveries', {})
    if stage in records:
        record = records[stage]
        core.require(all(Path(f).is_file() and core.sha(Path(f)) == h for f, h in record['files'].items()), 'Immutable delivery changed')
        return record['path']
    core.require(not out.exists() or not any(out.iterdir()), 'Use an empty, separate delivery directory')
    path = Path(storyboard.render_aggregation(p, project, out))
    dest = out / '01_分镜图审查.md'
    path.rename(dest)
    records[stage] = dict(path=str(dest), files={str(f): core.sha(f) for f in out.rglob('*') if f.is_file()},
                          aggregation_fingerprint=core.digest(p['aggregation']), table_count=1,
                          delivery_format_version=3, source_project=str(Path(project).resolve()))
    return str(dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='action', required=True)
    for name in ('decide', 'export-prompt'):
        q = sub.add_parser(name)
        q.add_argument('project'); q.add_argument('group')
        if name == 'export-prompt': q.add_argument('output')
    args = ap.parse_args()
    with core.locked(args.project):
        p = core.read(args.project)
        if args.action == 'decide': result = decide(p, args.project, args.group)
        else:
            from repair_export import export_prompt
            result = export_prompt(p, args.project, args.group, args.output)
        core.save(args.project, p)
    import json
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
