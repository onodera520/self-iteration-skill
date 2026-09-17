"""Incremental drafts preserve approvals' validation path; visual content is simulated."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest

import test_imported_review as fixtures
import previs as core
import storyboard as boards
import planner
import incremental


class IncrementalReviewTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.ImportedReviewTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.mapping = self.case.mapping()
        core.record_review(self.case.p, self.case.path, self.case.review_data())
        self.old_review = copy.deepcopy(self.case.p['reviews'][-1])

    def prepare(self, fresh_time=None):
        c = self.case
        evidence = core.read(self.mapping['evidence_file'])
        if fresh_time is not None:
            path = c.png('new-frame', (200,100,50))
            evidence['frames'].append(dict(path=str(path),sha256=core.sha(path),time=fresh_time))
            evidence['sampling'] = dict(dense_ranges=[[fresh_time-.1,fresh_time+.1]])
        out = c.path.parent / 'incremental-evidence.json'
        core.save(out,evidence)
        report_path = c.path.parent / 'incremental-review.json'
        report = incremental.prepare(c.p,c.path,'G01',out,report_path)
        return report, report_path

    def test_unchanged_rows_are_drafts_not_revived_approval_and_delivery_identical(self):
        c = self.case
        full = planner.post_review_plan(c.p,c.path,{})
        planner.store_aggregation(c.p,c.path,full)
        before_dir = c.path.parent / 'before'
        boards.render(c.p,c.path,before_dir)
        report, path = self.prepare()
        self.assertTrue(report['draft_only'])
        self.assertEqual(report['impact']['reuse'],['S01','S02','S03'])
        boards.record_mapping_batch(c.p,c.path,report['mapping_draft'])
        self.assertIsNone(core.review_current(c.p,c.path,'G01'))
        pending = planner.post_review_plan(c.p,c.path,{})
        self.assertTrue(all(d['status']=='pending' for d in pending['decisions']))
        with self.assertRaises(ValueError):
            core.record_review(c.p,c.path,self.old_review)
        ctx = incremental.resume_context(c.p,c.path,'G01',path)
        inc = ctx['incremental']
        self.assertEqual(inc['needs_review_rows'],[])
        self.assertEqual(len(inc['reusable_observations']),3)
        self.assertNotIn('checks',inc['review_draft'])
        self.assertNotIn('context_fingerprint',inc['review_draft'])
        # Agent retains observations, reviews aggregate checks, then uses normal validator.
        new = c.review_data()
        new.update(inc['review_draft'])
        core.record_review(c.p,c.path,new)
        planner.store_aggregation(c.p,c.path,planner.post_review_plan(c.p,c.path,{}))
        after_dir = c.path.parent / 'after'
        boards.render(c.p,c.path,after_dir)
        contents = lambda folder: {f.relative_to(folder).as_posix():f.read_bytes() for f in folder.rglob('*') if f.is_file()}
        self.assertEqual(contents(before_dir),contents(after_dir))

    def test_new_frames_recheck_affected_rows_but_keep_old_visible_facts(self):
        c = self.case
        report,path = self.prepare(2.6)
        self.assertIn('S02',report['impact']['primary'])
        boards.record_mapping_batch(c.p,c.path,report['mapping_draft'])
        before = copy.deepcopy(c.p)
        ctx = incremental.resume_context(c.p,c.path,'G01',path)
        self.assertEqual(c.p,before)
        self.assertEqual(ctx['incremental']['review_draft']['shot_reviews'],[])
        self.assertEqual(ctx['incremental']['reusable_observations'],self.old_review['evidence'])
        self.assertIsNone(core.review_current(c.p,c.path,'G01'))

    def test_cli_context_uses_report_after_batch_remap(self):
        c = self.case
        report,path = self.prepare()
        with self.assertRaisesRegex(ValueError,'batch map'):
            incremental.resume_context(c.p,c.path,'G01',path)
        boards.record_mapping_batch(c.p,c.path,report['mapping_draft'])
        core.save(c.path,c.p)
        result = subprocess.run([sys.executable,core.__file__,'context',str(c.path),'G01',
            '--incremental-from',str(path)],capture_output=True,text=True,encoding='utf8')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('review_draft',result.stdout)

    def test_manifest_and_snapshot_tampering_rejected(self):
        c = self.case
        report,path = self.prepare()
        boards.record_mapping_batch(c.p,c.path,report['mapping_draft'])
        modified = copy.deepcopy(report)
        modified['base_context']['shots'][0]['script'] = 'changed'
        core.save(path,modified)
        with self.assertRaisesRegex(ValueError,'snapshot changed'):
            incremental.resume_context(c.p,c.path,'G01',path)
        core.save(path,report)
        ev = core.read(report['evidence_file'])
        ev['frames'][0]['time'] += .1
        core.save(report['evidence_file'],ev)
        with self.assertRaisesRegex(ValueError,'manifest changed'):
            incremental.resume_context(c.p,c.path,'G01',path)

    def test_replaced_source_or_image_cannot_reuse_draft(self):
        for target in ('video','frame','asset'):
            with self.subTest(target=target):
                c = self.case
                report,path = self.prepare()
                boards.record_mapping_batch(c.p,c.path,report['mapping_draft'])
                ctx = report['base_context']
                file = Path(ctx['video'] if target=='video' else ctx['extraction']['frames'][0]['path']
                            if target=='frame' else ctx['assets'][0]['path'])
                original = file.read_bytes()
                try:
                    file.write_bytes(b'changed')
                    with self.assertRaises(ValueError):
                        incremental.resume_context(c.p,c.path,'G01',path)
                finally:
                    file.write_bytes(original)

    def test_additive_evidence_required(self):
        c = self.case
        report,path = self.prepare()
        ev = core.read(report['evidence_file'])
        ev['frames'].pop()
        core.save(report['evidence_file'],ev)
        with self.assertRaisesRegex(ValueError,'retain all prior frames'):
            incremental.prepare(c.p,c.path,'G01',report['evidence_file'],path)


class ImpactTests(unittest.TestCase):
    def setUp(self):
        # Isolate conservative routing from actual visual review. Candidate times
        # deliberately do not assert exact shot boundaries.
        self.ids = [f'S{i:02}' for i in range(1,9)]
        self.p = dict(shots=[dict(id=s,requirements={}) for s in self.ids],groups=[dict(id='G01',shot_ids=self.ids)])
        frames = [dict(path=str(Path(f'frame-{i}.png').resolve()),sha256=str(i),time=i*2+.25) for i in range(8)]
        self.old = dict(group_id='G01',video_sha256='video',version=1,group_fingerprint='script',review_schema=5,
            reference_policy_version=5,assets=[dict(id='A01',sha256='asset')],boundaries=[],
            shots=[dict(shot_id=s,asset_ids=['A01']) for s in self.ids],extraction=dict(frames=frames),
            mapping=dict(shots=[dict(shot_id=s,status='matched',candidates=[frames[i]]) for i,s in enumerate(self.ids)]))
        self.current = copy.deepcopy(self.old)
        self.evidence = dict(frames=frames+[dict(path=str(Path('new.png').resolve()),sha256='new',time=4.3)],duration=16)

    def analyze(self):
        return incremental.analyze(self.p,self.old,self.current,self.evidence,None)

    def test_local_frames_leave_distant_matches_untouched(self):
        report = self.analyze()
        self.assertIn('S03',report['primary'])
        self.assertTrue({'S01','S06','S07','S08'} <= set(report['reuse']))
        self.assertNotIn('S03',report['reuse'])

    def test_unresolved_shot_not_skipped_by_guessed_time(self):
        self.old['mapping']['shots'][7].update(status='uncertain',candidates=[])
        self.current = copy.deepcopy(self.old)
        self.assertIn('S08',self.analyze()['primary'])

    def test_state_and_reference_dependency_expand_beyond_neighbors(self):
        self.p['shots'][7]['requirements']['inherits_from']='S03'
        self.p['reviews']=[dict(group_id='G01',reference_assessments=[dict(shot_id='S07',basis_shot_ids=['S03','S08'])])]
        report = self.analyze()
        self.assertTrue({'S07','S08'} <= set(report['dependency_recheck']))
        self.assertNotIn('S07',report['reuse'])

    def test_rule_or_script_changes_cannot_reuse_old_verdicts(self):
        for field,value in (('review_schema',6),('reference_policy_version',6),('group_fingerprint','new-script')):
            with self.subTest(field=field):
                self.current=copy.deepcopy(self.old)
                self.current[field]=value
                self.assertEqual(self.analyze()['reuse'],[])

    def test_asset_change_invalidates_all_dependent_shots(self):
        self.current['assets'][0]['sha256']='new-asset'
        self.assertEqual(self.analyze()['reuse'],[])

    def test_neighbor_group_change_rechecks_correct_local_edge(self):
        self.evidence['frames']=self.old['extraction']['frames']
        self.p['shots'].append(dict(id='S09',requirements={}))
        self.p['groups'].append(dict(id='G02',shot_ids=['S09']))
        self.current['boundaries']=[dict(group_id='G02',shot_id='S09',video_sha256='new-video')]
        report=self.analyze()
        self.assertEqual(report['boundary_recheck'],['S09'])
        self.assertEqual(report['adjacent'],['S08'])
        self.assertIn('S01',report['reuse'])


if __name__ == '__main__':
    unittest.main()
