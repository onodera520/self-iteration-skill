"""Workflow contracts and timing arithmetic, not visual-review speed/quality claims."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import test_previs as fixtures
import test_parallel_review as parallel_fixtures
import test_repair_cycle as repair_fixtures
import previs as core
import parallel_review as parallel
import finish_review
import review_timing
import planner
import repair_cycle as repair


class WorklistTests(fixtures.Base):
    setUp = parallel_fixtures.ParallelReviewTests.setUp
    png = parallel_fixtures.ParallelReviewTests.png
    select_mapping = parallel_fixtures.ParallelReviewTests.select_mapping
    mapping = parallel_fixtures.ParallelReviewTests.mapping
    review_data = parallel_fixtures.ParallelReviewTests.review_data
    prepare = parallel_fixtures.ParallelReviewTests.prepare

    def test_compact_views_keep_full_owned_evidence_and_neighbors(self):
        b = self.prepare()
        for task in b['tasks']:
            w = core.read(self.bundle_dir / task['id'] / 'worklist.json')
            self.assertEqual(w['source_script'], self.p['source_script'])
            self.assertEqual([s['shot_id'] for s in w['owned_shots']], task['shot_ids'])
            self.assertEqual(w['assets'], b['context']['assets'])
            for row in w['owned_shots'] + w['neighbor_context']:
                original = next(s for s in b['context']['shots'] if s['shot_id'] == row['shot_id'])
                self.assertEqual(row['requirements'], original['requirements'])
                self.assertEqual(row['mapping'], next(s for s in b['context']['mapping']['shots'] if s['shot_id'] == row['shot_id']))
            self.assertTrue(w['neighbor_context'])
        path = self.bundle_dir / 'T01/worklist.json'
        w = core.read(path); w['owned_shots'][0]['script'] = 'tampered'
        core.save(path, w)
        with self.assertRaisesRegex(ValueError, 'worklist changed'):
            parallel.assemble(self.path, self.bundle_dir, self.path.parent / 'bad.json')

    def test_drafts_preserve_findings_but_cannot_approve_themselves(self):
        self.prepare(verdicts={'S02': 'FAIL'})
        directory = self.path.parent / 'coordinator'
        c = parallel.assemble(self.path, self.bundle_dir, self.path.parent / 'collected-new.json', directory)
        r = core.read(directory / 'FINAL_REVIEW.json')
        a = core.read(directory / 'COORDINATOR_AUDIT.json')
        self.assertEqual(r, c['review'])
        self.assertEqual(a['task_hashes'], c['task_hashes'])
        self.assertEqual(r['shot_reviews'][1]['verdict'], 'FAIL')
        with self.assertRaises(ValueError):
            parallel.commit(self.path, self.bundle_dir, directory / 'FINAL_REVIEW.json', directory / 'COORDINATOR_AUDIT.json')
        self.assertEqual(core.read(self.path), self.p)
        with self.assertRaises(ValueError):
            parallel.assemble(self.path, self.bundle_dir, self.path.parent / 'again.json', directory)
        self.assertFalse((self.path.parent / 'again.json').exists())


class FinishTests(fixtures.Base):
    setUp = repair_fixtures.RepairCycleTests.setUp
    png = repair_fixtures.RepairCycleTests.png
    select_mapping = repair_fixtures.RepairCycleTests.select_mapping
    mapping = repair_fixtures.RepairCycleTests.mapping
    review_data = repair_fixtures.RepairCycleTests.review_data
    assessment = repair_fixtures.RepairCycleTests.assessment

    def prepare(self, assessed=True):
        self.mapping()
        r = self.review_data({'S02': 'FAIL'}, middle_derivable=False)
        core.record_review(self.p, self.path, self.assessment(r, True) if assessed else r)
        core.save(self.path, self.p)
        self.output = self.path.parent / 'delivery'
        self.run_dir = self.path.parent / 'finish-run'

    def test_finish_equals_individual_commands_without_submitting(self):
        self.prepare()
        expected = copy.deepcopy(self.p)
        plan = planner.post_review_plan(expected, self.path, {})
        planner.store_aggregation(expected, self.path, plan)
        expected_path = repair.snapshot(expected, self.path, self.path.parent / 'manual', 'original')
        decision = repair.decide(expected, self.path, 'G01')
        with patch.object(repair, 'submit', side_effect=AssertionError('No paid submission')):
            result = finish_review.finish(self.path, {}, self.output, self.run_dir)
        actual = core.read(self.path)
        self.assertEqual(core.digest(actual['aggregation']), core.digest(expected['aggregation']))
        self.assertEqual(actual['repair_decisions']['G01'], decision)
        self.assertEqual(Path(result['delivery']).read_bytes(), Path(expected_path).read_bytes())
        self.assertEqual(actual['tasks'], self.p['tasks'])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(result['phases']), 4)
        self.assertTrue(all(p['elapsed_seconds'] >= 0 and p['status'] == 'complete' for p in result['phases']))
        self.assertFalse(Path(str(self.path) + '.lock').exists())
        # A repeated finish can verify/reuse the exact immutable delivery, with a new log.
        again = finish_review.finish(self.path, {}, self.path.parent / 'unused', self.path.parent / 'run2')
        self.assertEqual(result['delivery'], again['delivery'])
        self.assertFalse((self.path.parent / 'unused').exists())

    def test_missing_assessment_keeps_original_and_reports_blocked(self):
        self.prepare(False)
        result = finish_review.finish(self.path, {}, self.output, self.run_dir)
        self.assertEqual(result['status'], 'delivery_complete_decision_blocked')
        self.assertIn('repair_assessments', result['decisions']['G01']['reason'])
        self.assertTrue(Path(result['delivery']).is_file())
        self.assertNotIn('G01', core.read(self.path).get('repair_decisions', {}))

    def test_stale_review_or_lock_cannot_produce_delivery(self):
        self.prepare()
        with core.locked(self.path), self.assertRaises(FileExistsError):
            finish_review.finish(self.path, {}, self.output, self.run_dir)
        self.assertFalse(self.run_dir.exists())
        self.p['source_script'] += ' changed'
        core.save(self.path, self.p)
        with self.assertRaises(ValueError):
            finish_review.finish(self.path, {}, self.output, self.run_dir)
        self.assertFalse(self.output.exists())
        self.assertEqual(core.read(self.run_dir / 'FINISH_REPORT.json')['status'], 'failed')

    def test_tampered_thumbnail_or_stale_snapshot_rejected(self):
        self.prepare()
        finish_review.finish(self.path, {}, self.output, self.run_dir)
        p = core.read(self.path)
        thumb = next(self.output.glob('images/thumb-*.png'))
        thumb.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Immutable delivery changed'):
            finish_review.validate_delivery(p, 'original')
        p['repair_deliveries']['original']['aggregation_fingerprint'] = 'wrong'
        core.save(self.path, p)
        with self.assertRaisesRegex(ValueError, 'earlier aggregation'):
            finish_review.finish(self.path, {}, self.output, self.path.parent / 'retry')


class TimingTests(fixtures.Base):
    def test_overlap_is_union_not_sum_and_open_phases_are_visible(self):
        rows = [dict(phase='T01', started_at='2026-09-18T00:00:00+00:00', ended_at='2026-09-18T00:00:10+00:00'),
                dict(phase='T02', started_at='2026-09-18T00:00:02+00:00', ended_at='2026-09-18T00:00:12+00:00'),
                dict(phase='coordination', started_at='2026-09-18T00:00:15+00:00', ended_at='2026-09-18T00:00:20+00:00'),
                dict(phase='unfinished', started_at='2026-09-18T00:00:20+00:00')]
        result = review_timing.summary(dict(phases=rows))
        self.assertEqual(result['recorded_union_seconds'], 17)
        self.assertEqual(result['recorded_span_seconds'], 20)
        self.assertEqual(result['incomplete_phase_ids'], ['unfinished'])

    def test_journal_does_not_overwrite_existing_phase(self):
        path = self.path.parent / 'TIMING.json'
        review_timing.mark(path, 'start', 'T01')
        with self.assertRaises(ValueError): review_timing.mark(path, 'start', 'T01')
        review_timing.mark(path, 'end', 'T01')
        with self.assertRaises(ValueError): review_timing.mark(path, 'end', 'T01')
        self.assertFalse(Path(str(path)+'.lock').exists())


if __name__ == '__main__':
    unittest.main()
