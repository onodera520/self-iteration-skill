"""Small, lossless semantic views and disk-backed progress for agent reading.

Views are conveniences, never evidence or approval. Full contexts and frozen
receipts stay on disk; normal review validation remains authoritative.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def reading_view(ctx, shot_ids=None):
    """Keep scripts/states verbatim, share repeated requirements, omit file hashes."""
    view = copy.deepcopy({key: value for key, value in ctx.items() if key not in
                          ('source_fingerprint', 'group_fingerprint', 'review_overviews')})
    ids = [s['shot_id'] for s in ctx['shots']]
    if shot_ids is not None:
        requested = list(shot_ids)
        if not requested or len(set(requested)) != len(requested) or not set(requested) <= set(ids):
            raise ValueError('镜号须非空、不重复，且属于本批输入')
        positions = {i for i, sid in enumerate(ids) if sid in requested}
        included = {j for i in positions for j in (i - 1, i, i + 1) if 0 <= j < len(ids)}
        view['shots'] = [s for i, s in enumerate(view['shots']) if i in included]
        view['requested_shot_ids'] = requested
        view['batch_shot_ids'] = ids
    for asset in view['assets']:
        asset.pop('sha256', None)
    counts = Counter(encoded(value) for s in view['shots'] for value in s['requirements'].values())
    shared, names = {}, {}
    for shot in view['shots']:
        shot['image'].pop('sha256', None)
        for field, value in shot['requirements'].items():
            key = encoded(value)
            if counts[key] < 2 or len(key) < 64:
                continue
            if key not in names:
                name = 'R' + str(len(names) + 1).zfill(2)
                names[key] = name
                shared[name] = value
            shot['requirements'][field] = {'$ref': names[key]}
    view.update(view_version=1, shared_requirements=shared,
                reading_rule='requirements 中 {$ref:Rxx} 的完整值见 shared_requirements；原文未摘要。'
                             '此视图不构成证据或审查结论，指纹由工具校验。')
    if ctx.get('review_overviews'):
        view['overview_pages'] = [{key: page[key] for key in ('path', 'shot_ids')}
                                  for page in ctx['review_overviews']['pages']]
    return view


def batch_view(ctx, page_number):
    """Read one nine-shot page, its boundary neighbours and explicitly used assets."""
    pages = ctx.get('review_overviews', {}).get('pages', [])
    if type(page_number) is not int or not 1 <= page_number <= len(pages):
        raise ValueError('页码须为本批总览的有效正整数')
    page = pages[page_number - 1]
    view = reading_view(ctx, page['shot_ids'])
    asset_ids = {aid for shot in view['shots'] for aid in shot.get('asset_ids', [])}
    asset_ids.update(shot.get('scene_id') for shot in view['shots'])
    # State requirements may refer to offscreen assets omitted from asset_ids.
    def state_assets(value):
        if isinstance(value, dict):
            for key, item in value.items():
                asset_ids.add(key.split('.', 1)[0])
                state_assets(item)
        elif isinstance(value, list):
            for item in value:
                state_assets(item)
        elif isinstance(value, str):
            asset_ids.add(value)
    included = {s['shot_id'] for s in view['shots']}
    for shot in ctx['shots']:
        if shot['shot_id'] in included:
            state_assets(shot['requirements'])
    view['assets'] = [dict(asset, visual_label=f'A{index:02d}')
                      for index, asset in enumerate(view['assets'], 1) if asset['id'] in asset_ids]
    original_paths = {a['asset_id']: a['path'] for a in ctx['review_overviews'].get('asset_images', [])}
    for asset in view['assets']:
        if asset['id'] in original_paths:
            asset['original_image_path'] = original_paths[asset['id']]
    view['overview_pages'] = [{key: page[key] for key in ('path', 'shot_ids')}]
    view['batch_page'] = page_number
    view['batch_page_count'] = len(pages)
    view['boundary_neighbor_shot_ids'] = [s['shot_id'] for s in view['shots']
                                         if s['shot_id'] not in page['shot_ids']]
    view['images_to_open'] = [dict(role='storyboards', path=page['path'], shot_ids=page['shot_ids'])]
    single = ctx.get('review_scope', {}).get('view_policy') == 'single_pass'
    sheets = [] if single else ctx['review_overviews'].get('asset_sheets', [])
    view['images_to_open'].extend(dict(role='assets', path=sheet['path'],
                                      asset_ids=sheet['asset_ids'], visual_labels=sheet['visual_labels'])
                                  for sheet in sheets if sheet['path'] in page.get('asset_sheet_paths', []))
    # The next page reviews the next boundary. Only its preceding original is needed here.
    before = next((s for s in view['shots'] if s['shot_id'] not in page['shot_ids']), None)
    if not single and before and before['shot_id'] == view['shots'][0]['shot_id']:
        view['images_to_open'].append(dict(role='previous_boundary', path=before['image']['path'],
                                           shot_ids=[before['shot_id']]))
    view['batch_rule'] = ('本页镜号逐镜判断；相邻镜号只作连续性背景，不代表已审查。'
                          '同一批已看清且未变化的原资产可复用；每张分镜的实际可见事实仍须单独记录。'
                          '总览不清的关键细节集中打开原图；不能由其他图片推定本图通过。')
    if single:
        view['batch_rule'] = ('每张分镜只看一次，三组检查和三级放宽在同一次观察中完成。'
            '首看已保存且来源未变的可见事实直接复用，不再次打开本页；未看过的页只显示一次。'
            '不默认显示或拼接原资产；跨页连续性使用 saved_rows 中相邻镜的可见事实。'
            '核心矛盾直接 FAIL；关键细节看不清记 uncertain，写明疑点后交付，不放大或排队复查。'
            '三级均须满足全部必要剧情元素，不以多数元素相似抵消关键矛盾，不重新选帧。')
    return view


def progress(data, ctx=None):
    """Describe saved records only; never certify them or infer PASS."""
    recorded, needs_recording, uncertain, incomplete = [], [], [], []
    check_keys = {'identity', 'scene', 'props', 'composition', 'key_state', 'continuity', 'cleanliness'}
    for row in data['shots']:
        sid = row['shot_id']
        concise_valid = True
        if data.get('worklist_version') == 4:
            from storyboard_conclusions import row_records
            shot = next((s for s in (ctx or {}).get('shots', []) if s['shot_id'] == sid), None)
            try:
                if shot is None:
                    raise ValueError('Current context required for concise progress')
                row, _, _, _ = row_records(shot, row)
            except ValueError:
                concise_valid = False
        observation = row.get('observation')
        facts = observation.get('visible_facts') if isinstance(observation, dict) else None
        has_facts = isinstance(facts, list) and bool(facts) and all(isinstance(f, str) and f.strip() for f in facts)
        (recorded if has_facts else needs_recording).append(sid)
        if row.get('verdict') == 'uncertain':
            uncertain.append(sid)
        checks = row.get('checks', {})
        if data.get('worklist_version') in (3, 4):
            from prepare_storyboards import expand_check_groups
            try:
                checks = expand_check_groups(row)
            except ValueError:
                checks = {}
        ref = row.get('reference', {})
        fields_present = (concise_valid and has_facts and isinstance(checks, dict) and set(checks) == check_keys
                          and all(v in ('PASS', 'FAIL', 'uncertain') for v in checks.values())
                          and row.get('verdict') in ('PASS', 'FAIL', 'uncertain')
                          and row.get('reference_phase') in ('entry', 'action', 'exit', 'unknown')
                          and isinstance(ref, dict) and all(k in ref for k in
                              ('decision', 'derivable', 'basis_shot_ids')))
        if row.get('verdict') != 'PASS':
            fields_present = fields_present and isinstance(row.get('reason'), str) and bool(row['reason'].strip())
        if row.get('verdict') == 'uncertain':
            fields_present = fields_present and isinstance(row.get('followup'), str) and bool(row['followup'].strip())
        if not fields_present:
            incomplete.append(sid)
    return dict(recorded_shot_ids=recorded, needs_recording_shot_ids=needs_recording,
                uncertain_shot_ids=uncertain, incomplete_record_shot_ids=incomplete,
                validated=False, meaning='仅统计已保存字段；不代表看图完成、通过或可交付。'
                '全部结论、分组、问题、省图及提示词仍须最终整批校验。')


def cli_summary(action, result, run_dir=None):
    """Keep large evidence/file manifests on disk rather than in model context."""
    if action == 'prepare':
        summary = {key: result[key] for key in ('group_id', 'context', 'worklist', 'review_view', 'run_receipt')}
        summary['overview_pages'] = [{key: page[key] for key in ('path', 'shot_ids')}
                                     for page in result['review_overviews']['pages']]
        if result['review_overviews'].get('review_batches'):
            summary['review_batches'] = result['review_overviews']['review_batches']
        if result.get('reused_observation_shot_ids'):
            summary['reused_observation_shot_ids'] = result['reused_observation_shot_ids']
            summary['view_rule'] = '这些镜头复用首看记录，不再次打开图片；仍须根据对应脚本填写明确结论。'
        if 'initial_reuse' in result['review_overviews']:
            summary['initial_reuse'] = result['review_overviews']['initial_reuse']
        if result.get('worklist_version') == 4:
            summary['writing_rule'] = '简短结论工作单：每镜判断覆盖三组；错误只写 findings 一次，疑点只写 unresolved；其余记录由 complete 展开。'
        return summary
    if action != 'complete':
        return result
    summary = {key: result[key] for key in ('status', 'seconds', 'prompt_status', 'prompt_next_action',
               'prompt_inputs', 'prompt_plan', 'prompt_work', 'prompt_work_view', 'prompt_output',
               'delivery_next_action', 'error') if key in result}
    if run_dir is not None:
        directory = Path(run_dir).resolve()
        summary['finish_report'] = str(directory / 'FINISH_REPORT.json')
        summary['finish_view'] = str(directory / 'FINISH.view.json')
        if result.get('prompt_plan'):
            summary['prompt_view'] = str(directory / 'PROMPT.view.json')
    delivery = result.get('delivery', {})
    summary['delivery'] = (delivery if isinstance(delivery, str) else
                           {key: delivery[key] for key in ('path', 'delivery_format_version') if key in delivery})
    summary['validation'] = copy.deepcopy(result.get('validation', {}))
    summary['decision'] = {key: result['decision'][key] for key in
                           ('triggered', 'trigger', 'error_count', 'total', 'ratio', 'problem_shot_ids')
                           if key in result.get('decision', {})}
    return summary
