"""Write each image conclusion once; expand existing, source-bound review records."""
from __future__ import annotations
import copy

import previs as core

CHECK_GROUPS = dict(content=('identity', 'scene', 'props'),
                    state=('key_state', 'continuity'), reference=('composition', 'cleanliness'))
CHECKS = {key for members in CHECK_GROUPS.values() for key in members}
CRITICAL_KINDS = {'missing_key_node', 'wrong_actor', 'broken_causality',
                  'wrong_transfer_result', 'explicit_key_requirement'}


def aggregate(values):
    values = list(values)
    return 'FAIL' if 'FAIL' in values else 'uncertain' if 'uncertain' in values else 'PASS'


def draft(ctx):
    core.require(ctx.get('review_scope', {}).get('view_policy') == 'single_pass',
                 '简短结论工作单只用于一次看图策略')
    result = dict(worklist_version=4, group_id=ctx['group_id'],
                  context_fingerprint=ctx['context_fingerprint'],
                  reviewed_groups=list(CHECK_GROUPS), grouping_checked=False,
                  limitations=[], asset_comparisons=[], shots=[])
    if ctx.get('review_overviews'):
        result['overview_manifest'] = copy.deepcopy(ctx['review_overviews']['manifest'])
    for shot in ctx['shots']:
        result['shots'].append(dict(shot_id=shot['shot_id'], verdict=None,
            reference_phase='unknown', match_level=None,
            observation=dict(visible_facts=[]), findings=[], unresolved=[]))
    return result


def row_records(shot, row):
    """A verdict explicitly covers all three groups; exceptions carry their own evidence."""
    sid = shot['shot_id']
    core.require(isinstance(row, dict) and row.get('shot_id') == sid, '简短结论须按原镜序填写')
    core.require(set(row) <= {'shot_id', 'verdict', 'reference_phase', 'match_level', 'observation',
                             'findings', 'unresolved', 'reference'}, '简短结论不另填重复的检查、问题或返修记录')
    verdict = row.get('verdict')
    core.require(verdict in ('PASS', 'FAIL', 'uncertain'), '每镜须明确判断三组检查的整体结论')
    findings, unresolved = row.get('findings', []), row.get('unresolved', [])
    core.require(isinstance(findings, list) and isinstance(unresolved, list), '问题和疑点须为列表')
    core.require((verdict == 'FAIL') == bool(findings), '仅 FAIL 必须填写明确错误；不能隐藏或凭空生成错误')
    core.require(verdict != 'uncertain' or bool(unresolved), '待核查须定位具体无法确认的信息')
    core.require(verdict != 'PASS' or not unresolved, '有未确认的必要信息不能通过')
    per = dict.fromkeys(CHECKS, 'PASS')
    issues, impacts, fixes = [], [], []
    critical_kind, damage, trigger_quote = None, None, None
    affects_story = False
    for index, finding in enumerate(findings, 1):
        core.require(isinstance(finding, dict) and finding.get('check') in CHECKS, '错误须定位到具体检查项')
        for key in ('script_quote', 'actual', 'fix'):
            core.require(isinstance(finding.get(key), str) and finding[key].strip(), '错误须填写 ' + key)
        core.require(finding['script_quote'] in shot['script'], '错误引文须逐字取自同镜脚本')
        kind = finding.get('kind')
        core.require(kind in CRITICAL_KINDS | {'ordinary', 'severe_visual_damage'}, '须明确错误种类')
        core.require(type(finding.get('affects_story')) is bool and finding.get('preserves_script') is True,
                     '须明确剧情影响及修正保留脚本原意')
        impact = finding.get('impact', '脚本：' + finding['script_quote'] + '；画面：' + finding['actual'])
        core.require(isinstance(impact, str) and impact.strip(), '须说明错误影响')
        if kind in CRITICAL_KINDS or kind == 'severe_visual_damage':
            core.require(finding['affects_story'] and isinstance(finding.get('impact'), str)
                         and finding['impact'].strip(), '关键错误或严重损坏须明确必要剧情受到的影响')
        if kind in CRITICAL_KINDS:
            critical_kind = critical_kind or kind
            trigger_quote = finding['script_quote']
        if kind == 'severe_visual_damage':
            trigger_quote = trigger_quote or finding['script_quote']
            for key in ('damage_description', 'obscured_content'):
                core.require(isinstance(finding.get(key), str) and finding[key].strip(), '严重损坏须说明 ' + key)
            if damage is None:
                damage = dict(damage_description=finding['damage_description'],
                              obscured_content=finding['obscured_content'], image_sha256=shot['image']['sha256'])
            else:
                damage['damage_description'] += '；' + finding['damage_description']
                damage['obscured_content'] += '；' + finding['obscured_content']
        per[finding['check']] = 'FAIL'
        issue = dict(id=f'I-{sid}-{index:02d}', shot_ids=[sid],
            severity='critical' if kind in CRITICAL_KINDS else 'high' if kind == 'severe_visual_damage' else 'medium',
            problem=finding['actual'], expected=finding['script_quote'], actual=finding['actual'],
            fix=finding['fix'], asset_ids=copy.deepcopy(finding.get('asset_ids', [])),
            asset_comparison_ids=copy.deepcopy(finding.get('asset_comparison_ids', [])))
        issues.append(issue)
        impacts.append(impact)
        fixes.append(finding['fix'])
        affects_story = affects_story or finding['affects_story']
    doubts = []
    for item in unresolved:
        core.require(isinstance(item, dict) and item.get('check') in CHECKS
                     and isinstance(item.get('reason'), str) and item['reason'].strip(),
                     '疑点须填写具体检查项和无法确认的信息')
        if per[item['check']] != 'FAIL':
            per[item['check']] = 'uncertain'
        doubts.append(item['reason'])
    target = copy.deepcopy(row)
    target.pop('findings', None)
    target.pop('unresolved', None)
    target.update(check_groups={key: aggregate(per[name] for name in members)
                               for key, members in CHECK_GROUPS.items()},
                  check_exceptions={key: value for key, value in per.items() if value != 'PASS'})
    if verdict == 'FAIL':
        target['reason'] = '；'.join(finding['actual'] for finding in findings)
    elif verdict == 'uncertain':
        target.update(reason='；'.join(doubts), followup='；'.join(doubts))
    target.setdefault('reference', dict(decision='anchor' if verdict == 'PASS' else 'pending',
                                       derivable=False if verdict == 'PASS' else None, basis_shot_ids=[]))
    assessment = None
    if findings:
        assessment = dict(shot_id=sid, critical=critical_kind is not None, critical_kind=critical_kind,
            affects_story=affects_story, script_quote=trigger_quote or findings[0]['script_quote'],
            issue_ids=[issue['id'] for issue in issues], impact='；'.join(impacts),
            correction='；'.join(fixes), preserves_script=True)
        if damage is not None:
            assessment['severe_visual_damage'] = damage
    return target, per, issues, assessment


