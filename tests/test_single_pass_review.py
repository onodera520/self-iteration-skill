"""Single-view orchestration with real image files and simulated judgments."""
import copy
from pathlib import Path
from unittest.mock import patch

import storyboard_fixtures as fixtures
import test_storyboard_images as existing
import test_review_batches as batches
import previs as core
import storyboard_inputs as images
import storyboard_overviews as overviews
import prepare_storyboards as batch
import agent_context


class SinglePassTests(fixtures.Base):
    review = existing.StoryboardImagesTests.review
    compact_input = existing.StoryboardImagesTests.compact_input
    context = batches.ReviewBatchTests.context

    def setUp(self):
        existing.StoryboardImagesTests.setUp(self)
        self.p['config']['storyboard_review_policy'] = 'single_pass'
        core.save(self.path, self.p)
        self.run = self.path.parent / 'prepare'

    def work(self, ctx, review):
        result = batch.worklist(ctx)
        for key in ('checks', 'grouping_checked', 'issues', 'uncertainties', 'asset_comparisons', 'repair_assessments'):
            result[key] = copy.deepcopy(review[key])
        for item, row, ref, evidence in zip(result['shots'], review['shot_reviews'],
                                           review['reference_assessments'], review['evidence']):
            item.update({k: copy.deepcopy(v) for k, v in row.items() if k not in ('checks', 'evidence_sha256')})
            item['check_exceptions'] = {k: v for k, v in row['checks'].items() if v != 'PASS'}
            for group, members in batch.CHECK_GROUPS.items():
                values = [row['checks'][k] for k in members]
                item['check_groups'][group] = 'FAIL' if 'FAIL' in values else 'uncertain' if 'uncertain' in values else 'PASS'
            item['match_level'] = 0 if row['verdict'] == 'PASS' else None
            item['reference'].update({k: v for k, v in ref.items() if k not in ('shot_id', 'evidence_sha256')})
            item['observation']['visible_facts'] = evidence['visible_facts']
        return result

    def test_new_project_defaults_to_three_groups_without_asset_image_decode(self):
        opened = []
        original = overviews.Image.open
        asset_paths = {str(Path(a['path']).resolve()) for a in self.p['assets']}

        def open_image(path, *args, **kwargs):
            opened.append(str(Path(path).resolve()))
            if opened[-1] in asset_paths:
                raise AssertionError('Default review must not open asset images')
            return original(path, *args, **kwargs)

        project = self.path.parent / 'new.json'
        with patch.object(overviews.Image, 'open', side_effect=open_image):
            prepared = batch.prepare(project, None, self.run, input_data=self.compact_input())
        ctx, work = core.read(prepared['context']), core.read(prepared['worklist'])
        self.assertTrue(opened)
        self.assertEqual(ctx['review_scope']['view_policy'], 'single_pass')
        self.assertEqual(work['worklist_version'], 3)
        self.assertNotIn('checks', work['shots'][0])
        self.assertEqual(set(work['shots'][0]['check_groups']), {'content', 'state', 'reference'})
        self.assertEqual(prepared['review_overviews']['asset_sheets'], [])
        self.assertFalse(list(self.run.rglob('assets_*.png')))

    def test_next_page_keeps_text_boundary_without_reopening_boundary_or_assets(self):
        ctx = self.context()
        prepared = overviews.build(ctx, self.run, self.path)
        packet = core.read(prepared['review_batches'][1]['path'])
        self.assertIn('S09', packet['boundary_neighbor_shot_ids'])
        self.assertEqual([item['role'] for item in packet['images_to_open']], ['storyboards'])
        self.assertEqual(packet['images_to_open'][0]['shot_ids'], [f'S{i:02d}' for i in range(10, 15)])
        overviews.validate(ctx, prepared['manifest'])

    def test_matching_levels_and_omission_use_one_grouped_observation(self):
        ctx = images.context(self.p, self.path, 'G01')
        for level in range(4):
            with self.subTest(level=level):
                work = self.work(ctx, self.review(omit=True))
                for row in work['shots']:
                    row['match_level'] = level
                expanded = batch.expand(ctx, work)
                images.record_review(self.p, self.path, expanded)
                self.assertEqual(expanded['shot_reviews'][0]['match_level'], level)
                self.assertEqual(expanded['evidence'][0]['visible_facts'], work['shots'][0]['observation']['visible_facts'])
                self.assertEqual(expanded['reference_assessments'][1]['decision'], 'ai_fill')

    def test_groups_cannot_hide_a_failure_or_invent_pass_without_observation(self):
        ctx = images.context(self.p, self.path, 'G01')
        good = self.work(ctx, self.review(fails=('S01',)))
        for kind in ('exception', 'group', 'verdict', 'facts', 'level'):
            bad = copy.deepcopy(good)
            if kind == 'exception':
                bad['shots'][0]['check_exceptions'] = {}
            elif kind == 'group':
                bad['shots'][0]['check_groups']['content'] = 'PASS'
            elif kind == 'verdict':
                bad['shots'][0].update(verdict='PASS', match_level=3)
            elif kind == 'facts':
                bad['shots'][0]['observation']['visible_facts'] = []
            else:
                bad['shots'][1]['match_level'] = 4
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                images.record_review(self.p, self.path, batch.expand(ctx, bad))

    def test_script_identity_conflict_needs_no_asset_comparison(self):
        ctx = images.context(self.p, self.path, 'G01')
        review = self.review(fails=('S01',))
        row = review['shot_reviews'][0]
        row['checks'].update(identity='FAIL', props='PASS')
        row['reason'] = 'SIMULATED wrong actor is visible'
        work = self.work(ctx, review)
        self.assertEqual(work['asset_comparisons'], [])
        images.record_review(self.p, self.path, batch.expand(ctx, work))
        self.assertEqual(self.p['reviews'][-1]['shot_reviews'][0]['checks']['identity'], 'FAIL')

    def test_explicit_prop_comparison_still_cannot_hide_behind_identity_pass(self):
        ctx = images.context(self.p, self.path, 'G01')
        work = self.work(ctx, self.review(fails=('S01',)))
        work['shots'][0]['check_exceptions'] = {'key_state': 'FAIL'}
        work['shots'][0]['check_groups'].update(content='PASS', state='FAIL')
        work['asset_comparisons'] = [dict(id='prop-conflict', shot_id='S01', asset_id='key',
            aspect='prop', decision='FAIL', stable_conflicts=[dict(feature='shape', expected='key',
            observed='coin', environment_exclusion='SIMULATED solid outline')], followup='')]
        work['issues'][0].update(asset_ids=['key'], asset_comparison_ids=['prop-conflict'])
        with self.assertRaisesRegex(ValueError, 'asset conflict must fail'):
            images.record_review(self.p, self.path, batch.expand(ctx, work))

    def test_uncertain_is_delivered_with_all_originals_and_no_recheck_queue(self):
        prepared = batch.prepare(self.path, None, self.run)
        ctx = core.read(prepared['context'])
        review = self.review(fails=('S01',), uncertain=('S02',))
        review['shot_reviews'][1].update(reason='SIMULATED hand conceals the key holder',
                                       followup='需确认该参考阶段的钥匙持有者')
        work = self.work(ctx, review)
        core.save(prepared['worklist'], work)
        resumed = batch.resume(self.path, self.run, page=1)
        self.assertEqual(resumed['detail_queue'], [])
        self.assertEqual(resumed['view']['images_to_open'], [])
        self.assertEqual(resumed['unresolved_items'][0]['shot_id'], 'S02')
        self.assertNotIn('image_path', resumed['unresolved_items'][0])
        result = batch.complete(self.path, prepared['worklist'], self.path.parent / 'delivery', self.path.parent / 'finish')
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['decision']['triggered'])
        report = Path(result['delivery']).read_text(encoding='utf-8')
        row = next(line for line in report.splitlines() if '| S02 |' in line)
        self.assertIn('—', row)
        self.assertIn('暂不省图', row)
        self.assertNotIn('漏镜', report)
        self.assertIn('修改该分镜图的钥匙持有者', report)
        delivered = [p for p in (self.path.parent / 'delivery/images').iterdir() if not p.name.startswith('thumb-')]
        self.assertEqual(len(delivered), 3)
        self.assertEqual({p.read_bytes() for p in delivered},
                         {Path(r['path']).read_bytes() for r in self.p['storyboard_images']})

    def test_first_facts_reuse_skips_image_render_and_does_not_approve(self):
        first = overviews.build_initial(self.compact_input(), self.path.parent / 'first')
        facts = core.read(first['observations'])
        for row in facts['shots']:
            row['visible_facts'] = ['SIMULATED once-viewed facts for ' + row['shot_id']]
        core.save(first['observations'], facts)
        with patch.object(overviews, '_tile', side_effect=AssertionError('No second render or asset collage')):
            prepared = batch.prepare(self.path, None, self.run, reuse_overviews=self.path.parent / 'first')
        self.assertEqual(prepared['reused_observation_shot_ids'], ['S01', 'S02', 'S03'])
        work = core.read(prepared['worklist'])
        self.assertEqual(work['shots'][0]['observation']['visible_facts'], facts['shots'][0]['visible_facts'])
        self.assertEqual(work['shots'][0]['verdict'], 'uncertain')
        self.assertEqual(work['shots'][0]['match_level'], None)
        resumed = batch.resume(self.path, self.run, page=1)
        self.assertEqual(resumed['view']['images_to_open'], [])
        self.assertEqual(resumed['progress']['incomplete_record_shot_ids'], ['S01', 'S02', 'S03'])

    def test_first_facts_wrong_image_binding_is_rejected(self):
        first = overviews.build_initial(self.compact_input(), self.path.parent / 'first')
        facts = core.read(first['observations'])
        facts['shots'][0].update(image_sha256='wrong', visible_facts=['SIMULATED fact'])
        core.save(first['observations'], facts)
        with self.assertRaisesRegex(ValueError, '首看观察的镜序或原图'):
            batch.prepare(self.path, None, self.run, reuse_overviews=self.path.parent / 'first')

    def test_replaced_image_drops_first_facts_and_rejects_saved_conclusion(self):
        first = overviews.build_initial(self.compact_input(), self.path.parent / 'first')
        facts = core.read(first['observations'])
        facts['shots'][0]['visible_facts'] = ['SIMULATED stale observation']
        core.save(first['observations'], facts)
        self.png('board-S01', (255, 10, 15))
        prepared = batch.prepare(self.path, None, self.run, reuse_overviews=self.path.parent / 'first')
        self.assertFalse(prepared['review_overviews']['initial_reuse']['reused'])
        self.assertEqual(prepared['reused_observation_shot_ids'], [])
        self.assertEqual(core.read(prepared['worklist'])['shots'][0]['observation']['visible_facts'], [])
        self.png('board-S01', (0, 2, 5))
        with self.assertRaisesRegex(ValueError, '审查依据已变化'):
            batch.resume(self.path, self.run)

    def test_legacy_context_without_policy_is_unchanged(self):
        legacy = copy.deepcopy(self.p)
        legacy['config']['storyboard_review_policy'] = 'legacy'
        before = images.context(legacy, self.path, 'G01')
        del legacy['config']['storyboard_review_policy']
        after = images.context(legacy, self.path, 'G01')
        self.assertEqual(before, after)
        self.assertEqual(batch.worklist(after)['worklist_version'], 2)
        self.assertNotIn('view_policy', after['review_scope'])
