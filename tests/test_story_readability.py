"""Simulated review judgments verify policy/planning/rendering, not visual accuracy."""
import copy
from pathlib import Path
import unittest
import test_previs as fixtures
import test_imported_review as imported
import previs as core
import planner
import storyboard as boards


class StoryReadabilityTests(fixtures.Base):
    setUp = imported.ImportedReviewTests.setUp
    png = imported.ImportedReviewTests.png
    select_mapping = imported.ImportedReviewTests.select_mapping
    mapping = imported.ImportedReviewTests.mapping
    review_data = imported.ImportedReviewTests.review_data
    finish = imported.ImportedReviewTests.finish

    def umbrella_story(self):
        # Reuse the three-shot fixture, replacing its handoff with an ordinary detail.
        ids = {'S01': 'S03', 'S02': 'S04', 'S03': 'S05'}
        def rename(value):
            if isinstance(value, dict):
                return {k: rename(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rename(v) for v in value]
            return ids.get(value, value) if isinstance(value, str) else value
        self.p = rename(self.p)
        scripts = ['持伞，目送林默', '手指滑过伞柄的局部特写', '抬眼，目光转折']
        facts = copy.deepcopy(self.p['shots'][0]['facts'])
        for fact in facts:
            if fact['attribute'] == 'fob_color':
                fact['attribute'] = 'handle_color'
        for i, shot in enumerate(self.p['shots']):
            shot.update(script=scripts[i], facts=copy.deepcopy(facts), state_changes=[],
                        required_result='仍持伞，观察关系不变')
            shot['intent'].update(critical_result=False, narrative_turn=False)
            shot['requirements'].update(purpose='目送与犹豫', must_have=['仍持伞'], must_not_have=[])
            shot['requirements']['keyframe']['description'] = scripts[i]
            shot['requirements']['provenance'][0]['source'] = scripts[i]
        middle = self.p['shots'][1]
        middle['facts'].append(dict(entity='girl', attribute='finger_gesture',
            value='滑过伞柄', status='known', phase='static', critical=False,
            source=dict(kind='script', ref='S04 手指细节')))
        for asset in self.p['assets']:
            if asset['id'] == 'key':
                asset['name'] = '雨伞'
        self.p['source_script'] = ' '.join(s['id']+' '+s['script'] for s in self.p['shots'])
        self.p['narrative_plan']['safe_spans'][0]['reason'] = '持伞目送，普通手部细节，抬眼反应'

    def omission_review(self):
        r = self.review_data(middle_derivable=False)
        r['reference_assessments'][1].update(decision='ai_fill', derivable=True,
            basis_shot_ids=['S03', 'S05'],
            reason='S03 持伞目送到 S05 抬眼仍可读懂犹豫；S04 手指轨迹不能唯一推出，但不丢剧情节点或产生歧义')
        return r

    def test_nonunique_performance_detail_can_be_omitted_without_changing_script(self):
        self.umbrella_story()
        self.mapping()
        before = copy.deepcopy(self.p['shots'])
        result = self.finish(self.omission_review())
        self.assertEqual([d['mode'] for d in result['decisions']], ['anchor', 'ai_fill', 'anchor'])
        self.assertEqual(result['groups'][0]['planned_duration'], 6)
        self.assertEqual(self.p['shots'], before)
        document = Path(boards.render(self.p, self.path, self.path.parent/'delivery')).read_text(encoding='utf8')
        row = next(line for line in document.splitlines() if '| S04 |' in line)
        self.assertIn('| 可推导生成 | 检验通过 | 建议省图，未验证 | S03 + S05 |', row)
        self.assertNotIn('![', row)
        self.assertFalse(list((self.path.parent/'delivery').rglob('*S04*.png')))
        self.assertIsNotNone(boards.current_mapping(self.p, self.path, 'G01'))

    def test_missing_performance_detail_remains_absent_not_pass(self):
        self.umbrella_story()
        self.mapping({'S04': 'absent'})
        result = self.finish(self.omission_review())
        self.assertEqual(result['decisions'][1]['status'], 'absent_fill_suggested_unverified')
        self.assertEqual(result['missing_summary'][0]['bad_num'], 0)
        self.assertEqual(core.review_current(self.p, self.path, 'G01')['checks']['story'], 'FAIL')
        self.assertEqual(result['groups'][0]['planned_duration'], 6)

    def test_plot_nodes_override_omission_candidate(self):
        for flag in ('critical_result', 'narrative_turn'):
            with self.subTest(flag=flag):
                self.setUp()
                self.p['shots'][1]['intent'][flag] = True
                self.mapping()
                result = self.finish()
                self.assertEqual(result['decisions'][1]['mode'], 'anchor')
        self.setUp()
        # First appearance of a character remains protected, even if its asset exists.
        self.p['shots'][0]['asset_ids'].remove('boy')
        self.p['shots'][0]['facts'] = [f for f in self.p['shots'][0]['facts'] if f['entity'] != 'boy']
        self.mapping()
        self.assertEqual(self.finish()['decisions'][1]['mode'], 'anchor')

    def test_screen_text_is_out_of_default_group_scope(self):
        self.mapping()
        ctx = core.video_context(self.p, self.path, 'G01')
        scope = ctx['review_scope']
        self.assertFalse(scope['subtitles'])
        self.assertFalse(scope['screen_text'])
        self.assertFalse(scope['unique_visual_reconstruction_required'])
        self.assertFalse(scope['performance_detail_alone_protected'])
        self.assertEqual(scope['reference_omission_basis'], 'story_readable_without_ambiguity')
        self.finish()
        self.assertEqual(set(core.review_current(self.p, self.path, 'G01')['checks']), {'shot','continuity','story'})
        for extra in ('PASS', 'FAIL', 'uncertain'):
            r = self.review_data()
            r['checks']['subtitles'] = extra
            with self.assertRaisesRegex(ValueError, 'checks must match scope'):
                core.record_review(self.p, self.path, r)
        r = self.review_data()
        del r['checks']['story']
        with self.assertRaisesRegex(ValueError, 'checks must match scope'):
            core.record_review(self.p, self.path, r)

    def test_previous_rules_cannot_be_reused_but_valid_mapping_survives(self):
        self.mapping()
        old = self.review_data()
        old.update(review_schema=4, reference_policy_version=4)
        with self.assertRaisesRegex(ValueError, 'old review version'):
            core.record_review(self.p, self.path, old)
        self.finish()
        review = core.review_current(self.p, self.path, 'G01')
        self.assertEqual((review['review_schema'], review['reference_policy_version']), (5,5))
        review['review_schema'] = 4
        self.assertIsNone(core.review_current(self.p, self.path, 'G01'))
        self.assertIsNone(planner.current_aggregation(self.p, self.path))
        self.assertIsNotNone(boards.current_mapping(self.p, self.path, 'G01'))


if __name__ == '__main__':
    unittest.main()
