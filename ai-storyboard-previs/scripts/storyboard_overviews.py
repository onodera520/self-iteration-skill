"""Numbered 3x3 review sheets derived from the already-bound original images."""
import copy
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
import previs as core
from evidence_runtime import evidence_operation


PER_PAGE = 9
COLUMNS = ROWS = 3
TILE = (640, 360)
LABEL = 32
GAP = 12
PAGE = (COLUMNS * TILE[0] + (COLUMNS + 1) * GAP,
        ROWS * (TILE[1] + LABEL) + (ROWS + 1) * GAP)


def _tile(canvas, draw, font, slot, label, path, expected_hash):
    core.require(core.sha(path) == expected_hash, '原图或原资产已变化，请重新 prepare')
    x = GAP + (slot % COLUMNS) * (TILE[0] + GAP)
    y = GAP + (slot // COLUMNS) * (TILE[1] + LABEL + GAP)
    draw.rectangle((x, y, x + TILE[0] - 1, y + LABEL - 1), fill='#202632')
    draw.text((x + 10, y + 2), label, font=font, fill='white')
    draw.rectangle((x, y + LABEL, x + TILE[0] - 1, y + LABEL + TILE[1] - 1), fill='#eeeeee')
    with Image.open(path) as source:
        frame = ImageOps.contain(ImageOps.exif_transpose(source).convert('RGBA'), TILE,
                                method=Image.Resampling.LANCZOS)
    left = x + (TILE[0] - frame.width) // 2
    top = y + LABEL + (TILE[1] - frame.height) // 2
    canvas.paste(frame, (left, top), frame)
    return [left, top, left + frame.width, top + frame.height]


def reading_materials(manifest):
    """Only paths and identifiers enter reading views; hashes remain in the receipt."""
    materials = dict(layout='3x3', images_per_page=PER_PAGE,
                     pages=[{k: p[k] for k in ('path', 'shot_ids', 'asset_sheet_paths') if k in p}
                            for p in manifest['pages']])
    if 'asset_sheets' in manifest:
        materials['asset_sheets'] = [{k: s[k] for k in ('path', 'asset_ids', 'visual_labels')}
                                     for s in manifest['asset_sheets']]
        materials['review_batches'] = [{k: b[k] for k in ('page', 'path', 'shot_ids')}
                                       for b in manifest['review_batches']]
        images = {t['asset_id']: dict(asset_id=t['asset_id'], path=t['image_path'])
                  for sheet in manifest['asset_sheets'] for t in sheet['tiles']}
        materials['asset_images'] = list(images.values())
    return materials


def _font():
    try:
        return ImageFont.load_default(size=24)
    except TypeError:  # Older Pillow still supports the image workflow.
        return ImageFont.load_default()


def _pages(shots, root):
    font = _font()
    pages = []
    for start in range(0, len(shots), PER_PAGE):
        canvas = Image.new('RGB', PAGE, 'white')
        draw = ImageDraw.Draw(canvas)
        tiles = []
        for slot, shot in enumerate(shots[start:start + PER_PAGE]):
            image = shot['image']
            rect = _tile(canvas, draw, font, slot, shot['shot_id'], image['path'], image['sha256'])
            tiles.append(dict(shot_id=shot['shot_id'], image_path=image['path'],
                              image_sha256=image['sha256'], row=slot // COLUMNS, column=slot % COLUMNS,
                              image_rect=rect))
        path = root / f'overview_{len(pages) + 1:03d}.png'
        canvas.save(path)
        pages.append(dict(path=str(path), sha256=core.sha(path),
                          shot_ids=[t['shot_id'] for t in tiles], tiles=tiles))
    return pages


def build_initial(data, root):
    """Render raw-script reading materials before any narrative fields exist."""
    root = Path(root).resolve()
    core.require(not root.exists(), '首看拼图须使用新目录，不覆盖已有材料')
    shots = []
    for shot in data['shots']:
        path = Path(shot['image']).resolve()
        fingerprint = core.sha(path)
        with Image.open(path) as source:
            source.verify()
        shots.append(dict(shot_id=shot['id'], image=dict(path=str(path), sha256=fingerprint)))
    root.mkdir(parents=True)
    pages = _pages(shots, root)
    for index, page in enumerate(pages, 1):
        path = root / f'INITIAL.page{index:03d}.json'
        view = dict(schema='storyboard-initial-view-1', status='unreviewed',
                    purpose='首看材料，尚未补齐要求和原资产；不能作为正式审查结论。',
                    shots=copy.deepcopy(data['shots'][(index - 1) * PER_PAGE:index * PER_PAGE]),
                    images_to_open=[dict(role='storyboards', path=page['path'], shot_ids=page['shot_ids'])])
        core.save(path, view)
        page['view'] = dict(path=str(path), sha256=core.sha(path))
    manifest = root / 'INITIAL_OVERVIEWS.json'
    core.save(manifest, dict(schema='storyboard-initial-overviews-1', layout='3x3', images_per_page=PER_PAGE,
                            source_script_fingerprint=core.digest(data['source_script']),
                            script_shots_fingerprint=core.digest([(s['id'], s['script'], s['duration'])
                                                                 for s in data['shots']]), pages=pages))
    observations = root / 'OBSERVATIONS.json'
    core.save(observations, dict(schema='storyboard-first-observations-1',
        source_script_fingerprint=core.digest(data['source_script']),
        shots=[dict(shot_id=s['shot_id'], image_sha256=s['image']['sha256'], visible_facts=[]) for s in shots]))
    return dict(status='unreviewed', manifest=dict(path=str(manifest), sha256=core.sha(manifest)),
                observations=str(observations),
                pages=[dict(path=p['path'], shot_ids=p['shot_ids'], view=p['view']['path']) for p in pages])


def overview(script_file, supplied, output, *, image_base):
    """Independent first-look entry; never read or overwrite an existing INPUT."""
    from script_input import read_input
    output = Path(output).resolve()
    core.require(not output.exists(), '首看拼图须使用新目录，不覆盖已有材料')
    with evidence_operation():
        data = read_input(script_file, supplied, image_base=image_base)
        result = build_initial(data, output)
    # Optional mechanical draft saves the agent a second extraction; still unreviewed.
    draft = output / 'INPUT.draft.json'
    core.save(draft, data)
    return dict(result, input_draft=str(draft), shots=len(data['shots']),
                next_action='立即显示 pages 中的拼图；再补齐新 INPUT，prepare --reuse-overviews 使用此目录。首看不是审查结论。')


def initial_observations(ctx, initial, source_script):
    """Carry bound first-view facts forward; never generate verdicts from them."""
    if initial is None or not ctx.get('review_overviews', {}).get('initial_reuse', {}).get('reused'):
        return {}
    path = Path(initial['path'] if isinstance(initial, dict) else initial).resolve()
    path = (path if path.is_dir() else path.parent) / 'OBSERVATIONS.json'
    if not path.exists():
        return {}  # Older first-look directories remain usable.
    data = core.read(path)
    core.require(isinstance(data, dict) and data.get('schema') == 'storyboard-first-observations-1'
                 and data.get('source_script_fingerprint') == core.digest(source_script), '首看观察的脚本绑定已变化')
    rows = data.get('shots')
    core.require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows)
                 and [(r.get('shot_id'), r.get('image_sha256')) for r in rows]
                 == [(s['shot_id'], s['image']['sha256']) for s in ctx['shots']], '首看观察的镜序或原图绑定已变化')
    result = {}
    for row in rows:
        facts = row.get('visible_facts')
        core.require(isinstance(facts, list) and all(isinstance(f, str) and f.strip() for f in facts),
                     '首看可见事实须为非空文字列表，未看镜头保留空数组')
        if facts:
            result[row['shot_id']] = copy.deepcopy(facts)
    return result


