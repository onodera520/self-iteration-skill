"""Ordered, user-paired storyboard images. No video processing or inferred matches."""
from __future__ import annotations
import copy
from fractions import Fraction
from pathlib import Path
import uuid

from PIL import Image, ImageOps
import previs as core
from evidence_runtime import memo_read, verified_read


def enabled(p):
    return p.get('config', {}).get('workflow') == 'storyboard_images'


def single_pass(ctx):
    return ctx.get('review_scope', {}).get('view_policy') == 'single_pass'


@memo_read
def image_info(project, value):
    path = core.resolve(project, value)
    core.require(path.is_file(), '输入问题：图片不存在：' + str(path))
    core.require(path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'), '输入问题：请使用 PNG、JPEG 或 WebP 扩展名')
    fingerprint = core.sha(path)
    try:
        with Image.open(path) as image:
            core.require(image.format in ('PNG', 'JPEG', 'WEBP'), '输入问题：请提供 PNG、JPEG 或 WebP 图片')
            image.load()
            size = ImageOps.exif_transpose(image).size
    except (OSError, ValueError) as exc:
        raise ValueError('输入问题：无法读取图片：' + str(path)) from exc
    ratio = Fraction(*size)
    return dict(path=str(path), sha256=fingerprint, width=size[0], height=size[1],
                aspect_ratio=f'{ratio.numerator}:{ratio.denominator}', source=dict(kind='provided'))


@memo_read
def inputs(p, project):
    rows = p.get('storyboard_images', [])
    ids = [s['id'] for s in p['shots']]
    core.require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows) and
                 [r.get('shot_id') for r in rows] == ids,
                 '输入问题：图片数量、镜号或顺序不符；每镜须有且仅有一个对应项，请修正输入')
    core.require(all(isinstance(r.get('path'), str) and r['path'].strip() for r in rows),
                 '输入问题：每镜需要原图路径')
    return [dict(shot_id=r['shot_id'], **image_info(project, r['path'])) for r in rows]


def current_image(p, project, sid):
    row = next(r for r in inputs(p, project) if r['shot_id'] == sid)
    return {k: v for k, v in row.items() if k != 'shot_id'}


@verified_read
@memo_read
def context(p, project, gid):
    from requirements import contexts
    from grouping import has_input_groups, input_partition
    g = core.group(p, gid)
    images = inputs(p, project)
    ids = [s['id'] for s in p['shots']]
    core.require(len(p['groups']) == 1 and g['shot_ids'] == ids,
                 '图片工作流以整批为审查单位；可选分组请使用 input_shot_groups')
    resolved = contexts(p)
    rows = []
    for shot, image in zip(p['shots'], images):
        row = {k: copy.deepcopy(shot.get(k)) for k in
               ('script', 'shot_size', 'scene_id', 'continuity_id', 'asset_ids', 'beat', 'event', 'duration_source')}
        row.update(shot_id=shot['id'], planned_duration=shot.get('duration'),
                   requirements=resolved.get(shot['id']), image=image)
        rows.append(row)
    assets = [dict(a, sha256=core.sha(core.resolve(project, a['path']))
                   if a.get('path') and core.resolve(project, a['path']).is_file() else 'MISSING') for a in p['assets']]
    result = dict(group_id=gid, version=g['version'], source_kind='provided', workflow='storyboard_images',
                  source_fingerprint=core.digest(images), group_fingerprint=core.group_fingerprint(p, project, g),
                  review_schema=6, reference_policy_version=5, assets=assets, shots=rows, boundaries=[],
                  grouping_mode='input' if has_input_groups(p) else 'automatic',
                  review_scope=dict(standard='storyboard_reference', motion_proof_required=False,
                    phase_rule='Judge the visible entry/action/exit state. Do not demand a completed action in an entry reference.',
                    uncertainty_rule='Unclear necessary details or unknown phase require zoom/clarification, never automatic FAIL.',
                    visual_match_basis='narrative_equivalence', noncritical_visual_variations_allowed=True,
                    group_checks=['shot', 'continuity', 'story'], group_duration_basis='script_plan'))
    # Absent policy means historical behavior: existing contexts/frozen receipts
    # keep their fingerprints. New preparations opt in explicitly.
    if p.get('config', {}).get('storyboard_review_policy') == 'single_pass':
        result['review_scope'].update(view_policy='single_pass', asset_visual_comparison='on_request',
            uncertainty_rule='Record unclear necessary details as uncertain and deliver; no automatic zoom or second view.',
            continuity_evidence='Reuse recorded neighbouring visible facts; do not reopen reviewed images.',
            offscreen_rule='Correct visible action/pose can PASS when the scripted prop or support lies outside the crop and no visible fact contradicts it. Do not claim unseen objects were observed or mark uncertain solely because they are offscreen.',
            facing_rule='A visibly wrong character-facing direction specified by the script must FAIL. Judge against the scripted reference, not camera angle, reverse-shot projection or gaze alone; do not invent an unspecified direction.',
            relaxation_levels=[
                'Core subjects and necessary relations match; allow shot-size/camera-angle differences, not a wrong scripted character-facing direction.',
                'Core subjects and necessary relations match; allow reasonable action-phase/lighting differences.',
                'All essential narrative elements match; optional visual details may differ.'],
            essential_conflicts='Visible contradictions of scripted actor, key prop, holder, plot state or specified character-facing direction cannot pass at any level. Offscreen cropping alone is not a contradiction.')
    if has_input_groups(p):
        result.update(input_shot_groups=copy.deepcopy(p['input_shot_groups']), input_group_validation=input_partition(p))
    else:
        result['narrative_plan'] = copy.deepcopy(p.get('narrative_plan'))
    result['context_fingerprint'] = core.digest(result)
    return result


