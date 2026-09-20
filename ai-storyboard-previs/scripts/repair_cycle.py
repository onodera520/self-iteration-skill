"""Evidence-bound, one-submission repair cycle. No visual judgments or implicit submission."""
from __future__ import annotations
import argparse
import copy
from decimal import Decimal
from pathlib import Path
import re

import previs as core
import planner
import repair_prompt

POLICY = 2
WORKFLOW = "2099403222661287938"
PREVIS_DIRECTIVE = '严格按照分镜脚本生成一段快速切镜的视频，每个分镜不需要很大的动作幅度。没有台词，没有音乐，不要出现字幕。每个分镜硬切转场。'
DECISION_STATE = ('fingerprint', 'execution_status', 'task_key', 'automatic_allowance_used')
DELIVERY_STAGES = ('original', 'repaired')
DELIVERY_NAMES = {'original': '01_原视频审查.md', 'repaired': '02_返修视频审查.md'}


def lineage_tasks(p, gid, video_sha256=None):
    return [t for t in p.get('tasks', {}).values() if t.get('repair_source_group') and t.get('reserved') and
            (t['repair_source_group'] == gid or (video_sha256 and video_sha256 in
             [t['request']['binding']['video_sha256'], *t.get('output_hashes', [])]))]


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
    """Optional review extension; mandatory before an automatic repair decision."""
    rows = r.get('repair_assessments', [])
    problems = {v['shot_id']: v for v in r['shot_reviews'] if v['verdict'] in ('FAIL', 'absent')}
    core.require(len(rows) == len(problems) and {a.get('shot_id') for a in rows} == set(problems),
                 'repair_assessments must cover each confirmed FAIL/absent once')
    shots = {s['id']: s for s in p['shots']}
    issues = {i['id']: i for i in r['issues']}
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
        # Matched failures already require same-shot timed evidence; absent uses full rescan instead.
        if problems[sid]['verdict'] == 'FAIL':
            core.require(any(e['shot_id'] == sid and e['time'] in problems[sid]['evidence_times']
                             for e in r['evidence']), 'Repair FAIL needs same-shot timed evidence')


def threshold(total, eligible, critical, necessary_missing=()):
    ids = list(dict.fromkeys(eligible))
    keys = list(dict.fromkeys(critical))
    missing = list(dict.fromkeys(necessary_missing))
    core.require(total > 0 and len(ids) <= total and set(keys) <= set(ids) and
                 set(missing) <= set(ids), 'Invalid repair counts')
    ratio = Decimal(len(ids)) / Decimal(total)
    critical_trigger = bool(missing) and bool(keys)
    cumulative = len(ids) >= (2 if missing else 3) and ratio >= Decimal('0.2')
    return dict(triggered=critical_trigger or cumulative,
                error_count=len(ids), total=total, ratio=float(ratio), critical_shot_ids=keys,
                necessary_missing_shot_ids=missing, problem_shot_ids=ids,
                trigger='critical' if critical_trigger else ('cumulative' if cumulative else 'below_threshold'))


def binding(p, project, gid):
    g = core.group(p, gid)
    r = core.review_current(p, project, gid)
    a = planner.current_aggregation(p, project)
    core.require(r and a, 'Current group review and final aggregation required')
    b = baseline(p)
    assets = [dict(id=x['id'], path=str(core.resolve(project, x['path'])), sha256=core.sha(core.resolve(project, x['path'])))
              for x in p['assets']]
    return dict(policy=POLICY, source_group_id=gid, version=g['version'],
                video_sha256=r['video_sha256'], review_fingerprint=core.digest(r),
                context_fingerprint=r['context_fingerprint'], aggregation_fingerprint=core.digest(a),
                script_fingerprint=core.digest(b), assets=assets,
                style_fingerprint=core.digest(p.get('repair_asset_style')),
                group_fingerprint=core.group_fingerprint(p, project, g))


