"""Batch prepare/review/freeze for user-paired images; no video tools or paid calls."""
from __future__ import annotations
import argparse
import copy
from pathlib import Path
from time import perf_counter

import previs as core
import storyboard_inputs as images
import storyboard_overviews as overviews
import agent_context
from evidence_runtime import evidence_operation
from review_timing import utc_now
from validation import Report, ValidationError, text, shot_path


CHECK_GROUPS = dict(content=('identity', 'scene', 'props'),
                    state=('key_state', 'continuity'), reference=('composition', 'cleanliness'))


def delivery_available(path):
    """Existing empty directories are safe; never remove or reuse delivery content."""
    return not path.exists() or (path.is_dir() and not any(path.iterdir()))


def check_source_bindings(bindings):
    """A single-table submission must still match what the agent actually saw."""
    core.require(bindings is None or isinstance(bindings, list), '来源绑定须为列表')
    for binding in bindings or []:
        core.require(isinstance(binding, dict) and text(binding.get('path')) and text(binding.get('sha256')),
                     '来源绑定须有路径和 SHA256')
        core.require(core.sha(binding['path']) == binding['sha256'],
                     '审查来源已变化，须另建审查：' + binding['path'])


def expand_check_groups(row):
    """Expand explicit grouped judgments, never infer a visual judgment from a verdict."""
    groups, exceptions = row.get('check_groups'), row.get('check_exceptions', {})
    core.require(isinstance(groups, dict) and set(groups) == set(CHECK_GROUPS)
                 and all(v in ('PASS', 'FAIL', 'uncertain') for v in groups.values()), '须填写三组图片检查')
    names = {name for members in CHECK_GROUPS.values() for name in members}
    core.require(isinstance(exceptions, dict) and set(exceptions) <= names
                 and all(v in ('FAIL', 'uncertain') for v in exceptions.values()), '异常须定位到具体检查项')
    checks = dict.fromkeys(names, 'PASS')
    checks.update(exceptions)
    for key, members in CHECK_GROUPS.items():
        values = [checks[name] for name in members]
        actual = 'FAIL' if 'FAIL' in values else 'uncertain' if 'uncertain' in values else 'PASS'
        core.require(groups[key] == actual, '三组检查与具体异常不一致：' + key)
    return checks


def shared_requirements(p):
    """Expand explicitly scoped common constraints, never per-shot story judgments."""
    templates = p.pop('requirement_templates', {})
    core.require(isinstance(templates, dict), 'requirement_templates 须为对象')
    for name, template in templates.items():
        core.require(isinstance(name, str) and name.strip() and isinstance(template, dict)
                     and set(template) <= {'scope', 'must_have', 'must_not_have', 'provenance'},
                     '共同要求只能包含 scope、must_have、must_not_have、provenance')
        scope = template.get('scope')
        core.require(isinstance(scope, dict) and bool(scope)
                     and set(scope) <= {'scene_id', 'continuity_id', 'asset_ids'}, '共同要求须明确场景、连续段或资产适用范围')
        for key, value in scope.items():
            core.require((isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value))
                         if key == 'asset_ids' else (isinstance(value, str) and bool(value.strip())),
                         '共同要求 scope 值无效')
        for key in ('must_have', 'must_not_have'):
            core.require(isinstance(template.get(key, []), list)
                         and all(isinstance(v, str) and v.strip() for v in template.get(key, [])), '共同约束须为文字列表')
        core.require(bool(template.get('must_have') or template.get('must_not_have'))
                     and isinstance(template.get('provenance'), list) and bool(template['provenance']),
                     '共同要求须有约束和明确来源')
    for shot in p['shots']:
        name = shot.pop('requirements_template', None)
        if name is None:
            continue
        core.require(isinstance(name, str) and name in templates, '未知的 requirements_template')
        template = templates[name]
        for key, value in template['scope'].items():
            core.require(set(value) <= set(shot.get(key, [])) if key == 'asset_ids' else shot.get(key) == value,
                         '共同要求适用范围与本镜不符；不能跨场景、连续段或资产套用')
        r = shot.get('requirements')
        core.require(isinstance(r, dict), '共同要求不能代替每镜阶段、状态和来源判断')
        for key in ('must_have', 'must_not_have'):
            core.require(isinstance(r.get(key, []), list), '逐镜约束须为列表')
            r[key] = list(dict.fromkeys(template.get(key, []) + r.get(key, [])))
        core.require(isinstance(r.get('provenance'), list), '每镜仍须明确阶段和特有要求的来源')
        r['provenance'] = copy.deepcopy(template['provenance']) + r['provenance']