def current_review(p, project, gid):
    try:
        ctx = context(p, project, gid)
    except (ValueError, OSError):
        return None
    return next((r for r in reversed(p.get('reviews', [])) if r.get('group_id') == gid and
                 r.get('review_schema') == 6 and r.get('context_fingerprint') == ctx['context_fingerprint'] and
                 r.get('source_fingerprint') == ctx['source_fingerprint'] and not r.get('stale')), None)


def draft(ctx):
    from storyboard import CHECKS
    result = {k: copy.deepcopy(ctx[k]) for k in ('group_id', 'version', 'source_kind', 'source_fingerprint',
              'context_fingerprint', 'review_schema', 'reference_policy_version')}
    result.update(checks={k: 'uncertain' for k in ('shot', 'continuity', 'story')}, grouping_checked=False,
                  coverage=dict(shot_ids=[s['shot_id'] for s in ctx['shots']], limitations=[]),
                  shot_reviews=[], reference_assessments=[], evidence=[], issues=[], uncertainties=[],
                  asset_comparisons=[], repair_assessments=[], boundary_checks=[])
    for s in ctx['shots']:
        sid, image = s['shot_id'], s['image']
        result['evidence'].append(dict(shot_id=sid, path=image['path'], sha256=image['sha256'],
                                       observation='', visible_facts=[], interpretation=''))
        result['shot_reviews'].append(dict(shot_id=sid, verdict='uncertain', reason='', identity_reason='',
            reference_phase='unknown', phase_reason='', checks={k: 'uncertain' for k in sorted(CHECKS)},
            evidence_sha256=[image['sha256']], followup=''))
        result['reference_assessments'].append(dict(shot_id=sid, decision='pending', derivable=None,
            basis_shot_ids=[], evidence_sha256=[image['sha256']], reason=''))
    return result