def decide(p, project, gid):
    bound = binding(p, project, gid)
    r = core.review_current(p, project, gid)
    validate_assessments(p, r)
    rows = {x['shot_id']: x for x in planner.current_aggregation(p, project)['decisions']}
    assessments = {a['shot_id']: a for a in r.get('repair_assessments', [])}
    eligible, critical, allowed, missing = [], [], [], []
    for v in r['shot_reviews']:
        sid, verdict = v['shot_id'], v['verdict']
        necessary_absent = verdict == 'absent' and rows[sid]['status'] == 'missing_required'
        if necessary_absent:
            missing.append(sid)
        if verdict == 'FAIL' or necessary_absent:
            allowed.append(sid)
            a = assessments[sid]
            if necessary_absent or a['affects_story']:
                eligible.append(sid)
                if a['critical']:
                    critical.append(sid)
    result = dict(binding=bound, **threshold(len(r['shot_reviews']), eligible, critical, missing),
                  allowed_correction_shot_ids=allowed, assessments=list(assessments.values()),
                  review_verdict=r['verdict'], execution_status='not_started', task_key=None)
    # A repaired video never obtains another automatic allowance, even after new reviews.
    existing = lineage_tasks(p, gid, bound['video_sha256'])
    used = bool(existing)
    result['automatic_allowance_used'] = used
    if existing:
        result.update(execution_status=existing[0]['status'], task_key=existing[0]['id'])
    result['fingerprint'] = core.digest({k: v for k, v in result.items() if k not in DECISION_STATE})
    p.setdefault('repair_decisions', {})[gid] = result
    return result


def current_decision(p, project, gid):
    d = p.get('repair_decisions', {}).get(gid)
    core.require(d and d['binding'] == binding(p, project, gid), 'Repair decision stale; re-evaluate changed inputs')
    core.require(d['fingerprint'] == core.digest({k: v for k, v in d.items() if k not in DECISION_STATE}),
                 'Repair decision was modified')
    return d


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
                     'Visible asset style facts required; do not infer style from the failed video')
        core.require(isinstance(row.get('guidance'), str) and row['guidance'].strip(), 'Grounded asset style guidance required')
    core.require(profile.get('preserves_story') is True, 'Style guidance must preserve script and narrative-first tolerance')
    return profile


