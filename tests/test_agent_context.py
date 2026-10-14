"""Context reduction must preserve meaning, evidence freshness and final gates."""
import copy
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import storyboard_fixtures as fixtures
import test_storyboard_images as existing
import previs as core
import storyboard_inputs as images
import prepare_storyboards as batch
import agent_context


class AgentContextTests(fixtures.Base):
    # Reuse simulated review builders, without inheriting unrelated test methods.
    review = existing.StoryboardImagesTests.review
    worklist = existing.StoryboardImagesTests.worklist

    def setUp(self):
        existing.StoryboardImagesTests.setUp(self)
        self.run = self.path.parent / 'prepare'

    def prepare(self):
        result = batch.prepare(self.path, None, self.run, output=self.path.parent / 'delivery')
        self.p = core.read(self.path)
        return result

    def save_review(self, **kwargs):
        saved = core.read(self.run / 'WORKLIST.json')
        saved.update(self.worklist(self.review(**kwargs)))
        core.save(self.run / 'WORKLIST.json', saved)
        return saved

    def test_view_preserves_scripts_states_and_requirements_without_mutating_evidence(self):
        ctx = images.context(self.p, self.path, 'G01')
        common = ['明确保留两个人物与同一把钥匙的剧情关系，当前阶段不得改变持物者。' * 8]
        for row in ctx['shots']:
            row['requirements']['must_have'] = copy.deepcopy(common)
        original = copy.deepcopy(ctx)
        view = agent_context.reading_view(ctx)
        self.assertTrue(view['shared_requirements'])
        for actual, expected in zip(view['shots'], ctx['shots']):
            restored = copy.deepcopy(actual)
            for field, value in restored['requirements'].items():
                if isinstance(value, dict) and set(value) == {'$ref'}:
                    restored['requirements'][field] = view['shared_requirements'][value['$ref']]
            expected = copy.deepcopy(expected)
            expected['image'].pop('sha256')
            self.assertEqual(restored, expected)
        self.assertEqual(ctx, original)
        self.assertLess(len(agent_context.encoded(view)), len(agent_context.encoded(ctx)))
        self.assertTrue(all('sha256' in s['image'] for s in ctx['shots']))

    def test_recovery_keeps_saved_uncertainty_without_approving_and_reads_neighbours(self):
        prepared = self.prepare()
        receipt = core.read(prepared['run_receipt'])
        self.assertEqual(receipt['project'], str(self.path))
        self.assertEqual(receipt['planned_output'], str(self.path.parent / 'delivery'))
        saved = core.read(prepared['worklist'])
        row = saved['shots'][1]
        row['observation']['visible_facts'] = ['SIMULATED necessary hand detail unresolved']
        row.update(reason='SIMULATED not visible', followup='SIMULATED inspect original', reference_phase='entry')
        core.save(prepared['worklist'], saved)
        before = Path(prepared['worklist']).read_bytes()
        summary = batch.resume(self.path, self.run)
        self.assertEqual(summary['progress']['recorded_shot_ids'], ['S02'])
        self.assertEqual(summary['progress']['needs_recording_shot_ids'], ['S01', 'S03'])
        self.assertFalse(summary['progress']['validated'])
        selected = batch.resume(self.path, self.run, ['S02'])
        self.assertEqual([s['shot_id'] for s in selected['view']['shots']], ['S01', 'S02', 'S03'])
        self.assertEqual(selected['saved_rows'][1]['verdict'], 'uncertain')
        self.assertEqual(before, Path(prepared['worklist']).read_bytes())

    def test_subset_includes_cross_page_continuity_and_rejects_unknown_or_duplicate_ids(self):
        ctx = images.context(self.p, self.path, 'G01')
        ctx['shots'] = [dict(copy.deepcopy(ctx['shots'][0]), shot_id=f'S{i:02}') for i in range(1, 15)]
        ctx['input_shot_groups'] = [['S01', 'S02'], ['S03']]
        view = agent_context.reading_view(ctx, ['S09', 'S14'])
        self.assertEqual([s['shot_id'] for s in view['shots']], ['S08', 'S09', 'S10', 'S13', 'S14'])
        self.assertEqual(view['input_shot_groups'], ctx['input_shot_groups'])
        for ids in ([], ['S09', 'S09'], ['bad']):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                agent_context.reading_view(ctx, ids)

    def test_recovery_rejects_replaced_images_scripts_assets_and_grouping(self):
        self.prepare()
        original_project = core.read(self.path)
        image = Path(self.p['storyboard_images'][0]['path'])
        original_image = image.read_bytes()
        self.png(image.stem, (90, 91, 92))
        with self.assertRaises(ValueError):
            batch.resume(self.path, self.run)
        image.write_bytes(original_image)
        asset = Path(self.p['assets'][0]['path'])
        original_asset = asset.read_bytes()
        self.png(asset.stem, (93, 94, 95))
        with self.assertRaises(ValueError):
            batch.resume(self.path, self.run)
        asset.write_bytes(original_asset)
        for kind in ('script', 'group'):
            changed = copy.deepcopy(original_project)
            if kind == 'script':
                changed['shots'][0]['script'] += ' SIMULATED changed requirement'
            else:
                changed['input_shot_groups'] = [['S01', 'S02'], ['S03']]
            core.save(self.path, changed)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                batch.resume(self.path, self.run)
        core.save(self.path, original_project)
        self.assertFalse(batch.resume(self.path, self.run)['progress']['validated'])

    def test_recovery_rejects_tampered_overviews_worklist_and_reading_view(self):
        prepared = self.prepare()
        overview = Path(prepared['review_overviews']['pages'][0]['path'])
        page = overview.read_bytes()
        overview.write_bytes(page + b'changed')
        with self.assertRaisesRegex(ValueError, '总览'):
            batch.resume(self.path, self.run)
        overview.write_bytes(page)
        saved = core.read(prepared['worklist'])
        broken = copy.deepcopy(saved)
        broken['shots'][1]['shot_id'] = 'S01'
        core.save(prepared['worklist'], broken)
        with self.assertRaisesRegex(ValueError, '完整覆盖'):
            batch.resume(self.path, self.run)
        core.save(prepared['worklist'], saved)
        view = core.read(prepared['review_view'])
        view['shots'][0]['script'] = 'tampered'
        core.save(prepared['review_view'], view)
        with self.assertRaisesRegex(ValueError, '阅读视图'):
            batch.resume(self.path, self.run)
        self.assertNotEqual(batch.resume(self.path, self.run, ['S01'])['view']['shots'][0]['script'], 'tampered')

    def test_recovery_rehashes_sources_before_return_and_handles_malformed_progress(self):
        self.prepare()
        image = Path(self.p['storyboard_images'][0]['path'])
        before = image.read_bytes()
        original_progress = agent_context.progress
        def replace_after_initial_read(data):
            image.write_bytes(before + b'changed during recovery')
            return original_progress(data)
        with patch.object(agent_context, 'progress', side_effect=replace_after_initial_read):
            with self.assertRaises(ValueError):
                batch.resume(self.path, self.run, ['S01'])
        image.write_bytes(before)
        saved = core.read(self.run / 'WORKLIST.json')
        saved['shots'][0]['observation'] = None
        core.save(self.run / 'WORKLIST.json', saved)
        self.assertIn('S01', batch.resume(self.path, self.run)['progress']['incomplete_record_shot_ids'])

    def test_legacy_preparation_and_incomplete_records_remain_usable(self):
        prepared = self.prepare()
        Path(prepared['review_view']).unlink()
        Path(prepared['run_receipt']).unlink()
        recovered = batch.resume(self.path, self.run)
        self.assertEqual(recovered['review_view'], prepared['context'])
        self.assertEqual(recovered['progress']['incomplete_record_shot_ids'], ['S01', 'S02', 'S03'])
        # Empty default fields never become a valid review by recovering them.
        with self.assertRaises(ValueError):
            batch.complete(self.path, prepared['worklist'], self.path.parent / 'bad-delivery',
                           self.path.parent / 'bad-finish')

    def test_cli_summary_keeps_full_finish_on_disk_and_threshold_export_contract(self):
        prepared = self.prepare()
        self.save_review(fails=('S02',), critical=True)
        finish = self.path.parent / 'finish'
        argv = ['prepare_storyboards.py', 'complete', str(self.path), prepared['worklist'],
                '--output', str(self.path.parent / 'delivery'), '--run-dir', str(finish)]
        stream = io.StringIO()
        with patch.object(sys, 'argv', argv), redirect_stdout(stream):
            batch.main()
        brief = json.loads(stream.getvalue())
        full = core.read(finish / 'FINISH_REPORT.json')
        self.assertEqual(brief, core.read(finish / 'FINISH.view.json'))
        self.assertTrue(brief['decision']['triggered'])
        self.assertEqual(brief['delivery'], full['delivery'])
        self.assertEqual(brief['validation'], full['validation'])
        self.assertLess(len(stream.getvalue()), len(json.dumps(full, ensure_ascii=False, indent=2)) / 2)
        self.assertNotIn('baseline', brief['decision'])
        self.assertEqual(len(core.read(finish / 'PROMPT.view.json')['blocks']), len(self.p['shots']))
        self.assertEqual(brief['prompt_view'], str(finish / 'PROMPT.view.json'))
        self.assertTrue(Path(brief['delivery']).is_file())
        # Source manifest remains frozen and contains every original and thumbnail.
        stored = core.read(self.path)['repair_deliveries']['original']
        self.assertEqual(len(stored['files']), 1 + 2 * len(self.p['shots']))
