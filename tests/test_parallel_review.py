"""Parallel orchestration contracts with simulated observations, not vision scores."""
import copy
from pathlib import Path
import unittest
import test_previs as fixtures
import test_imported_review as imported
import previs as core
import parallel_review as parallel
import planner
import storyboard


class ParallelReviewTests(fixtures.Base):
    png = imported.ImportedReviewTests.png
    select_mapping = imported.ImportedReviewTests.select_mapping
    mapping = imported.ImportedReviewTests.mapping
    review_data = imported.ImportedReviewTests.review_data

    def setUp(self):
        imported.ImportedReviewTests.setUp(self)
        # Synthetic two-event partition; this test is not a dramatic interpretation.
        self.p['shots'][-1]['event']['id'] = 'E02'
        self.units = [dict(shot_ids=['S01', 'S02'], reason='SIMULATED event one', workload=2),
                      dict(shot_ids=['S03'], reason='SIMULATED event two', workload=1)]
        self.bundle_dir = self.path.parent / 'parallel'

    def prepare(self, statuses=None, verdicts=None):
        self.mapping(statuses)
        core.save(self.path, self.p)
        bundle = parallel.prepare(self.path, 'G01', self.units, self.bundle_dir)
        self.final = self.review_data(verdicts)
        for task in bundle['tasks']:
            owned = set(task['shot_ids'])
            draft = dict(task_id=task['id'], bundle_fingerprint=bundle['fingerprint'], limitations=[])
            for field in parallel.ROWS:
                draft[field] = [copy.deepcopy(r) for r in self.final.get(field, [])
                    if (any(sid in r for sid in owned) if field == 'uncertainties' else
                        set(r['shot_ids']) <= owned if field == 'issues' else r['shot_id'] in owned)]
            core.save(self.bundle_dir / task['id'] / 'draft.json', draft)
        self.collected = parallel.assemble(self.path, self.bundle_dir, self.path.parent / 'collected.json')
        self.audit = dict(task_hashes=self.collected['task_hashes'],
            boundaries=[dict(b, verdict='PASS', visual_reason='SIMULATED continuity visible',
                             state_reason='SIMULATED shared state inspected') for b in self.collected['boundary_audit_required']],
            cross_references=[dict(shot_id=s, reason='SIMULATED anchors checked')
                              for s in self.collected['cross_reference_audit_required']],
            rechecked_shot_ids=[], deferred_shot_ids=[], accepted_shot_ids=[], resolutions=[])
        return bundle

    def commit(self):
        review, audit = self.path.parent / 'final.json', self.path.parent / 'audit.json'
        core.save(review, self.final); core.save(audit, self.audit)
        return parallel.commit(self.path, self.bundle_dir, review, audit)

    def test_end_to_end_matches_serial_planning_and_two_tables(self):
        bundle = self.prepare()
        original = copy.deepcopy(self.p)
        serial = copy.deepcopy(self.p)
        core.record_review(serial, self.path, copy.deepcopy(self.final))
        expected = planner.post_review_plan(serial, self.path, {})
        self.assertEqual(bundle['mode'], 'parallel')
        self.assertEqual(len(bundle['tasks']), 2)
        self.assertEqual(self.collected['review']['checks']['story'], 'uncertain')
        self.assertFalse(self.collected['review']['grouping_checked'])
        self.assertEqual(core.read(self.path), original)  # workers and collect never wrote state
        result = self.commit()
        self.assertEqual(result['verdict'], 'PASS')
        actual = core.read(self.path)
        for field in ('shots', 'groups', 'tasks', 'config', 'board_mappings'):
            self.assertEqual(actual[field], original[field])
        plan = planner.post_review_plan(actual, self.path, {})
        self.assertEqual(plan['decisions'], expected['decisions'])
        self.assertEqual(plan['groups'], expected['groups'])
        planner.store_aggregation(actual, self.path, plan)
        text = Path(storyboard.render(actual, self.path, self.path.parent/'delivery')).read_text(encoding='utf8')
        self.assertEqual(sum(l.startswith('| --- |') for l in text.splitlines()), 2)
        self.assertIn('可推导生成', text)
        self.assertLessEqual(plan['groups'][0]['planned_duration'], 15)
        self.assertFalse(Path(str(self.path)+'.lock').exists())

    def test_contiguous_event_cannot_be_split(self):
        self.p['shots'][-1]['event']['id'] = 'E01'
        self.mapping(); core.save(self.path, self.p)
        with self.assertRaisesRegex(ValueError, 'continuous event'):
            parallel.prepare(self.path, 'G01', self.units, self.bundle_dir)

    def test_single_unit_serial_and_short_units_balanced_without_cutting(self):
        ctx = dict(shots=[dict(shot_id=f'S{i}',event=dict(id=f'E{i}')) for i in range(5)])
        units = [dict(shot_ids=[f'S{i}'],reason='complete event',workload=w)
                 for i,w in enumerate([5,4,2,1,1])]
        lanes = parallel.schedule(ctx, units)
        self.assertEqual(len(lanes), 2)
        self.assertEqual(sorted(t['workload'] for t in lanes), [6,7])
        whole = [dict(shot_ids=[f'S{i}' for i in range(5)],reason='one continuous event',workload=13)]
        self.assertEqual(len(parallel.schedule(ctx, whole)), 1)

    def test_unit_gap_or_duplicate_rejected(self):
        ctx = dict(shots=[dict(shot_id='S01',event=dict(id='E01'))])
        for ids in ([], ['S01','S01'], ['S02']):
            with self.assertRaises(ValueError):
                parallel.schedule(ctx,[dict(shot_ids=ids,reason='event',workload=1)])

    def test_missing_worker_does_not_register(self):
        self.prepare()
        (self.bundle_dir/'T02/draft.json').unlink()
        with self.assertRaises(FileNotFoundError): self.commit()
        self.assertEqual(core.read(self.path),self.p)

    def test_worker_ownership_and_coverage_rejected(self):
        self.prepare()
        path = self.bundle_dir/'T01/draft.json'
        original = core.read(path)
        for mutate in (lambda d:d['evidence'].append(copy.deepcopy(self.final['evidence'][-1])),
                       lambda d:d['shot_reviews'].pop(),
                       lambda d:d.update(state_changes=[])):
            d=copy.deepcopy(original); mutate(d); core.save(path,d)
            with self.assertRaises(ValueError): parallel.assemble(self.path,self.bundle_dir,self.path.parent/'x.json')

    def test_project_frame_asset_and_source_changes_invalidate(self):
        self.prepare()
        paths=[self.path, Path(self.final['evidence'][0]['path']), Path(self.p['assets'][0]['path']),
               Path(core.video_context(self.p,self.path,'G01')['video'])]
        for path in paths:
            data=path.read_bytes()
            try:
                path.write_bytes(data+b'changed')
                with self.assertRaises((ValueError,AssertionError)):
                    parallel.assemble(self.path,self.bundle_dir,self.path.parent/'stale.json')
            finally: path.write_bytes(data)

    def test_draft_change_after_coordination_rejected(self):
        self.prepare()
        path=self.bundle_dir/'T01/draft.json'; d=core.read(path)
        d['shot_reviews'][0]['reason']='changed after coordinator read'
        core.save(path,d)
        with self.assertRaisesRegex(ValueError,'drafts changed'): self.commit()

    def test_boundary_state_and_visual_evidence_both_required(self):
        self.prepare(); original=copy.deepcopy(self.audit)
        for field in ('state_reason','visual_reason','entry_state','exit_state'):
            self.audit=copy.deepcopy(original);self.audit['boundaries'][0].pop(field)
            with self.assertRaisesRegex(ValueError,'state|reason'): self.commit()
        self.audit=copy.deepcopy(original);self.audit['boundaries']=[]
        with self.assertRaisesRegex(ValueError,'boundary audit'): self.commit()

    def test_boundary_failure_cannot_disappear(self):
        self.prepare()
        self.audit['boundaries'][0].update(verdict='FAIL',affected_shot_ids=['S03'])
        with self.assertRaisesRegex(ValueError,'boundary problem'): self.commit()

    def test_cross_unit_fill_requires_coordinator_audit(self):
        self.prepare();self.audit['cross_references']=[]
        with self.assertRaisesRegex(ValueError,'reference audit'):self.commit()

    def test_original_validator_still_rejects_wrong_time(self):
        self.prepare()
        old=copy.deepcopy(self.final['evidence'][0]);self.final['evidence'][0]['time']=5.9
        self.audit['resolutions']=[dict(record_hash=core.digest(old),reason='SIMULATED intentional invalid evidence')]
        with self.assertRaises(ValueError):self.commit()

    def test_issue_dropped_without_resolution_is_rejected(self):
        self.prepare(verdicts={'S02':'FAIL'})
        self.final['issues']=[]
        with self.assertRaisesRegex(ValueError,'without resolution'):self.commit()

    def test_mixed_verdicts_and_confirmed_absence_are_preserved(self):
        self.prepare(statuses={'S02':'absent'})
        self.commit()
        r=core.review_current(core.read(self.path),self.path,'G01')
        self.assertEqual([s['verdict'] for s in r['shot_reviews']],['PASS','absent','PASS'])
        self.assertEqual(r['checks']['story'],'FAIL')
        self.assertEqual(r['reference_assessments'][1]['decision'],'ai_fill')

    def test_uncertainty_remains_unknown_not_absence(self):
        self.prepare(statuses={'S02':'uncertain'})
        self.audit['deferred_shot_ids']=['S02']
        self.commit()
        r=core.read(self.path)['reviews'][-1]
        self.assertEqual(r['shot_reviews'][1]['verdict'],'uncertain')
        self.assertEqual(r['reference_assessments'][1]['decision'],'pending')

    def test_recheck_cap_and_no_promoting_deferred(self):
        self.prepare()
        b=core.read(self.bundle_dir/'bundle.json');c=copy.deepcopy(self.collected)
        b['context']['shots']=[dict(shot_id=f'S{i}') for i in range(8)]
        c['boundary_audit_required']=[];self.audit['boundaries']=[]
        self.audit['rechecked_shot_ids']=[f'S{i}' for i in range(5)]
        with self.assertRaisesRegex(ValueError,'cap exceeded'):
            parallel.audit_final(b,c,self.final,self.audit)
        self.audit['rechecked_shot_ids']=[];self.audit['deferred_shot_ids']=['S01']
        b=core.read(self.bundle_dir/'bundle.json');self.audit['boundaries']=[dict(row,verdict='PASS',visual_reason='seen',state_reason='checked') for row in self.collected['boundary_audit_required']]
        with self.assertRaisesRegex(ValueError,'must remain uncertain'):
            parallel.audit_final(b,self.collected,self.final,self.audit)

    def test_lock_and_repeat_commit_prevent_overwrite(self):
        self.prepare()
        with core.locked(self.path):
            with self.assertRaises(FileExistsError):self.commit()
        self.commit()
        with self.assertRaisesRegex(ValueError,'project changed'):self.commit()


if __name__=='__main__':
    unittest.main()