def _initial_pages(ctx, binding, source_script):
    if isinstance(binding, (str, Path)):
        path = Path(binding).resolve()
        if path.is_dir():
            path /= 'INITIAL_OVERVIEWS.json'
        binding = dict(path=str(path), sha256=core.sha(path))
    core.require(isinstance(binding, dict) and isinstance(binding.get('path'), str) and binding.get('sha256'),
                 '首看拼图清单绑定不完整')
    core.require(core.sha(binding['path']) == binding['sha256'], '首看拼图清单已变化')
    data = core.read(binding['path'])
    core.require(isinstance(data, dict), '首看拼图清单格式无效')
    core.require(data.get('schema') == 'storyboard-initial-overviews-1' and data.get('layout') == '3x3'
                 and data.get('images_per_page') == PER_PAGE
                 and isinstance(source_script, str)
                 and data.get('source_script_fingerprint') == core.digest(source_script)
                 and data.get('script_shots_fingerprint') == core.digest(
                     [(s['shot_id'], s['script'], s['planned_duration']) for s in ctx['shots']]),
                 '首看拼图脚本已变化')
    pages = data.get('pages')
    core.require(isinstance(pages, list) and len(pages) == (len(ctx['shots']) + PER_PAGE - 1) // PER_PAGE,
                 '首看拼图覆盖已变化')
    for index, page in enumerate(pages):
        expected = ctx['shots'][index * PER_PAGE:(index + 1) * PER_PAGE]
        core.require(page['shot_ids'] == [s['shot_id'] for s in expected]
                     and [(t['shot_id'], t['image_path'], t['image_sha256']) for t in page['tiles']]
                     == [(s['shot_id'], s['image']['path'], s['image']['sha256']) for s in expected],
                     '首看拼图镜序或原图已变化')
        core.require(core.sha(page['path']) == page['sha256']
                     and core.sha(page['view']['path']) == page['view']['sha256'], '首看拼图或阅读材料已变化')
    # Early narrative-free views are never carried into formal review packets.
    return [{k: copy.deepcopy(p[k]) for k in ('path', 'sha256', 'shot_ids', 'tiles')} for p in pages]


