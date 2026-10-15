"""Register raw inputs, then compile one explicit review into the existing workflow."""
from __future__ import annotations
import argparse
import copy
from pathlib import Path
import re
import uuid

import previs as core
import prepare_storyboards as batch
import script_input
import storyboard_overviews as overviews
from evidence_runtime import evidence_operation
from review_timing import utc_now
from storyboard_conclusions import row_records
from validation import Report, text, text_array


FIXED_SHOT = ('id', 'script', 'duration', 'duration_source', 'shot_design', 'image')
INTENT = ('critical_result', 'narrative_turn', 'required_cut')
IMAGE_NUMBER = re.compile(r'(?:S|镜头)?(\d+)', re.IGNORECASE)
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}


def numbered_images(directory, shots):
    """Accept exact shot-number filenames only; never guess narrative correspondence."""
    directory = Path(directory).resolve()
    core.require(directory.is_dir(), '图片目录不存在：' + str(directory))
    found = {}
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        match = IMAGE_NUMBER.fullmatch(path.stem)
        core.require(match is not None, '图片文件名须为镜号（如 1.png、S01.png）；其他顺序请用 --images 有序列表')
        number = int(match[1])
        core.require(number not in found, '同一镜号有多张图片：' + str(number))
        found[number] = str(path)
    numbers = [int(s['id'][1:]) for s in shots]
    core.require(set(found) == set(numbers), '图片镜号须完整对应脚本，不能缺镜或混入其他编号')
    return [found[n] for n in numbers]


def read_groups(path, ids):
    """Parse explicit lists, not free-form grouping instructions or inferred ranges."""
    path = Path(path).resolve()
    if path.suffix.lower() == '.json':
        groups = core.read(path)
    else:
        groups = []
        for line in path.read_bytes().decode('utf-8-sig').splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r'\s*[^:：]+[:：]\s*((?:S?\d+\s*[,，、\s]*?)+)\s*', line, re.IGNORECASE)
            core.require(match is not None, '分组格式须为“shot1：1、2、3”；其他格式请用 JSON 镜号列表')
            groups.append(re.findall(r'S?\d+', match[1], re.IGNORECASE))
    core.require(isinstance(groups, list) and groups, '分组须为非空列表')
    normalized = []
    for group in groups:
        core.require(isinstance(group, list) and group, '每组须为非空镜号列表')
        row = []
        for sid in group:
            value = str(sid)
            core.require(re.fullmatch(r'S?\d+', value, re.IGNORECASE) is not None, '分组镜号无效：' + value)
            row.append(f'S{int(value.lstrip("Ss")):02d}')
        normalized.append(row)
    core.require([sid for group in normalized for sid in group] == ids, '分组须按原镜序完整覆盖每镜一次')
    return normalized


def register_assets(specs):
    assets = []
    for index, spec in enumerate(specs or [], 1):
        kind, separator, value = spec.partition('=')
        core.require(separator and kind in ('character', 'scene', 'prop') and value,
                     '--asset 须为 character=路径、scene=路径或 prop=路径')
        path = Path(value).resolve()
        core.require(path.is_file(), '原资产不存在：' + str(path))
        assets.append(dict(id=f'A{index:02d}', kind=kind, path=str(path), description=path.stem))
    core.require(len({a['path'] for a in assets}) == len(assets), '原资产路径不得重复登记')
    return assets


