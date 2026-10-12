"""Fixed user Shot partitions; visual judgments in fixtures are simulated."""
import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import test_previs as fixtures
import test_imported_review as imported
import previs as core
import grouping
import incremental
import planner
import storyboard as boards


class InputParsingTests(fixtures.Base):
    def setUp(self):
        super().setUp()
        for s in self.p['shots']:
            s.update(duration=2, duration_source=dict(kind='script', ref='SIMULATED script'))

    def test_text_table_and_json_forms_preserve_ids_and_order(self):
        expected = [dict(id='A01', shot_ids=['S01', 'S02']), dict(id='A02', shot_ids=['S03', 'S04'])]
        ids = [s['id'] for s in self.p['shots']]
        for value in ('A01：S01–S02；A02：S03–S04',
                      '| 分组编号 | 镜头顺序 |\n| --- | --- |\n| A01 | S01–S02 |\n| A02 | S03、S04 |',
                      expected, {'A01': ['S01', 'S02'], 'A02': 'S03–S04'},
                      {'input_shot_groups': expected}):
            with self.subTest(value=value):
                self.assertEqual(grouping.parse_input_groups(value, ids), expected)
        self.assertEqual(grouping.parse_input_groups(dict(id='mine', shot_ids='S01–S04'), ids),
                         [dict(id='mine', shot_ids=ids)])
        self.assertEqual(grouping.parse_input_groups('A01:S03–S01', ids)[0]['shot_ids'], ['S03', 'S02', 'S01'])

    def test_conflicts_collected_without_mutating_input(self):
        self.p['shots'][2]['beat'] = dict(id='B02')
        self.p['input_shot_groups'] = [dict(id='A01', shot_ids=['S03', 'S01', 'S99']),
                                       dict(id='A01', shot_ids=['S01', 'S02'])]
        before = copy.deepcopy(self.p)
        report = grouping.input_partition(self.p)
        self.assertTrue({'unknown', 'order', 'nonadjacent', 'beat', 'duplicate_group', 'duplicate', 'missing', 'group_order'}
                        <= {c['code'] for c in report['conflicts']})
        self.assertEqual(self.p, before)
        self.assertFalse(report['feasible'])
        self.assertEqual(report['groups'][0]['shot_ids'], ['S03', 'S01', 'S99'])

    def test_public_partition_is_stable_after_json_roundtrip(self):
        self.p['input_shot_groups'] = 'A01:S01–S02；A02:S03–S04'
        report = grouping.input_partition(self.p)
        self.assertEqual(report['valid_ranges'], {'0': [0, 2], '1': [2, 4]})
        self.assertEqual(json.loads(json.dumps(report)), report)

    def test_exact_limits_and_missing_metadata(self):
        self.p['shots'] = self.p['shots'][:3]
        self.p['input_shot_groups'] = 'mine:S01–S03'
        for durations, valid in (([1, 1, 2], True), ([7.1, .2, 7.7], True),
                                 ([7.1, .2, 7.70001], False), ([1, 1, 1.99], False)):
            for s, d in zip(self.p['shots'], durations):
                s['duration'] = d
            self.assertEqual(grouping.input_partition(self.p)['feasible'], valid)
        self.p['shots'][0]['duration'] = None
        self.p['shots'][1].pop('duration_source')
        self.assertTrue({'duration', 'duration_source'} <= {c['code'] for c in grouping.input_partition(self.p)['conflicts']})

    def test_twelve_clip_limit_and_deferred_source_boundary(self):
        shot = self.p['shots'][0]
        self.p['shots'] = [dict(shot, id=f'S{i:02}', duration=1) for i in range(1, 14)]
        self.p['input_shot_groups'] = 'mine:S01–S13'
        report = grouping.input_partition(self.p, {3})
        self.assertTrue({'shot_limit', 'source_boundary'} <= {c['code'] for c in report['conflicts']})
        self.assertTrue(grouping.input_partition(self.p)['boundary_checks_deferred'])

    def test_empty_is_conflict_null_is_automatic(self):
        self.p['input_shot_groups'] = []
        self.assertFalse(grouping.input_partition(self.p)['feasible'])
        self.assertEqual(grouping.input_partition(self.p)['groups'], [])
        self.p['input_shot_groups'] = None
        self.assertIsNone(grouping.input_partition(self.p))

    def test_cli_check_is_read_only_apply_only_changes_input(self):
        core.save(self.path, self.p)
        source = self.path.parent / 'groups.md'
        source.write_text('A01:S01–S02；A02:S03–S04', encoding='utf8')
        command = [sys.executable, '-X', 'utf8', str(fixtures.ROOT / 'ai-storyboard-previs/scripts/grouping.py'), str(self.path), str(source)]
        original = self.path.read_bytes()
        subprocess.run(command, capture_output=True, check=True)
        self.assertEqual(self.path.read_bytes(), original)
        subprocess.run(command + ['--apply'], capture_output=True, check=True)
        result = core.read(self.path)
        self.assertIn('input_shot_groups', result)
        result.pop('input_shot_groups')
        self.assertEqual(result, self.p)
        self.assertFalse(Path(str(self.path) + '.lock').exists())


