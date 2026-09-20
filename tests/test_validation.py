"""Batch diagnostics and dependency blocking; no visual or paid operations."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'ai-storyboard-previs/scripts'
sys.path.insert(0, str(SCRIPTS))
import previs as core
import requirements
import grouping
import planner
from validation import Report, ValidationError


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.template = ROOT / 'ai-storyboard-previs/assets/imported-project.json'
        self.p = core.read(self.template)

    def errors(self, p=None):
        with self.assertRaises(ValidationError) as raised:
            core.validate(self.p if p is None else p, self.template)
        return raised.exception

    def test_five_independent_errors_one_call_without_mutation_or_file_reads(self):
        self.p['title'] = ''
        self.p['config']['budget_cny'] = -1
        self.p['shots'][0]['requirements']['purpose'] = ''
        self.p['shots'][0]['requirements']['must_have'] = 'not an array'
        self.p['shots'][1]['requirements']['keyframe']['phase'] = 'wrong'
        before = copy.deepcopy(self.p)
        with patch.object(core, 'resolve', side_effect=AssertionError('file I/O too early')):
            result = self.errors()
        self.assertEqual(len(result.errors), 5)
        self.assertEqual({r['path'] for r in result.errors}, {
            'title', 'config.budget_cny', 'shots[S01].requirements.purpose',
            'shots[S01].requirements.must_have', 'shots[S02].requirements.keyframe.phase'})
        self.assertTrue(any('S02' in r['path'] for r in result.blocked))
        self.assertEqual(self.p, before)

    def test_invalid_state_blocks_descendants_but_not_independent_root(self):
        fourth = copy.deepcopy(self.p['shots'][0])
        fourth['id'] = 'S04'
        self.p['shots'].append(fourth)
        self.p['shots'][0]['requirements']['entry_state']['key.holder'] = 'boy'
        report = Report()
        resolved = requirements.contexts(self.p, report=report)
        self.assertEqual(set(resolved), {'S04'})
        self.assertEqual(resolved['S04']['exit_state']['key.holder'], 'girl')
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(len(report.blocked), 2)
        self.assertIn('state baseline conflict', report.errors[0]['message'])
        with self.assertRaises(ValidationError):
            requirements.contexts(self.p)

    def test_bad_fact_source_prevents_state_resolution(self):
        self.p['shots'][0]['facts'][0]['source'] = {'kind': 'invalid', 'ref': 'S01'}
        result = self.errors()
        self.assertTrue(any(r['path'].endswith('.facts[0].source') for r in result.errors))
        self.assertEqual(len(result.blocked), 2)
        self.assertTrue(all('upstream state' in r['message'] for r in result.blocked))

    def test_wrong_nested_shapes_are_diagnostics_not_python_crashes(self):
        edits = [
            (('assets',), {}), (('shots',), 'wrong'), (('config',), []),
            (('shots', 0), []), (('shots', 0, 'id'), []),
            (('shots', 0, 'requirements'), []),
            (('shots', 0, 'requirements', 'entry_state'), 'wrong'),
            (('shots', 0, 'requirements', 'inherits_from'), {}),
            (('shots', 0, 'requirements', 'keyframe'), []),
            (('shots', 0, 'requirements', 'provenance'), [None]),
            (('shots', 0, 'facts'), {}), (('shots', 0, 'facts', 0), []),
            (('shots', 0, 'facts', 0, 'entity'), {}),
            (('shots', 0, 'state_changes'), 'wrong'),
            (('shots', 0, 'reference'), []), (('shots', 0, 'asset_ids'), [{}]),
            (('groups', 0, 'shot_ids'), [{}]), (('groups', 0, 'id'), []),
            (('narrative_plan', 'boundaries'), [None]),
            (('narrative_plan', 'safe_spans'), [{'shot_ids': [{}]}]),
        ]
        for keys, value in edits:
            with self.subTest(path=keys):
                p = copy.deepcopy(self.p)
                target = p
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                self.assertTrue(self.errors(p).errors)

    def test_metadata_collects_across_edges_and_spans(self):
        data = self.p['narrative_plan']
        data['boundaries'][0]['merge_allowed'] = 'yes'
        data['boundaries'][1]['strength'] = 9
        data['safe_spans'][0]['reason'] = ''
        data['safe_spans'][0]['shot_ids'] = ['S01', 'S03']
        with self.assertRaises(ValidationError) as raised:
            grouping.validate_metadata(self.p)
        self.assertEqual(len(raised.exception.errors), 4)

    def test_facts_collect_independent_missing_fields(self):
        self.p['shots'][0]['facts'][0].pop('source')
        self.p['shots'][1]['intent']['critical_result'] = 'yes'
        self.p['shots'][2]['state_changes'][0].pop('after')
        with self.assertRaises(ValidationError) as raised:
            planner.validate_facts(self.p)
        self.assertEqual(len(raised.exception.errors), 3)

    def test_optional_style_catches_wrong_array_and_other_missing_fields(self):
        self.p['repair_asset_style'] = dict(preserves_story=True, assets=[{
            'asset_id': 'girl', 'sha256': 'a' * 64,
            'visible_style_facts': 'yellow coat', 'guidance': ''}, {}])
        result = self.errors()
        paths = {r['path'] for r in result.errors}
        self.assertIn('repair_asset_style.assets[0].visible_style_facts', paths)
        self.assertIn('repair_asset_style.assets[0].guidance', paths)
        self.assertIn('repair_asset_style.assets[1].sha256', paths)

    def test_failed_mutating_cli_preserves_bytes_and_releases_lock(self):
        self.p['title'] = ''
        self.p['config']['budget_cny'] = -1
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'project.json'
            project.write_text(json.dumps(self.p, ensure_ascii=False), encoding='utf-8')
            before = project.read_bytes()
            result = subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPTS / 'previs.py'),
                'import-video', str(project), 'G01', str(Path(temp) / 'missing.mp4')],
                capture_output=True, text=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ERROR title:', result.stderr)
            self.assertIn('ERROR config.budget_cny:', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(project.read_bytes(), before)
            self.assertEqual(list(Path(temp).iterdir()), [project])

    def test_modern_template_passes_without_fabricated_outputs(self):
        from repair_cycle import baseline
        before = copy.deepcopy(self.p)
        self.assertEqual(core.validate(self.p, self.template)['shots'], 3)
        planner.validate_facts(self.p)
        resolved = requirements.contexts(self.p)
        self.assertEqual(resolved['S01']['entry_state']['key.holder'], 'girl')
        self.assertEqual(resolved['S03']['exit_state']['key.holder'], 'boy')
        self.assertTrue(grouping.partition(self.p)['feasible'])
        baseline(copy.deepcopy(self.p))
        self.assertFalse(self.p['tasks'])
        self.assertFalse(self.p['reviews'])
        self.assertNotIn('repair_asset_style', self.p)
        self.assertTrue(all(s['duration_source']['kind'] == 'inference' for s in self.p['shots']))
        self.assertEqual(self.p, before)

    def test_legacy_fields_optional_until_planning(self):
        self.p.pop('narrative_plan')
        for s in self.p['shots']:
            for key in ('requirements', 'facts', 'state_changes', 'omission_assessment',
                        'intent', 'duration', 'duration_source', 'event'):
                s.pop(key, None)
        self.assertEqual(core.validate(self.p, self.template)['shots'], 3)
        self.assertFalse(grouping.partition(self.p)['feasible'])
        with self.assertRaises(ValidationError):
            planner.validate_facts(self.p)

    def test_ledger_conflicts_reported_early_together(self):
        # Facts omitted from entry_state used to escape validation until planning.
        for i, shot in enumerate(self.p['shots']):
            for attr in ('test_position', 'test_wetness'):
                shot['facts'].append(dict(entity='girl', attribute=attr, value=i,
                    status='known', phase='static', critical=True,
                    source=dict(kind='script', ref='SIMULATED source conflict')))
        before = copy.deepcopy(self.p)
        result = self.errors()
        ledger = [r for r in result.errors if r['path'].endswith('.facts/state_changes')]
        self.assertEqual(len(ledger), 4)
        self.assertEqual(self.p, before)

    def test_shared_fact_state_key_and_inference_are_not_conflicts(self):
        # Template legitimately uses key.holder both as a fact and a state key.
        core.validate(self.p, self.template)
        for i, shot in enumerate(self.p['shots']):
            shot['facts'].append(dict(entity='girl', attribute='inferred_position', value=i,
                status='known', phase='static', critical=True,
                source=dict(kind='inference', ref='SIMULATED assumption')))
        core.validate(self.p, self.template)


if __name__ == '__main__':
    unittest.main()
