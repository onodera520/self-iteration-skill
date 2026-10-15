"""Export a source-bound, audited prompt for the user to generate a new video."""
from pathlib import Path
import previs as core
import repair_prompt


def _line(text):
    return ' '.join(text.split())


def _sentences(parts):
    return '。'.join(_line(part).rstrip('。') for part in parts if part and part.strip()) + '。'


def render_prompt(p, request):
    """Render the user's plain prompt layout from a validated internal request.

    Version 6 uses a source-bound, audited body. The source view retains its
    stored contributions and target phase, without extra scope commentary.
    """
    assets = {a['id']: a for a in (request['asset_descriptions'] if request.get('prompt_version') == 6 else p['assets'])}
    adaptations = request.get('visual_adaptations', {})

    def visual(path, source):
        return adaptations.get(path, {}).get('visual_text', source)

    mapping = []
    for i, asset in enumerate(request['assets'], 1):
        aid = asset['id']
        description = visual(f'asset.{aid}.description', assets[aid].get('description', ''))
        mapping.append(f'图{i}是{_line(description) or aid}')
    lines = ['，'.join(mapping) + '，以下内容是具体的分镜脚本：']
    for i, block in enumerate(request['blocks'], 1):
        compiled = request.get('prompt_version') == 6
        body = [block['compiled_content'] if compiled else block['generation_text']]
        if not compiled:
            if block.get('correction'):
                body.append(block['correction'])
            body.extend(block.get('input_prompt_guidance', []))
            body.extend(block.get('critical_changes', []))
        target = block.get('keyframe_target')
        if target and not compiled:
            phase = {'entry': '起态', 'action': '动作中', 'exit': '终态'}[target['phase']]
            body.append(f'{phase}画面：{target["description"]}')
        line = (f'镜头{i},【时长】1s。【镜头设计】{_line(block["design"]).rstrip("。")}。'
                f'【镜头内容】{_sentences(body)}')
        for name, label in (('must_have', '本镜必须出现'), ('must_not_have', '本镜不得出现')):
            if block.get(name):
                line += f'【{label}】' + '；'.join(_line(value) for value in block[name])
        lines += ['', line]
    fixed = ['参考上传的图片，' + request['previs_directive'],
             '小幅运动仍须清楚呈现原脚本的关键动作和结果，全部镜头按上述顺序各自独立硬切，不得遗漏、合并或重排',
             repair_prompt.SILENT_DIRECTIVE]
    fixed.extend(request.get('format_requirements', []))
    origin = {'common_images': '分镜图的共同画幅', 'most_images': '画幅'}.get(
        request['input_aspect']['selection'], '已确定的目标画幅')
    fixed.append(f'采用{origin} {request["aspect_ratio"]}')
    lines += ['', _sentences(fixed)]
    style = []
    for i, row in enumerate(request['asset_style']['assets'], 1):
        guidance = visual(f'asset.{row["asset_id"]}.guidance', row['guidance'])
        style.append(f'图{i}：{guidance}')
    style.append('资产风格仅约束视觉表现；资产展示背景不替代剧情背景，人物关系、动作与时空按脚本')
    lines += ['', _sentences(style), '']
    content = '\n'.join(lines)
    core.require(all(content.count(tag) == len(request['blocks'])
                     for tag in ('【时长】', '【镜头设计】', '【镜头内容】')),
                 'Prompt delivery contains duplicate shot headers')
    core.require(not repair_prompt.speech_signals(content.replace(repair_prompt.SILENT_DIRECTIVE, '')),
                 'Prompt delivery contains speech/audio/text instructions')
    return content


def export_prompt(p, project, gid, output):
    import repair_cycle as repair

    # Standalone exports still reconstruct against current evidence. The combined
    # finish command builds the same request once under its existing project lock.
    return _export_request(p, project, gid, output, repair.make_prompt(p, project, gid))


def check_output(p, output):
    """Current image cases accept new prompts; frozen evidence is never a target."""
    output = Path(output).resolve()
    core.require(output.suffix.lower() == '.md', 'Prompt delivery must be a Markdown file')
    current = p.get('repair_deliveries', {}).get('original')
    frozen = list(p.get('repair_deliveries', {}).values())
    frozen += [item['record'] for item in p.get('repair_delivery_history', [])]
    for record in frozen:
        root = Path(record['path']).resolve().parent
        if not output.is_relative_to(root):
            continue
        core.require(record is current and record.get('delivery_format_version', 1) >= 3
                     and output.parent in (root, root / '新视频提示词')
                     and str(output) not in record['files'],
                     'Prompt output would modify a frozen report/image or historical delivery')
        from finish_review import intact
        intact(record)
        delivery_prompt_files(p, root)


def delivery_prompt_files(p, root):
    """Only registered, unchanged prompt exports may extend a case's file set."""
    root, result = Path(root).resolve(), set()
    for history in p.get('repair_prompt_exports', {}).values():
        for record in history:
            path = Path(record['path']).resolve()
            if not path.is_relative_to(root):
                continue
            source = Path(record['request_path']).resolve()
            core.require(path.parent in (root, root / '新视频提示词') and path.suffix.lower() == '.md'
                         and not source.is_relative_to(root), 'Invalid prompt export location in delivery')
            core.require(path.is_file() and core.sha(path) == record['sha256']
                         and source.is_file() and core.sha(source) == record['request_sha256'],
                         'Immutable prompt export changed')
            result.add(str(path))
    return result


def _export_request(p, project, gid, output, request):
    """Internal writer for a freshly compiled request, under the caller's lock."""
    import repair_cycle as repair

    project, output = Path(project).resolve(), Path(output).resolve()
    check_output(p, output)
    # Reuse the complete source/evidence/visual-text checks. Workflow availability,
    # provider limits and payment allowance are not prerequisites for a text export.
    repair_prompt.validate(request, [block['shot_id'] for block in request['blocks']])
    content = render_prompt(p, request)
    core.require(not output.exists() or output.read_text(encoding='utf-8') == content,
                 'Prompt delivery already exists with different content; choose a new output path')
    # Immutable internal snapshot; no tasks, execution status or quota reservations.
    internal = project.parent / '.repair' / f'{gid}-export-v{request["prompt_version"]}-{core.digest(request)[:12]}.json'
    repair.save_prompt(internal, request, explicit=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.exists():
        with output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
    record = dict(path=str(output), sha256=core.sha(output), request_path=str(internal),
                  request_sha256=core.sha(internal), request_fingerprint=core.digest(request),
                  decision_fingerprint=request['decision_fingerprint'], binding=request['binding'])
    history = p.setdefault('repair_prompt_exports', {}).setdefault(gid, [])
    if record not in history:
        history.append(record)
    return record
