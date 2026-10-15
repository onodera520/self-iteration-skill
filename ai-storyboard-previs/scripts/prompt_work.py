"""One source-bound submission for preparation, grouped review and prompt export."""
import copy

import previs as core
import repair_prompt
from evidence_runtime import evidence_operation, verified_read


@verified_read
def packet(p, project, gid, source=None, inputs=None):
    import repair_cycle as repair
    import repair_quality as quality
    import repair_reference
    if source is None and inputs is None:
        try:
            source = quality.source_request(p, project, gid)
        except repair_prompt.PreparationError as exc:
            inputs = exc.inputs
    context = source if source is not None else inputs['prompt_context']
    decision = repair.current_decision(p, project, gid)
    preparation = {}
    try:
        repair.asset_style(p, decision['binding']['assets'])
    except ValueError:
        preparation['assets'] = {a['id']: dict(visible_style_facts=[], guidance='')
                                 for a in decision['binding']['assets']}
    visual_text = {}
    for path, field in (inputs or {}).get('visual_sources', {}).items():
        visual = repair_prompt.VisualOnly(p.get('repair_visual_adaptations', {}))
        visual.text(path, field['source_text'])
        if visual.errors:
            visual_text[path] = ''
    if visual_text:
        preparation.update(visual_text=visual_text, visual_basis='')
    reference = repair_reference.current(p, gid)
    if reference is not None:
        originals = {s['shot_id']: s for s in repair.baseline(p)['shots']}
        try:
            repair_reference.validate(reference, decision['binding'], originals,
                                      [b['shot_id'] for b in context['blocks']])
        except ValueError:
            preparation['reference'] = dict(compatibility_reason='', selections=[], excluded=[])
    fingerprint = core.digest(dict(context=context,
        style=p.get('repair_asset_style'), adaptations=p.get('repair_visual_adaptations'),
        original_prompt=reference, deferred=p.get('deferred_storyboard_prompts', {}).get(gid)))
    plan = quality.batch_template(context)
    del plan['source_fingerprint']  # The tool binds the prepared request after the submission is checked.
    work = dict(work_version=1, input_fingerprint=fingerprint, preparation=preparation, plan=plan)
    view = quality.reading_view(context, p)
    view.pop('source_fingerprint')
    view['focus_shot_ids'] = view.pop('required_note_shot_ids')
    for block in view['blocks']:
        block['sources'] = {','.join(item['paths']): item['text'] for item in block['sources']}
    view['check_groups'] = quality.CHECK_GROUPS
    view['check_rules'] = dict(
        story='核对全部原镜、已有可见动作与结果、先后阶段及必要硬切；对白内容与含义不检查，不新增事件。',
        subjects='核对行动者、对象、道具归属和状态、跨镜位置与承接，不用代词造成错配。',
        visual='核对关键关系可读、原资产风格及场景一致，合并重复与过宽否定，全部独立来源仍保留。',
        generation='每镜一秒、静音、无说话口型或新增文字，画幅按工具结果；不能删除必要动作或改次序来凑时长。')
    asset_paths = {a['id']: a['path'] for a in context['assets']}
    styles = {a['asset_id']: a for a in view.pop('asset_style')}
    for asset in view['assets']:
        asset['path'] = asset_paths[asset['id']]
        asset.update({key: value for key, value in styles[asset['id']].items()
                      if key != 'asset_id' and value})
    view['preparation_required'] = list(preparation)
    if visual_text:
        view['visual_fields'] = {path: dict(signals=field['signals']) for path, field in inputs['visual_sources'].items()
                                 if path in visual_text}
    if reference is not None and 'reference' in preparation:
        view['original_prompt'] = reference['source']['text']
        view['reference_instructions'] = repair_reference.editing_guide()
    if inputs and inputs.get('deferred_original_prompt'):
        view['unavailable_original_prompt'] = inputs['deferred_original_prompt']
    view['submission_template'] = copy.deepcopy(work)
    view['next_action'] = ('Read this batch once. Copy submission_template, fill only preparation and plan, '
        'save it to PROMPT.work.json, then finish. For original-prompt selections/exclusions use reference_instructions. '
        'Four grouped judgments cover all nine checks. Notes are optional for real ambiguities; '
        'do not copy each edit or unchanged source into a second explanation. Never approve blank judgments.')
    return dict(work=work, view=view)


