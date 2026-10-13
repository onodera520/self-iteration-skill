"""Grouping rules shared by the current image workflow."""
import copy
import json
from decimal import Decimal
import unittest
import storyboard_fixtures
import grouping

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
