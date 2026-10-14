"""Numbered 3x3 review sheets derived from the already-bound original images."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
import previs as core


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


def build(ctx, run_dir, project=None):
    """Keep input order, EXIF orientation and full image bounds; never invent reviews."""
    root = Path(run_dir).resolve() / 'overviews'
    root.mkdir()
    try:
        font = ImageFont.load_default(size=24)
    except TypeError:  # Older Pillow still supports the image workflow.
        font = ImageFont.load_default()
    pages = []
    for start in range(0, len(ctx['shots']), PER_PAGE):
        canvas = Image.new('RGB', PAGE, 'white')
        draw = ImageDraw.Draw(canvas)
        tiles = []
        for slot, shot in enumerate(ctx['shots'][start:start + PER_PAGE]):
            image = shot['image']
            rect = _tile(canvas, draw, font, slot, shot['shot_id'], image['path'], image['sha256'])
            tiles.append(dict(shot_id=shot['shot_id'], image_path=image['path'],
                              image_sha256=image['sha256'], row=slot // COLUMNS, column=slot % COLUMNS,
                              image_rect=rect))
        path = root / f'overview_{len(pages) + 1:03d}.png'
        canvas.save(path)
        pages.append(dict(path=str(path), sha256=core.sha(path),
                          shot_ids=[t['shot_id'] for t in tiles], tiles=tiles))
    data = dict(schema='storyboard-overviews-1', layout='3x3', images_per_page=PER_PAGE,
                source_fingerprint=ctx['source_fingerprint'],
                context_fingerprint=ctx['context_fingerprint'], pages=pages)
    if 'assets' in ctx:
        import agent_context
        sheets, cached_sets = [], {}
        data.update(asset_sheets=sheets, review_batches=[])
        for index, page in enumerate(pages, 1):
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
    return dict(reading_materials(data), manifest=dict(path=str(manifest), sha256=core.sha(manifest)))


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
        core.require(len(paths) == len(set(paths)) and all(p in by_path for p in paths)
                     and [aid for p in paths for aid in by_path[p]['asset_ids']]
                     == [a['id'] for a in ctx['assets'] if a['id'] in expected], '本页原资产覆盖已变化')
        core.require(packet['page'] == index and packet['shot_ids'] == page['shot_ids']
                     and core.sha(packet['path']) == packet['sha256']
                     and core.read(packet['path']) == view, '批量阅读材料已变化，请重新 prepare')
