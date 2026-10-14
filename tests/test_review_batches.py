"""Batch materials preserve evidence, boundaries and exceptions; judgments simulated."""
import copy
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import storyboard_fixtures as fixtures
import test_storyboard_images as existing
import previs as core
import storyboard_inputs as images
import storyboard_overviews as overviews
import prepare_storyboards as batch
import agent_context


class ReviewBatchTests(fixtures.Base):
    review = existing.StoryboardImagesTests.review
    worklist = existing.StoryboardImagesTests.worklist

    def setUp(self):
        existing.StoryboardImagesTests.setUp(self)
        self.run = self.path.parent / 'prepare'

    def context(self, count=14):
        self.run.mkdir()
        ctx = images.context(self.p, self.path, 'G01')
        rows = []
        for index in range(1, count + 1):
            row = copy.deepcopy(ctx['shots'][0])
            path = self.png(f'ordered-{index}', (index * 10, 20, 30))
            row.update(shot_id=f'S{index:02d}', script=f'SIMULATED exact script {index}',
                       asset_ids=['girl'], scene_id='hall',
                       image=dict(path=str(path), sha256=core.sha(path), width=64, height=36),
                       requirements=dict(ready=True, purpose='SIMULATED batch boundary',
                                         entry_state={}, exit_state={}, keyframe=dict(phase='entry', state={}),
                                         must_have=['SIMULATED exact necessary condition'], must_not_have=[]))
            rows.append(row)
        rows[8]['requirements']['entry_state'] = {'key.holder': 'girl'}
        ctx['shots'] = rows
        ctx['source_fingerprint'] = core.digest([r['image'] for r in rows])
        ctx['context_fingerprint'] = core.digest(ctx)
        return ctx

    def test_page_packets_preserve_scripts_boundary_states_and_only_referenced_assets(self):
        ctx = self.context()
        result = overviews.build(ctx, self.run, self.path)
        material_ctx = dict(ctx, review_overviews=result)
        packet = core.read(result['review_batches'][1]['path'])
        self.assertEqual(packet, agent_context.batch_view(material_ctx, 2))
        self.assertEqual(packet['requested_shot_ids'], [f'S{i:02d}' for i in range(10, 15)])
        self.assertEqual(packet['boundary_neighbor_shot_ids'], ['S09'])
        self.assertEqual([s['script'] for s in packet['shots']], [s['script'] for s in ctx['shots'][8:]])
        self.assertEqual(packet['shots'][0]['requirements']['entry_state'], {'key.holder': 'girl'})
        self.assertEqual([a['id'] for a in packet['assets']], ['girl', 'hall', 'key'])
        self.assertEqual([a['visual_label'] for a in packet['assets']], ['A01', 'A03', 'A04'])
        self.assertTrue(all(Path(a['original_image_path']).is_absolute() for a in packet['assets']))
        self.assertEqual(packet['images_to_open'][-1]['shot_ids'], ['S09'])
        self.assertEqual(packet['images_to_open'][0]['shot_ids'], packet['requested_shot_ids'])
        self.assertLess(len(agent_context.encoded(packet)), len(agent_context.encoded(agent_context.reading_view(material_ctx))))
        overviews.validate(ctx, result['manifest'])

    def test_shared_assets_render_once_and_small_panels_keep_original_pixels(self):
        ctx = self.context()
        # Use actual distinct pixels to verify labels and source order, not simulated approval.
        for index, asset in enumerate(ctx['assets']):
            asset['path'] = str(self.png('asset-' + asset['id'], (20 + 30 * index, 40, 50)))
            asset['sha256'] = core.sha(asset['path'])
        before = {a['path']: Path(a['path']).read_bytes() for a in ctx['assets']}
        result = overviews.build(ctx, self.run, self.path)
        self.assertEqual(len(result['asset_sheets']), 1)
        self.assertEqual(result['pages'][0]['asset_sheet_paths'], result['pages'][1]['asset_sheet_paths'])
        manifest = core.read(result['manifest']['path'])
        sheet = manifest['asset_sheets'][0]
        with Image.open(sheet['path']) as picture:
            self.assertEqual(picture.height, overviews.TILE[1] + overviews.LABEL + 2 * overviews.GAP)
            for tile in sheet['tiles']:
                left, top, right, bottom = tile['image_rect']
                asset_index = next(i for i, a in enumerate(ctx['assets']) if a['id'] == tile['asset_id'])
                self.assertEqual(picture.getpixel(((left + right) // 2, (top + bottom) // 2)),
                                 (20 + 30 * asset_index, 40, 50))
        self.assertEqual(before, {p: Path(p).read_bytes() for p in before})
        self.assertNotIn('previous_boundary', [i['role'] for i in core.read(result['review_batches'][0]['path'])['images_to_open']])

    def test_asset_sets_split_after_nine_and_relative_sources_resolve_from_project(self):
        ctx = self.context()
        for index in range(10):
            name = f'extra-{index}'
            path = self.png(name)
            ctx['assets'].append(dict(id=name, kind='prop', description='SIMULATED',
                                      path=path.name, sha256=core.sha(path)))
            ctx['shots'][0]['asset_ids'].append(name)
        result = overviews.build(ctx, self.run, self.path)
        self.assertEqual(len(result['pages'][0]['asset_sheet_paths']), 2)
        packet = core.read(result['review_batches'][0]['path'])
        extra = next(a for a in packet['assets'] if a['id'] == 'extra-0')
        self.assertEqual(extra['path'], 'extra-0.png')
        self.assertEqual(extra['original_image_path'], str(self.path.parent / 'extra-0.png'))
        self.assertEqual(result['pages'][1]['asset_sheet_paths'], [result['asset_sheets'][-1]['path']])
        overviews.validate(ctx, result['manifest'])

    def test_tampered_batch_or_asset_sheet_blocks_resume_and_complete(self):
        prepared = batch.prepare(self.path, None, self.run)
        for path in (prepared['review_overviews']['review_batches'][0]['path'],
                     prepared['review_overviews']['asset_sheets'][0]['path']):
            path = Path(path)
            original = path.read_bytes()
            path.write_bytes(original + b' changed')
            with self.subTest(path=path.name):
                with self.assertRaisesRegex(ValueError, '阅读材料|原资产总览'):
                    batch.resume(self.path, self.run, page=1)
                with self.assertRaisesRegex(ValueError, '阅读材料|原资产总览'):
                    batch.expand(core.read(prepared['context']), core.read(prepared['worklist']))
            path.write_bytes(original)
        self.assertFalse(batch.resume(self.path, self.run, page=1)['progress']['validated'])

    def test_page_resume_keeps_real_uncertainty_queue_and_never_queues_unseen_drafts(self):
        prepared = batch.prepare(self.path, None, self.run)
        self.p = core.read(self.path)
        self.assertEqual(batch.resume(self.path, self.run, page=1)['detail_queue'], [])
        saved = core.read(prepared['worklist'])
        saved.update(self.worklist(self.review(uncertain=('S02',))))
        core.save(prepared['worklist'], saved)
        before = Path(prepared['worklist']).read_bytes()
        result = batch.resume(self.path, self.run, page=1)
        self.assertEqual([r['shot_id'] for r in result['detail_queue']], ['S02'])
        self.assertEqual(result['detail_queue'][0]['followup'], '放大原图确认手部状态')
        self.assertEqual(before, Path(prepared['worklist']).read_bytes())
        for page in (0, -1, 2, True):
            with self.subTest(page=page), self.assertRaises(ValueError):
                batch.resume(self.path, self.run, page=page)
        with self.assertRaises(ValueError):
            batch.resume(self.path, self.run, ['S01'], page=1)

    def test_cli_page_and_legacy_overview_receipts_remain_usable(self):
        prepared = batch.prepare(self.path, None, self.run)
        argv = ['prepare_storyboards.py', 'resume', str(self.path), str(self.run), '--page', '1']
        output = io.StringIO()
        with patch.object(sys, 'argv', argv), redirect_stdout(output):
            batch.main()
        self.assertEqual(json.loads(output.getvalue())['view']['requested_shot_ids'], ['S01', 'S02', 'S03'])
        ctx = core.read(prepared['context'])
        manifest_path = ctx['review_overviews']['manifest']['path']
        manifest = core.read(manifest_path)
        manifest.pop('asset_sheets'); manifest.pop('review_batches')
        for page in manifest['pages']:
            page.pop('asset_sheet_paths')
        core.save(manifest_path, manifest)
        binding = dict(path=manifest_path, sha256=core.sha(manifest_path))
        ctx['review_overviews'] = dict(overviews.reading_materials(manifest), manifest=binding)
        saved = core.read(prepared['worklist']); saved['overview_manifest'] = binding
        core.save(prepared['context'], ctx); core.save(prepared['worklist'], saved)
        core.save(prepared['review_view'], agent_context.reading_view(ctx))
        result = batch.resume(self.path, self.run, page=1)
        self.assertEqual([i['role'] for i in result['view']['images_to_open']], ['storyboards'])
        self.assertFalse(result['progress']['validated'])