def start(script, delivery, *, images_dir=None, images_file=None, assets=None, groups=None,
          original_prompt=None, run_dir=None):
    delivery = Path(delivery).resolve()
    run = Path(run_dir).resolve() if run_dir else delivery.parent / '.storyboard-internal' / (
        delivery.name + '-' + uuid.uuid4().hex[:10])
    core.require(not run.is_relative_to(delivery) and not delivery.is_relative_to(run),
                 '内部记录和交付须使用独立目录')
    core.require(batch.delivery_available(delivery), '交付须使用新目录或空目录，不覆盖已有交付')
    core.require(not run.exists(), '内部记录须使用新目录；已有任务请继续填写 REVIEW.json 或 submit')
    core.require((images_dir is None) != (images_file is None), '须提供 --images-dir 或 --images 之一')
    started_at = utc_now()
    with evidence_operation():
        script = Path(script).resolve()
        raw = script.read_bytes().decode('utf-8-sig')
        shots = script_input.parse(raw, script.name)
        supplied = numbered_images(images_dir, shots) if images_dir else core.read(images_file)
        image_base = Path(images_dir).resolve() if images_dir else Path(images_file).resolve().parent
        data = script_input.read_input(script, supplied, image_base=image_base)
        core.require(data['source_script'] == raw, '登记时脚本已变化，请重试')
        data['assets'] = register_assets(assets)
        if groups:
            data['input_shot_groups'] = read_groups(groups, [s['id'] for s in data['shots']])
        dependencies = [script] + [Path(s['image']) for s in data['shots']] + [Path(a['path']) for a in data['assets']]
        dependencies += [Path(p).resolve() for p in (groups, images_file) if p]
        core.require(all(not p.is_relative_to(delivery) and not p.is_relative_to(run) for p in dependencies),
                     '原始输入须与新交付和内部输出分开')
        bindings = [dict(path=str(p), sha256=core.sha(p)) for p in dict.fromkeys(dependencies)]
        first = overviews.build_initial(data, run / 'first')
    # Save only after evidence_operation has verified every registered input again.
    core.save(run / 'first/INPUT.draft.json', data)
    session = dict(session_version=1, started_at=started_at, run_dir=str(run), delivery=str(delivery),
        project=str(run / 'PROJECT.json'), input_fingerprint=core.digest(data), bindings=bindings,
        first_manifest=first['manifest'],
        original_prompt=str(Path(original_prompt).resolve()) if original_prompt else None)
    review = dict(review_version=1, session_fingerprint=core.digest(session), title=data['title'],
        assets=copy.deepcopy(data['assets']), input_shot_groups=copy.deepcopy(data.get('input_shot_groups')),
        defaults=dict(scene_id=None, continuity_id=None, intent=dict.fromkeys(INTENT)),
        reviewed_groups=list(batch.CHECK_GROUPS), grouping_checked=False,
        limitations=[], asset_comparisons=[], shots=[])
    for shot in data['shots']:
        row = {key: copy.deepcopy(shot[key]) for key in FIXED_SHOT}
        row.update(asset_ids=[], purpose=None, phase=None, must_have=[],
                   visible_facts=[], verdict=None, match_level=None, findings=[], unresolved=[])
        review['shots'].append(row)
    core.save(run / 'SESSION.json', session)
    core.save(run / 'REVIEW.json', review)
    return dict(status='unreviewed', session=str(run / 'SESSION.json'), review=str(run / 'REVIEW.json'), project=session['project'],
                pages=first['pages'], shots=len(shots),
                next_action='立即显示 pages；一次填写 REVIEW.json，随后 submit SESSION.json。原文、镜序、路径和时长由工具维护。')


def load_session(value):
    path = Path(value).resolve()
    if path.is_dir():
        path /= 'SESSION.json'
    session = core.read(path)
    core.require(isinstance(session, dict) and session.get('session_version') == 1
                 and path == Path(session.get('run_dir', '')) / 'SESSION.json', 'SESSION 来源或目录不一致')
    return session