def build(ctx, run_dir, project=None, *, initial=None, source_script=None):
    """Reuse verified early sheets; bind current requirements and assets afresh."""
    root = Path(run_dir).resolve() / 'overviews'
    root.mkdir()
    pages, reuse = None, None
    if initial is not None:
        try:
            pages = _initial_pages(ctx, initial, source_script)
            reuse = dict(reused=True)
        except (ValueError, OSError, UnicodeError, KeyError, TypeError) as exc:
            # No judgments exist at startup. Rebuild changed/missing early material
            # from current sources instead of approving it or adding a retry step.
            reuse = dict(reused=False, reason=str(exc))
    if pages is None:
        pages = _pages(ctx['shots'], root)
    font = _font()
    data = dict(schema='storyboard-overviews-1', layout='3x3', images_per_page=PER_PAGE,
                source_fingerprint=ctx['source_fingerprint'],
                context_fingerprint=ctx['context_fingerprint'], pages=pages)
    if reuse is not None:
        data['initial_reuse'] = reuse
    if 'assets' in ctx:
        import agent_context
        sheets, cached_sets = [], {}
        data.update(asset_sheets=sheets, review_batches=[])
        # New reviews compare script content in one view. Asset files stay bound
        # in the context for prompts/staleness, but are never decoded for sheets.
        single = ctx.get('review_scope', {}).get('view_policy') == 'single_pass'
        for index, page in enumerate([] if single else pages, 1):
            view = agent_context.batch_view(dict(ctx, review_overviews=reading_materials(data)), index)
            used = {a['id'] for a in view['assets']}
            available = [(i, a) for i, a in enumerate(ctx['assets'], 1)
                         if a['id'] in used and a.get('path') and a['sha256'] != 'MISSING']
            key = tuple(a['id'] for _, a in available)
            if key not in cached_sets:
                paths = []
                for start in range(0, len(available), PER_PAGE):
                    chunk = available[start:start + PER_PAGE]
                    columns = min(COLUMNS, len(chunk))
                    rows = (len(chunk) + columns - 1) // columns
                    size = (columns * TILE[0] + (columns + 1) * GAP,
                            rows * (TILE[1] + LABEL) + (rows + 1) * GAP)
                    canvas = Image.new('RGB', size, 'white')
                    draw = ImageDraw.Draw(canvas)
                    tiles = []
                    for slot, (asset_index, asset) in enumerate(chunk):
                        path = core.resolve(project, asset['path']) if project else Path(asset['path'])
                        core.require(path.is_absolute(), '相对原资产路径需要 PROJECT.json 路径')
                        label = f'A{asset_index:02d}'
                        rect = _tile(canvas, draw, font, slot, label, path, asset['sha256'])
                        tiles.append(dict(asset_id=asset['id'], visual_label=label, asset_path=asset['path'],
                                          image_path=str(path), image_sha256=asset['sha256'], image_rect=rect))
                    path = root / f'assets_{len(sheets) + 1:03d}.png'
                    canvas.save(path)
                    sheets.append(dict(path=str(path), sha256=core.sha(path), tiles=tiles,
                                       asset_ids=[t['asset_id'] for t in tiles],
                                       visual_labels=[t['visual_label'] for t in tiles]))
                    paths.append(str(path))
                cached_sets[key] = paths
            page['asset_sheet_paths'] = cached_sets[key]
        for index, page in enumerate(pages, 1):
            view = agent_context.batch_view(dict(ctx, review_overviews=reading_materials(data)), index)
            path = root / f'REVIEW.page{index:03d}.json'
            core.save(path, view)
            data['review_batches'].append(dict(page=index, path=str(path), sha256=core.sha(path),
                                               shot_ids=page['shot_ids']))
    manifest = root / 'OVERVIEWS.json'
    core.save(manifest, data)
    return dict(reading_materials(data), manifest=dict(path=str(manifest), sha256=core.sha(manifest)),
                **({'initial_reuse': reuse} if reuse is not None else {}))


