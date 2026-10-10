"""Narrative decisions are supplied fixtures, not a claim of visual validation."""
import copy
import json
from decimal import Decimal
import unittest
from unittest.mock import patch
from pathlib import Path
import test_previs  # installs script import path
import test_imported_review as imported
import grouping
import previs as core
import planner
import storyboard as boards
import review_draft


def project(durations, events=None, strengths=None):
    shots = [dict(id=f'S{i+1:02d}', duration=d, duration_source=dict(kind='script', ref='fixture script'),
                  continuity_id='continuous', event=dict(id=(events or ['E01']*len(durations))[i], summary='剧情段 '+str(i)))
             for i, d in enumerate(durations)]
    return dict(shots=shots, narrative_plan=dict(source=dict(kind='inference', ref='fixture full plot'),
        boundaries=[dict(before_shot_id=s['id'], merge_allowed=True, strength=(strengths or [2]*(len(shots)-1))[i], reason='自然承接')
                    for i, s in enumerate(shots[1:])],
        safe_spans=[dict(shot_ids=[s['id'] for s in shots], reason='完整区间的主体关系稳定，复杂度可接受')]))


class NarrativeRulesTests(unittest.TestCase):
    def test_initial_events_merge_and_short_group_is_explicitly_reviewed(self):
        p=project([2,2,2], ['E1','E2','E3'])
        result=grouping.partition(p)
        self.assertEqual(result['ranges'],[(0,3)])
        self.assertEqual(sum(t['stage']=='adjacent_merge' for t in result['trace']),2)
        self.assertEqual(result['trace'][-1]['stage'],'short_review')

    def test_reaction_short_os_and_shot_form_are_not_hard_boundaries(self):
        p=project([4,3,2],['action','reaction','os'])
        for s,size in zip(p['shots'],['全景','特写','近景']):
            s.update(shot_size=size, scene_id=size, script='短 OS / VO，角色即时反应')
        self.assertEqual(grouping.partition(p)['ranges'],[(0,3)])

    def test_independent_event_or_explicit_time_jump_keeps_short_group(self):
        for reason in ('独立新事件，目标改变','翌日，明确时间跳跃'):
            p=project([4,4])
            p['narrative_plan']['boundaries'][0].update(merge_allowed=False,reason=reason)
            result=grouping.partition(p)
            self.assertEqual(result['ranges'],[(0,1),(1,2)])
            self.assertTrue(all(reason in r for r in result['reasons']))

    def test_exact_fifteen_and_decimal_sum(self):
        for durations in ([7.1,7.9],[.1,.2,14.7]):
            p=project(durations)
            self.assertEqual(grouping.partition(p)['ranges'],[(0,len(durations))])
        p=project([7.1,7.90000001])
        self.assertEqual(grouping.partition(p)['ranges'],[(0,1),(1,2)])

    def test_whole_interval_complexity_cannot_be_inferred_from_pairs(self):
        p=project([4,4,4],['E1','E2','E3'])
        p['narrative_plan']['safe_spans']=[dict(shot_ids=ids,reason='only this interval checked')
                                         for ids in (['S01','S02'],['S02','S03'])]
        result=grouping.partition(p)
        self.assertEqual(result['ranges'],[(0,2),(2,3)])
        self.assertIn('整段生成复杂度',result['reasons'][-1])

    def test_short_group_prefers_stronger_side_then_left_on_tie(self):
        for strengths,expected in (([1,3],[(0,1),(1,3)]),([2,2],[(0,2),(2,3)])):
            p=project([7,2,7],['E1','E2','E3'],strengths)
            self.assertEqual(grouping.partition(p)['ranges'],expected)

    def test_twelve_shots_cap_and_order(self):
        p=project([1]*13)
        result=grouping.partition(p)
        self.assertEqual(result['ranges'],[(0,9),(9,13)])
        self.assertIn('minimum_repartition',[t['stage'] for t in result['trace']])
        self.assertIn('12镜',result['reasons'][-1])

    def test_source_evidence_and_continuity_boundaries_remain_hard(self):
        p=project([4,4,4])
        self.assertEqual(grouping.partition(p,[1])['ranges'],[(0,1),(1,3)])
        p['shots'][1]['continuity_id']='next_day'
        self.assertEqual(grouping.partition(p)['ranges'],[(0,1),(1,2),(2,3)])

    def test_overlong_shot_and_missing_metadata_do_not_yield_compliant_groups(self):
        p=project([15.001,2])
        original=copy.deepcopy(p)
        result=grouping.partition(p)
        self.assertFalse(result['feasible'])
        self.assertIn('需拆分或调整计划时长',result['limitations'][0])
        self.assertEqual(p,original)
        for field in ('duration','duration_source','event'):
            p=project([2,2]);p['shots'][0].pop(field)
            if field=='duration': p['shots'][0].pop('duration_source')
            self.assertFalse(grouping.partition(p)['feasible'])

    def test_no_invented_duration_and_no_nonadjacent_span(self):
        p=project([2,2,2]);p.pop('narrative_plan')
        self.assertFalse(grouping.partition(p)['feasible'])
        p=project([2,2,2]);p['narrative_plan']['safe_spans'][0]['shot_ids']=['S01','S03']
        with self.assertRaisesRegex(ValueError,'contiguous'): grouping.partition(p)

    def test_exact_four_and_infeasible_short_independent_event(self):
        self.assertEqual(grouping.partition(project([1.1,2.9]))['ranges'],[(0,2)])
        for durations,blocked in (([3.99999999],()),([3,4],(1,))):
            p=project(durations)
            original=copy.deepcopy(p)
            result=grouping.partition(p,blocked)
            self.assertFalse(result['feasible'])
            self.assertEqual(result['ranges'],[])
            self.assertIn('4–15秒',result['limitations'][0])
            self.assertEqual(p,original)
        p=project([3,4])
        p['narrative_plan']['boundaries'][0].update(merge_allowed=False,reason='独立事件')
        self.assertFalse(grouping.partition(p)['feasible'])
        p=project([3,4,4])
        p['narrative_plan']['safe_spans']=[]
        self.assertFalse(grouping.partition(p)['feasible'])

    def test_explicit_beat_cannot_be_crossed_or_joined_nonadjacently(self):
        p=project([4,4,4])
        for s,bid in zip(p['shots'],['B1','B2','B1']):
            s['beat']=dict(id=bid,source=dict(kind='script',ref='原文 Beat'))
        self.assertEqual(grouping.partition(p)['ranges'],[(0,1),(1,2),(2,3)])
        p['shots'][0]['duration']=3
        self.assertFalse(grouping.partition(p)['feasible'])

    def test_beat_metadata_must_be_complete_and_sourced(self):
        p=project([4,4])
        p['shots'][0]['beat']=dict(id='B1',source=dict(kind='script',ref='原文 Beat'))
        with self.assertRaisesRegex(ValueError,'beat'): grouping.partition(p)
        p['shots'][1]['beat']=dict(id='B2',source=dict(kind='script',ref='原文 Beat'))
        for change in (lambda b:b.update(id='invalid id'),lambda b:b.pop('source'),
                       lambda b:b['source'].update(kind='asset')):
            invalid=copy.deepcopy(p)
            change(invalid['shots'][1]['beat'])
            with self.assertRaisesRegex(ValueError,'beat'): grouping.partition(invalid)

    def test_final_audit_rejects_missing_repeated_reordered_and_invalid_groups(self):
        p=project([4,4,4])
        for ranges in ([(0,2)],[(0,2),(1,3)],[(1,3),(0,1)],[],[(0,4)]):
            with self.assertRaisesRegex(ValueError,'every Clip'): grouping.validate_partition(p,ranges)
        duplicate=copy.deepcopy(p);duplicate['shots'][1]['id']='S01'
        with self.assertRaisesRegex(ValueError,'unique'): grouping.validate_partition(duplicate,[(0,3)])
        with self.assertRaisesRegex(ValueError,'4..15'): grouping.validate_partition(project([3]),[(0,1)])
        with self.assertRaisesRegex(ValueError,'4..15'): grouping.validate_partition(project([8,8]),[(0,2)])
        for s,bid in zip(p['shots'],['B1','B2','B2']): s['beat']=dict(id=bid)
        with self.assertRaisesRegex(ValueError,'Beat'): grouping.validate_partition(p,[(0,3)])

    def test_json_view_preserves_ids_duration_and_asset_order_without_second_judgment(self):
        p=project([2.1,1.9,4],['E1','E1','E2'])
        p['assets']=[dict(id=aid) for aid in ['scene','girl','key','boy','unused']]
        for s,aids in zip(p['shots'],[['girl','scene'],['key','girl'],['boy','key']]): s['asset_ids']=aids
        original=copy.deepcopy(p)
        ranges=[(0,2),(2,3)]
        result=json.loads(json.dumps(dict(clipGroupList=grouping.clip_group_list(p,ranges))))
        self.assertEqual(result,dict(clipGroupList=[
            dict(shotId='shot_1',originClipIdList=['S01','S02'],totalDuration=4.0,assetIdList=['scene','girl','key']),
            dict(shotId='shot_2',originClipIdList=['S03'],totalDuration=4.0,assetIdList=['key','boy'])]))
        self.assertEqual(sum(Decimal(str(g['totalDuration'])) for g in result['clipGroupList']),Decimal('8'))
        self.assertEqual(p,original)