def compile_review(session, review):
    """Expand explicit semantic fields and preserve the raw script mechanically."""
    run = Path(session['run_dir'])
    data = core.read(run / 'first/INPUT.draft.json')
    core.require(core.digest(data) == session['input_fingerprint'], '原始输入草稿已变化')
    core.require(isinstance(review, dict) and review.get('review_version') == 1
                 and review.get('session_fingerprint') == core.digest(session), '审查表的 SESSION 绑定已变化')
    core.require(set(review) <= {'review_version', 'session_fingerprint', 'title', 'assets', 'input_shot_groups',
        'defaults', 'reviewed_groups', 'grouping_checked', 'limitations', 'asset_comparisons', 'shots'},
        '审查表含未知字段，不能静默忽略判断')
    for key in ('title', 'assets', 'input_shot_groups'):
        core.require(review.get(key) == data.get(key), '审查表的原始字段已变化：' + key)
    rows = review.get('shots')
    core.require(isinstance(rows, list) and len(rows) == len(data['shots']), '审查表须覆盖全部原镜头')
    report = Report()
    defaults = review.get('defaults', {})
    core.require(isinstance(defaults, dict) and set(defaults) <= {'scene_id', 'continuity_id', 'intent'},
                 'defaults 只填写明确共享的场景、连续段与 intent')
    compiled = []
    asset_ids = {a['id'] for a in data['assets']}
    for shot, row in zip(data['shots'], rows):
        core.require(isinstance(row, dict), '审查镜头须为对象')
        core.require(set(row) <= set(FIXED_SHOT) | {'scene_id', 'continuity_id', 'intent', 'asset_ids', 'purpose',
            'phase', 'keyframe_phase', 'keyframe_description', 'must_have', 'provenance', 'visible_facts',
            'verdict', 'match_level', 'findings', 'unresolved'}, '逐镜含未知字段；状态建模或省图请用原 prepare 入口')
        for key in FIXED_SHOT:
            core.require(row.get(key) == shot[key], '原文、镜序、路径或时长被改动：' + shot['id'] + '.' + key)
        where = 'shots[' + shot['id'] + ']'
        scene = row.get('scene_id', defaults.get('scene_id'))
        continuity = row.get('continuity_id', defaults.get('continuity_id'))
        intent = row.get('intent', defaults.get('intent'))
        valid = report.check(text(scene), where + '.scene_id', '须明确场景，可填在 defaults')
        valid = report.check(text(continuity), where + '.continuity_id', '须明确连续段，可填在 defaults') and valid
        valid = report.check(isinstance(intent, dict) and set(intent) == set(INTENT)
                             and all(type(v) is bool for v in intent.values()),
                             where + '.intent', '三个剧情标记须明确布尔值，可填在 defaults') and valid
        valid = report.check(text(row.get('purpose')), where + '.purpose', '须填写本镜简短剧情目的') and valid
        valid = report.check(text_array(row.get('asset_ids')) and set(row['asset_ids']) <= asset_ids,
                             where + '.asset_ids', '须引用登记的原资产 ID') and valid
        phase = row.get('phase')
        key_phase = row.get('keyframe_phase', phase)
        valid = report.check(phase in ('entry', 'action', 'exit', 'unknown'), where + '.phase', '须填写实际参考阶段') and valid
        valid = report.check(key_phase in ('entry', 'action', 'exit'), where + '.keyframe_phase',
                             'unknown 阶段须另填 keyframe_phase，不能猜计划阶段') and valid
        valid = report.check(text_array(row.get('must_have')), where + '.must_have', '必要内容须为文字列表') and valid
        target_description = row.get('keyframe_description')
        if target_description is None and text_array(row.get('must_have')):
            target_description = '；'.join(row['must_have'])
        valid = report.check(text(target_description), where + '.keyframe_description',
                             '目标描述复用具体 must_have；无必要内容时须另填可见画面描述，不能用剧情目的代替') and valid
        valid = report.check(text_array(row.get('visible_facts')) and bool(row['visible_facts']),
                             where + '.visible_facts', '须填写实际观察，不自动批准空白镜头') and valid
        valid = report.check((type(row.get('match_level')) is int and 0 <= row['match_level'] <= 3)
                             if row.get('verdict') == 'PASS' else row.get('match_level') is None,
                             where + '.match_level', 'PASS 须填 0–3，其他结论须为 null') and valid
        for key in ('keyframe_description', 'provenance'):
            if key in row:
                valid = report.check(text(row[key]) if key == 'keyframe_description' else isinstance(row[key], list),
                                     where + '.' + key, '可选要求字段格式无效') and valid
        observation = dict(visible_facts=copy.deepcopy(row.get('visible_facts', [])))
        work = dict(shot_id=shot['id'], verdict=row.get('verdict'), reference_phase=phase,
                    match_level=row.get('match_level'), observation=observation,
                    findings=copy.deepcopy(row.get('findings', [])), unresolved=copy.deepcopy(row.get('unresolved', [])))
        if valid:
            try:
                # Catch missing/error evidence before creating a formal project or delivery.
                row_records(dict(shot_id=shot['id'], script=shot['script'],
                    image=dict(sha256=next(b['sha256'] for b in session['bindings'] if b['path'] == shot['image']))), work)
            except ValueError as exc:
                report.check(False, where, str(exc))
            shot.update(scene_id=scene, continuity_id=continuity, intent=copy.deepcopy(intent),
                asset_ids=copy.deepcopy(row['asset_ids']), required_result=row['purpose'],
                requirements=dict(status='ready', keyframe=dict(phase=key_phase,
                    description=target_description), must_have=copy.deepcopy(row['must_have']),
                    provenance=copy.deepcopy(row.get('provenance', [dict(field='purpose,keyframe,must_have',
                        status='script', source=data['title'] + '：' + shot['id'])]))))
        compiled.append(work)
    report.check(review.get('grouping_checked') is True, 'grouping_checked', '须明确核对分组')
    report.check(review.get('reviewed_groups') == list(batch.CHECK_GROUPS), 'reviewed_groups', '须覆盖主体、状态和参考可用性三组')
    report.check(text_array(review.get('limitations')), 'limitations', '限制须为文字列表')
    report.check(review.get('asset_comparisons') == [], 'asset_comparisons', '显式资产对照或状态建模请用原 prepare 入口')
    report.finish()
    return data, compiled


