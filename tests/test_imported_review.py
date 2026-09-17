"""Imported-video verdicts use simulated observations; media/PTS test is separate."""
import copy
from pathlib import Path
import unittest
from PIL import Image
import test_previs as fixtures
import test_video_evidence as video_fixtures
import previs as core
import storyboard as boards
import planner


class ImportedReviewTests(fixtures.Base):
    png = video_fixtures.VideoEvidenceTests.png
    select_mapping = video_fixtures.VideoEvidenceTests.select_mapping

    def setUp(self):
        fixtures.Base.setUp(self)
        self.p['config'].update(workflow='video_evidence', video_source='imported', video_input_mode='assets')
        self.p['shots'] = self.p['shots'][:3]
        self.p['groups'] = self.p['groups'][:1]
        s = self.p['shots'][1]
        s.update(script='同场景中景观察，女孩仍握钥匙。', shot_size='中景', required_result='持物无关键变化')
        s['requirements'].update(purpose='观察关系，无关键状态变化', must_have=['女孩仍持有钥匙', '两人在同一场景观察对方'])
        s['requirements']['keyframe']['description'] = '中景，两人观察对方，女孩仍握钥匙'
        s['requirements']['provenance'][0]['source'] = 'S02 同场景观察，无持物变化'
        self.p['source_script'] = ' '.join(s['id'] + ' ' + s['script'] for s in self.p['shots'])
        for s in self.p['shots']:
            s.update(duration=2, duration_source=dict(kind='script',ref='SIMULATED 2 seconds'),
                     event=dict(id='E01',summary='持钥匙、观察并交接',source=dict(kind='inference',ref='SIMULATED whole story')))
        self.p['narrative_plan']=dict(source=dict(kind='inference',ref='SIMULATED whole story'),
            boundaries=[dict(before_shot_id=s['id'],merge_allowed=True,strength=2,reason='连续行动') for s in self.p['shots'][1:]],
            safe_spans=[dict(shot_ids=[s['id'] for s in self.p['shots']],reason='同场两人一把钥匙，一次交接')])
        for i, a in enumerate(self.p['assets']):
            a['path'] = str(self.png(a['id'], (i*50, 60, 90)))

    def mapping(self, statuses=None, gid='G01', revision=1):
        g = core.group(self.p, gid)
        video = self.path.parent / f'{gid}-{revision}.mp4'
        video.write_bytes(f'SIMULATED local video {gid} {revision}'.encode())
        self.p.setdefault('imported_videos', []).append(dict(target_id=gid, version=g['version'], source='user_video',
            group_fingerprint=core.group_fingerprint(self.p, self.path, g), outputs=[str(video)], output_hashes=[core.sha(video)], duration=6))
        frames, rows = [], []
        for i, sid in enumerate(g['shot_ids']):
            path = self.png(f'{gid}-{sid}-{revision}', (i*60, revision*30, 60))
            frame = dict(path=str(path), sha256=core.sha(path), time=2*i+.25)
            frames.append(frame)
            status = (statuses or {}).get(sid, 'matched')
            row = dict(shot_id=sid, status=status, observation='SIMULATED '+status,
                candidates=[dict(path=str(path), time=frame['time'])] if status == 'matched' else [])
            if status == 'absent':
                row.update(full_rescan=True, rescan=dict(ranges=[[0,6]], observation='SIMULATED full original video inspected; shot absent'))
            rows.append(row)
        evidence = self.path.parent / f'{gid}-{revision}-evidence.json'
        core.save(evidence, dict(video_sha256=core.sha(video), duration=6, frames=frames, verified=False))
        data = dict(group_id=gid, video_sha256=core.sha(video), evidence_file=str(evidence), shots=rows)
        boards.record_mapping(self.p, self.path, data)
        self.select_mapping(gid)
        return data

    def review_data(self, verdicts=None, middle_derivable=True, gid='G01'):
        ctx = core.video_context(self.p, self.path, gid)
        r = dict(grouping_checked=True, group_id=gid, version=ctx['version'], video_sha256=ctx['video_sha256'], context_fingerprint=ctx['context_fingerprint'],
            checks={c:'PASS' for c in ('shot','continuity','story')},
            coverage=dict(shot_ids=core.group(self.p,gid)['shot_ids'], mapping_verified=True, limitations=[]),
            evidence=[], shot_reviews=[], reference_assessments=[], issues=[], uncertainties=[], asset_comparisons=[],
            boundary_checks=[dict(shot_id=b['shot_id'],verdict='PASS',observation='SIMULATED boundary inspected') for b in ctx['boundaries']])
        for row, frame in zip(ctx['mapping']['shots'],ctx['extraction']['frames']):
            sid = row['shot_id']
            verdict = (verdicts or {}).get(sid, 'PASS' if row['status']=='matched' else row['status'])
            times = [frame['time']] if verdict in ('PASS','FAIL') else []
            if times:
                r['evidence'].append(dict(frame, shot_id=sid, observation='SIMULATED frame content and continuous neighborhood',
                    visible_facts=['SIMULATED lapel, crew neck and face structure visible'], interpretation='SIMULATED structure matches'))
            checks = {c:'PASS' for c in boards.CHECKS}
            if verdict == 'FAIL':
                checks['props'] = 'FAIL'
            r['shot_reviews'].append(dict(shot_id=sid,verdict=verdict,checks=checks,evidence_times=times,reason='SIMULATED '+verdict, identity_reason='SIMULATED character/action relationship judged against story'))
            scope = []
            if verdict != 'absent':
                aids = next(s['asset_ids'] for s in self.p['shots'] if s['id']==sid)
                for asset in ctx['assets']:
                    if asset['id'] not in aids or asset['kind'] != 'character':
                        continue
                    for aspect in ('wardrobe','appearance'):
                        scope.append(dict(asset_id=asset['id'],aspect=aspect,required=True,reason='SIMULATED relevant structure'))
                        r['asset_comparisons'].append(dict(id=sid+'-'+asset['id']+'-'+aspect,shot_id=sid,asset_id=asset['id'],
                            asset_sha256=asset['sha256'],aspect=aspect,story_requirement='SIMULATED explicit identity clue', story_impact='SIMULATED required actor identity unclear' if not times else '',evidence_refs=[copy.deepcopy(frame)] if times else [],
                            condition_factors=['SIMULATED rain'],stable_matches=['SIMULATED stable structure'] if times else [],
                            stable_conflicts=[],decision='PASS' if times else 'uncertain',
                            unobservable_features=[] if times else ['SIMULATED necessary structure invisible'],
                            followup='' if times else 'Inspect a clear same-shot frame',basis_shot_ids=[]))
                r['shot_reviews'][-1]['identity_scope']=scope
            derivable = middle_derivable if sid=='S02' and verdict in ('PASS','absent') else (None if verdict=='uncertain' else False)
            decision = 'ai_fill' if derivable is True else ('anchor' if verdict=='PASS' else 'pending')
            r['reference_assessments'].append(dict(shot_id=sid,decision=decision,derivable=derivable,
                basis_shot_ids=['S01','S03'] if decision=='ai_fill' else [], evidence_times=times,
                reason='资产身份与 S01/S03 持物状态可承接，无关键新信息' if derivable else '保留必要状态或先补证据'))
            if verdict in ('FAIL','absent'):
                r['checks']['story'] = 'FAIL'
                r['issues'].append(dict(id='issue-'+sid,shot_ids=[sid],time_range=[0,6],severity='medium',
                    asset_ids=[],asset_comparison_ids=[],
                    problem='必要画面未出现' if verdict=='absent' else '交接前钥匙持有者错误，破坏交接因果', expected='脚本要求',
                    actual='SIMULATED discrepancy',evidence=['SIMULATED full rescan' if verdict=='absent' else frame['path']],
                    repair_target='video_shot',fix='先评估推导，必要时补生成' if verdict=='absent' else '重新生成该镜，修正钥匙持有者'))
            if verdict=='uncertain':
                checks['identity']='uncertain'
                r['shot_reviews'][-1]['followup']='Inspect more same-shot continuous frames'
                r['checks']['shot']='uncertain'
                r['uncertainties'].append(sid+' 需要更多连续帧')
        return r

    def finish(self, review=None):
        core.record_review(self.p,self.path,review or self.review_data())
        result = planner.post_review_plan(self.p,self.path,{})
        planner.store_aggregation(self.p,self.path,result)
        return result

    def test_three_shots_planned_duration_two_tables_and_local_thumbnails(self):
        core.validate(self.p,self.path)
        self.mapping()
        before = copy.deepcopy(self.p)
        result = self.finish()
        self.assertEqual([d['mode'] for d in result['decisions']],['anchor','ai_fill','anchor'])
        self.assertEqual(result['groups'][0]['planned_duration'],6)
        for field in ('groups','tasks','shots','board_mappings'):
            self.assertEqual(self.p[field],before[field])
        out = self.path.parent/'delivery'
        text = Path(boards.render(self.p,self.path,out)).read_text(encoding='utf8')
        self.assertEqual(sum(line.startswith('| --- |') for line in text.splitlines()),2)
        self.assertIn('| 总时长 |',text)
        self.assertIn('| 镜头时长 |',text)
        self.assertNotIn('视频结论',text)
        self.assertIn('| 检验通过 | 建议省图，未验证 | S01 + S03 |',text)
        self.assertEqual(len(list(out.rglob('*.png'))),4)
        row=next(l for l in text.splitlines() if '| S02 |' in l)
        self.assertIn('| 可推导生成 |',row)
        self.assertNotIn('![',row)
        self.assertFalse(list(out.glob('images/*S02*')))
        for sid in ('S01','S03'):
            thumb = next(out.glob('images/thumb-'+sid+'-*.png'))
            self.assertIn(thumb.name,text)
            with Image.open(thumb) as im:
                self.assertEqual(im.size,(240,168))
                self.assertGreater(len(im.crop((0,135,240,168)).getcolors(240*33)),1)  # caption is drawn below picture

    def test_absent_but_derivable_keeps_absence_and_others_pass(self):
        self.mapping({'S02':'absent'})
        result = self.finish()
        self.assertEqual([d['status'] for d in result['decisions']],['anchor_reviewed','absent_fill_suggested_unverified','anchor_reviewed'])
        self.assertIsNone(result['decisions'][1]['frame'])
        self.assertEqual(result['missing_summary'][0]['bad_num'],0)
        text=Path(boards.render(self.p,self.path,self.path.parent/'delivery')).read_text(encoding='utf8')
        row=next(l for l in text.splitlines() if '| S02 |' in l)
        self.assertIn('| 视频漏镜 | 建议省图，未验证 | S01 + S03 |',row)
        self.assertIn('未验证',row)
        self.assertIn('| 可推导生成 |',row)
        self.assertNotIn('![',row)
        self.assertFalse(list((self.path.parent/'delivery/images').glob('*S02*')))
        self.assertEqual(core.review_current(self.p,self.path,'G01')['checks']['story'],'FAIL')
        self.assertNotIn('建议重新生成视频',text)

    def test_final_anchor_overrides_fill_candidate_and_keeps_picture(self):
        self.p['shots'][1]['reference']['locked']=True
        self.mapping()
        result=self.finish()
        self.assertEqual(self.p['reviews'][-1]['reference_assessments'][1]['decision'],'ai_fill')
        self.assertEqual(result['decisions'][1]['mode'],'anchor')
        out=self.path.parent/'delivery'
        document=Path(boards.render(self.p,self.path,out)).read_text(encoding='utf8')
        row=next(l for l in document.splitlines() if '| S02 |' in l)
        self.assertIn('![',row)
        self.assertNotIn('| 可推导生成 |',row)
        self.assertTrue(list(out.glob('images/thumb-S02-*')))

    def test_plot_error_is_local_failure_not_missing(self):
        self.mapping()
        result=self.finish(self.review_data({'S02':'FAIL'}))
        self.assertEqual([d['status'] for d in result['decisions']],['anchor_reviewed','mismatch','anchor_reviewed'])
        self.assertEqual(result['missing_summary'][0]['bad_num'],0)
        text=Path(boards.render(self.p,self.path,self.path.parent/'delivery')).read_text(encoding='utf8')
        self.assertIn('| 该镜需重新生成 |',text)
        self.assertIn('钥匙持有者',text)

    def test_required_absence_and_unknown_inferability_are_distinct(self):
        self.mapping({'S02':'absent','S03':'absent'})
        result=self.finish(self.review_data(middle_derivable=None))
        self.assertEqual([d['status'] for d in result['decisions']],['anchor_reviewed','pending','missing_required'])
        self.assertEqual(result['missing_summary'][0]['bad_num'],1)

    def test_unknown_mapping_cannot_be_declared_fill(self):
        self.mapping({'S02':'uncertain'})
        r=self.review_data()
        self.finish(r)
        self.assertEqual(self.p['aggregation']['decisions'][1]['status'],'pending')
        r['reference_assessments'][1].update(decision='ai_fill',derivable=True,basis_shot_ids=['S01','S03'])
        with self.assertRaisesRegex(ValueError,'passed or confirmed absent'):
            core.record_review(self.p,self.path,r)

    def test_absence_requires_full_measured_rescan(self):
        data=self.mapping({'S02':'uncertain'})
        data['shots'][1].update(status='absent',full_rescan=True,rescan=dict(ranges=[[0,2],[3,6]],observation='gap'))
        with self.assertRaisesRegex(ValueError,'rescan|full source video coverage'):
            boards.record_mapping(self.p,self.path,data)
        data['shots'][1]['rescan']['ranges']=[[0,3]]
        with self.assertRaisesRegex(ValueError,'rescan|full source video coverage'):
            boards.record_mapping(self.p,self.path,data)
        ev=core.read(data['evidence_file'])
        ev['duration']=3
        core.save(data['evidence_file'],ev)
        with self.assertRaisesRegex(ValueError,'measured source'):
            boards.record_mapping(self.p,self.path,data)

    def test_absence_cannot_claim_frame_or_missing_basis(self):
        self.mapping({'S02':'absent'})
        r=self.review_data()
        f=core.video_context(self.p,self.path,'G01')['extraction']['frames'][1]
        r['evidence'].append(dict(f,shot_id='S02',observation='fake matching content'))
        with self.assertRaisesRegex(ValueError,'cannot claim'):
            core.record_review(self.p,self.path,r)
        self.mapping({'S02':'absent','S03':'absent'})
        with self.assertRaisesRegex(ValueError,'existing passed'):
            core.record_review(self.p,self.path,self.review_data())

    def test_basis_must_be_ordered_and_retained(self):
        self.mapping()
        r=self.review_data()
        r['reference_assessments'][1]['basis_shot_ids']=['S03','S01']
        with self.assertRaisesRegex(ValueError,'ordered before/after'):
            core.record_review(self.p,self.path,r)
        r=self.review_data()
        r['reference_assessments'][2]['decision']='pending'
        with self.assertRaisesRegex(ValueError,'retained anchors'):
            core.record_review(self.p,self.path,r)

    def test_key_result_cannot_be_omitted_even_if_semantic_assessment_says_yes(self):
        self.p['shots'][1]['intent']['critical_result']=True
        self.mapping({'S02':'absent'})
        result=self.finish()
        self.assertEqual(result['decisions'][1]['status'],'missing_required')
        self.assertEqual(result['missing_summary'][0]['bad_num'],1)

    def test_pass_decision_table_rejects_hidden_or_inconsistent_inference(self):
        self.mapping()
        for derivable, decision in ((True, 'anchor'), (None, 'pending'), (False, 'pending')):
            with self.subTest(derivable=derivable, decision=decision):
                r=self.review_data(middle_derivable=derivable)
                r['reference_assessments'][1].update(decision=decision,basis_shot_ids=[])
                with self.assertRaisesRegex(ValueError,'passed shot decision'):
                    core.record_review(self.p,self.path,r)
        for derivable in (False, None):
            result=self.finish(self.review_data(middle_derivable=derivable))
            self.assertEqual(result['decisions'][1]['status'],'anchor_reviewed')

    def test_new_group_endpoint_overrides_fill_candidate_without_changing_verdict(self):
        for status in ('matched', 'absent'):
            with self.subTest(status=status):
                for s, duration in zip(self.p['shots'], (8,6,8)):
                    s['duration']=duration
                self.mapping({'S02':status},revision=2 if status=='absent' else 1)
                result=self.finish()
                self.assertEqual(len(result['groups']),2)
                self.assertEqual(result['decisions'][1]['status'],
                                 'anchor_reviewed' if status=='matched' else 'missing_required')
                self.assertEqual(result['missing_summary'][0]['bad_num'],0 if status=='matched' else 1)
                review=core.review_current(self.p,self.path,'G01')
                self.assertEqual(review['reference_assessments'][1]['decision'],'ai_fill')
                self.assertEqual(review['shot_reviews'][1]['verdict'],'PASS' if status=='matched' else 'absent')

    def test_unchanged_state_does_not_allow_omitting_narrative_turn(self):
        s=self.p['shots'][1]
        s['state_changes']=[]
        s['intent']['narrative_turn']=True
        self.mapping()
        result=self.finish()
        self.assertEqual(result['decisions'][1]['status'],'anchor_reviewed')
        self.assertIn('CRITICAL_RESULT',result['analysis'][1]['mandatory_rules'])

    def test_previous_reference_policy_cannot_reuse_review_or_aggregation(self):
        self.mapping();self.finish()
        old_ctx=core.video_context(self.p,self.path,'G01')
        old_ctx.pop('reference_policy_version')
        old_ctx.pop('previous_review');old_ctx.pop('context_fingerprint')
        old_review=copy.deepcopy(self.p['reviews'][-1])
        old_review['context_fingerprint']=core.digest(old_ctx)
        self.p['reviews'][-1]=old_review
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        self.assertIsNone(planner.current_aggregation(self.p,self.path))
        with self.assertRaisesRegex(ValueError,'context changed'):
            core.record_review(self.p,self.path,old_review)

    def test_rescan_replaces_wrong_selection_and_requires_fresh_group_review(self):
        self.mapping({'S02':'uncertain'})
        self.finish()
        self.mapping(revision=2)
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        self.assertIsNone(planner.current_aggregation(self.p,self.path))
        result=self.finish()
        self.assertEqual(result['decisions'][1]['status'],'ai_fill_suggested_unverified')
        basis=boards.current_frame(self.p,self.path,'S01')
        core.resolve(self.path,basis['path']).write_bytes(b'changed basis picture')
        self.assertIsNone(planner.current_aggregation(self.p,self.path))

    def test_same_video_reselected_frame_invalidates_then_recovers(self):
        self.mapping()
        self.finish(self.review_data({'S02':'FAIL'}))
        mapping=copy.deepcopy(boards.current_mapping(self.p,self.path,'G01'))
        ev=core.read(mapping['evidence_file'])
        replacement=self.png('corrected-S02',(40,110,70))
        f=dict(path=str(replacement),sha256=core.sha(replacement),time=2.75)
        ev['frames'].append(f)
        evfile=self.path.parent/'rescanned.json'
        core.save(evfile,ev)
        mapping['evidence_file']=str(evfile)
        mapping['shots'][1].update(observation='SIMULATED found correct frame in original video', candidates=[dict(path=str(replacement),time=2.75)])
        boards.record_mapping(self.p,self.path,mapping)
        self.select_mapping('G01')
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        r=self.review_data()
        r['evidence'][1]=dict(f,shot_id='S02',observation='SIMULATED corrected frame and neighbors inspected',
            visible_facts=['SIMULATED corrected visible structure'],interpretation='SIMULATED structure matches')
        for c in r['asset_comparisons']:
            if c['shot_id']=='S02': c['evidence_refs']=[copy.deepcopy(f)]
        r['shot_reviews'][1]['evidence_times']=[2.75]
        r['reference_assessments'][1]['evidence_times']=[2.75]
        result=self.finish(r)
        self.assertEqual(result['decisions'][1]['review_verdict'],'PASS')

    def test_grouping_ignores_duration_profile_and_source_order_is_fixed(self):
        self.mapping()
        self.finish()
        a=planner.post_review_plan(self.p,self.path,{})
        b=planner.post_review_plan(self.p,self.path,dict(min_duration=999,max_duration=999,allowed_durations=[999],max_images=1))
        self.assertEqual(a['groups'],b['groups'])
        self.assertEqual([sid for g in b['groups'] for sid in g['shot_ids']],['S01','S02','S03'])

    def test_replacement_invalidates_neighbor_boundary_review(self):
        self.p['groups']=[dict(id='G01',version=1,shot_ids=['S01']),dict(id='G02',version=1,shot_ids=['S02']),dict(id='G03',version=1,shot_ids=['S03'])]
        for gid in ('G01','G02','G03'):
            self.mapping(gid=gid)
        for gid in ('G01','G02','G03'):
            core.record_review(self.p,self.path,self.review_data(gid=gid,middle_derivable=False))
        self.mapping(gid='G02',revision=2)
        for gid in ('G01','G02','G03'):
            self.assertIsNone(core.review_current(self.p,self.path,gid))
            r=self.review_data(gid=gid,middle_derivable=False)
            self.assertEqual(core.record_review(self.p,self.path,r),'PASS')

    def test_threshold_note_below_exactly_two_tables(self):
        self.mapping({'S01':'absent','S03':'absent'})
        result=self.finish(self.review_data(middle_derivable=False))
        self.assertTrue(result['missing_summary'][0]['regenerate'])
        text=Path(boards.render(self.p,self.path,self.path.parent/'delivery')).read_text(encoding='utf8')
        self.assertEqual(sum(line.startswith('| --- |') for line in text.splitlines()),2)
        self.assertEqual(text.count('建议重新生成视频'),1)
        self.assertGreater(text.index('建议重新生成视频'),text.rfind('| S03 |'))
        self.assertNotIn('bad_num',text)

    def test_reselecting_existing_candidate_invalidates_adjacent_reviews(self):
        self.p['groups']=[dict(id='G01',version=1,shot_ids=['S01']),dict(id='G02',version=1,shot_ids=['S02']),dict(id='G03',version=1,shot_ids=['S03'])]
        for gid in ('G01','G02','G03'):
            self.mapping(gid=gid)
        mapping=copy.deepcopy(boards.current_mapping(self.p,self.path,'G02'))
        ev=core.read(mapping['evidence_file'])
        path=self.png('alternate-S02',(20,130,40))
        f=dict(path=str(path),sha256=core.sha(path),time=.75)
        ev['frames'].append(f)
        core.save(mapping['evidence_file'],ev)
        mapping['shots'][0]['candidates'].append(dict(path=str(path),time=.75))
        boards.record_mapping(self.p,self.path,mapping)
        self.select_mapping('G02')
        for gid in ('G01','G02','G03'):
            core.record_review(self.p,self.path,self.review_data(gid=gid,middle_derivable=False))
            self.assertIsNotNone(core.review_current(self.p,self.path,gid))
        boards.select_image(self.p,self.path,dict(shot_id='S02',path=str(path),source=dict(kind='frame',time=.75),reason='SIMULATED new boundary picture'))
        for gid in ('G01','G02','G03'):
            self.assertIsNone(core.review_current(self.p,self.path,gid))

    def test_grouping_requires_passed_source_boundaries(self):
        self.p['groups']=[dict(id='G01',version=1,shot_ids=['S01']),dict(id='G02',version=1,shot_ids=['S02']),dict(id='G03',version=1,shot_ids=['S03'])]
        for gid in ('G01','G02','G03'):
            self.mapping(gid=gid)
        for gid in ('G01','G02','G03'):
            core.record_review(self.p,self.path,self.review_data(gid=gid,middle_derivable=False))
        self.assertEqual(len(planner.post_review_plan(self.p,self.path,{})['groups']),1)
        r=self.review_data({'S02':'uncertain'},gid='G02',middle_derivable=False)
        r['checks']['continuity']='uncertain'
        for boundary in r['boundary_checks']:
            boundary['verdict']='uncertain'
        core.record_review(self.p,self.path,r)
        result=planner.post_review_plan(self.p,self.path,{})
        self.assertEqual([g['shot_ids'] for g in result['groups']],[['S01'],['S02'],['S03']])


class MissingThresholdTests(unittest.TestCase):
    def test_thresholds_per_video_and_only_required_absence(self):
        for total, missing, expected in ((10,2,True),(11,2,False),(3,1,False)):
            with self.subTest(total=total,missing=missing):
                ids=[f'S{i}' for i in range(total)]
                groups=[dict(id='G01',shot_ids=ids),dict(id='G02',shot_ids=['T1'])]
                decisions=[dict(shot_id=s,status='missing_required' if i<missing else 'mismatch') for i,s in enumerate(ids)]
                decisions += [dict(shot_id='T1',status='absent_fill_suggested_unverified'),copy.deepcopy(decisions[0])]
                rows=planner.missing_summary(groups,decisions,{})
                self.assertEqual(rows[0]['regenerate'],expected)
                self.assertEqual(rows[0]['bad_num'],missing)
                self.assertEqual(rows[1]['bad_num'],0)


if __name__=='__main__':
    unittest.main()