class FixedGroupingTests(fixtures.Base):
    setUp = imported.ImportedReviewTests.setUp
    png = imported.ImportedReviewTests.png
    select_mapping = imported.ImportedReviewTests.select_mapping
    mapping = imported.ImportedReviewTests.mapping
    review_data = imported.ImportedReviewTests.review_data
    finish = imported.ImportedReviewTests.finish

    def fixed(self, value='mine:S01–S03'):
        self.p['input_shot_groups'] = value
        self.p.pop('narrative_plan', None)
        for s in self.p['shots']:
            s.pop('event', None)

    def add_fourth(self):
        original = core.read(fixtures.ROOT / 'ai-storyboard-previs/assets/example-project.json')
        fourth = original['shots'][3]
        fourth.update(duration=2, duration_source=dict(kind='script', ref='SIMULATED'))
        fourth.pop('event', None)
        self.p['shots'].append(fourth)
        self.p['groups'].append(original['groups'][1])
        self.p['source_script'] += ' S04 ' + fourth['script']

    def test_fixed_skips_automatic_annotations_and_all_auto_partition_steps(self):
        self.fixed()
        core.validate(self.p, self.path)
        self.mapping()
        review = self.review_data()
        review.pop('grouping_checked')
        before = copy.deepcopy(self.p)
        with patch.object(grouping, 'partition', side_effect=AssertionError('Must not auto-group')):
            result = self.finish(review)
        self.assertTrue(result['feasible'])
        self.assertEqual([(g['id'], g['shot_ids']) for g in result['groups']], [('mine', ['S01', 'S02', 'S03'])])
        self.assertEqual([d['mode'] for d in result['decisions']], ['anchor', 'ai_fill', 'anchor'])
        self.assertEqual(result['clipGroupList'][0]['shotId'], 'mine')
        self.assertEqual(self.p['groups'], before['groups'])
        self.assertEqual(self.p['board_mappings'], before['board_mappings'])
        ctx = core.video_context(self.p, self.path, 'G01')
        self.assertNotIn('narrative_plan', ctx)
        self.assertEqual(ctx['input_shot_groups'], 'mine:S01–S03')

    def test_same_partition_same_per_shot_results_as_automatic(self):
        self.mapping()
        auto = self.finish()
        self.p['input_shot_groups'] = 'mine:S01–S03'
        fixed = self.finish()
        self.assertEqual([(d['mode'], d['status'], d['bracket']) for d in fixed['decisions']],
                         [(d['mode'], d['status'], d['bracket']) for d in auto['decisions']])

    def test_conflict_does_not_fail_picture_or_trigger_missing_count(self):
        self.fixed('A01:S01、S03；A02:S02')
        self.mapping()
        result = self.finish()
        self.assertFalse(result['feasible'])
        self.assertEqual([g['shot_ids'] for g in result['groups']], [['S01', 'S03'], ['S02']])
        self.assertTrue(result['input_group_conflicts'])
        self.assertEqual([d['review_verdict'] for d in result['decisions']], ['PASS'] * 3)
        self.assertTrue(all(d['mode'] == 'anchor' for d in result['decisions']))
        self.assertEqual(result['missing_summary'][0]['bad_num'], 0)
        self.assertFalse(result['missing_summary'][0]['regenerate'])

    def test_conflict_does_not_convert_derivable_absence_to_necessary_missing(self):
        self.fixed('A01:S01、S03；A02:S02')
        self.mapping({'S02': 'absent'})
        result = self.finish()
        self.assertEqual(result['decisions'][1]['status'], 'pending')
        self.assertEqual(result['decisions'][1]['review_verdict'], 'absent')
        self.assertEqual(result['missing_summary'][0]['bad_num'], 0)
        self.assertEqual(core.review_current(self.p, self.path, 'G01')['checks']['story'], 'FAIL')

    def test_other_valid_group_can_still_approve_fill(self):
        self.fixed('A01:S01–S03；A02:S04')
        self.add_fourth()
        self.mapping(gid='G01')
        self.mapping(gid='G02')
        core.record_review(self.p, self.path, self.review_data(gid='G02'))
        result = self.finish()
        self.assertFalse(result['feasible'])  # A02 is only 2 seconds.
        self.assertEqual(result['groups'][0]['planning_status'], 'ready')
        self.assertEqual(result['groups'][1]['planning_status'], 'pending')
        self.assertEqual(result['decisions'][1]['mode'], 'ai_fill')
        self.assertEqual(result['decisions'][3]['review_verdict'], 'PASS')

    def test_fixed_edges_protect_anchors(self):
        self.fixed('A01:S01–S02；A02:S03')
        self.p['shots'][2]['duration'] = 4
        self.mapping()
        result = self.finish()
        self.assertTrue(result['feasible'])
        self.assertEqual([d['mode'] for d in result['decisions']], ['anchor'] * 3)
        self.assertEqual([g['id'] for g in result['groups']], ['A01', 'A02'])

    def test_group_change_invalidates_conclusions_but_reuses_media_and_observations(self):
        self.fixed()
        self.mapping()
        self.finish()
        before = core.video_context(self.p, self.path, 'G01')
        review = core.review_current(self.p, self.path, 'G01')
        mapping = copy.deepcopy(boards.mapping_row(self.p, self.path, 'S02'))
        frame = copy.deepcopy(boards.current_frame(self.p, self.path, 'S02'))
        self.p['input_shot_groups'] = 'renamed:S01–S03'
        after = core.video_context(self.p, self.path, 'G01')
        self.assertIsNone(core.review_current(self.p, self.path, 'G01'))
        self.assertIsNone(planner.current_aggregation(self.p, self.path))
        self.assertEqual(before['group_fingerprint'], after['group_fingerprint'])
        self.assertEqual(before['video_sha256'], after['video_sha256'])
        self.assertEqual(boards.mapping_row(self.p, self.path, 'S02'), mapping)
        self.assertEqual(boards.current_frame(self.p, self.path, 'S02'), frame)
        impact = incremental.analyze(self.p, before, after, after['extraction'], review)
        self.assertEqual(impact['primary'], [])
        self.assertEqual(impact['dependency_recheck'], ['S01', 'S02', 'S03'])
        self.assertEqual(review['evidence'], before['previous_review']['evidence'])

    def test_cross_video_boundary_requires_current_passed_evidence(self):
        self.fixed('mine:S01–S04')
        self.add_fourth()
        self.mapping(gid='G01')
        self.mapping(gid='G02')
        right = self.review_data(gid='G02')
        core.record_review(self.p, self.path, right)
        left = self.review_data({'S03': 'uncertain'}, middle_derivable=False)
        left['boundary_checks'][0]['verdict'] = 'uncertain'
        left['checks']['continuity'] = 'uncertain'
        result = self.finish(left)
        self.assertIn('source_boundary', [c['code'] for c in result['input_group_conflicts']])
        self.assertEqual(result['groups'][0]['shot_ids'], ['S01', 'S02', 'S03', 'S04'])
        self.assertEqual(result['missing_summary'][0]['bad_num'], 0)
        self.assertTrue(self.finish()['feasible'])

    def test_single_table_complete_ordered_rows_and_existing_fill_thumbnail(self):
        self.fixed()
        self.mapping()
        self.finish()
        text = Path(boards.render(self.p, self.path, self.path.parent / 'delivery')).read_text(encoding='utf8')
        self.assertEqual(sum(l.startswith('| --- |') for l in text.splitlines()), 1)
        rows = [l for l in text.splitlines() if l.startswith('| mine |')]
        self.assertEqual([l.split('|')[2].strip() for l in rows], ['S01', 'S02', 'S03'])
        self.assertIn('![', rows[1])
        self.assertIn('建议省图，未验证', rows[1])
        self.assertNotIn('| 总时长 |', text)
        self.assertNotIn('| 分组理由 |', text)

    def test_absent_approved_fill_remains_plain_text_and_absent(self):
        self.fixed()
        self.mapping({'S02': 'absent'})
        self.finish()
        out = self.path.parent / 'delivery'
        text = Path(boards.render(self.p, self.path, out)).read_text(encoding='utf8')
        row = next(l for l in text.splitlines() if '| S02 |' in l)
        self.assertIn('| 可推导生成 | 视频漏镜 |', row)
        self.assertNotIn('![', row)
        self.assertFalse(list(out.rglob('*S02*.png')))