def expand(ctx, data):
    core.require(set(data) <= {'worklist_version', 'group_id', 'context_fingerprint', 'reviewed_groups',
        'grouping_checked', 'limitations', 'asset_comparisons', 'shots', 'overview_manifest'},
        '简短工作单只写一次结论，不另填 checks、issues 或 repair_assessments')
    core.require(ctx.get('review_scope', {}).get('view_policy') == 'single_pass', '简短工作单须使用一次看图策略')
    core.require(data.get('reviewed_groups') == list(CHECK_GROUPS), '结论须明确覆盖主体内容、状态承接和参考可用性')
    core.require([row.get('shot_id') for row in data.get('shots', [])] == [s['shot_id'] for s in ctx['shots']],
                 '简短工作单须按原序完整覆盖每镜一次')
    result = {key: copy.deepcopy(data[key]) for key in
              ('group_id', 'context_fingerprint', 'grouping_checked', 'limitations', 'asset_comparisons')}
    if 'overview_manifest' in data:
        result['overview_manifest'] = copy.deepcopy(data['overview_manifest'])
    result.update(worklist_version=3, shots=[], issues=[], uncertainties=[], repair_assessments=[])
    checks = []
    for shot, row in zip(ctx['shots'], data['shots']):
        target, per, issues, assessment = row_records(shot, row)
        result['shots'].append(target)
        result['issues'].extend(issues)
        if assessment:
            result['repair_assessments'].append(assessment)
        checks.append(per)
    result['checks'] = dict(shot=aggregate(value for per in checks for value in per.values()),
        continuity=aggregate(per['continuity'] for per in checks),
        story=aggregate(per[key] for per in checks for key in ('identity', 'props', 'key_state')))
    if result['limitations'] and result['checks']['shot'] == 'PASS':
        result['checks']['shot'] = 'uncertain'
    return result