def project_input(data):
    """Expand mechanical defaults only; narrative requirements remain explicit."""
    core.require(isinstance(data, dict) and data.get('input_version') == 1, '精简输入版本须为 1')
    p = copy.deepcopy(data)
    del p['input_version']
    p['schema_version'] = 1
    core.require(isinstance(p.get('shots'), list) and p['shots'], '精简输入需要按原序填写全部镜头')
    core.require(all(isinstance(s, dict) for s in p['shots']), '镜头须为对象')
    report = Report()
    source = p.get('source_script')
    report.check(text(source), 'source_script', '须保留完整原脚本')
    seen = set()
    for i, s in enumerate(p['shots']):
        where = shot_path(s, i)
        sid = s.get('id')
        if report.check(text(sid), where + '.id', '须保留原镜号'):
            report.check(sid not in seen, where + '.id', '镜号不得重复')
            seen.add(sid)
        report.check(text(s.get('image')), where + '.image', '每镜须有 image 原图路径')
        report.check(core.number(s.get('duration')) and s['duration'] > 0, where + '.duration', '计划时长须为有限正数')
        ds = s.get('duration_source')
        report.check(isinstance(ds, dict) and ds.get('kind') and ds.get('ref'),
                     where + '.duration_source', '计划时长须保留来源')
        for key in ('script', 'scene_id', 'continuity_id', 'required_result'):
            report.check(text(s.get(key)), where + '.' + key, '须明确填写逐镜必要字段')
        if text(source) and text(s.get('script')):
            report.check(s['script'] in source, where + '.script', '逐镜原文须原样取自 source_script；不能合并换行或替换标点')
        report.check(isinstance(s.get('requirements'), dict), where + '.requirements', '须明确参考阶段、必要要求及来源')
        r = s.get('requirements', {})
        if isinstance(r, dict):
            k = r.get('keyframe')
            report.check(isinstance(k, dict) and k.get('phase') in ('entry', 'action', 'exit'),
                         where + '.requirements.keyframe.phase', '阶段须为 entry/action/exit，不自动猜测')
        facts = s.get('facts', [])
        if report.check(isinstance(facts, list), where + '.facts', '可选状态事实须为数组'):
            for j, f in enumerate(facts):
                report.check(isinstance(f, dict) and f.get('phase') in ('static', 'before', 'after'),
                             f'{where}.facts[{j}].phase', '事实阶段须为 static/before/after，不能填写 current')
        report.check(isinstance(s.get('intent'), dict), where + '.intent', '须明确剧情关键性标记')
    report.finish()
    shared_requirements(p)
    supplied = []
    for s in p['shots']:
        core.require(isinstance(s, dict) and isinstance(s.get('image'), str) and s['image'].strip(),
                     '精简输入每镜须有 image 原图路径')
        supplied.append(dict(shot_id=s.get('id'), path=s.pop('image')))
        core.require(isinstance(s.get('duration_source'), dict) and s['duration_source'].get('kind')
                     and s['duration_source'].get('ref'), '计划时长须保留 duration_source 来源')
        r = s.get('requirements')
        core.require(isinstance(r, dict), '每镜须明确 requirements；不能从脚本自动猜测阶段或硬要求')
        r.setdefault('version', 1)
        r.setdefault('purpose', s.get('required_result'))
        r.setdefault('inherits_from', None)
        r.setdefault('entry_state', {})
        r.setdefault('must_have', [])
        r.setdefault('must_not_have', [])
        if isinstance(r.get('keyframe'), dict):
            r['keyframe'].setdefault('state', {})
        # Visual evidence belongs in the worklist. Planner facts are only needed
        # for explicit state modelling/omission, never synthesized from shot prose.
        s.setdefault('facts', [])
        core.require(isinstance(s.get('intent'), dict), '每镜须明确 intent 剧情关键性标记')
        s.setdefault('state_changes', [])
        s.setdefault('reference', dict(mode='anchor', path=None, role='representative',
                                     reason='初始占位，尚未校对；不代表通过或省图结论。'))
    core.require('storyboard_images' not in p and 'groups' not in p, '精简输入的图片对应及来源批次由程序生成')
    core.require(not (p.get('reviews') or p.get('tasks') or p.get('imported_videos')),
                 '精简输入仅用于新项目，不能导入已有审查或视频历史')
    p.update(storyboard_images=supplied, groups=[dict(id='G01', shot_ids=[s.get('id') for s in p['shots']], version=1)])
    p.setdefault('config', {})
    core.require(isinstance(p['config'], dict), '精简输入的 config 须为对象')
    p['config'].update(workflow='storyboard_images', video_input_mode='assets', delivery_mode='storyboard_images',
                       storyboard_review_policy='single_pass')
    for key, value in dict(tasks={}, reviews=[], repairs=[], repair_round=0, delivery=None).items():
        p.setdefault(key, value)
    return p