def _compose_prompt(p, project, gid, version):
    # None/0 reproduce the two historical unversioned formats for installation only.
    d = current_decision(p, project, gid)
    core.require(d['triggered'], 'Repair threshold not reached')
    from requirements import contexts
    resolved = contexts(p)
    original = {s['shot_id']: s for s in baseline(p)['shots']}
    assessment = {s['shot_id']: s for s in d['assessments']}
    ss = core.shots(p, core.group(p, gid))
    views = repair_prompt.input_views(ss, original, resolved,
        {s['id']: i for i, s in enumerate(p['shots'], 1)}) if version == repair_prompt.VERSION else {}
    assets = d['binding']['assets']
    style = asset_style(p, assets)
    descriptions = {a['id']: a.get('description', '') for a in p['assets']}
    lines = ['按下列完整脚本生成视频，保留镜号、镜序、剧情及必要切镜。',
             '资产图顺序：' + '；'.join(f"图{i}: {a['id']} {descriptions[a['id']]}" for i, a in enumerate(assets, 1)),
             '画幅：' + str(p['config'].get('aspect_ratio', ''))]
    lines.extend(baseline(p)['format_requirements'])
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
        core.require(version == 0 or not requirement or requirement['ready'],
                     'Resolve provisional shot requirements before repair: ' + s['id'])
        must = [x for x in (requirement.get('must_have') or []) if x]
        must_not = [x for x in (requirement.get('must_not_have') or []) if x]
        changes = [f"{c['entity']}.{c['attribute']} 由 {c['before']} 变为 {c['after']}"
                   for c in s.get('state_changes', []) if c.get('authorized') and c.get('critical')]
        if must:
            block['must_have'] = must
        if must_not:
            block['must_not_have'] = must_not
        if (must or must_not) and version != 0:
            frame = requirement['keyframe']
            block['keyframe_target'] = dict(phase=frame['phase'], description=frame['description'])
        if changes:
            block['critical_changes'] = changes
        blocks.append(block)
        duration_tag = '生成时长' if views else '时长'
        line = f"镜头{i},【{duration_tag}】1.0s。【镜头设计】{block['design']}。【镜头内容】{block.get('generation_text', block['text'])}"
        if 'keyframe_target' in block:
            phase = {'entry': '起态', 'action': '动作中', 'exit': '终态'}[frame['phase']]
            line += f"【目标静帧】{phase}：{frame['description']}。以下必须/不得出现仅约束该时刻，完整动作仍按原脚本先后呈现。"
        if must:
            line += '【本镜必须出现】' + '；'.join(must)
        if must_not:
            line += '【本镜不得出现】' + '；'.join(must_not)
        if changes:
            line += '【本镜关键变化】' + '；'.join(changes)
        if 'correction' in block:
            line += '【仅本镜返修补充】' + block['correction']
        lines += [line]
    lines += ['\n【固定预演要求】', PREVIS_DIRECTIVE,
              '小幅运动仍须清楚呈现原脚本的关键动作和结果。对白、OS、VO仅用于理解剧情，不输出声音或屏幕文字。']
    if corrections:
        correction_label = ('以下镜头在上一次生成中缺失或未被独立呈现，必须各自单独成一个硬切镜头，不得省略、不得与相邻镜合并：'
            if version == 0 else '以下为本次需修正或补齐的镜头，必须各自单独成一个硬切镜头，不得省略、不得与相邻镜合并：')
        lines += ['【必须独立成镜的镜头】',
                  correction_label
                  + '、'.join(f"镜头{i}={sid}" for i, sid in corrections)]
        if views:
            missing = set(d['necessary_missing_shot_ids'])
            for label, ids in [('【必要漏镜补齐】', [(i, sid) for i, sid in corrections if sid in missing]),
                               ('【已定位画面修正】', [(i, sid) for i, sid in corrections if sid not in missing])]:
                if ids:
                    lines.append(label + '、'.join(f'镜头{i}={sid}' for i, sid in ids))
    lines += ['【原始资产风格】', '以下风格仅约束视觉表现，不改变原脚本人物关系、动作、场景与时空；资产展示背景不替代剧情背景。']
    lines.extend(f"图{i}（{row['asset_id']}）：{row['guidance']}" for i, row in enumerate(style['assets'], 1))
    seconds = len(ss)
    result = dict(workflow_id=WORKFLOW, instance_type='plus', source_group_id=gid,
                decision_fingerprint=d['fingerprint'], binding=copy.deepcopy(d['binding']),
                prompt='\n'.join(lines), blocks=blocks, assets=copy.deepcopy(assets),
                asset_style=copy.deepcopy(style), previs_directive=PREVIS_DIRECTIVE,
                duration_seconds=float(seconds), aspect_ratio=p['config'].get('aspect_ratio'))
    if version == repair_prompt.VERSION:
        result['prompt_version'] = version
        result['prompt_fingerprint'] = core.digest(dict(version=version, prompt=result['prompt'], blocks=blocks))
        repair_prompt.validate(result, [s['id'] for s in ss])
    return result


def make_prompt(p, project, gid):
    return _compose_prompt(p, project, gid, repair_prompt.VERSION)