@verified_read
def record_review(p, project, review):
    from storyboard import CHECKS
    from validation import text
    from asset_review import validate_asset_evidence
    from repair_cycle import validate_assessments
    ctx = context(p, project, review['group_id'])
    for key in ('version', 'source_kind', 'source_fingerprint', 'context_fingerprint', 'review_schema', 'reference_policy_version'):
        core.require(review.get(key) == ctx[key], '分镜图审查依据已变化，请重新校对：' + key)
    ids = [s['shot_id'] for s in ctx['shots']]
    core.require(review.get('boundary_checks', []) == [], '相邻图片连续性使用逐镜检查，不建立视频边界记录')
    core.require('video_sha256' not in review and 'mapping_verified' not in review.get('coverage', {}),
                 '图片审查不得制造视频或匹配记录')
    coverage = review.get('coverage', {})
    core.require(coverage.get('shot_ids') == ids and isinstance(coverage.get('limitations'), list), '整批覆盖信息不完整')
    checks = review.get('checks', {})
    core.require(set(checks) == {'shot', 'continuity', 'story'} and
                 all(v in ('PASS', 'FAIL', 'uncertain') for v in checks.values()), '整批审查结论不完整')
    if ctx['grouping_mode'] != 'input' and ctx.get('narrative_plan'):
        core.require(review.get('grouping_checked') is True, '需完成整批分组校对')
    for key in ('shot_reviews', 'reference_assessments', 'evidence'):
        core.require(isinstance(review.get(key), list) and [r.get('shot_id') for r in review[key]] == ids,
                     key + ' 必须按原顺序完整覆盖每镜一次')
    rows = {r['shot_id']: r for r in review['shot_reviews']}
    refs = {r['shot_id']: r for r in review['reference_assessments']}
    issues = review.get('issues', [])
    core.require(isinstance(issues, list) and len({i.get('id') for i in issues}) == len(issues), '问题编号必须唯一')
    for issue in issues:
        core.require(all(issue.get(k) for k in ('id', 'shot_ids', 'problem', 'expected', 'actual', 'evidence', 'fix')),
                     '问题需要明确的可见矛盾、脚本依据和图片修改建议')
        core.require(set(issue['shot_ids']) <= set(ids) and
                     all(rows[sid]['verdict'] == 'FAIL' for sid in issue['shot_ids']), '明确问题须定位到不符合的图片')
        core.require(issue.get('repair_target') == 'storyboard_image' and 'time_range' not in issue,
                     '图片问题须使用 storyboard_image，不得使用视频时间段')
        expected_paths = {core.resolve(project, s['image']['path']) for s in ctx['shots'] if s['shot_id'] in issue['shot_ids']}
        core.require(isinstance(issue['evidence'], list) and
                     {core.resolve(project, value) for value in issue['evidence']} == expected_paths,
                     '问题证据必须对应全部所指镜号的原图，不能借用其他图片')
        core.require(issue.get('severity') in ('low', 'medium', 'high', 'critical'), '问题严重程度无效')
    for s, evidence in zip(ctx['shots'], review['evidence']):
        sid, image = s['shot_id'], s['image']
        row, ref = rows[sid], refs[sid]
        core.require(not any(key in item for item in (row, ref, evidence)
                             for key in ('time', 'time_range', 'evidence_times', 'video_sha256')),
                     '图片审查不得制造视频时间或来源')
        core.require(core.resolve(project, evidence.get('path', '')) == core.resolve(project, image['path']) and
                     evidence.get('sha256') == image['sha256'] and 'time' not in evidence,
                     '审查证据必须绑定该镜原图与文件指纹')
        core.require(text(evidence.get('observation')), '原图可见观察不能为空')
        core.require(row.get('evidence_sha256') == [image['sha256']] and ref.get('evidence_sha256') == [image['sha256']],
                     '逐镜与省图结论须引用该镜原图')
        verdict, per = row.get('verdict'), row.get('checks', {})
        core.require(verdict in ('PASS', 'FAIL', 'uncertain') and text(row.get('reason')), '图片结论或理由无效')
        core.require(set(per) == CHECKS and all(v in ('PASS', 'FAIL', 'uncertain') for v in per.values()), '逐镜检查不完整')
        core.require(row.get('reference_phase') in ('entry', 'action', 'exit', 'unknown') and text(row.get('phase_reason')),
                     '需要说明参考图所处阶段及依据')
        localized = [i for i in issues if sid in i['shot_ids']]
        if verdict == 'PASS':
            core.require(all(v == 'PASS' for v in per.values()) and not localized and
                         s['requirements'] and s['requirements']['ready'] and row['reference_phase'] != 'unknown',
                         '通过需要明确阶段、就绪的脚本要求及所有检查通过')
        elif verdict == 'FAIL':
            core.require('FAIL' in per.values() and localized and 'FAIL' in checks.values(), '不符合需有明确可见矛盾')
        else:
            core.require('uncertain' in per.values() and 'FAIL' not in per.values() and text(row.get('followup')),
                         '待核查需说明具体无法确认的信息，不能隐藏明确错误')
        core.require(ref.get('decision') in ('anchor', 'ai_fill', 'pending') and text(ref.get('reason')) and
                     (ref.get('derivable') is None or type(ref.get('derivable')) is bool), '省图判断不完整')
        if verdict != 'PASS':
            core.require(ref['decision'] == 'pending' and ref.get('derivable') is not True, '不符合或待核查图片暂不省图')
        else:
            core.require(ref['decision'] == ('ai_fill' if ref.get('derivable') is True else 'anchor'), '省图结论矛盾')
        if ref['decision'] == 'ai_fill':
            basis = ref.get('basis_shot_ids', [])
            core.require(len(basis) == 2 and all(b in ids for b in basis) and ids.index(basis[0]) < ids.index(sid) < ids.index(basis[1]),
                         '省图需要前后两个依据镜头')
            core.require(all(rows[b]['verdict'] == 'PASS' and refs[b]['decision'] == 'anchor' for b in basis),
                         '省图依据须为通过且保留的原图，不能循环推导')
            core.require(s['asset_ids'] and all(any(a['id'] == aid and a['sha256'] != 'MISSING' for a in ctx['assets'])
                         for aid in s['asset_ids']), '省图需要当前资产依据')
    verdicts = [r['verdict'] for r in rows.values()]
    if 'uncertain' in verdicts:
        core.require('uncertain' in checks.values() or 'FAIL' in checks.values(), '待核查不得整批通过')
    if 'FAIL' in checks.values():
        core.require(issues and 'FAIL' in verdicts, '整批不符合须定位具体图片')
    if all(v == 'PASS' for v in checks.values()):
        core.require(all(v == 'PASS' for v in verdicts) and not review.get('uncertainties') and not coverage['limitations'],
                     '存在待核查信息不能整批通过')
    validate_asset_evidence(p, project, review, ctx)
    validate_assessments(p, review)
    result = copy.deepcopy(review)
    result.update(id=uuid.uuid4().hex, fingerprint=ctx['group_fingerprint'],
                  verdict='FAIL' if 'FAIL' in checks.values() else 'PASS' if all(v == 'PASS' for v in checks.values()) else 'uncertain')
    p.setdefault('reviews', []).append(result)
    return result['verdict']


def source_aspect(p, project, expected):
    rows = inputs(p, project)
    core.require(core.digest(rows) == expected, '图片已变化，请重新校对并判断阈值')
    ratios = list(dict.fromkeys(r['aspect_ratio'] for r in rows))
    target = ratios[0] if len(ratios) == 1 else p.get('storyboard_target_aspect')
    core.require(target, '分镜图混用画幅；校对可完成，导出提示词前请确定 storyboard_target_aspect')
    try:
        ratio = Fraction(str(target).replace(':', '/'))
        core.require(ratio > 0, '目标画幅必须为正数')
    except (ValueError, ZeroDivisionError):
        raise ValueError('目标画幅应为宽:高，例如 16:9') from None
    return dict(policy=1, source_kind='provided', source_fingerprint=expected,
                aspect_ratio=f'{ratio.numerator}:{ratio.denominator}', input_ratios=ratios,
                selection='common_images' if len(ratios) == 1 else 'explicit_target')