def worklist(ctx):
    full = images.draft(ctx)
    result = {k: copy.deepcopy(full[k]) for k in ('group_id', 'context_fingerprint', 'checks', 'grouping_checked',
              'issues', 'uncertainties', 'asset_comparisons', 'repair_assessments')}
    result.update(worklist_version=2, limitations=[], shots=[])
    if ctx.get('review_overviews'):
        result['overview_manifest'] = copy.deepcopy(ctx['review_overviews']['manifest'])
    for row, ref in zip(full['shot_reviews'], full['reference_assessments']):
        item = {k: v for k, v in row.items() if k in ('shot_id', 'verdict', 'reference_phase', 'checks')}
        item['reference'] = {k: v for k, v in ref.items() if k in ('decision', 'derivable', 'basis_shot_ids')}
        item['observation'] = dict(visible_facts=[])
        if images.single_pass(ctx):
            item.pop('checks')
            item.update(check_groups=dict.fromkeys(CHECK_GROUPS, 'uncertain'), check_exceptions={}, match_level=None)
        result['shots'].append(item)
    if images.single_pass(ctx):
        result['worklist_version'] = 3
    return result


def expand(ctx, data):
    if data.get('worklist_version') == 4:
        from storyboard_conclusions import expand as expand_conclusions
        data = expand_conclusions(ctx, data)
    core.require(data.get('worklist_version') in (1, 2, 3) and data.get('context_fingerprint') == ctx['context_fingerprint']
                 and data.get('group_id') == ctx['group_id'], '审查依据已变化，请重新 prepare 并核验工作表')
    overviews.validate(ctx, data.get('overview_manifest'))
    full = images.draft(ctx)
    core.require([r.get('shot_id') for r in data.get('shots', [])] == full['coverage']['shot_ids'],
                 '逐镜工作表必须按输入顺序完整覆盖每镜一次')
    for key in ('checks', 'grouping_checked', 'issues', 'uncertainties', 'asset_comparisons', 'repair_assessments'):
        full[key] = copy.deepcopy(data[key])
    full['coverage']['limitations'] = copy.deepcopy(data['limitations'])
    for row, target, ref, evidence in zip(data['shots'], full['shot_reviews'], full['reference_assessments'], full['evidence']):
        row = copy.deepcopy(row)
        if data['worklist_version'] == 3:
            core.require(images.single_pass(ctx), '三组工作单须使用一次看图策略')
            row['checks'] = expand_check_groups(row)
            if row.get('verdict') == 'PASS':
                core.require(type(row.get('match_level')) is int and 0 <= row['match_level'] <= 3,
                             '通过须记录同一次观察采用的匹配等级 0–3')
        if data['worklist_version'] in (2, 3):
            core.require(isinstance(row.get('checks'), dict) and set(row['checks']) == set(target['checks'])
                         and 'verdict' in row and 'reference_phase' in row,
                         '每镜须显式填写检查、结论和参考阶段')
            reference = row.get('reference')
            core.require(isinstance(reference, dict) and all(key in reference for key in
                         ('decision', 'derivable', 'basis_shot_ids')), '每镜须填写参考图取舍与依据镜号')
            if reference['decision'] == 'ai_fill':
                core.require(isinstance(reference.get('reason'), str) and reference['reason'].strip(),
                             '省图须明确填写双侧推导理由')
            facts = row.get('observation', {}).get('visible_facts')
            core.require(isinstance(facts, list) and facts and all(isinstance(v, str) and v.strip() for v in facts),
                         '每镜须记录实际看图所得的 visible_facts')
            observed = '；'.join(facts)
            if row['verdict'] == 'PASS':
                row.update(reason='符合脚本', followup='')
            core.require(isinstance(row.get('reason'), str) and row['reason'].strip(), '不通过或待核查镜头须说明原因')
            row.setdefault('identity_reason', observed)
            row.setdefault('phase_reason', observed)
            row['observation'].setdefault('observation', observed)
            row['observation'].setdefault('interpretation', row['reason'])
            # Anchor and pending receipts reuse the already reviewed conclusion.
            # Omission still needs its own explicit two-sided derivation rationale.
            if row['reference'].get('decision') == 'anchor':
                row['reference'].setdefault('reason', '保留原图')
            elif row['reference'].get('decision') == 'pending':
                row['reference'].setdefault('reason', row.get('followup') or row['reason'])
        for key in ('verdict', 'reason', 'identity_reason', 'reference_phase', 'phase_reason', 'checks', 'followup', 'identity_scope', 'match_level'):
            if key in row:
                target[key] = copy.deepcopy(row[key])
        for key in ('decision', 'derivable', 'basis_shot_ids', 'reason'):
            ref[key] = copy.deepcopy(row['reference'][key])
        for key in ('observation', 'visible_facts', 'interpretation'):
            evidence[key] = copy.deepcopy(row['observation'][key])
    if data['worklist_version'] in (2, 3):
        bound = {s['shot_id']: s['image'] for s in ctx['shots']}
        assets = {a['id']: a for a in ctx['assets']}
        for comparison in full['asset_comparisons']:
            sid, aid = comparison.get('shot_id'), comparison.get('asset_id')
            core.require(sid in bound and aid in assets, '资产对照须引用当前镜号和原资产')
            comparison.setdefault('asset_sha256', assets[aid]['sha256'])
            comparison.setdefault('evidence_refs', [dict(path=bound[sid]['path'], sha256=bound[sid]['sha256'])])
            for key in ('condition_factors', 'stable_matches', 'stable_conflicts', 'unobservable_features', 'basis_shot_ids'):
                comparison.setdefault(key, [])
            if comparison.get('decision') == 'PASS':
                comparison.setdefault('followup', '')
        for issue in full['issues']:
            ids = issue.get('shot_ids', [])
            core.require(isinstance(ids, list) and all(sid in bound for sid in ids), '问题须引用当前原镜号')
            issue.setdefault('evidence', [bound[sid]['path'] for sid in ids])
            issue.setdefault('repair_target', 'storyboard_image')
    return full


