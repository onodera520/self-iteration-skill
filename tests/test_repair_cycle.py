"""Simulated judgments/transport, not real visual or paid-workflow acceptance."""
import copy
from pathlib import Path
from unittest.mock import patch
import unittest

import test_previs as fixtures
import test_imported_review as imported_fixtures
import previs as core
import planner
import repair_cycle as repair


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
        self.mapping(statuses)
        review = self.assessment(self.review_data(verdicts or {'S02':'FAIL'}, middle_derivable=derivable), critical)
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
        for total, ids, critical, expected in [(10,['a','b'],[],True),(11,['a','b'],[],False),
                (3,['a'],[],False),(100,['a'],['a'],True),(10,['a','a'],[],False)]:
            with self.subTest(total=total,ids=ids,critical=critical):
                self.assertEqual(repair.threshold(total,ids,critical)['triggered'],expected)

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
            self.assertIn(f"镜头{i},【时长】1.0s。【镜头设计】{b['design']}。【镜头内容】{b['text']}",request['prompt'])
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
        self.assertGreater(request['prompt'].index(repair.PREVIS_DIRECTIVE),request['prompt'].index('镜头3,【时长】'))
        self.assertTrue(request['prompt'].endswith(self.p['repair_asset_style']['assets'][-1]['guidance']))
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
        for gid in ('G01','G02'): self.mapping(gid=gid)
        for gid,sid in [('G01','S01'),('G02','S04')]:
            core.record_review(self.p,self.path,self.assessment(self.review_data({sid:'FAIL'},middle_derivable=False,gid=gid),True))
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


if __name__=='__main__':unittest.main()