def validate_stored_request(p, project, task):
    """Old requests can recover/install, but never become a new-submission format."""
    request = task['request']
    core.require(task['fingerprint'] == core.digest(request), 'Invalid stored repair request')
    gid = task['repair_source_group']
    if 'prompt_version' in request:
        core.require(request['prompt_version'] == repair_prompt.VERSION, 'Unsupported repair prompt version')
        expected = prepare(p, project, gid)
        core.require(request == expected, 'Inputs changed since submission; do not attach stale repair')
    else:
        # Reconstruct exact historical bytes/fields while still checking current evidence,
        # original baseline, asset hashes and decision binding. No migration of saved data.
        matched = False
        for version in (None, 0):
            try:
                matched = request == _compose_prompt(p, project, gid, version)
            except ValueError:
                continue
            if matched:
                break
        core.require(matched, 'Inputs changed since submission or unsupported legacy request')
        request_limits(p, request)


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


def prepare(p, project, gid, request=None):
    expected = make_prompt(p, project, gid)
    if request is not None and request.get('prompt_version') == repair_prompt.VERSION:
        repair_prompt.validate(request, [s['id'] for s in core.shots(p, core.group(p, gid))])
    core.require(request is None or request == expected, 'Prompt/request changed outside approved correction scope')
    request_limits(p, expected)
    return expected