def prepare(project, supplied, run_dir, original_prompt=None, input_data=None, *, original_prompt_file=None,
            output=None, reuse_overviews=None, concise=False, source_bindings=None):
    import repair_cycle as repair
    project, run_dir = Path(project).resolve(), Path(run_dir).resolve()
    report = Report()
    report.check(project.parent.is_dir(), 'project', '项目父目录须已存在')
    report.check(not run_dir.exists() and not project.is_relative_to(run_dir), 'run_dir', '请使用新的内部工作目录')
    if output is not None:
        output = Path(output).resolve()
        report.check(not project.is_relative_to(output) and not run_dir.is_relative_to(output)
                     and not output.is_relative_to(run_dir), 'output', '内部记录、交付和项目应使用独立目录')
        report.check(delivery_available(output), 'output', '交付须使用新目录或空目录，不覆盖已有交付')
    candidate = None
    if input_data is not None:
        can_build = report.check(not project.exists() and supplied is None, 'input',
                                '精简输入仅用于新项目；不要覆盖已有项目或另传 --images')
        if can_build:
            try:
                candidate = project_input(input_data)
                # Collect independent field errors even when layout is invalid.
                # On the normal path the locked validation below runs just once.
                if report.errors or report.blocked:
                    core.validate(candidate, project)
            except ValidationError as error:
                report.errors.extend(row for row in error.errors if row not in report.errors)
                report.blocked.extend(row for row in error.blocked if row not in report.blocked)
            except ValueError as error:
                report.check(False, 'input', str(error))
    report.finish()
    with core.locked(project):
        if input_data is not None:
            core.require(not project.exists() and supplied is None, '精简输入仅用于新项目；不要覆盖已有项目或另传 --images')
            p = candidate
        else:
            p = core.read(project)
        core.require(images.enabled(p) or not (p.get('imported_videos') or p.get('tasks') or p.get('reviews')),
                     '已有视频项目请保留原样；为分镜图复制脚本和原资产到新项目')
        p['config'].update(workflow='storyboard_images', video_input_mode='assets')
        if not p.get('reviews'):
            p['config'].setdefault('storyboard_review_policy', 'single_pass')
        p['config'].pop('video_source', None)
        if supplied is not None:
            core.require(isinstance(supplied, list), '输入问题：需要按顺序排列的图片路径或镜号对应项列表')
            if all(isinstance(r, str) for r in supplied):
                core.require(len(supplied) == len(p['shots']), '输入问题：图片数量与脚本镜头数量不一致')
                supplied = [dict(shot_id=s['id'], path=path) for s, path in zip(p['shots'], supplied)]
            p['storyboard_images'] = copy.deepcopy(supplied)
        ids = [s['id'] for s in p['shots']]
        # One source batch; input_shot_groups and later aggregation never change its denominator.
        if len(p.get('groups', [])) != 1 or p['groups'][0]['shot_ids'] != ids:
            p['groups'] = [dict(id='G01', shot_ids=ids, version=1)]
        gid = p['groups'][0]['id']
        with evidence_operation():
            check_source_bindings(source_bindings)
            core.validate(p, project)
            previous = p.pop('repair_baseline', None)
            baseline = repair.baseline(p)
            images.inputs(p, project)  # Decode only after script/field checks; persist nothing on failure.
            if previous and previous != baseline:
                p.setdefault('repair_baseline_history', []).append(previous)
            core.require(original_prompt is None or original_prompt_file is None, '原提示词只传文本或文件之一')
            if original_prompt_file is not None:
                # Resolve only: the file is deliberately not opened, even for existence checks.
                p.setdefault('deferred_storyboard_prompts', {})[gid] = dict(
                    path=str(Path(original_prompt_file).resolve()))
            elif original_prompt is not None:
                core.require(isinstance(original_prompt, str) and original_prompt.strip(), '原提示词须为非空文本')
                p.setdefault('deferred_storyboard_prompts', {})[gid] = dict(text=original_prompt)
            ctx = images.context(p, project, gid)
            run_dir.mkdir(parents=True)
            ctx['review_overviews'] = overviews.build(ctx, run_dir, project, initial=reuse_overviews,
                                                     source_script=p['source_script'])
            if concise:
                from storyboard_conclusions import draft as conclusions_draft
                draft = conclusions_draft(ctx)
            else:
                draft = worklist(ctx)
            first_facts = overviews.initial_observations(ctx, reuse_overviews, p['source_script'])
            for row in draft['shots']:
                if row['shot_id'] in first_facts:
                    row['observation']['visible_facts'] = first_facts[row['shot_id']]
        core.save(run_dir / 'CONTEXT.json', ctx)
        core.save(run_dir / 'WORKLIST.json', draft)
        core.save(run_dir / 'REVIEW.view.json', agent_context.reading_view(ctx))
        core.save(run_dir / 'RUN.json', dict(run_version=1, project=str(project), group_id=gid,
                  context_fingerprint=ctx['context_fingerprint'], context=str(run_dir / 'CONTEXT.json'),
                  worklist=str(run_dir / 'WORKLIST.json'), review_view=str(run_dir / 'REVIEW.view.json'),
                  planned_output=str(Path(output).resolve()) if output else None,
                  next_action='实际看图并及时保存 WORKLIST；压缩后先 resume 校验来源，不重新 prepare。'))
        core.save(project, p)
    return dict(group_id=gid, context=str(run_dir / 'CONTEXT.json'), worklist=str(run_dir / 'WORKLIST.json'),
                worklist_version=draft['worklist_version'],
                review_view=str(run_dir / 'REVIEW.view.json'), run_receipt=str(run_dir / 'RUN.json'),
                reused_observation_shot_ids=list(first_facts),
                review_overviews=ctx['review_overviews'])


