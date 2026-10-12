"""Evidence-bound threshold regression; judgments and workflow are simulated."""
import copy
from pathlib import Path
from unittest.mock import patch

import test_previs as fixtures
import test_repair_cycle as helpers
import previs as core
import repair_cycle as repair
import repair_export
import repair_readiness
import storyboard as boards


class RepairThresholdTests(fixtures.Base):
    setUp = helpers.RepairCycleTests.setUp
    png = helpers.RepairCycleTests.png
    select_mapping = helpers.RepairCycleTests.select_mapping
    mapping = helpers.RepairCycleTests.mapping
    review_data = helpers.RepairCycleTests.review_data
    assessment = helpers.RepairCycleTests.assessment
    finish = helpers.RepairCycleTests.finish
    ready = helpers.RepairCycleTests.ready
    start = helpers.RepairCycleTests.start

    def damage_review(self):
        self.mapping()
        review = self.assessment(self.review_data({'S02': 'FAIL'}), False)
        review['repair_assessments'][0]['severe_visual_damage'] = dict(
            time_range=[2.0, 2.5], damage_description='SIMULATED broken hand and key geometry',
            obscured_content='SIMULATED necessary key holder cannot be identified')
        return review

    def test_one_critical_present_error_triggers_without_missing_reference(self):
        decision = self.ready({'S02': 'FAIL'}, critical=True)
        self.assertTrue(decision['triggered'])
        self.assertEqual(decision['trigger'], 'critical')
        self.assertEqual(decision['error_count'], 1)
        self.assertEqual(decision['necessary_missing_shot_ids'], [])

    def test_two_ordinary_errors_trigger_and_uncertain_does_not_count(self):
        decision = self.ready({'S01': 'FAIL', 'S02': 'FAIL', 'S03': 'uncertain'},
                              {'S03': 'uncertain'}, critical=False)
        self.assertEqual(decision['problem_shot_ids'], ['S01', 'S02'])
        self.assertEqual(decision['total'], 3)
        self.assertEqual(decision['trigger'], 'cumulative')

    def test_present_error_and_confirmed_absence_count_together(self):
        decision = self.ready({'S01': 'FAIL', 'S02': 'absent'}, {'S02': 'absent'}, critical=False)
        self.assertEqual(decision['problem_shot_ids'], ['S01', 'S02'])
        self.assertTrue(decision['triggered'])
        self.assertEqual(decision['confirmed_missing_shot_ids'], ['S02'])

    def test_derivable_absence_triggers_critical_gate_but_stays_missing(self):
        decision = self.ready(derivable=True)
        self.assertTrue(decision['triggered'])
        self.assertEqual(decision['necessary_missing_shot_ids'], [])
        self.assertEqual(self.p['aggregation']['missing_summary'][0]['bad_num'], 0)
        text = Path(boards.render(self.p, self.path, self.path.parent / 'delivery')).read_text(encoding='utf8')
        row = next(line for line in text.splitlines() if '| S02 |' in line)
        self.assertIn('| 可推导生成 | 视频漏镜 |', row)
        self.assertNotIn('![', row)
        self.assertIn('原因是已确认关键剧情错误或关键节点缺失', text)
        self.assertEqual(sum(line.startswith('| --- |') for line in text.splitlines()), 1)

    def test_absence_counts_before_reference_necessity_is_decided(self):
        decision = self.ready(critical=False, derivable=None)
        self.assertEqual(decision['problem_shot_ids'], ['S02'])
        self.assertEqual(decision['confirmed_missing_shot_ids'], ['S02'])
        self.assertEqual(decision['necessary_missing_shot_ids'], [])
        self.assertEqual(self.p['aggregation']['missing_summary'][0]['bad_num'], 0)
        self.assertEqual(self.p['aggregation']['decisions'][1]['mode'], 'pending')

    def test_pure_detail_and_allowed_difference_do_not_count(self):
        self.mapping({'S03': 'uncertain'})
        review = self.assessment(self.review_data({'S01': 'FAIL', 'S02': 'FAIL', 'S03': 'uncertain'}))
        for row in review['repair_assessments']:
            row.update(affects_story=False, impact='SIMULATED performance detail; story unchanged')
        self.finish(review)
        decision = repair.decide(self.p, self.path, 'G01')
        self.assertEqual(decision['problem_shot_ids'], [])
        self.assertFalse(decision['triggered'])

    def test_multiple_issues_on_one_shot_count_once(self):
        self.mapping()
        review = self.assessment(self.review_data({'S02': 'FAIL'}))
        extra = copy.deepcopy(review['issues'][0])
        extra['id'] = 'another-S02'
        review['issues'].append(extra)
        review['repair_assessments'][0]['issue_ids'].append(extra['id'])
        self.finish(review)
        decision = repair.decide(self.p, self.path, 'G01')
        self.assertEqual(decision['error_count'], 1)
        self.assertFalse(decision['triggered'])

    def test_denominator_is_source_coverage_not_final_shot_group(self):
        self.p['input_shot_groups'] = 'A01:S01–S02；A02:S03'
        for shot in self.p['shots']:
            shot['duration'] = 4
        decision = self.ready({'S01': 'FAIL', 'S02': 'FAIL'}, critical=False)
        self.assertEqual(len(self.p['aggregation']['groups']), 2)
        self.assertEqual(decision['total'], 3)
        self.assertAlmostEqual(decision['ratio'], 2 / 3)

    def test_severe_damage_needs_one_shot_and_timed_evidence(self):
        self.finish(self.damage_review())
        decision = repair.decide(self.p, self.path, 'G01')
        self.assertTrue(decision['triggered'])
        self.assertEqual(decision['trigger'], 'severe_visual_damage')
        self.assertEqual(decision['severe_visual_damage_shot_ids'], ['S02'])
        text = Path(boards.render(self.p, self.path, self.path.parent / 'delivery')).read_text(encoding='utf8')
        self.assertIn('原因是严重画面损坏遮挡必要内容', text)

    def test_damage_empty_or_invalid_interval_cannot_trigger(self):
        review = self.damage_review()
        cases = [('damage_description', ''), ('obscured_content', ''),
                 ('time_range', [2.0, 2.0]), ('time_range', [float('nan'), 2.5]),
                 ('time_range', [True, 2.5]), ('time_range', [3.0, 3.5])]
        for field, value in cases:
            bad = copy.deepcopy(review)
            bad['repair_assessments'][0]['severe_visual_damage'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                core.record_review(self.p, self.path, bad)

    def test_damage_must_be_story_affecting_present_failure_and_own_issue(self):
        review = self.damage_review()
        for mutation in ('nonstory', 'other_issue', 'outside_issue', 'absent'):
            bad = copy.deepcopy(review)
            row = bad['repair_assessments'][0]
            if mutation == 'nonstory':
                row['affects_story'] = False
            elif mutation == 'other_issue':
                bad['issues'][0]['shot_ids'] = ['S01']
            elif mutation == 'outside_issue':
                bad['issues'][0]['time_range'] = [0, 1]
            else:
                bad['shot_reviews'][1]['verdict'] = 'absent'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                repair.validate_assessments(self.p, bad)

    def test_damage_diagnostics_collect_all_missing_evidence(self):
        review = self.damage_review()
        row = review['repair_assessments'][0]
        row['severe_visual_damage'] = dict(time_range=[2.0, 2.5])
        row['issue_ids'] = None
        report = repair_readiness.diagnose(self.p, review)
        with self.assertRaises(ValueError) as caught:
            report.finish()
        for field in ('damage_description', 'obscured_content', 'issue_ids', 'referenced same-shot issue'):
            self.assertIn(field, str(caught.exception))

    def test_derivable_missing_prompt_keeps_internal_label_without_submission(self):
        self.ready(derivable=True)
        tasks = copy.deepcopy(self.p['tasks'])
        with patch.object(repair, 'submit', side_effect=AssertionError('No API call')):
            record = repair_export.export_prompt(self.p, self.path, 'G01', self.path.parent / 'prompts/new.md')
        text = Path(record['path']).read_text(encoding='utf8')
        request = core.read(record['request_path'])
        self.assertIn('【已确认漏镜补齐】镜头2=S02', request['prompt'])
        self.assertNotIn('【已定位画面修正】镜头2=S02', request['prompt'])
        self.assertNotIn('【已确认漏镜补齐】', text)
        self.assertIn(request['blocks'][1]['generation_text'], text)
        self.assertIn(request['blocks'][1]['correction'], text)
        self.assertEqual(self.p['tasks'], tasks)

    def test_stale_threshold_cannot_be_rendered_or_exported(self):
        with patch.object(repair, 'POLICY', 2):
            self.ready()
        with self.assertRaisesRegex(ValueError, 'stale'):
            boards.render(self.p, self.path, self.path.parent / 'delivery')
        self.assertFalse((self.path.parent / 'delivery').exists())
        with self.assertRaisesRegex(ValueError, 'stale'):
            repair_export.export_prompt(self.p, self.path, 'G01', self.path.parent / 'prompts/new.md')

    def test_previous_policy_task_resumes_and_installs_without_resubmission(self):
        with patch.object(repair, 'POLICY', 2):
            api, key, _, _ = self.start()
        self.assertEqual(repair.resume(self.p, self.path, key, api), 'SUCCESS')
        repair.validate_stored_request(self.p, self.path, self.p['tasks'][key])
        with patch('media.probe', return_value={'streams': [{'codec_type': 'video'}]}), \
             patch('media.duration', return_value=6):
            repair.install(self.p, self.path, key)
        self.assertEqual(api.submissions, 1)
        self.assertEqual(core.group(self.p, 'G01')['version'], 2)
        self.assertIsNone(core.review_current(self.p, self.path, 'G01'))

    def test_legacy_policy_exception_does_not_accept_changed_inputs_or_decisions(self):
        with patch.object(repair, 'POLICY', 2):
            _, key, _, _ = self.start()
        task = self.p['tasks'][key]
        original = copy.deepcopy(self.p)
        self.p['repair_decisions']['G01']['allowed_correction_shot_ids'].append('S01')
        with self.assertRaisesRegex(ValueError, 'modified'):
            repair.validate_stored_request(self.p, self.path, task)
        self.p = original
        self.p['assets'][0]['path'] = str(self.png('replacement-asset', (200, 30, 90)))
        with self.assertRaises(ValueError):
            repair.validate_stored_request(self.p, self.path, task)

    def test_numeric_boundaries_and_damage_deduplication(self):
        for total, ids, triggered in ((10, ['a', 'b'], True), (11, ['a', 'b'], False),
                                      (3, ['a'], False), (10, ['a', 'a'], False)):
            with self.subTest(total=total, ids=ids):
                self.assertEqual(repair.threshold(total, ids, [])['triggered'], triggered)
        decision = repair.threshold(100, ['a', 'a'], [], severe_visual_damage=['a', 'a'])
        self.assertTrue(decision['triggered'])
        self.assertEqual(decision['error_count'], 1)
        self.assertEqual(decision['severe_visual_damage_shot_ids'], ['a'])
        with self.assertRaises(ValueError):
            repair.threshold(3, ['a'], [], severe_visual_damage=['b'])