def submit(session_file):
    session = load_session(session_file)
    run = Path(session['run_dir'])
    with core.locked(run / 'SUBMISSION.json'):
        with evidence_operation():
            for binding in session['bindings']:
                core.require(core.sha(binding['path']) == binding['sha256'], '输入已变化，须另建审查：' + binding['path'])
            review = core.read(run / 'REVIEW.json')
            data, rows = compile_review(session, review)
            receipt_path = run / 'SUBMISSION.json'
            receipt = dict(review_fingerprint=core.digest(review), input_fingerprint=core.digest(data))
            if receipt_path.exists():
                core.require(core.read(receipt_path) == receipt, '已提交的判断发生变化；请另建审查，不覆盖原交付')
            # Validate the first-look binding before prepare can fall back to regenerated sheets.
            manifest = session['first_manifest']
            core.require(core.sha(manifest['path']) == manifest['sha256'], '首看清单已变化，不能复用旧判断')
            for page in core.read(manifest['path'])['pages']:
                core.require(core.sha(page['path']) == page['sha256']
                             and core.sha(page['view']['path']) == page['view']['sha256'], '首看材料已变化，须另建审查')
            source_bindings = copy.deepcopy(session['bindings']) + [
                dict(path=str(run / 'REVIEW.json'), sha256=core.sha(run / 'REVIEW.json')),
                dict(path=manifest['path'], sha256=manifest['sha256'])]
            for page in core.read(manifest['path'])['pages']:
                source_bindings.extend([dict(path=page['path'], sha256=page['sha256']),
                                        dict(path=page['view']['path'], sha256=page['view']['sha256'])])
        if (run / 'finish/FINISH_REPORT.json').exists():
            result = core.read(run / 'finish/FINISH_REPORT.json')
            core.require(result.get('status') == 'complete', '已有失败的收尾记录，请按该记录定位修复，不重复生成')
            from finish_review import validate_delivery
            validate_delivery(core.read(session['project']), 'original', session['project'])
            return dict(result, project=session['project'])
        core.require(batch.delivery_available(Path(session['delivery'])), '交付目录已有文件，不覆盖')
        if not (run / 'prepare').exists():
            # Both sidecars are generated from the single reviewed table, never filled twice.
            observations = core.read(run / 'first/OBSERVATIONS.json')
            for target, row in zip(observations['shots'], rows):
                target['visible_facts'] = copy.deepcopy(row['observation']['visible_facts'])
            core.save(run / 'first/OBSERVATIONS.json', observations)
            core.save(run / 'INPUT.json', data)
            prepared = batch.prepare(session['project'], None, run / 'prepare', input_data=data,
                original_prompt_file=session['original_prompt'], output=session['delivery'],
                reuse_overviews=run / 'first', concise=True, source_bindings=source_bindings)
            work = core.read(prepared['worklist'])
            work.update(reviewed_groups=review['reviewed_groups'], grouping_checked=True,
                        limitations=review['limitations'], shots=rows)
            core.save(prepared['worklist'], work)
            core.save(receipt_path, receipt)
        else:
            core.require(receipt_path.exists(), '存在未完成的准备记录，请用原 resume 入口恢复')
        result = batch.complete(session['project'], run / 'prepare/WORKLIST.json',
                                session['delivery'], run / 'finish', source_bindings=source_bindings)
        return dict(result, project=session['project'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    first = actions.add_parser('start', help='Register inputs and generate first-look sheets plus one review table')
    first.add_argument('script')
    mapping = first.add_mutually_exclusive_group(required=True)
    mapping.add_argument('--images-dir', help='Images named exactly by shot number, such as 1.png or S01.png')
    mapping.add_argument('--images', dest='images_file', help='Ordered JSON paths or shot_id/path rows')
    first.add_argument('--asset', dest='assets', action='append', help='character=PATH, scene=PATH or prop=PATH; repeat per asset')
    first.add_argument('--groups', help='Explicit JSON lists or numbered lines such as shot1：1、2、3')
    first.add_argument('--original-prompt', help='Register only; read after the threshold triggers')
    first.add_argument('--delivery', required=True)
    first.add_argument('--run-dir', help='Optional new internal directory outside delivery')
    done = actions.add_parser('submit', help='Compile the filled REVIEW.json and finish the report in one command')
    done.add_argument('session_file', help='SESSION.json path or its directory')
    args = vars(parser.parse_args())
    action = args.pop('action')
    try:
        result = start(**args) if action == 'start' else submit(**args)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    import json
    if action == 'submit':
        result = {k: v for k, v in result.items() if k in (
            'status', 'project', 'decision', 'delivery', 'validation', 'seconds', 'ended_at', 'prompt_status',
            'prompt_work', 'prompt_work_view', 'prompt_output', 'delivery_next_action')}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