def resume(project, run_dir, shot_ids=None, page=None):
    """Recover persisted progress after compaction, checking original evidence afresh."""
    project, run_dir = (Path(v).resolve() for v in (project, run_dir))
    with core.locked(project), evidence_operation():
        p = core.read(project)
        core.require(images.enabled(p), '恢复入口只用于已准备的分镜图项目')
        data = core.read(run_dir / 'WORKLIST.json')
        stored = core.read(run_dir / 'CONTEXT.json')
        core.require(isinstance(data, dict) and data.get('worklist_version') in (1, 2, 3, 4)
                     and isinstance(data.get('group_id'), str) and isinstance(stored, dict),
                     '工作单版本、批次或上下文无效')
        ctx = images.context(p, project, data['group_id'])
        core.require(data.get('context_fingerprint') == stored.get('context_fingerprint') == ctx['context_fingerprint']
                     and data.get('group_id') == stored.get('group_id'),
                     '审查依据已变化，请重新 prepare 并核验工作表；旧结论不能用于新来源')
        core.require({k: v for k, v in stored.items() if k != 'review_overviews'} == ctx,
                     '保存的上下文已变化，不能作为恢复依据')
        rows = data.get('shots')
        core.require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows)
                     and [r.get('shot_id') for r in rows] == [s['shot_id'] for s in ctx['shots']],
                     '逐镜工作表必须按输入顺序完整覆盖每镜一次')
        overviews.validate(ctx, data.get('overview_manifest'))
        if stored.get('review_overviews'):
            core.require(data.get('overview_manifest') == stored['review_overviews']['manifest'],
                         '工作单总览绑定已变化，不能跳过来源校验')
            manifest = core.read(data['overview_manifest']['path'])
            ctx['review_overviews'] = overviews.reading_materials(manifest)
        core.require(shot_ids is None or page is None, '--page 与 --shots 只选一个')
        view_file = run_dir / 'REVIEW.view.json'
        if shot_ids is None and page is None and view_file.exists():
            core.require(core.read(view_file) == agent_context.reading_view(ctx),
                         '阅读视图已变化；使用 resume --shots 镜号重新读取当前来源，不采用改写视图')
        result = dict(group_id=ctx['group_id'], context_fingerprint=ctx['context_fingerprint'],
                      worklist=str(run_dir / 'WORKLIST.json'),
                      review_view=str(view_file if view_file.exists() else run_dir / 'CONTEXT.json'),
                      progress=(agent_context.progress(data, ctx) if data['worklist_version'] == 4
                                else agent_context.progress(data)),
                      next_action='按保存记录继续实际审查；--page 页码读取一批，--shots 镜号定位本镜和相邻镜。'
                                  'complete 仍校验整批，不凭恢复状态批准。')
        if images.single_pass(ctx):
            result['next_action'] = '复用已保存判断，只继续未记录或不完整字段；待核查直接交付，不重开已看图片。'
        if shot_ids is not None or page is not None:
            result['view'] = (agent_context.batch_view(ctx, page) if page is not None
                              else agent_context.reading_view(ctx, shot_ids))
            included = {s['shot_id'] for s in result['view']['shots']}
            result['saved_rows'] = [r for r in rows if r['shot_id'] in included]
            for field in ('issues', 'uncertainties', 'asset_comparisons', 'repair_assessments'):
                entries = data.get(field, [])
                core.require(isinstance(entries, list) and all(isinstance(r, dict) and
                             isinstance(r.get('shot_ids', []), list) and
                             all(isinstance(sid, str) for sid in r.get('shot_ids', [])) for r in entries),
                             field + ' 须为含有效镜号关联的记录列表')
                result[field] = [r for r in entries if r.get('shot_id') in included
                                 or included.intersection(r.get('shot_ids', []))]
            requested = set(result['view'].get('requested_shot_ids', []))
            recorded = set(result['progress']['recorded_shot_ids'])
            result['detail_queue'] = [dict(shot_id=r['shot_id'], image_path=s['image']['path'],
                                           reason=r.get('reason', ''), followup=r.get('followup', ''))
                                     for r, s in zip(rows, ctx['shots']) if r['shot_id'] in requested
                                     and r['shot_id'] in recorded
                                     and (r.get('verdict') == 'uncertain'
                                          or (isinstance(r.get('checks'), dict)
                                              and 'uncertain' in r['checks'].values()))]
            if images.single_pass(ctx):
                result['unresolved_items'] = []
                for row in rows:
                    if row['shot_id'] not in requested or row['shot_id'] not in recorded or row.get('verdict') != 'uncertain':
                        continue
                    reason = ('；'.join(item['reason'] for item in row['unresolved'])
                              if data['worklist_version'] == 4 else row.get('reason', ''))
                    result['unresolved_items'].append(dict(shot_id=row['shot_id'], reason=reason,
                        followup=reason if data['worklist_version'] == 4 else row.get('followup', '')))
                result['detail_queue'] = []
                result['view']['images_to_open'] = [item for item in result['view'].get('images_to_open', [])
                    if not set(item.get('shot_ids', [])) <= recorded]
                result['next_action'] = '复用已保存判断，只继续未记录镜头；待核查保留后直接 complete，不重开已看图片。'
    return result