class NarrativeIntegrationTests(imported.fixtures.Base):
    # Reuse the three-shot simulated evidence setup, without inheriting its tests.
    setUp=imported.ImportedReviewTests.setUp
    png=imported.ImportedReviewTests.png
    select_mapping=imported.ImportedReviewTests.select_mapping
    mapping=imported.ImportedReviewTests.mapping
    review_data=imported.ImportedReviewTests.review_data
    finish=imported.ImportedReviewTests.finish

    def test_absent_fill_pending_still_count_and_suggestions_render(self):
        for s,d in zip(self.p['shots'],[7.1,.2,7.7]): s['duration']=d
        self.p['shots'][1]['duration_source']=dict(kind='inference',ref='建议短观察镜头')
        self.mapping({'S02':'absent'})
        result=self.finish()
        self.assertEqual(result['groups'][0]['planned_duration'],15)
        self.assertEqual(result['decisions'][1]['status'],'absent_fill_suggested_unverified')
        text=Path(boards.render(self.p,self.path,self.path.parent/'delivery')).read_text(encoding='utf8')
        self.assertIn('15 秒（含建议值）',text)
        self.assertIn('0.2 秒（建议）',text)
        self.mapping({'S02':'uncertain'},revision=2)
        self.assertEqual(self.finish()['groups'][0]['planned_duration'],15)

    def test_missing_duration_still_allows_review_but_not_final_grouping(self):
        self.p['shots'][1].pop('duration');self.p['shots'][1].pop('duration_source')
        core.validate(self.p,self.path)
        self.mapping()
        result=self.finish()
        self.assertFalse(result['feasible'])
        self.assertEqual(result['clipGroupList'],[])
        self.assertEqual(result['decisions'][0]['status'],'anchor_reviewed')
        text=Path(boards.render(self.p,self.path,self.path.parent/'delivery')).read_text(encoding='utf8')
        self.assertIn('待确定',text)
        self.assertNotIn('| A01 |',text)

    def test_single_clip_over_limit_delivers_actionable_pending_not_success(self):
        self.p['shots'][0]['duration']=16
        self.mapping();result=self.finish()
        self.assertFalse(result['feasible'])
        text=Path(boards.render(self.p,self.path,self.path.parent/'delivery')).read_text(encoding='utf8')
        self.assertIn('需拆分或调整计划时长',text)
        self.assertIn('16 秒',text)
        self.assertNotIn('| A01 |',text)

    def test_pending_timing_does_not_create_or_hide_required_absence(self):
        self.p['shots'][1].pop('duration');self.p['shots'][1].pop('duration_source')
        self.mapping({'S02':'absent'})
        self.assertEqual(self.finish()['decisions'][1]['status'],'pending')
        self.p['shots'][1]['intent']['critical_result']=True
        self.mapping({'S02':'absent'},revision=2)
        self.assertEqual(self.finish()['decisions'][1]['status'],'missing_required')

    def test_duration_source_and_narrative_edits_invalidate_evidence(self):
        for change in (lambda p:p['shots'][1].update(duration=2.5),
                       lambda p:p['shots'][1]['duration_source'].update(ref='changed basis'),
                       lambda p:p['narrative_plan']['boundaries'][0].update(strength=1)):
            self.mapping();self.finish()
            original=copy.deepcopy(self.p)
            change(self.p)
            self.assertIsNone(core.review_current(self.p,self.path,'G01'))
            self.assertIsNone(planner.current_aggregation(self.p,self.path))
            self.p=original

    def test_beat_is_in_batch_context_compact_view_and_evidence_binding(self):
        for s in self.p['shots']:
            s['beat']=dict(id='B01',source=dict(kind='script',ref='第一 Beat'))
        self.mapping();result=self.finish()
        ctx=core.video_context(self.p,self.path,'G01')
        view=review_draft.agent_view(ctx,self.path.parent/'context.json')
        self.assertEqual([s['beat'] for s in view['shots']],[s['beat'] for s in self.p['shots']])
        self.assertEqual(result['groups'][0]['beat_id'],'B01')
        self.assertEqual(result['clipGroupList'][0]['originClipIdList'],result['groups'][0]['shot_ids'])
        before=core.group_fingerprint(self.p,self.path,self.p['groups'][0])
        self.p['shots'][1]['beat']['source']['ref']='新分段依据'
        self.assertNotEqual(before,core.group_fingerprint(self.p,self.path,self.p['groups'][0]))
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        self.assertIsNone(planner.current_aggregation(self.p,self.path))

    def test_old_policy_and_old_grouping_scope_cannot_reuse_valid_result(self):
        self.mapping();self.finish()
        with patch.object(grouping,'POLICY_VERSION',grouping.POLICY_VERSION-1):
            self.assertIsNone(planner.current_aggregation(self.p,self.path))
        r=self.review_data()
        ctx=core.video_context(self.p,self.path,'G01')
        ctx['review_scope'].pop('min_group_seconds')
        ctx['review_scope'].pop('grouping_scope')
        ctx.pop('context_fingerprint');ctx.pop('previous_review')
        r['context_fingerprint']=core.digest(ctx)
        with self.assertRaisesRegex(ValueError,'context'): core.record_review(self.p,self.path,r)

    def test_short_impossible_group_stays_placeholder_and_does_not_relabel_verdicts(self):
        self.p['narrative_plan']['boundaries'][0].update(merge_allowed=False,reason='独立事件')
        self.mapping();result=self.finish()
        self.assertFalse(result['feasible'])
        self.assertEqual(result['clipGroupList'],[])
        self.assertTrue(all(g['id'].startswith('P') for g in result['groups']))
        self.assertEqual(result['decisions'][0]['status'],'anchor_reviewed')
        text=Path(boards.render(self.p,self.path,self.path.parent/'delivery')).read_text(encoding='utf8')
        self.assertEqual(sum(l.startswith('| --- |') for l in text.splitlines()),2)
        self.assertIn('4–15秒',text)
        self.assertNotIn('| A01 |',text)

    def test_batch_grouping_review_required_and_dialogue_excluded_from_scope(self):
        self.p['shots'][1]['script']+=' 她说：明天见。'
        self.mapping()
        ctx=core.video_context(self.p,self.path,'G01')
        self.assertFalse(ctx['review_scope']['dialogue_text'])
        self.assertFalse(ctx['review_scope']['dialogue_lip_sync'])
        self.assertFalse(ctx['review_scope']['duration_accuracy'])
        self.assertEqual(ctx['review_scope']['min_group_seconds'],4)
        self.assertEqual(ctx['review_scope']['grouping_scope'],'same_beat')
        self.assertTrue(ctx['review_scope']['visual_actions'])
        self.assertFalse(ctx['review_scope']['subtitles'])
        r=self.review_data();r.pop('grouping_checked')
        with self.assertRaisesRegex(ValueError,'grouping'):core.record_review(self.p,self.path,r)
        r=self.review_data()
        r['evidence'][1]['observation']='SIMULATED: 配音为再见，与原文不同，但可见动作、人物、持物、衔接符合；不验收逐字对白。'
        self.assertEqual(core.record_review(self.p,self.path,r),'PASS')
        for check in ('identity','props','key_state','continuity'):
            r=self.review_data({'S02':'FAIL'})
            r['shot_reviews'][1]['checks']={c:('FAIL' if c==check else 'PASS') for c in boards.CHECKS}
            if check=='identity':
                c=next(c for c in r['asset_comparisons'] if c['shot_id']=='S02')
                c.update(decision='FAIL',story_impact='SIMULATED disguise identity clue contradicted',stable_conflicts=[dict(feature='collar',expected='lapel',observed='zipper collar',environment_exclusion='lighting cannot replace fasteners')])
                r['issues'][0].update(asset_ids=[c['asset_id']],asset_comparison_ids=[c['id']])
            core.record_review(self.p,self.path,r)
            result=planner.post_review_plan(self.p,self.path,{})
            self.assertEqual([d['status'] for d in result['decisions']],['anchor_reviewed','mismatch','anchor_reviewed'])


if __name__=='__main__': unittest.main()
