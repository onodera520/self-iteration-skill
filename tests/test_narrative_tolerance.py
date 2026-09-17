"""Simulated semantic judgments test the review/planning contract, not vision accuracy."""
from pathlib import Path
import unittest
import test_previs as fixtures
import test_imported_review as imported
import previs as core
import planner
import storyboard as boards


class NarrativeToleranceTests(fixtures.Base):
    setUp = imported.ImportedReviewTests.setUp
    png = imported.ImportedReviewTests.png
    select_mapping = imported.ImportedReviewTests.select_mapping
    mapping = imported.ImportedReviewTests.mapping
    review_data = imported.ImportedReviewTests.review_data
    finish = imported.ImportedReviewTests.finish

    def ordinary_review(self):
        r = self.review_data(middle_derivable=False)
        r['asset_comparisons'] = []
        for row in r['shot_reviews']:
            row.pop('identity_scope', None)
        return r

    def test_noncritical_variations_survive_review_planning_and_delivery(self):
        self.mapping()
        ctx = core.video_context(self.p, self.path, 'G01')
        self.assertEqual(ctx['review_scope']['visual_match_basis'], 'narrative_equivalence')
        self.assertTrue(ctx['review_scope']['noncritical_visual_variations_allowed'])
        self.assertTrue(ctx['review_scope']['explicit_strict_requirements'])
        r = self.ordinary_review()
        r['evidence'][1].update(
            visible_facts=['较近景别，两人左右投影与脚本不同', '同一房间，女孩仍握唯一钥匙，两人互相观察'],
            interpretation='景别、姿势和站位有偏差，但观察关系与交接前状态清楚，无严格站位要求')
        r['shot_reviews'][1]['reason'] = '剧情等效：角色、地点、持物和观察关系成立'
        result = self.finish(r)
        self.assertEqual(result['decisions'][1]['status'], 'anchor_reviewed')
        text = Path(boards.render(self.p, self.path, self.path.parent/'delivery')).read_text(encoding='utf8')
        row = next(line for line in text.splitlines() if '| S02 |' in line)
        self.assertIn('| 检验通过 |', row)
        self.assertNotIn('该镜需重新生成', text)
        # Tolerance does not rewrite the source or reduce planned duration.
        self.assertEqual(self.p['shots'][1]['shot_size'], '中景')
        self.assertIn('中景', self.p['shots'][1]['script'])
        self.assertEqual(result['groups'][0]['planned_duration'], 6)

    def test_explicit_strict_composition_failure_remains_local(self):
        s = self.p['shots'][1]
        s['script'] += ' 用户明确要求本镜必须中景，完整呈现两人的上半身。'
        s['requirements']['must_have'].append('严格中景，两人上半身完整可见')
        s['requirements']['provenance'][0]['source'] = s['script']
        self.mapping()
        r = self.review_data({'S02':'FAIL'}, middle_derivable=False)
        r['shot_reviews'][1]['checks'].update(props='PASS', composition='FAIL')
        r['shot_reviews'][1]['reason'] = '违反用户明确严格的双人中景要求'
        r['issues'][0].update(problem='裁切违反明确严格构图要求',
            expected='双人中景，上半身完整可见', actual='近景裁掉其中一人的上半身',
            fix='重生成该镜，满足明确指定的中景构图')
        result = self.finish(r)
        self.assertEqual([d['status'] for d in result['decisions']],
                         ['anchor_reviewed', 'mismatch', 'anchor_reviewed'])
        self.assertEqual(result['missing_summary'][0]['bad_num'], 0)

    def test_required_result_unclear_still_needs_evidence(self):
        self.mapping()
        r = self.ordinary_review()
        r['evidence'][2].update(visible_facts=['两人及交接对象可辨认，交接处被遮挡'],
            interpretation='无法确认钥匙最终持有者，需要同镜连续帧')
        row = r['shot_reviews'][2]
        row.update(verdict='uncertain', reason='必要交接结果不可见', followup='回看本镜交接后的连续帧')
        row['checks']['key_state'] = 'uncertain'
        r['reference_assessments'][2].update(decision='pending', derivable=None, reason='先确认交接结果')
        r['checks']['shot'] = 'uncertain'
        r['uncertainties'] = ['S03 关键交接结果不可见']
        result = self.finish(r)
        self.assertEqual(result['decisions'][2]['status'], 'pending')
        self.assertEqual(result['missing_summary'][0]['bad_num'], 0)
        self.assertEqual(core.review_current(self.p,self.path,'G01')['shot_reviews'][2]['verdict'], 'uncertain')

    def test_old_policy_cannot_be_registered_or_reused_but_mapping_survives(self):
        self.mapping()
        old = self.review_data()
        old.update(review_schema=4, reference_policy_version=3)
        with self.assertRaisesRegex(ValueError, 'old review version'):
            core.record_review(self.p, self.path, old)
        self.finish()
        current = core.review_current(self.p, self.path, 'G01')
        self.assertEqual(current['reference_policy_version'], 5)
        current['reference_policy_version'] = 3
        self.assertIsNone(core.review_current(self.p, self.path, 'G01'))
        self.assertIsNone(planner.current_aggregation(self.p, self.path))
        self.assertIsNotNone(boards.current_mapping(self.p, self.path, 'G01'))


if __name__ == '__main__':
    unittest.main()
