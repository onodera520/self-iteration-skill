"""Event grouping regression; all image/video judgments below are simulated."""
import copy
from pathlib import Path
import test_previs as fixtures
import test_imported_review as imported
import previs as core
import planner
import storyboard as boards
from requirements import contexts


class EventGroupingTests(fixtures.Base):
    png = imported.ImportedReviewTests.png
    select_mapping = imported.ImportedReviewTests.select_mapping
    review_data = imported.ImportedReviewTests.review_data
    finish = imported.ImportedReviewTests.finish

    def setUp(self):
        super().setUp()
        self.p['config'].update(workflow='video_evidence', video_source='imported', video_input_mode='assets')
        self.p['shots'] = self.p['shots'][:3]
        self.p['groups'] = self.p['groups'][:1]
        s = self.p['shots'][1]
        s.update(script='同场景中景观察，女孩仍握钥匙。', shot_size='中景', required_result='持物无关键变化')
        s['requirements'].update(purpose='观察关系，无关键状态变化', must_have=['女孩仍持有钥匙', '同场景中景'])
        s['requirements']['keyframe']['description'] = '中景，两人观察对方，女孩仍握钥匙'
        s['requirements']['provenance'][0]['source'] = 'S02 同场景观察，无持物变化'
        self.p['source_script'] = ' '.join(s['id'] + ' ' + s['script'] for s in self.p['shots'])
        for s in self.p['shots']:
            s.pop('duration')
        for i, a in enumerate(self.p['assets']):
            a['path'] = str(self.png(a['id'], (i*50, 60, 90)))
        self.events(['E01'] * 3)

    def events(self, ids, summaries=None):
        for s, eid in zip(self.p['shots'], ids):
            s['event'] = dict(id=eid, summary=(summaries or {}).get(eid, '连续行动 ' + eid),
                              source=dict(kind='inference', ref='测试脚本事件分析 ' + s['id']))

    def mapping(self, gid='G01'):
        g = core.group(self.p, gid)
        duration = 2 * len(g['shot_ids'])
        video = self.path.parent / (gid + '.mp4')
        video.write_bytes(b'SIMULATED VIDEO - not visual evidence')
        self.p.setdefault('imported_videos', []).append(dict(target_id=gid, version=g['version'], source='user_video',
            group_fingerprint=core.group_fingerprint(self.p,self.path,g), outputs=[str(video)],
            output_hashes=[core.sha(video)], duration=duration))
        frames, rows = [], []
        for i, sid in enumerate(g['shot_ids']):
            image = self.png(gid+sid, ((i*30)%256, 50, 70))
            frames.append(dict(path=str(image), sha256=core.sha(image), time=2*i+.25))
            rows.append(dict(shot_id=sid, status='matched', observation='SIMULATED candidate',
                             candidates=[dict(path=str(image),time=2*i+.25)]))
        evidence = self.path.parent / (gid+'-evidence.json')
        core.save(evidence, dict(video_sha256=core.sha(video),duration=duration,frames=frames,verified=False))
        boards.record_mapping(self.p,self.path,dict(group_id=gid,video_sha256=core.sha(video),evidence_file=str(evidence),shots=rows))
        self.select_mapping(gid)

    def run_plan(self, verdicts=None):
        self.mapping()
        return self.finish(self.review_data(verdicts,middle_derivable=False))

    def partitions(self, result):
        return [g['shot_ids'] for g in result['groups']]

    def test_same_scene_different_events_and_nonadjacent_repeated_ids(self):
        self.events(['E01','E02','E01'])
        result = self.run_plan()
        self.assertEqual(self.partitions(result),[['S01'],['S02'],['S03']])

    def test_cross_scene_same_event_preserves_scene_anchors_and_state_inheritance(self):
        self.p['shots'][1]['scene_id']='doorway'
        before = contexts(self.p)
        self.mapping()
        result = self.finish(self.review_data())  # S02 suggested fill but protected by scene change.
        self.assertEqual(self.partitions(result),[['S01','S02','S03']])
        self.assertEqual([d['mode'] for d in result['decisions']],['anchor']*3)
        self.assertEqual(before, contexts(self.p))

    def test_shot_size_and_required_cuts_do_not_split_event(self):
        for s, size in zip(self.p['shots'],['中景','特写','近景']):
            s['shot_size']=size
            s['intent']['required_cut']=True
        self.assertEqual(self.partitions(self.run_plan()),[['S01','S02','S03']])

    def test_time_jump_starts_new_event_even_in_same_scene(self):
        self.events(['E01','E01','E02'])
        self.p['shots'][2]['script']='翌日同一地点，男孩已拿稳钥匙。'
        self.assertEqual(self.partitions(self.run_plan()),[['S01','S02'],['S03']])

    def test_legacy_without_events_keeps_scene_boundary(self):
        for s in self.p['shots']: s.pop('event')
        self.p['shots'][2]['scene_id']='outside'
        self.assertEqual(self.partitions(self.run_plan()),[['S01','S02'],['S03']])

    def test_event_schema_rejects_partial_or_untraceable_annotations(self):
        original=copy.deepcopy(self.p)
        mutations=[lambda p:p['shots'][0].pop('event'),
                   lambda p:p['shots'][0]['event'].pop('source'),
                   lambda p:p['shots'][0]['event'].update(summary='different summary')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                self.p=copy.deepcopy(original)
                mutate(self.p)
                with self.assertRaises(ValueError): core.validate(self.p,self.path)

    def test_event_change_invalidates_video_review_and_aggregation(self):
        self.run_plan()
        ctx=core.video_context(self.p,self.path,'G01')
        self.assertEqual(ctx['shots'][0]['event'],self.p['shots'][0]['event'])
        before=core.group_fingerprint(self.p,self.path,self.p['groups'][0])
        self.p['shots'][1]['event']['source']['ref']='corrected script interpretation'
        self.assertNotEqual(before,core.group_fingerprint(self.p,self.path,self.p['groups'][0]))
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        self.assertIsNone(planner.current_aggregation(self.p,self.path))
        self.assertEqual(core.current_video(self.p,self.path,self.p['groups'][0]),(None,None))

    def test_source_boundary_needs_valid_reviews_even_for_same_event(self):
        self.p['groups']=[dict(id='G01',version=1,shot_ids=['S01']),dict(id='G02',version=1,shot_ids=['S02','S03'])]
        for gid in ('G01','G02'): self.mapping(gid)
        for gid in ('G01','G02'):
            ctx=core.video_context(self.p,self.path,gid)
            self.assertIn('event',ctx['boundaries'][0])
            core.record_review(self.p,self.path,self.review_data(gid=gid,middle_derivable=False))
        self.assertEqual(self.partitions(planner.post_review_plan(self.p,self.path,{})),[['S01','S02','S03']])
        self.p['reviews']=[r for r in self.p['reviews'] if r['group_id']!='G02']
        self.assertEqual(self.partitions(planner.post_review_plan(self.p,self.path,{})),[['S01'],['S02','S03']])

    def test_eight_shot_rain_chase_case_groups_events_without_approving_errors(self):
        self.p=core.read(Path(__file__).parent/'fixtures/rain-chase-script.json')
        for i,a in enumerate(self.p['assets']): a['path']=str(self.png(a['id'],(i*30,50,70)))
        summaries={'E01':'林默雨中离开，接身体细节，建立淋雨状态',
                   'E02':'苏晴从看伞、望人到作出决定，完成犹豫过程',
                   'E03':'推门、到门外开伞并追出，构成连续行动'}
        self.events(['E01']*2+['E02']*4+['E03']*2,summaries)
        self.mapping()
        r=self.review_data({'S03':'FAIL','S08':'FAIL'},middle_derivable=False)
        for issue in r['issues']:
            issue.update(time_range=[0,16],problem='SIMULATED 提前开伞或末镜动作不符',fix='按脚本修正伞状态与末镜动作')
        result=self.finish(r)
        self.assertEqual(self.partitions(result),[['S01','S02'],['S03','S04','S05','S06'],['S07','S08']])
        self.assertEqual([g['reason'] for g in result['groups']],list(summaries.values()))
        verdicts={d['shot_id']:d['status'] for d in result['decisions']}
        self.assertEqual(verdicts['S03'],'mismatch')
        self.assertEqual(verdicts['S08'],'mismatch')
        self.assertEqual(verdicts['S04'],'anchor_reviewed')
        self.assertEqual(verdicts['S07'],'anchor_reviewed')
        text=Path(boards.render(self.p,self.path,self.path.parent/'delivery')).read_text(encoding='utf-8')
        self.assertEqual(sum(line.startswith('| --- |') for line in text.splitlines()),2)
        self.assertIn(summaries['E03'],text)

    def test_long_event_is_split_only_inside_event_and_explained(self):
        template=copy.deepcopy(self.p['shots'][1])
        self.p['shots']=[]
        for i in range(13):
            s=copy.deepcopy(template)
            s['id']=f'S{i+1:02d}'
            s['requirements']['inherits_from']=None
            self.p['shots'].append(s)
        self.p['groups'][0]['shot_ids']=[s['id'] for s in self.p['shots']]
        result=self.run_plan()
        self.assertEqual(len(result['groups']),2)
        self.assertEqual([sid for g in result['groups'] for sid in g['shot_ids']],self.p['groups'][0]['shot_ids'])
        self.assertTrue(all(len(g['shot_ids'])<=12 and '12镜' in g['reason'] for g in result['groups']))