def validate(ctx, binding):
    """Legacy worklists remain valid; new sheets must retain their original bindings."""
    if binding is None:
        return
    core.require(isinstance(binding, dict) and isinstance(binding.get('path'), str)
                 and binding.get('sha256'), '总览图清单绑定不完整')
    core.require(core.sha(binding['path']) == binding['sha256'], '总览图清单已变化，请重新 prepare')
    manifest = core.read(binding['path'])
    core.require(manifest.get('schema') == 'storyboard-overviews-1'
                 and manifest.get('layout') == '3x3' and manifest.get('images_per_page') == PER_PAGE
                 and manifest.get('source_fingerprint') == ctx['source_fingerprint']
                 and manifest.get('context_fingerprint') == ctx['context_fingerprint'],
                 '总览图来源已变化，请重新 prepare')
    pages = manifest.get('pages', [])
    core.require(len(pages) == (len(ctx['shots']) + PER_PAGE - 1) // PER_PAGE, '总览图覆盖不完整')
    for index, page in enumerate(pages):
        expected = ctx['shots'][index * PER_PAGE:(index + 1) * PER_PAGE]
        tiles = page.get('tiles', [])
        core.require(page.get('shot_ids') == [s['shot_id'] for s in expected]
                     and [(t.get('shot_id'), t.get('image_path'), t.get('image_sha256')) for t in tiles]
                     == [(s['shot_id'], s['image']['path'], s['image']['sha256']) for s in expected],
                     '总览图镜序或原图对应已变化，请重新 prepare')
        core.require(core.sha(page['path']) == page['sha256'], '总览图已变化，请重新 prepare')
    if 'asset_sheets' not in manifest:
        return  # Old overview receipts did not create batch reading materials.
    assets = {a['id']: (a, f'A{i:02d}') for i, a in enumerate(ctx['assets'], 1)}
    sheets = manifest['asset_sheets']
    single = ctx.get('review_scope', {}).get('view_policy') == 'single_pass'
    if single:
        core.require(not sheets and all(not p.get('asset_sheet_paths') for p in pages),
                     '一次看图策略不应包含原资产拼图')
    for sheet in sheets:
        tiles = sheet['tiles']
        core.require(0 < len(tiles) <= PER_PAGE and sheet['asset_ids'] == [t['asset_id'] for t in tiles]
                     and sheet['visual_labels'] == [t['visual_label'] for t in tiles], '原资产总览对应不完整')
        for tile in tiles:
            asset, label = assets[tile['asset_id']]
            core.require((tile['asset_path'], tile['image_sha256'], tile['visual_label'])
                         == (asset['path'], asset['sha256'], label)
                         and core.sha(tile['image_path']) == asset['sha256'], '原资产总览来源已变化')
        core.require(core.sha(sheet['path']) == sheet['sha256'], '原资产总览已变化，请重新 prepare')
    import agent_context
    core.require(len(manifest['review_batches']) == len(pages), '批量阅读材料覆盖不完整')
    material_ctx = dict(ctx, review_overviews=reading_materials(manifest))
    by_path = {s['path']: s for s in sheets}
    for index, (page, packet) in enumerate(zip(pages, manifest['review_batches']), 1):
        view = agent_context.batch_view(material_ctx, index)
        expected = {a['id'] for a in view['assets'] if a.get('path') and assets[a['id']][0]['sha256'] != 'MISSING'}
        paths = page.get('asset_sheet_paths', [])
        core.require(single or (len(paths) == len(set(paths)) and all(p in by_path for p in paths)
                     and [aid for p in paths for aid in by_path[p]['asset_ids']]
                     == [a['id'] for a in ctx['assets'] if a['id'] in expected]), '本页原资产覆盖已变化')
        core.require(packet['page'] == index and packet['shot_ids'] == page['shot_ids']
                     and core.sha(packet['path']) == packet['sha256']
                     and core.read(packet['path']) == view, '批量阅读材料已变化，请重新 prepare')
