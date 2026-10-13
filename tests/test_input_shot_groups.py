"""Explicit user partitions; no video dependencies."""
import copy
import json
import subprocess
import sys
from pathlib import Path
import storyboard_fixtures as fixtures
import previs as core
import grouping

class InputParsingTests(fixtures.Base):
    def setUp(self):
        super().setUp()
        self.p['shots'].append(dict(self.p['shots'][-1], id='S04'))
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