def preflight_reference(p, gid, work):
    """Reject incomplete selections before rebuilding image evidence or writing output."""
    preparation = work.get('preparation') if isinstance(work, dict) else None
    if not isinstance(preparation, dict) or 'reference' not in preparation:
        return
    import repair_cycle as repair
    import repair_reference
    try:
        fields = preparation['reference']
        core.require(isinstance(fields, dict) and set(fields) == {'compatibility_reason', 'selections', 'excluded'},
                     'reference 只含 compatibility_reason、selections、excluded')
        source = p.get('source_storyboard_prompts', {}).get(gid)
        core.require(isinstance(source, dict), '尚无已登记的原提示词；请核对当前 preparation 字段')
        originals = {s['shot_id']: s for s in repair.baseline(p)['shots']}
        group = next((g for g in p['groups'] if g['id'] == gid), None)
        core.require(group is not None, '原提示词筛选须引用当前来源组')
        repair_reference.validate_fields(source['text'], fields, originals, group['shot_ids'])
    except ValueError as exc:
        raise ValueError('preparation.reference 预检未通过。按现有 PROMPT.work.view.json 的 '
                         'reference_instructions 修正下列字段后直接 finish，无需重做审查或搜索源码。\n' + str(exc)) from None


def _apply(p, gid, work, current, inputs):
    """Bind agent text to tool-owned hashes; never accept arbitrary project patches."""
    core.require(work.get('work_version') == 1 and type(work.get('work_version')) is int,
                 'Unsupported prompt work version')
    core.require(work.get('input_fingerprint') == current['input_fingerprint'],
                 'Prompt work stale; regenerate the packet against current sources')
    prep, expected = work.get('preparation'), current['preparation']
    core.require(isinstance(prep, dict) and set(prep) == set(expected), 'Complete only the listed prompt preparation fields')
    plan = work.get('plan')
    core.require(isinstance(plan, dict) and plan.get('plan_version') == 3
                 and plan.get('preserves_story') is True,
                 'Explicit visible-story review required in the grouped plan')
    if 'assets' in expected:
        assets = p['repair_decisions'][gid]['binding']['assets']
        rows = prep['assets']
        core.require(isinstance(rows, dict) and set(rows) == {a['id'] for a in assets},
                     'Asset style preparation must cover current original assets exactly once')
        core.require(all(isinstance(row, dict) and set(row) == {'visible_style_facts', 'guidance'}
                         for row in rows.values()), 'Only grounded style facts and guidance may be supplied')
        p['repair_asset_style'] = dict(preserves_story=True, assets=[dict(asset_id=a['id'],
            sha256=a['sha256'], **copy.deepcopy(rows[a['id']])) for a in assets])
    if 'visual_text' in expected:
        texts, basis = prep['visual_text'], prep['visual_basis']
        core.require(isinstance(texts, dict) and set(texts) == set(expected['visual_text'])
                     and isinstance(basis, str) and basis.strip(), 'Complete the listed visual texts and one visible-story basis')
        adaptations = p.setdefault('repair_visual_adaptations', {})
        core.require(isinstance(adaptations, dict), 'repair_visual_adaptations must be an object')
        for path, text in texts.items():
            adaptations[path] = dict(source_sha256=inputs['visual_sources'][path]['source_sha256'],
                visual_text=text, preserves_story=True, story_basis=basis)
    if 'reference' in expected:
        reference = prep['reference']
        core.require(isinstance(reference, dict) and set(reference) == {'compatibility_reason', 'selections', 'excluded'},
                     'Complete original-prompt compatibility, selections and exclusions')
        source = p['source_storyboard_prompts'][gid]
        binding = p['repair_decisions'][gid]['binding']
        p.setdefault('repair_prompt_references', {})[gid] = dict(source_sha256=source['text_sha256'],
            source_fingerprint=source['source_fingerprint'], script_fingerprint=binding['script_fingerprint'],
            preserves_story=True, **copy.deepcopy(reference))


def finish(p, project, gid, work, output):
    """Validate the current packet, then prepare and export in one evidence cycle."""
    import repair_cycle as repair
    import repair_quality as quality
    from repair_export import check_output, _export_request
    working = copy.deepcopy(p)
    check_output(working, output)
    preflight_reference(working, gid, work)
    with evidence_operation():
        inputs = None
        try:
            source = quality.source_request(working, project, gid)
        except repair_prompt.PreparationError as exc:
            source, inputs = None, exc.inputs
        current = packet(working, project, gid, source=source, inputs=inputs)['work']
        _apply(working, gid, work, current, inputs)
        if source is None or current['preparation']:
            repair.refresh_prompt_style(working, project, gid)
            source = quality.source_request(working, project, gid)
        plan = copy.deepcopy(work['plan'])
        plan.update(source_fingerprint=core.digest(source), work_input_fingerprint=work['input_fingerprint'])
        request = quality.compile_request(plan, source, working)
    record = _export_request(working, project, gid, output, request)
    working.setdefault('repair_prompt_plans', {})[gid] = plan
    return record, working