def request_limits(p, expected):
    core.require(1 <= len(expected['assets']) <= 9, 'Fixed workflow needs 1 to 9 original assets; do not drop or split')
    core.require(expected['aspect_ratio'], 'Explicit aspect ratio required')
    for a in expected['assets']:
        core.require(Path(a['path']).suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'), 'Unsupported asset type')
    limits = p['config'].get('fixed_workflow_limits', {})
    if 'max_duration_seconds' in limits:
        core.require(expected['duration_seconds'] <= limits['max_duration_seconds'], 'Full script exceeds configured workflow duration')


def snapshot(p, project, out, stage):
    """Immutable two-table delivery; never render a fake second review."""
    import storyboard
    core.require(stage in DELIVERY_STAGES, 'Unknown delivery stage')
    core.require(planner.current_aggregation(p, project), 'Current aggregation required before delivery')
    core.require(all(core.review_current(p, project, g['id']) for g in p['groups']), 'All source/boundary reviews must be current')
    if stage != 'original':
        tasks = [t for t in p.get('tasks', {}).values() if t.get('repair_source_group')]
        core.require(tasks and all(t.get('installed') for t in tasks), 'Repaired video not installed; no delivery report')
        for t in tasks:
            gid = t['repair_source_group']
            g = core.group(p, gid)
            current, _ = core.current_video(p, project, g)
            core.require(current and current['output_hashes'] == t['output_hashes'] and g['version'] == t['installed_version'],
                         'Delivery must describe the latest installed repair output for ' + gid)
    out = Path(out).resolve()
    records = p.setdefault('repair_deliveries', {})
    if stage in records:
        record = records[stage]
        core.require(all(Path(f).is_file() and core.sha(Path(f)) == h for f, h in record['files'].items()), 'Immutable delivery changed')
        return record['path']
    core.require(not out.exists() or not any(out.iterdir()), 'Use an empty, separate delivery directory')
    path = Path(storyboard.render(p, project, out))
    text = path.read_text(encoding='utf-8').replace('重新生成仅为建议，本流程不调用 API；待检查先补证据。',
        '是否自动返修由独立阈值与执行条件决定；未达阈值不代表审查通过，待检查先补证据。')
    if stage != 'original':
        text += '\n一次自动返修额度已用完；本表按新视频独立审查，仍有错误或待检查时以上述逐镜结论为准。\n'
    dest = out / DELIVERY_NAMES[stage]
    dest.write_text(text, encoding='utf-8')
    path.unlink()
    records[stage] = dict(path=str(dest), files={str(f): core.sha(f) for f in out.rglob('*') if f.is_file()},
                          aggregation_fingerprint=core.digest(p['aggregation']))
    return str(dest)


def submit(p, project, gid, transport, authorized=False):
    source, _ = core.current_video(p, project, core.group(p, gid))
    existing = lineage_tasks(p, gid, source['output_hashes'][0] if source else None)
    if existing:
        return resume(p, project, existing[0]['id'], transport)
    core.require(authorized, 'Actual paid-generation authorization required')
    request = prepare(p, project, gid)
    d = current_decision(p, project, gid)
    core.require(not d['automatic_allowance_used'], 'One automatic submission already reserved')
    core.require('original' in p.get('repair_deliveries', {}), 'Save immutable original report before submission')
    record = p['repair_deliveries']['original']
    core.require(record['aggregation_fingerprint'] == core.digest(p['aggregation']) and
                 all(Path(f).is_file() and core.sha(Path(f)) == h for f, h in record['files'].items()),
                 'Original report missing, stale or modified')
    c = p['config']
    core.require(p.get('repair_round', 0) < min(3, c.get('max_repair_rounds', 3)), 'Repair round limit reached')
    reserved = [t for t in p.get('tasks', {}).values() if t.get('reserved')]
    if 'max_submissions' in c:
        core.require(len(reserved) < c['max_submissions'], 'Existing submission cap reached; do not clear it silently')
    core.require('budget_cny' not in c, 'Existing CNY budget cannot be checked against RH coins; preserve budget and stop')
    transport.prepare(request)  # Offline compatibility check; no submission or credentials.
    core.require(prepare(p, project, gid) == request, 'Inputs changed during preparation')
    key = 'repair-' + core.digest([gid, request['binding']['video_sha256']])[:24]
    t = dict(id=key, kind='fixed_workflow_video', repair_source_group=gid, target_id=gid,
             request=request, fingerprint=core.digest(request), reserved=True, status='submitting',
             outputs=[], output_hashes=[], installed=False)
    p.setdefault('tasks', {})[key] = t
    d.update(execution_status='submitting', task_key=key)
    core.save(project, p)  # Reservation survives a process crash or ambiguous create.
    try:
        response = transport.submit(request)
        tid = str(response.get('taskId', ''))
        core.require(re.fullmatch(r'\d+', tid), 'Create response missing numeric taskId')
        t.update(task_id=tid, status='QUEUED')
    except Exception as exc:
        t.update(status='submission_unknown', last_error=type(exc).__name__)
    d['execution_status'] = t['status']
    core.save(project, p)
    return t['status']


def attach(p, key, task_id):
    t = p['tasks'][key]
    core.require(t.get('repair_source_group') and t['status'] in ('submitting', 'submission_unknown') and not t.get('task_id'),
                 'Attach only an unknown original submission')
    core.require(re.fullmatch(r'\d+', task_id), 'Verified numeric original taskId required')
    t.update(task_id=task_id, status='QUEUED')


def resume(p, project, key, transport):
    t = p['tasks'][key]
    core.require(t.get('repair_source_group') and t['fingerprint'] == core.digest(t['request']), 'Invalid stored repair request')
    if t['status'] in ('SUCCESS', 'FAILED', 'CANCELLED', 'CANCELED'):
        return t['status']
    if not t.get('task_id'):
        t['status'] = 'submission_unknown'
    else:
        try:
            if t.get('remote_status') != 'SUCCESS':
                response = transport.query(t['task_id'])
                core.require(str(response.get('taskId')) == t['task_id'], 'Query taskId mismatch')
                status = response.get('status')
                core.require(status in ('QUEUED', 'RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED', 'CANCELED'), 'Unknown remote status')
                t.update(remote_status=status, status=status, results=response.get('results', []))
                # Do not save SUCCESS until output is durably downloaded and hashed.
                if status == 'SUCCESS':
                    t['status'] = 'download_pending'
                core.save(project, p)
            if t.get('remote_status') == 'SUCCESS':
                candidates = [r for r in t['results'] if str(r.get('outputType', '')).lower() in ('mp4', 'video') or
                              str(r.get('url', '')).split('?')[0].lower().endswith('.mp4')]
                core.require(len(candidates) == 1, 'Expected one MP4 output; inspect original task, never resubmit')
                dest = Path(project).parent / '.repair' / key / 'output.mp4'
                dest.parent.mkdir(parents=True, exist_ok=True)
                transport.download(candidates[0]['url'], dest)
                core.require(dest.is_file() and dest.stat().st_size > 0, 'Empty downloaded video')
                t.update(outputs=[str(dest.resolve())], output_hashes=[core.sha(dest)], status='SUCCESS')
        except Exception as exc:
            t.update(status='download_error' if t.get('remote_status') == 'SUCCESS' else 'query_error', last_error=type(exc).__name__)
    d = p.get('repair_decisions', {}).get(t['repair_source_group'])
    if d:
        d['execution_status'] = t['status']
    core.save(project, p)
    return t['status']


def install(p, project, key):
    tasks = [t for t in p['tasks'].values() if t.get('repair_source_group')]
    core.require(key == 'all' or key in {t['id'] for t in tasks}, 'Repair task required')
    pending = [t for t in tasks if not t.get('installed')]
    # Batch all original decisions before advancing any versions/boundary fingerprints.
    core.require(pending and all(t['status'] == 'SUCCESS' for t in pending),
                 'Complete all reserved source repairs before installing; failed or unknown task cannot become a second review')
    core.require(key == 'all' or len(pending) == 1, 'Multiple sources: use install all for atomic version/boundary invalidation')
    for t in pending:
        validate_stored_request(p, project, t)
        core.require(core.sha(Path(t['outputs'][0])) == t['output_hashes'][0], 'Downloaded output changed')
    # Mutate a copy: failed probing cannot leave a partially advanced version.
    candidate = copy.deepcopy(p)
    core.require(candidate.get('repair_round', 0) < 3, 'Three-round ceiling reached')
    core.repair(candidate, project, [t['repair_source_group'] for t in pending],
                'One-shot fixed workflow repair; full independent review required')
    for t in pending:
        gid = t['repair_source_group']
        core.import_video(candidate, project, gid, Path(t['outputs'][0]))
        candidate['tasks'][t['id']]['installed'] = True
        candidate['tasks'][t['id']]['installed_version'] = core.group(candidate, gid)['version']
    candidate.pop('aggregation', None)
    p.clear()
    p.update(candidate)
    core.save(project, p)
    return '\n'.join(t['outputs'][0] for t in pending)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=('baseline', 'decide', 'prompt', 'submit', 'resume', 'attach', 'install') + DELIVERY_STAGES)
    ap.add_argument('project', type=Path)
    ap.add_argument('target', nargs='?')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--task-id')
    ap.add_argument('--submit', action='store_true', help='Explicit authorized RH-coin submission; implementation tests never use this')
    args = ap.parse_args()
    project = args.project.resolve()
    with core.locked(project):
        p = core.read(project)
        cmd = args.command
        if cmd == 'baseline':
            result = baseline(p)
        elif cmd == 'decide':
            result = decide(p, project, args.target)
        elif cmd == 'prompt':
            result = prepare(p, project, args.target)
        elif cmd in DELIVERY_STAGES:
            core.require(args.output, '--output delivery directory required')
            result = snapshot(p, project, args.output, cmd)
        elif cmd == 'attach':
            attach(p, args.target, args.task_id or '')
            result = 'QUEUED'
        elif cmd == 'install':
            result = install(p, project, args.target)
        else:
            from workflow_tasks import FixedWorkflow
            transport = FixedWorkflow(project.parent / '.repair')
            result = submit(p, project, args.target, transport, args.submit) if cmd == 'submit' else resume(p, project, args.target, transport)
        core.save(project, p)
        if cmd in ('decide', 'prompt'):
            output = args.output or project.parent / '.repair' / f'{args.target}-{cmd}.json'
            if cmd == 'prompt':
                output = save_prompt(output, result, explicit=args.output is not None)
            else:
                core.save(output, result)
            print(str(output.resolve()))
        else:
            print(result if isinstance(result, str) else 'Saved')


if __name__ == '__main__':
    main()