def load_original_prompt(p, project, gid):
    """Read/register optional generation guidance only after a current threshold trigger."""
    import repair_cycle as repair
    core.require(repair.current_decision(p, project, gid)['triggered'], '未达阈值，不读取原提示词')
    pending = p.get('deferred_storyboard_prompts', {}).get(gid)
    if pending is None:
        return
    text = Path(pending['path']).read_text(encoding='utf-8-sig') if 'path' in pending else pending['text']
    import repair_reference
    source = repair_reference.register(p, project, gid, text)
    if 'path' in pending:
        source['input_path'] = pending['path']
    del p['deferred_storyboard_prompts'][gid]


def complete(project, worklist_file, output, run_dir, profile=None, target_aspect=None, *, source_bindings=None):
    import planner
    import repair_cycle as repair
    from finish_review import intact, validate_delivery
    project, output, run_dir = (Path(v).resolve() for v in (project, output, run_dir))
    core.require(not run_dir.exists() and not project.is_relative_to(run_dir)
                 and not run_dir.is_relative_to(output) and not output.is_relative_to(run_dir)
                 and not project.is_relative_to(output), '内部记录、交付和项目应使用独立目录；内部目录须为新目录')
    started = perf_counter()
    report = dict(schema='storyboard-images-finish-1', started_at=utc_now(), status='running')
    with core.locked(project):
        p = core.read(project)
        core.require(images.enabled(p), '请先整批 prepare 分镜图')
        data = core.read(worklist_file)
        if target_aspect is not None:
            p['storyboard_target_aspect'] = target_aspect
        run_dir.mkdir(parents=True)
        try:
            # One operation shares hashes, decoded image metadata and contexts across all stages.
            # It rehashes every dependency before committing, including same-size replacements.
            with evidence_operation():
                check_source_bindings(source_bindings)
                ctx = images.context(p, project, data['group_id'])
                review = expand(ctx, data)
                images.record_review(p, project, review)
                plan = planner.post_review_plan(p, project, profile or {})
                planner.store_aggregation(p, project, plan)
                decision = repair.decide(p, project, ctx['group_id'])
                previous = p.get('repair_deliveries', {}).get('original')
                if previous:
                    intact(previous)
                    if previous['aggregation_fingerprint'] != core.digest(plan):
                        p.setdefault('repair_delivery_history', []).append(dict(stage='original', record=copy.deepcopy(previous),
                            revision_reason='分镜图、脚本、资产或审查修订', superseded_at=utc_now()))
                        del p['repair_deliveries']['original']
                report['delivery'] = repair.snapshot(p, project, output, 'original')
                report['validation'] = validate_delivery(p, 'original', project)
                report['delivery_next_action'] = ('自动校验通过，直接交付；无需再次人工逐镜核对。' if
                    p['repair_deliveries']['original'].get('delivery_format_version', 1) >= 3 else
                    '旧版冻结交付保留原校验能力，按需核对；不改写原文件。')
                report['decision'] = decision
                if decision['triggered']:
                    report['delivery_next_action'] = '审查报告已冻结；达到阈值，下一优先事项是导出整批新视频提示词，完成后再结束交付。无需重看报告或图片。'
                    import repair_quality
                    work = None
                    try:
                        source = repair_quality.source_request(p, project, ctx['group_id'])
                    except (ValueError, OSError, UnicodeError) as exc:
                        report['prompt_status'] = 'needs_preparation'
                        report['prompt_next_action'] = '优先导出新提示词：按内部清单集中补齐缺项，再 prepare／finish；对白内容及含义不阻止导出。\n' + str(exc)
                        if isinstance(getattr(exc, 'inputs', None), dict):
                            inputs_file = run_dir / 'PROMPT.inputs.json'
                            core.save(inputs_file, exc.inputs)
                            report['prompt_inputs'] = str(inputs_file)
                            if 'prompt_context' in exc.inputs:
                                from prompt_work import packet
                                work = packet(p, project, ctx['group_id'], inputs=exc.inputs)
                    else:
                        core.save(run_dir / 'PROMPT.source.json', source)
                        core.save(run_dir / 'PROMPT.view.json', repair_quality.reading_view(source, p))
                        core.save(run_dir / 'PROMPT.json', repair_quality.compact_template(source))
                        report.update(prompt_status='needs_semantic_review', prompt_plan=str(run_dir / 'PROMPT.json'),
                            prompt_next_action='优先按 PROMPT.view.json 核对已有可见剧情并填写计划，然后 finish 导出；不检查对白内容及含义，不重跑有效审查。')
                        from prompt_work import packet
                        work = packet(p, project, ctx['group_id'], source=source)
                    if work is not None:
                        core.save(run_dir / 'PROMPT.work.json', work['work'])
                        core.save(run_dir / 'PROMPT.work.view.json', work['view'])
                        report.update(prompt_work=str(run_dir / 'PROMPT.work.json'),
                            prompt_work_view=str(run_dir / 'PROMPT.work.view.json'),
                            prompt_output=str(output / f"{ctx['group_id']}_新视频提示词.md"),
                            prompt_next_action='只读 PROMPT.work.view.json，集中填写 PROMPT.work.json 的 preparation、必要 edits 和四组结论，随后直接 repair_quality.py finish 导出到 prompt_output；无需 prepare、重抄指纹或逐镜重复说明。')
                else:
                    report['prompt_status'] = 'below_threshold'
            core.save(project, p)
            report['status'] = 'complete'
        except Exception as exc:
            report.update(status='failed', error=str(exc))
            raise
        finally:
            report.update(ended_at=utc_now(), seconds=round(perf_counter() - started, 4))
            core.save(run_dir / 'FINISH_REPORT.json', report)
            core.save(run_dir / 'FINISH.view.json', agent_context.cli_summary('complete', report, run_dir))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='action', required=True)
    raw = sub.add_parser('extract', help='Extract labelled raw script into an INPUT draft; no narrative inference')
    raw.add_argument('script')
    raw.add_argument('--images', required=True, help='Ordered JSON paths or shot_id/path rows; relative to this JSON file')
    raw.add_argument('--output', required=True, help='New internal INPUT.json; parent directory must exist')
    first = sub.add_parser('overview', help='Render raw-script first-look sheets before narrative preparation')
    first.add_argument('script')
    first.add_argument('--images', required=True, help='Ordered JSON paths or shot_id/path rows; relative to this JSON file')
    first.add_argument('--output', required=True, help='New internal first-look directory; never overwrite INPUT')
    first.add_argument('--delivery', help='Planned public case directory; keep first-look records outside it')
    prep = sub.add_parser('prepare')
    prep.add_argument('project')
    prep.add_argument('--images', help='JSON list of paths or shot_id/path objects, relative to the project')
    prep.add_argument('--input', help='Compact input JSON for a new project; image paths remain relative to PROJECT.json')
    prep.add_argument('--run-dir', required=True)
    prep.add_argument('--reuse-overviews', help='First-look directory or INITIAL_OVERVIEWS.json; verify before reuse')
    prep.add_argument('--concise', action='store_true', help='Write each conclusion/error once; expand review and repair records automatically')
    prep.add_argument('--output', help='Planned new delivery directory; check separation before preparing')
    prep.add_argument('--original-prompt', help='Optional UTF-8 prompt file; read only after the repair threshold triggers')
    recovery = sub.add_parser('resume', help='Check saved progress; read selected shots and their neighbours')
    recovery.add_argument('project'); recovery.add_argument('run_dir')
    selection = recovery.add_mutually_exclusive_group()
    selection.add_argument('--shots', nargs='+', help='Selected shot IDs, with adjacent continuity context')
    selection.add_argument('--page', type=int, help='One nine-shot batch with relevant assets and boundary context')
    done = sub.add_parser('complete')
    done.add_argument('project'); done.add_argument('worklist')
    done.add_argument('--output', required=True); done.add_argument('--run-dir', required=True)
    done.add_argument('--profile'); done.add_argument('--target-aspect')
    for parser in (raw, first, prep, recovery, done):
        parser.add_argument('--detailed', action='store_true', help='Print full tool result; normally keep evidence on disk')
    args = ap.parse_args()
    try:
        if args.action == 'extract':
            from script_input import extract
            result = extract(args.script, core.read(args.images), args.output,
                             image_base=Path(args.images).resolve().parent)
        elif args.action == 'overview':
            if args.delivery:
                public, internal = (Path(v).resolve() for v in (args.delivery, args.output))
                core.require(not internal.is_relative_to(public) and not public.is_relative_to(internal),
                             '首看内部目录与交付目录应使用独立目录，不在 case 交付内创建内部文件夹')
                core.require(delivery_available(public), '交付须使用新目录或空目录，不覆盖已有交付')
            result = overviews.overview(args.script, core.read(args.images), args.output,
                                       image_base=Path(args.images).resolve().parent)
        elif args.action == 'prepare':
            result = prepare(args.project, core.read(args.images) if args.images else None, args.run_dir,
                             input_data=core.read(args.input) if args.input else None,
                             original_prompt_file=args.original_prompt, output=args.output,
                             reuse_overviews=args.reuse_overviews, concise=args.concise)
        elif args.action == 'resume':
            result = resume(args.project, args.run_dir, args.shots, args.page)
        else:
            result = complete(args.project, args.worklist, args.output, args.run_dir,
                              core.read(args.profile) if args.profile else None, args.target_aspect)
    except (ValueError, OSError, UnicodeError) as exc:
        ap.exit(2, f'{args.action} 失败：{exc}\n已停止本步骤；修正后重试，不继续运行依赖其输出的步骤。\n')
    import json
    summary = result if args.detailed else agent_context.cli_summary(args.action, result, getattr(args, 'run_dir', None))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
