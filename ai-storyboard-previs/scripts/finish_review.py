"""Automatic source/content checks for an already rendered image report."""
from pathlib import Path
import re
from PIL import Image
import previs as core
import planner


def validate_delivery(p, stage, project=None):
    """Check delivery bytes; new image reports also bind cells and previews to sources."""
    record = p['repair_deliveries'][stage]
    md = Path(record['path']).resolve()
    core.require(record['aggregation_fingerprint'] == core.digest(p['aggregation']), 'Delivery aggregation stale')
    core.require(all(Path(f).is_file() and core.sha(Path(f)) == h for f, h in record['files'].items()),
                 'Immutable delivery changed')
    text = md.read_text(encoding='utf-8')
    table_count = record.get('table_count', 1)
    core.require(table_count == 1, 'Unknown delivery table format')
    core.require(sum(line.startswith('| --- |') for line in text.splitlines()) == table_count,
                 f'Expected exactly {table_count} table(s)')
    rows = [re.split(r'(?<!\\)\|', line)[1:-1] for line in text.splitlines() if line.startswith('|')]
    rows = [r for r in rows if len(r) == 9 and r[1].strip() not in ('原镜号', '---')]
    core.require([r[1].strip() for r in rows] == [s['id'] for s in p['shots']], 'Delivery shot order/coverage changed')
    decisions = {d['shot_id']: d for d in p['aggregation']['decisions']}
    expected = None
    if record.get('delivery_format_version', 1) >= 3:
        from storyboard_inputs import enabled
        from storyboard import delivery_row, delivery_escape, current_image
        core.require(enabled(p), 'Unknown delivery content validation format')
        project = Path(project or record['source_project']).resolve()
        core.require(planner.current_aggregation(p, project), 'Delivery review/aggregation stale')
        reviews = {g['id']: core.review_current(p, project, g['id']) for g in p['groups']}
        core.require(all(reviews.values()), 'Delivery needs current accepted reviews')
        expected = {}
        for shot in p['shots']:
            sid, decision = shot['id'], decisions[shot['id']]
            group = next(g for g in p['groups'] if sid in g['shot_ids'])
            cells, _ = delivery_row(p, shot, decision, p['aggregation']['groups'], reviews[group['id']])
            source = current_image(p, project, sid)
            core.require(source, 'Every provided shot needs its original image')
            original = f"images/{sid}-{source['sha256'][:12]}{Path(source['path']).suffix.lower()}"
            thumb = f"images/thumb-{sid}-{core.digest([decision, (source, False)])[:12]}.png"
            cells[4] = f"[![{delivery_escape(sid)} · {delivery_escape(cells[5])}](<{thumb}>)](<{original}>)"
            expected[sid] = dict(cells=cells, source=source, original=original, thumb=thumb)
        files = {str(md), *(str(md.parent / item[key]) for item in expected.values() for key in ('original', 'thumb'))}
        core.require(set(record['files']) == files
                     and {str(f.resolve()) for f in md.parent.rglob('*') if f.is_file()} == files,
                     'Delivery file set differs from the report and original images')
    pictures = 0
    for row in rows:
        sid, picture = row[1].strip(), row[4].strip()
        if expected is not None:
            item = expected[sid]
            core.require([cell.strip() for cell in row] == item['cells'],
                         f'Delivery content differs from accepted review/script: {sid}')
            source = core.resolve(project, item['source']['path'])
            core.require(core.sha(source) == item['source']['sha256']
                         and core.sha(md.parent / item['original']) == item['source']['sha256'],
                         f'Delivery original image does not match shot: {sid}')
            # Compare only the preview pixels; no second report render, OCR or model call.
            from PIL import ImageOps
            with Image.open(source) as img:
                preview = ImageOps.contain(ImageOps.exif_transpose(img).convert('RGB'), (240, 135))
            canvas = Image.new('RGB', (240, 135), '#edf0f4')
            canvas.paste(preview, ((240-preview.width)//2, (135-preview.height)//2))
            with Image.open(md.parent / item['thumb']) as img:
                core.require(img.crop((0, 0, 240, 135)).convert('RGB').tobytes() == canvas.tobytes(),
                             f'Delivery thumbnail does not match shot: {sid}')
        links = re.findall(r'\]\(<([^>]+)>\)', picture)
        core.require(links, 'Present or non-fill shot needs a local thumbnail')
        for i, link in enumerate(links):
            image = (md.parent / link).resolve()
            core.require(image.is_relative_to(md.parent) and str(image) in record['files'], 'Image outside immutable delivery')
            with Image.open(image) as img:
                if i == 0:
                    core.require(img.size == (240, 168), 'Unexpected thumbnail dimensions')
                img.verify()
        pictures += 1
    return dict(shot_count=len(rows), thumbnail_count=pictures, table_count=table_count,
                visual_review='existing evidence-bound review; no new visual approval')


def intact(record):
    core.require(all(Path(f).is_file() and core.sha(Path(f)) == h for f, h in record['files'].items()),
                 'Immutable delivery changed')
