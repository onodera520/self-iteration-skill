"""Simulated judgments/transport, not real visual or paid-workflow acceptance."""
import copy
import hashlib
from pathlib import Path
from unittest.mock import patch
import unittest

import test_previs as fixtures
import test_imported_review as imported_fixtures
import previs as core
import planner
import repair_cycle as repair
import repair_prompt
import repair_aspect
import repair_reference


class FakeWorkflow:
    def __init__(self):
        self.submissions = self.queries = self.downloads = 0
        self.create_error = self.query_error = self.download_error = False
        self.status = 'SUCCESS'

    def prepare(self, request):
        return {'prepared': True}

    def submit(self, request):
        self.submissions += 1
        if self.create_error:
            raise TimeoutError('SIMULATED unknown create')
        return {'taskId': '123456'}

    def query(self, task_id):
        self.queries += 1
        if self.query_error:
            raise TimeoutError('SIMULATED query timeout')
        return dict(taskId=task_id, status=self.status, results=[dict(url='https://example.invalid/output.mp4', outputType='mp4')])

    def download(self, url, path):
        self.downloads += 1
        if self.download_error:
            raise OSError('SIMULATED download interruption')
        path.write_bytes(b'SIMULATED local video G01 2')


class RepairCycleTests(fixtures.Base):
    png = imported_fixtures.ImportedReviewTests.png
    select_mapping = imported_fixtures.ImportedReviewTests.select_mapping
    mapping = imported_fixtures.ImportedReviewTests.mapping
    review_data = imported_fixtures.ImportedReviewTests.review_data
    finish = imported_fixtures.ImportedReviewTests.finish
    def setUp(self):
        imported_fixtures.ImportedReviewTests.setUp(self)
        # Synthetic video bytes cannot be probed. The real-media tests exercise ffprobe.
        self.aspect_probe = patch.object(repair_aspect, 'probe', return_value={
            'streams': [dict(codec_type='video', width=1920, height=1080, sample_aspect_ratio='1:1')]})
        self.mock_aspect_probe = self.aspect_probe.start()
        self.addCleanup(self.aspect_probe.stop)
        self.p['repair_asset_style'] = dict(preserves_story=True, assets=[dict(
            asset_id=a['id'], sha256=core.sha(Path(a['path'])), visible_style_facts=['SIMULATED flat colour'],
            guidance='SIMULATED asset style, not real visual acceptance') for a in self.p['assets']])

    def assessment(self, review, critical=False):
        ss = {s['id']: s for s in self.p['shots']}
        review['repair_assessments'] = [dict(shot_id=v['shot_id'], critical=critical,
            critical_kind='wrong_transfer_result' if critical else None, affects_story=True,
            script_quote=ss[v['shot_id']]['script'], impact='SIMULATED wrong key holder changes transfer causality',
            issue_ids=['issue-'+v['shot_id']], correction='按本镜原文恢复钥匙持有者和交接结果，不改变其他镜头。',
            preserves_script=True) for v in review['shot_reviews'] if v['verdict'] in ('FAIL','absent')]
        return review

    def ready(self, verdicts=None, statuses=None, critical=True, derivable=False):
        self.p['config']['max_submissions'] = 3
        repair.baseline(self.p)
        if verdicts is None:
            verdicts = {'S02':'absent'}
            if statuses is None:
                statuses = {'S02':'absent'}
        self.mapping(statuses)
        review = self.assessment(self.review_data(verdicts, middle_derivable=derivable), critical)
        self.finish(review)
        d = repair.decide(self.p, self.path, 'G01')
        return d

    def start(self, transport=None):
        self.ready()
        original = repair.snapshot(self.p, self.path, self.path.parent/'original', 'original')
        api = transport or FakeWorkflow()
        status = repair.submit(self.p, self.path, 'G01', api, True)
        key = next(k for k,t in self.p['tasks'].items() if t.get('repair_source_group'))
        return api, key, original, status

    def test_threshold_critical_cumulative_exact_and_deduplication(self):
        cases = [
            (3,['a'],['a'],[],False), (3,['a','b'],['a'],[],False),
            (14,['a','b'],['a','b'],[],False),
            (15,['a','b','c'],[],[],True), (16,['a','b','c'],['a'],[],False),
            (10,['a','a','b'],[],[],False), (10,['a','b','c','c'],[],[],True),
            (100,['a'],['a'],['a'],True), (10,['a','b'],[],['a'],True),
            (11,['a','b'],[],['a'],False), (3,['a'],[],['a'],False),
            (100,['a','b'],['b'],['a'],True)]
        for total, ids, critical, missing, expected in cases:
            with self.subTest(total=total,ids=ids,critical=critical,missing=missing):
                d = repair.threshold(total,ids,critical,missing)
                self.assertEqual(d['triggered'],expected)
                self.assertEqual(d['error_count'],len(set(ids)))
                self.assertEqual(d['necessary_missing_shot_ids'],missing)
        with self.assertRaises(ValueError):
            repair.threshold(3,['a'],[],['b'])

    def test_no_missing_failures_keep_verdict_and_block_paid_submission(self):
        for verdicts in ({'S02':'FAIL'}, {'S01':'FAIL','S02':'FAIL'}):
            with self.subTest(verdicts=verdicts):
                d = self.ready(verdicts, critical=True)
                self.assertFalse(d['triggered'])
                self.assertEqual(d['necessary_missing_shot_ids'],[])
                self.assertEqual(d['review_verdict'],'FAIL')
                self.assertEqual(set(d['allowed_correction_shot_ids']),set(verdicts))
                api = FakeWorkflow()
                with self.assertRaisesRegex(ValueError,'threshold not reached'):
                    repair.prepare(self.p,self.path,'G01')
                with self.assertRaises(ValueError):
                    repair.submit(self.p,self.path,'G01',api,True)
                self.assertEqual(api.submissions,0)

    def test_three_confirmed_failures_trigger_without_missing(self):
        d = self.ready({'S01':'FAIL','S02':'FAIL','S03':'FAIL'},critical=False)
        self.assertTrue(d['triggered'])
        self.assertEqual(d['trigger'],'cumulative')
        self.assertEqual(d['total'],3)
        self.assertEqual(d['necessary_missing_shot_ids'],[])

    def test_policy_change_invalidates_old_decision_without_new_review(self):
        with patch.object(repair,'POLICY',1):
            self.ready({'S02':'FAIL'})
        with self.assertRaisesRegex(ValueError,'stale'):
            repair.current_decision(self.p,self.path,'G01')
        d = repair.decide(self.p,self.path,'G01')
        self.assertEqual(d['binding']['policy'],2)
        self.assertFalse(d['triggered'])

    def test_real_decision_excludes_derivable_missing_and_preserves_bad_num(self):
        self.ready({'S02':'absent'}, {'S02':'absent'}, critical=False, derivable=True)
        d = self.p['repair_decisions']['G01']
        self.assertFalse(d['triggered'])
        self.assertEqual(d['problem_shot_ids'],[])
        self.assertEqual(d['allowed_correction_shot_ids'],[])
        self.assertEqual(self.p['aggregation']['missing_summary'][0]['bad_num'],0)
        self.assertEqual(core.review_current(self.p,self.path,'G01')['verdict'],'FAIL')

    def test_necessary_absence_and_uncertain_count_independently(self):
        self.p['config']['max_submissions']=1
        self.mapping({'S01':'absent','S02':'uncertain'})
        self.finish(self.assessment(self.review_data({'S01':'absent','S02':'uncertain'},middle_derivable=False),True))
        d=repair.decide(self.p,self.path,'G01')
        self.assertEqual(d['problem_shot_ids'],['S01'])
        self.assertEqual(d['critical_shot_ids'],['S01'])
        self.assertTrue(d['triggered'])
        self.assertEqual(d['necessary_missing_shot_ids'],['S01'])
        self.assertEqual(self.p['aggregation']['missing_summary'][0]['bad_num'],1)

    def test_missing_semantic_basis_blocks_automatic_decision(self):
        self.mapping()
        self.finish(self.review_data({'S02':'FAIL'}))
        with self.assertRaisesRegex(ValueError,'repair_assessments'):
            repair.decide(self.p,self.path,'G01')

    def test_assessment_cannot_borrow_other_shot_or_script(self):
        self.mapping()
        review=self.assessment(self.review_data({'S02':'FAIL'}),True)
        for field,value in [('script_quote','INVENTED STORY'),('issue_ids',['issue-S01']),('impact',''),('preserves_script',False)]:
            bad=copy.deepcopy(review)
            bad['repair_assessments'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                core.record_review(self.p,self.path,bad)

    def test_prompt_preserves_all_original_text_order_assets_and_duration(self):
        self.ready()
        request=repair.prepare(self.p,self.path,'G01')
        self.assertEqual([b['text'] for b in request['blocks']],[s['script'] for s in self.p['shots']])
        self.assertEqual([b['shot_id'] for b in request['blocks']],['S01','S02','S03'])
        self.assertEqual([b['shot_id'] for b in request['blocks'] if 'correction' in b],['S02'])
        self.assertEqual([a['id'] for a in request['assets']],[a['id'] for a in self.p['assets']])
        self.assertEqual(request['duration_seconds'],3)
        self.assertEqual([b['duration'] for b in request['blocks']],[1.0]*3)
        for i,b in enumerate(request['blocks'],1):
            self.assertIn(f"镜头{i},【生成时长】1.0s。【镜头设计】{b['design']}。【镜头内容】{b['text']}",request['prompt'])
        for mutate in ('prompt','blocks','assets','duration_seconds'):
            bad=copy.deepcopy(request)
            if mutate=='prompt': bad[mutate]+='任意新剧情'
            elif mutate=='blocks': bad[mutate][0]['text']='改写通过镜头'
            elif mutate=='assets': bad[mutate].reverse()
            else: bad[mutate]=2
            with self.subTest(field=mutate),self.assertRaises(ValueError):
                repair.prepare(self.p,self.path,'G01',bad)

    def test_prompt_carries_shot_constraints_without_advancing_transfer_state(self):
        self.ready()
        request=repair.prepare(self.p,self.path,'G01')
        for shot,block in zip(self.p['shots'],request['blocks']):
            with self.subTest(shot=shot['id']):
                req=shot['requirements']
                self.assertEqual(block['must_have'],req['must_have'])
                self.assertEqual(block['must_not_have'],req['must_not_have'])
                self.assertEqual(block['keyframe_target'],dict(phase=req['keyframe']['phase'],description=req['keyframe']['description']))
                line=next(l for l in request['prompt'].splitlines() if '【镜头内容】'+shot['script'] in l)
                for constraint in req['must_have']+req['must_not_have']:
                    self.assertIn(constraint,line)
        # S03 inherits the girl's key from S02, then ends with the boy holding it.
        transfer=request['blocks'][2]
        self.assertEqual(transfer['keyframe_target']['phase'],'exit')
        self.assertEqual(transfer['critical_changes'],['key.holder 由 girl 变为 boy'])
        self.assertIn('【目标静帧】终态：'+transfer['keyframe_target']['description'],request['prompt'])
        self.assertIn(transfer['critical_changes'][0],request['prompt'])
        self.assertNotIn('critical_changes',request['blocks'][1])
        self.assertNotIn('correction',transfer)
        tampered=copy.deepcopy(request)
        tampered['blocks'][2]['keyframe_target']['phase']='entry'
        with self.assertRaises(ValueError):repair.prepare(self.p,self.path,'G01',tampered)

    def test_provisional_requirements_cannot_be_sent_as_generation_constraints(self):
        self.p['shots'][1]['requirements']['status']='provisional'
        self.p['shots'][2]['requirements']['inherits_from']='S01'
        self.ready()
        api=FakeWorkflow()
        with self.assertRaisesRegex(ValueError,'provisional shot requirements'):
            repair.prepare(self.p,self.path,'G01')
        with self.assertRaises(ValueError):repair.submit(self.p,self.path,'G01',api,True)
        self.assertEqual(api.submissions,0)

    def test_changed_requirement_invalidates_repair_before_submission(self):
        self.ready()
        request=repair.prepare(self.p,self.path,'G01')
        self.p['shots'][1]['requirements']['must_not_have'].append('SIMULATED changed target')
        with self.assertRaises(ValueError):repair.prepare(self.p,self.path,'G01',request)
        with self.assertRaises(ValueError):repair.decide(self.p,self.path,'G01')
        api=FakeWorkflow()
        with self.assertRaises(ValueError):repair.submit(self.p,self.path,'G01',api,True)
        self.assertEqual(api.submissions,0)

    def test_fingerprint_invalidation_and_immutable_baseline(self):
        self.ready()
        original=copy.deepcopy(self.p)
        self.p['repair_decisions']['G01']['allowed_correction_shot_ids'].append('S01')
        with self.assertRaises(ValueError):repair.prepare(self.p,self.path,'G01')
        self.p=copy.deepcopy(original)
        self.p['shots'][0]['script']+=' changed'
        with self.assertRaises(ValueError):repair.prepare(self.p,self.path,'G01')
        self.p=copy.deepcopy(original)
        Path(self.p['assets'][0]['path']).write_bytes(b'changed asset')
        with self.assertRaises(ValueError):repair.prepare(self.p,self.path,'G01')

    def test_fixed_previs_tail_style_binding_and_no_extra_visual_pass(self):
        self.ready()
        request=repair.prepare(self.p,self.path,'G01')
        self.assertEqual(request['prompt'].count(repair.PREVIS_DIRECTIVE),1)
        self.assertGreater(request['prompt'].index(repair.PREVIS_DIRECTIVE),request['prompt'].index('镜头3,【生成时长】'))
        self.assertTrue(request['prompt'].startswith(repair_prompt.SILENT_DIRECTIVE+'\n'))
        self.assertTrue(request['prompt'].endswith(repair_prompt.SILENT_DIRECTIVE))
        bad=copy.deepcopy(request)
        bad['prompt']=bad['prompt'].replace(repair.PREVIS_DIRECTIVE,'允许音乐和字幕')
        with self.assertRaises(ValueError):repair.prepare(self.p,self.path,'G01',bad)
        self.p['repair_asset_style']['assets'][0]['guidance']='changed style'
        with self.assertRaisesRegex(ValueError,'stale'):repair.prepare(self.p,self.path,'G01')
        repair.decide(self.p,self.path,'G01')
        self.p['repair_asset_style']['assets'][0]['sha256']='0'*64
        repair.decide(self.p,self.path,'G01')
        with self.assertRaisesRegex(ValueError,'style evidence'):repair.prepare(self.p,self.path,'G01')

    def test_missing_style_or_incompatible_duration_cannot_submit(self):
        self.ready()
        repair.snapshot(self.p,self.path,self.path.parent/'original','original')
        api=FakeWorkflow()
        profile=self.p.pop('repair_asset_style')
        repair.decide(self.p,self.path,'G01')
        with self.assertRaises(ValueError):repair.submit(self.p,self.path,'G01',api,True)
        self.p['repair_asset_style']=profile
        self.p['config']['fixed_workflow_limits']={'max_duration_seconds':2}
        repair.decide(self.p,self.path,'G01')
        with self.assertRaisesRegex(ValueError,'duration'):repair.submit(self.p,self.path,'G01',api,True)
        self.assertEqual(api.submissions,0)

    def test_save_reservation_before_create_and_never_submit_twice(self):
        api=FakeWorkflow()
        original_submit=api.submit
        def check(request):
            disk=core.read(self.path)
            rows=[t for t in disk['tasks'].values() if t.get('repair_source_group')]
            self.assertEqual(rows[0]['status'],'submitting')
            self.assertTrue(rows[0]['reserved'])
            return original_submit(request)
        api.submit=check
        api,key,_,status=self.start(api)
        self.assertEqual(status,'QUEUED')
        self.assertEqual(repair.submit(self.p,self.path,'G01',api,True),'SUCCESS')
        self.assertEqual(repair.submit(self.p,self.path,'G01',api,True),'SUCCESS')
        self.assertEqual(api.submissions,1)

    def test_unknown_submission_survives_reload_until_verified_attach(self):
        api=FakeWorkflow();api.create_error=True
        api,key,_,status=self.start(api)
        self.assertEqual(status,'submission_unknown')
        self.p=core.read(self.path)
        self.assertEqual(repair.submit(self.p,self.path,'G01',api,True),'submission_unknown')
        repair.attach(self.p,key,'123456')
        self.assertEqual(repair.resume(self.p,self.path,key,api),'SUCCESS')
        self.assertEqual(api.submissions,1)

    def test_query_timeout_and_download_retry_never_create_or_requery_success(self):
        api,key,_,_=self.start()
        api.query_error=True
        self.assertEqual(repair.resume(self.p,self.path,key,api),'query_error')
        api.query_error=False;api.download_error=True
        self.assertEqual(repair.resume(self.p,self.path,key,api),'download_error')
        calls=api.queries
        self.p=core.read(self.path)
        api.download_error=False
        self.assertEqual(repair.resume(self.p,self.path,key,api),'SUCCESS')
        self.assertEqual(api.queries,calls)
        self.assertEqual(api.submissions,1)

    def test_failed_task_terminal_and_second_report_forbidden(self):
        api,key,_,_=self.start()
        api.status='FAILED'
        self.assertEqual(repair.resume(self.p,self.path,key,api),'FAILED')
        self.assertEqual(repair.submit(self.p,self.path,'G01',api,True),'FAILED')
        with self.assertRaises(ValueError):repair.snapshot(self.p,self.path,self.path.parent/'new','repaired')
        self.assertEqual(api.submissions,1)

    def apply_new_project_repair_defaults(self):
        config = core.read(fixtures.ROOT / 'ai-storyboard-previs/assets/imported-project.json')['config']
        self.assertEqual(config['max_submissions'], 1)
        self.assertNotIn('budget_cny', config)
        self.p['config']['max_submissions'] = config['max_submissions']
        self.p['config']['max_repair_rounds'] = config['max_repair_rounds']

    def test_new_project_standing_authorization_allows_only_one_fake_submission(self):
        self.ready()
        self.apply_new_project_repair_defaults()
        repair.snapshot(self.p, self.path, self.path.parent / 'original', 'original')
        api = FakeWorkflow()
        # The agent supplies the existing explicit switch under standing user authorization.
        self.assertEqual(repair.submit(self.p, self.path, 'G01', api, True), 'QUEUED')
        self.assertEqual(repair.submit(self.p, self.path, 'G01', api, True), 'SUCCESS')
        self.assertEqual(api.submissions, 1)
        self.assertEqual(api.queries, 1)
        self.assertTrue(repair.decide(self.p, self.path, 'G01')['automatic_allowance_used'])

    def test_new_project_cap_counts_reservation_from_other_source(self):
        self.ready()
        self.apply_new_project_repair_defaults()
        repair.snapshot(self.p, self.path, self.path.parent / 'original', 'original')
        self.p['tasks']['other-source'] = dict(reserved=True, status='submission_unknown')
        api = FakeWorkflow()
        with self.assertRaisesRegex(ValueError, 'Existing submission cap reached'):
            repair.submit(self.p, self.path, 'G01', api, True)
        self.assertEqual(api.submissions, 0)

    def test_existing_budget_caps_rounds_and_missing_authorization_stop(self):
        self.ready()
        repair.snapshot(self.p,self.path,self.path.parent/'original','original')
        api=FakeWorkflow()
        with self.assertRaises(ValueError):repair.submit(self.p,self.path,'G01',api)
        for key,value in [('budget_cny',100),('max_submissions',0),('max_repair_rounds',0)]:
            previous=copy.deepcopy(self.p['config'])
            self.p['config'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):repair.submit(self.p,self.path,'G01',api,True)
            self.p['config']=previous
        self.assertEqual(api.submissions,0)

    def test_new_video_never_inherits_pass_and_first_delivery_immutable(self):
        api,key,original,_=self.start()
        before={f:core.sha(Path(f)) for f in self.p['repair_deliveries']['original']['files']}
        repair.resume(self.p,self.path,key,api)
        # Fake ffprobe only: tests remain explicitly synthetic, not actual video review.
        with patch('media.probe',return_value={'streams':[{'codec_type':'video'}]}),patch('media.duration',return_value=6):
            repair.install(self.p,self.path,key)
        self.assertEqual(core.group(self.p,'G01')['version'],2)
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        with self.assertRaises(ValueError):repair.snapshot(self.p,self.path,self.path.parent/'new','repaired')
        # Replace output with independent simulated video/evidence; formerly passed S01 now fails.
        self.mapping(revision=2)
        self.finish(self.assessment(self.review_data({'S01':'FAIL'},middle_derivable=False),True))
        second=repair.snapshot(self.p,self.path,self.path.parent/'new','repaired')
        text=Path(second).read_text(encoding='utf-8')
        self.assertIn('该镜需重新生成',next(l for l in text.splitlines() if '| S01 |' in l))
        self.assertIn('一次自动返修额度已用完',text)
        self.assertEqual(sum(l.startswith('| --- |') for l in text.splitlines()),2)
        self.assertEqual(before,{f:core.sha(Path(f)) for f in before})
        self.assertEqual(Path(original).name,'01_原视频审查.md')
        self.assertEqual(Path(second).name,'02_返修视频审查.md')
        for stage in ('repaired2','repaired3'):
            out=self.path.parent/stage
            with self.subTest(stage=stage),self.assertRaises(ValueError):
                repair.snapshot(self.p,self.path,out,stage)
            self.assertFalse(out.exists())
            self.assertNotIn(stage,self.p['repair_deliveries'])
        self.assertTrue(repair.decide(self.p,self.path,'G01')['automatic_allowance_used'])
        repair.submit(self.p,self.path,'G01',api,True)
        self.assertEqual(api.submissions,1)

    def test_redeciding_after_reservation_keeps_prompt_fingerprint(self):
        api,key,_,_=self.start()
        before=copy.deepcopy(self.p['tasks'][key]['request'])
        updated=repair.decide(self.p,self.path,'G01')
        self.assertTrue(updated['automatic_allowance_used'])
        self.assertEqual(repair.prepare(self.p,self.path,'G01'),before)
        repair.resume(self.p,self.path,key,api)
        with patch('media.probe',return_value={'streams':[{'codec_type':'video'}]}),patch('media.duration',return_value=6):
            repair.install(self.p,self.path,key)

    def test_historical_round_reports_use_latest_bound_video_without_more_submissions(self):
        api, key, original, _ = self.start()
        original_hash = core.sha(Path(original))
        repair.resume(self.p, self.path, key, api)
        with patch('media.probe', return_value={'streams': [{'codec_type': 'video'}]}), patch('media.duration', return_value=6):
            repair.install(self.p, self.path, key)
        self.mapping(revision=2)
        self.finish(self.assessment(self.review_data({'S01': 'FAIL'}, middle_derivable=False), True))
        # Synthetic historical bookkeeping only: no second workflow execution or visual acceptance.
        historical = copy.deepcopy(self.p['tasks'][key])
        historical.update(id='historical', installed_version=1, output_hashes=['obsolete-output'])
        self.p['tasks']['historical'] = historical  # Old task occurs after latest: order must not select it.
        self.p['repair_round'] = 2
        report = repair.snapshot(self.p, self.path, self.path.parent / 'round2', 'repaired2')
        self.assertEqual(Path(report).name, '03_返修视频审查（第二轮）.md')
        self.assertEqual(sum(l.startswith('| --- |') for l in Path(report).read_text(encoding='utf-8').splitlines()), 2)
        self.assertEqual(core.sha(Path(original)), original_hash)
        self.assertTrue(repair.decide(self.p, self.path, 'G01')['automatic_allowance_used'])
        repair.submit(self.p, self.path, 'G01', api, True)
        self.assertEqual(api.submissions, 1)
        for invalid_stage in ('repaired', 'repaired3'):
            with self.subTest(stage=invalid_stage), self.assertRaisesRegex(ValueError, 'actual installed repair round'):
                repair.snapshot(self.p, self.path, self.path.parent / invalid_stage, invalid_stage)
        self.p['repair_round'] = 3
        with self.assertRaisesRegex(ValueError, 'installed task evidence'):
            repair.snapshot(self.p, self.path, self.path.parent / 'round3', 'repaired3')
        self.p['tasks']['historical']['installed'] = False
        self.p['repair_round'] = 2
        with self.assertRaisesRegex(ValueError, 'not installed'):
            repair.snapshot(self.p, self.path, self.path.parent / 'uninstalled', 'repaired2')

    def test_atomic_multiple_source_install_invalidates_all_boundaries(self):
        for i,s in enumerate(copy.deepcopy(self.p['shots']),4):
            s['id']='S0'+str(i)
            s['continuity_id']='second-transfer'
            parent = s['requirements'].get('inherits_from')
            if parent:
                s['requirements']['inherits_from'] = 'S0'+str(int(parent[1:])+3)
            if i == 4:
                s['script']='男孩把钥匙还给女孩，开始下一次交接。'
                for fact in s['facts']:
                    if fact['attribute']=='holder':fact['value']='boy'
                s['requirements']['entry_state']['key.holder']='boy'
                s['state_changes']=[dict(entity='key',attribute='holder',before='boy',after='girl',
                    critical=True,authorized=True,source=dict(kind='script',ref=s['script']))]
            self.p['shots'].append(s)
        self.p['groups'].append(dict(id='G02',shot_ids=['S04','S05','S06'],reason='SIMULATED second source',version=1))
        self.p['source_script']=' '.join(s['id']+' '+s['script'] for s in self.p['shots'])
        self.p['narrative_plan']['boundaries']=[dict(before_shot_id=s['id'],merge_allowed=True,strength=2,reason='连续行动') for s in self.p['shots'][1:]]
        self.p['narrative_plan']['safe_spans']=[dict(shot_ids=[s['id'] for s in self.p['shots']],reason='SIMULATED safe full story')]
        self.p['config']['max_submissions']=2
        for gid,sid in [('G01','S02'),('G02','S05')]:
            self.mapping({sid:'absent'},gid=gid)
        for gid,sid in [('G01','S02'),('G02','S05')]:
            core.record_review(self.p,self.path,self.assessment(self.review_data({sid:'absent'},middle_derivable=False,gid=gid),True))
        planner.store_aggregation(self.p,self.path,planner.post_review_plan(self.p,self.path,{}))
        for gid in ('G01','G02'): repair.decide(self.p,self.path,gid)
        repair.snapshot(self.p,self.path,self.path.parent/'original','original')
        api=FakeWorkflow()
        for gid in ('G01','G02'): repair.submit(self.p,self.path,gid,api,True)
        keys=list(self.p['tasks'])
        for key in keys: repair.resume(self.p,self.path,key,api)
        with self.assertRaisesRegex(ValueError,'Multiple sources'): repair.install(self.p,self.path,keys[0])
        with patch('media.probe',return_value={'streams':[{'codec_type':'video'}]}),patch('media.duration',return_value=6):
            repair.install(self.p,self.path,'all')
        self.assertEqual(self.p['repair_round'],1)
        self.assertEqual([g['version'] for g in self.p['groups']],[2,2])
        self.assertEqual(self.p['repairs'][-1]['recheck'],['G01','G02'])
        self.assertTrue(all(core.review_current(self.p,self.path,gid) is None for gid in ('G01','G02')))
        self.assertEqual(api.submissions,2)

    def test_full_headers_visual_adaptation_preserves_frozen_dialogue_and_actions(self):
        bodies = [s['script'] for s in self.p['shots']]
        bodies[1] += '\n内心OS {等3秒再走。}，随后抬头。'
        for i, (shot, body) in enumerate(zip(self.p['shots'], bodies), 1):
            shot['script'] = f'镜头{i}，【时长】{i+1}s，【镜头设计】近景，侧面平视。\n【镜头内容】{body}'
        self.p['source_script'] = '\n'.join(s['script'] for s in self.p['shots'])
        self.ready()
        visual_body = bodies[1].split('\n内心OS', 1)[0] + '，随后抬头。'
        self.p['repair_visual_adaptations'] = {'S02.generation_text': dict(
            source_sha256=hashlib.sha256(bodies[1].encode('utf-8')).hexdigest(),
            visual_text=visual_body, preserves_story=True, story_basis='保留原有动作与随后抬头，不输出内心声音。')}
        before = copy.deepcopy(self.p)
        request = repair.prepare(self.p, self.path, 'G01')
        self.assertEqual(self.p, before)
        self.assertEqual([b['generation_text'] for b in request['blocks']], [bodies[0], visual_body, bodies[2]])
        self.assertEqual([b['text'] for b in request['blocks']], [s['script'] for s in self.p['shots']])
        self.assertEqual([b['design'] for b in request['blocks']], ['近景，侧面平视']*3)
        for tag in ('【生成时长】', '【镜头设计】', '【镜头内容】'):
            self.assertEqual(request['prompt'].count(tag), 3)
        self.assertNotIn('【时长】', request['prompt'])
        self.assertNotIn('等3秒再走', request['prompt'])
        self.assertIn('内心OS {等3秒再走。}', request['blocks'][1]['text'])
        self.assertIn('随后抬头', request['prompt'])
        self.assertEqual(request['prompt_version'], repair_prompt.VERSION)
        self.assertEqual(request['prompt_fingerprint'], core.digest(dict(
            version=repair_prompt.VERSION, prompt=request['prompt'], blocks=request['blocks'])))

    def test_dialogue_leaks_block_submission_and_adaptations_are_frozen(self):
        original_text = '她皱眉，开口问 {谁？}，随后推门。'
        self.p['shots'][0]['script'] = original_text
        self.p['source_script'] = '\n'.join(s['script'] for s in self.p['shots'])
        self.ready()
        api = FakeWorkflow()
        with self.assertRaisesRegex(ValueError, 'S01.generation_text: visual adaptation required'):
            repair.submit(self.p, self.path, 'G01', api, True)
        self.assertEqual(api.submissions, 0)
        self.assertEqual(self.p.get('tasks', {}), {})
        self.p['repair_visual_adaptations'] = {'S01.generation_text': dict(
            source_sha256=hashlib.sha256(original_text.encode('utf-8')).hexdigest(),
            visual_text='她皱眉，随后推门。', preserves_story=True, story_basis='保持原脚本皱眉和推门，问话只作为内部剧情信息。')}
        request = repair.prepare(self.p, self.path, 'G01')
        self.assertNotIn('谁？', request['prompt'])
        self.assertEqual(request['blocks'][0]['text'], original_text)
        task = dict(repair_source_group='G01', request=request, fingerprint=core.digest(request))
        repair.validate_stored_request(self.p, self.path, task)
        self.p['repair_visual_adaptations']['S01.generation_text']['visual_text'] = '她皱眉。'
        with self.assertRaisesRegex(ValueError, 'Inputs changed'):
            repair.validate_stored_request(self.p, self.path, task)

    def test_legacy_v2_dialogue_request_recovers_without_visual_adaptation(self):
        self.p['shots'][0]['script'] += '，开口问 {谁？}'
        self.p['source_script'] = '\n'.join(s['script'] for s in self.p['shots'])
        self.ready()
        for input_aspect in (False, True):
            with self.subTest(input_aspect=input_aspect):
                request = repair._compose_prompt(self.p, self.path, 'G01', 2, input_aspect=input_aspect)
                self.assertIn('开口问 {谁？}', request['prompt'])
                task = dict(repair_source_group='G01', request=request, fingerprint=core.digest(request))
                repair.validate_stored_request(self.p, self.path, task)
                with self.assertRaises(ValueError):
                    repair.prepare(self.p, self.path, 'G01', request)

    def test_final_prompt_guard_rejects_leaks_outside_shot_body(self):
        self.ready()
        request = repair.prepare(self.p, self.path, 'G01')
        for text in ('图1：配音响起。', '【本镜必须出现】他说 {别走。}', '内心VO：现在离开。'):
            bad = copy.deepcopy(request)
            bad['prompt'] = bad['prompt'].replace('【原始资产风格】', text+'\n【原始资产风格】')
            with self.assertRaisesRegex(ValueError, 'speech/audio/text leaked'):
                repair_prompt.validate(bad, ['S01', 'S02', 'S03'])

    def test_composition_routes_all_dynamic_sources_through_visual_gate(self):
        # Isolate assembly wiring from the already-tested source/review binding gates.
        from requirements import contexts
        self.ready()
        original = copy.deepcopy(repair.baseline(self.p))
        decision = copy.deepcopy(repair.current_decision(self.p, self.path, 'G01'))
        resolved = contexts(self.p)
        asset_id = self.p['assets'][0]['id']
        sources = {
            'S01.generation_text': ('她皱眉，开口问 {谁？}，随后推门。', '她皱眉，随后推门。'),
            'S01.design': ('近景，开口问 {谁？}', '近景'),
            'S02.correction': ('她抬头，开口问 {谁？}', '她抬头'),
            'S01.must_have.0': ('她举灯，开口问 {谁？}', '她举灯'),
            'S01.must_not_have.0': ('她离开时开口问 {谁？}', '她离开'),
            'S01.keyframe_target.description': ('她看门口，开口问 {谁？}', '她看门口'),
            'S01.critical_changes.0': ('girl.action 由 站立 变为 开口问 {谁？}', 'girl.action 由 站立 变为 看向门口'),
            f'asset.{asset_id}.description': ('素衣女孩，开口问 {谁？}', '素衣女孩'),
            f'asset.{asset_id}.guidance': ('写实人物，开口问 {谁？}', '写实人物'),
            'format.0': ('写实画面，开口问 {谁？}', '写实画面')}
        original['shots'][0].update(text=sources['S01.generation_text'][0], design=sources['S01.design'][0])
        original['format_requirements'] = [sources['format.0'][0]]
        decision['assessments'][0]['correction'] = sources['S02.correction'][0]
        resolved['S01'].update(must_have=[sources['S01.must_have.0'][0]],
            must_not_have=[sources['S01.must_not_have.0'][0]],
            keyframe=dict(phase='action', description=sources['S01.keyframe_target.description'][0]))
        self.p['shots'][0]['state_changes'] = [dict(entity='girl', attribute='action', before='站立',
            after='开口问 {谁？}', authorized=True, critical=True)]
        self.p['assets'][0]['description'] = sources[f'asset.{asset_id}.description'][0]
        self.p['repair_asset_style']['assets'][0]['guidance'] = sources[f'asset.{asset_id}.guidance'][0]
        with patch.object(repair, 'baseline', return_value=original), \
             patch.object(repair, 'current_decision', return_value=decision), \
             patch('requirements.contexts', return_value=resolved):
            with self.assertRaises(ValueError) as caught:
                repair._compose_prompt(self.p, self.path, 'G01', repair_prompt.VERSION)
            for path in sources:
                self.assertIn(path + ': visual adaptation required', str(caught.exception))
            self.p['repair_visual_adaptations'] = {path: dict(
                source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(), visual_text=visual,
                preserves_story=True, story_basis='SIMULATED grounded visual adaptation, not visual acceptance')
                for path, (source, visual) in sources.items()}
            before = copy.deepcopy(self.p)
            request = repair._compose_prompt(self.p, self.path, 'G01', repair_prompt.VERSION)
        self.assertEqual(self.p, before)
        self.assertEqual(set(request['visual_adaptations']), set(sources))
        self.assertNotIn('谁？', request['prompt'])
        self.assertEqual(request['blocks'][0]['text'], sources['S01.generation_text'][0])
        for _, visual in sources.values():
            self.assertIn(visual, request['prompt'])

    def test_collect_all_malformed_original_headers_and_block_before_submit(self):
        for shot in self.p['shots'][:2]:
            shot['script'] = '【时长】3s，缺少完整镜头头部。' + shot['script']
        self.p['source_script'] = '\n'.join(s['script'] for s in self.p['shots'])
        self.ready()
        before = copy.deepcopy(self.p)
        api = FakeWorkflow()
        with self.assertRaises(ValueError) as caught:
            repair.submit(self.p, self.path, 'G01', api, True)
        self.assertIn('S01:', str(caught.exception))
        self.assertIn('S02:', str(caught.exception))
        self.assertEqual(api.submissions, 0)
        self.assertEqual(self.p, before)

    def test_collect_all_generated_request_errors(self):
        self.ready()
        bad = copy.deepcopy(repair.prepare(self.p, self.path, 'G01'))
        bad['blocks'].reverse()
        bad['blocks'][0]['generation_text'] = ''
        bad['blocks'][1].pop('keyframe_target')
        bad['duration_seconds'] = 14
        bad['prompt'] += '\n【镜头设计】重复【时长】3s'
        with self.assertRaises(ValueError) as caught:
            repair.prepare(self.p, self.path, 'G01', bad)
        for message in ('count/order', 'empty shot content', 'missing keyframe', 'duration sum', 'duplicate', 'leaked'):
            self.assertIn(message, str(caught.exception))

    def test_fail_and_absent_get_distinct_repair_labels(self):
        self.ready({'S01':'FAIL', 'S02':'absent'}, {'S02':'absent'})
        request = repair.prepare(self.p, self.path, 'G01')
        self.assertIn('【已定位画面修正】镜头1=S01', request['prompt'])
        self.assertIn('【必要漏镜补齐】镜头2=S02', request['prompt'])
        self.assertNotIn('以下镜头在上一次生成中缺失', request['prompt'])

    def test_prompt_preview_never_overwrites_previous_request(self):
        self.ready()
        request = repair.prepare(self.p, self.path, 'G01')
        path = self.path.parent / '.repair/G01-prompt.json'
        old = repair._compose_prompt(self.p, self.path, 'G01', 0)
        core.save(path, old)
        before = path.read_bytes()
        target = repair.save_prompt(path, request)
        self.assertNotEqual(path, target)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(core.read(target), request)
        self.assertEqual(repair.save_prompt(path, request), target)
        with self.assertRaisesRegex(ValueError, 'choose a new output'):
            repair.save_prompt(path, request, explicit=True)
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_formats_recover_and_install_without_new_submission(self):
        self.ready()
        original = copy.deepcopy(self.p)
        for version in (None, 0, 2, 3, repair_prompt.VERSION):
            with self.subTest(version=version):
                self.p = copy.deepcopy(original)
                request = repair._compose_prompt(self.p, self.path, 'G01', version)
                task = dict(id='old-task', kind='fixed_workflow_video', target_id='G01',
                    repair_source_group='G01', request=request, fingerprint=core.digest(request),
                    reserved=True, status='query_error', task_id='123456', installed=False,
                    outputs=[], output_hashes=[])
                self.p['tasks']['old-task'] = task
                api = FakeWorkflow()
                with self.assertRaises(ValueError):
                    repair.prepare(self.p, self.path, 'G01', request)
                self.assertEqual(repair.submit(self.p, self.path, 'G01', api, True), 'SUCCESS')
                repair.validate_stored_request(self.p, self.path, task)
                self.assertEqual(task['request'], request)
                with patch('media.probe', return_value={'streams':[{'codec_type':'video'}]}), patch('media.duration', return_value=6):
                    repair.install(self.p, self.path, 'old-task')
                self.assertTrue(self.p['tasks']['old-task']['installed'])
                self.assertEqual(api.submissions, 0)
                self.assertEqual(api.queries, 1)
                self.assertIsNone(core.review_current(self.p, self.path, 'G01'))

    def test_legacy_request_does_not_bypass_input_or_tamper_checks(self):
        self.ready()
        request = repair._compose_prompt(self.p, self.path, 'G01', 0)
        task = dict(repair_source_group='G01', request=request, fingerprint=core.digest(request))
        request['prompt'] += '改写剧情'
        with self.assertRaisesRegex(ValueError, 'Invalid stored'):
            repair.validate_stored_request(self.p, self.path, task)
        task['fingerprint'] = core.digest(request)
        with self.assertRaisesRegex(ValueError, 'Inputs changed'):
            repair.validate_stored_request(self.p, self.path, task)
        request = repair._compose_prompt(self.p, self.path, 'G01', 0)
        task.update(request=request, fingerprint=core.digest(request))
        Path(self.p['assets'][0]['path']).write_bytes(b'REPLACED')
        with self.assertRaises(ValueError):
            repair.validate_stored_request(self.p, self.path, task)

    def test_input_portrait_overrides_config_without_mutating_project(self):
        self.ready()
        before = copy.deepcopy(self.p)
        self.mock_aspect_probe.return_value = {'streams': [dict(codec_type='video', width=1080, height=1920)]}
        request = repair.prepare(self.p, self.path, 'G01')
        self.assertEqual(request['aspect_ratio'], '9:16')
        self.assertIn('画幅：9:16', request['prompt'])
        self.assertEqual(request['input_aspect']['video_sha256'], request['binding']['video_sha256'])
        self.assertEqual(request['input_aspect']['policy'], repair_aspect.POLICY)
        self.assertEqual(self.p, before)
        self.mock_aspect_probe.return_value = {'streams': [dict(codec_type='video', width=1376, height=768)]}
        following = repair.prepare(self.p, self.path, 'G01')
        self.assertEqual(following['aspect_ratio'], '16:9')
        self.assertEqual(self.p, before)

    def test_unsupported_input_stops_before_reserving_or_submitting(self):
        self.ready()
        repair.snapshot(self.p, self.path, self.path.parent / 'original', 'original')
        before = copy.deepcopy(self.p)
        api = FakeWorkflow()
        self.mock_aspect_probe.return_value = {'streams': [dict(codec_type='video', width=1000, height=1000)]}
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            repair.submit(self.p, self.path, 'G01', api, True)
        self.assertEqual(api.submissions, 0)
        self.assertEqual(self.p, before)

    def test_new_aspect_request_is_frozen_and_recovery_never_resubmits(self):
        self.mock_aspect_probe.return_value = {'streams': [dict(codec_type='video', width=1080, height=1920)]}
        api = FakeWorkflow()
        api.create_error = True
        api, key, _, status = self.start(api)
        self.assertEqual(status, 'submission_unknown')
        saved = copy.deepcopy(self.p['tasks'][key]['request'])
        self.assertEqual(saved['aspect_ratio'], '9:16')
        self.mock_aspect_probe.return_value = {'streams': [dict(codec_type='video', width=1920, height=1080)]}
        self.assertEqual(repair.submit(self.p, self.path, 'G01', api, True), 'submission_unknown')
        self.assertEqual(api.submissions, 1)
        self.assertEqual(self.p['tasks'][key]['request'], saved)
        with self.assertRaisesRegex(ValueError, 'Inputs changed'):
            repair.validate_stored_request(self.p, self.path, self.p['tasks'][key])

    def test_source_changed_during_probe_rejects_request(self):
        self.ready()
        _, path = core.current_video(self.p, self.path, core.group(self.p, 'G01'))
        def replace_source(_):
            path.write_bytes(b'REPLACED DURING PROBE')
            return {'streams': [dict(codec_type='video', width=1920, height=1080)]}
        self.mock_aspect_probe.side_effect = replace_source
        with self.assertRaisesRegex(ValueError, 'changed while probing'):
            repair.prepare(self.p, self.path, 'G01')


    def reference_ready(self, prepare_review=True):
        if prepare_review:
            self.ready()
        raw = '雨夜冷光。角色开口说话并配字幕。'
        source = repair_reference.register(self.p, self.path, 'G01', raw)
        bound = repair.current_decision(self.p, self.path, 'G01')['binding']
        assessment = dict(source_sha256=source['text_sha256'], video_sha256=source['video_sha256'],
            script_fingerprint=bound['script_fingerprint'], preserves_story=True,
            compatibility_reason='SIMULATED compatible visual atmosphere; script and fixed generation rules retain priority',
            selections=[dict(shot_id='S01', source_quote='雨夜冷光。',
                script_quote=self.p['shots'][0]['script'], visual_text='雨夜冷光。')],
            excluded=[dict(source_quote='角色开口说话并配字幕。', reason='与无声、无屏幕文字生成要求冲突')])
        self.p['repair_prompt_references'] = {'G01': assessment}
        return source, assessment

    def test_original_prompt_selected_only_and_visual_review_unchanged(self):
        self.ready()
        fingerprint = core.group_fingerprint(self.p, self.path, core.group(self.p, 'G01'))
        reviewed = copy.deepcopy(core.review_current(self.p, self.path, 'G01'))
        grouped = copy.deepcopy(planner.current_aggregation(self.p, self.path))
        self.reference_ready(prepare_review=False)
        request = repair.prepare(self.p, self.path, 'G01')
        self.assertIn('【原提示词参考】雨夜冷光。', request['prompt'])
        self.assertNotIn('角色开口说话并配字幕。', request['prompt'])
        self.assertEqual(request['blocks'][0]['text'], self.p['shots'][0]['script'])
        self.assertEqual(fingerprint, core.group_fingerprint(self.p, self.path, core.group(self.p, 'G01')))
        self.assertEqual(reviewed, core.review_current(self.p, self.path, 'G01'))
        self.assertEqual(grouped, planner.current_aggregation(self.p, self.path))

    def test_original_prompt_bad_bindings_and_leakage_rejected(self):
        self.reference_ready()
        original = copy.deepcopy(self.p)
        for key, value in [('source_sha256', '0'*64), ('video_sha256', '0'*64),
                           ('script_fingerprint', '0'*64), ('preserves_story', False),
                           ('compatibility_reason', '')]:
            with self.subTest(key=key):
                self.p = copy.deepcopy(original)
                self.p['repair_prompt_references']['G01'][key] = value
                with self.assertRaises(ValueError):
                    repair.prepare(self.p, self.path, 'G01')
        for key, value in [('shot_id', 'other'), ('script_quote', 'NOT IN SCRIPT'),
                           ('source_quote', 'NOT IN PROMPT'), ('visual_text', '角色开口说话')]:
            with self.subTest(key=key):
                self.p = copy.deepcopy(original)
                self.p['repair_prompt_references']['G01']['selections'][0][key] = value
                with self.assertRaises(ValueError):
                    repair.prepare(self.p, self.path, 'G01')
        self.p = copy.deepcopy(original)
        self.p['source_video_prompts']['G01']['video_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'source video'):
            repair.prepare(self.p, self.path, 'G01')

    def test_original_prompt_changes_invalidate_preview_but_preserve_stored_request(self):
        self.reference_ready()
        request = repair.prepare(self.p, self.path, 'G01')
        task = dict(request=copy.deepcopy(request), fingerprint=core.digest(request), repair_source_group='G01')
        repair_reference.register(self.p, self.path, 'G01', '新的原提示词')
        with self.assertRaisesRegex(ValueError, 'stale prompt'):
            repair.prepare(self.p, self.path, 'G01', request)
        repair.validate_stored_request(self.p, self.path, task)
        self.assertEqual(request, task['request'])

    def test_optional_original_prompt_without_selection_stops_and_all_excluded_is_valid(self):
        source, assessment = self.reference_ready()
        del self.p['repair_prompt_references']
        with self.assertRaisesRegex(ValueError, 'batch'):
            repair.prepare(self.p, self.path, 'G01')
        assessment['selections'] = []
        assessment['excluded'] = [dict(source_quote=source['text'], reason='SIMULATED conflict with script')]
        self.p['repair_prompt_references'] = {'G01': assessment}
        self.assertNotIn('【原提示词参考】', repair.prepare(self.p, self.path, 'G01')['prompt'])

    def test_absent_optional_prompt_preserves_v3_generation_text(self):
        self.ready()
        old = repair._compose_prompt(self.p, self.path, 'G01', 3, input_aspect=True)
        new = repair.prepare(self.p, self.path, 'G01')
        self.assertEqual(old['prompt'], new['prompt'])
        self.assertEqual(old['blocks'], new['blocks'])
        self.assertNotIn('source_prompt_reference', new)
        repair.validate_stored_request(self.p, self.path,
            dict(request=old, fingerprint=core.digest(old), repair_source_group='G01'))


if __name__=='__main__':unittest.main()
