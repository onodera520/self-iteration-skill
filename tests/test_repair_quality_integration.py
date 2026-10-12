"""Current prompt flow with project/evidence bindings; all judgments are simulated.

No real media review, generation, network calls or paid submissions occur here.
"""
import copy
import io
from contextlib import redirect_stdout
from pathlib import Path
import sys
from unittest.mock import patch

import test_previs as fixtures
import test_repair_cycle as lifecycle
import previs as core
import repair_cycle as repair
import repair_export
import repair_prompt
import repair_quality as quality


class PromptQualityIntegrationTests(fixtures.Base):
    prompt_version = 6
    setUp = lifecycle.RepairCycleTests.setUp
    png = lifecycle.RepairCycleTests.png
    select_mapping = lifecycle.RepairCycleTests.select_mapping
    mapping = lifecycle.RepairCycleTests.mapping
    review_data = lifecycle.RepairCycleTests.review_data
    assessment = lifecycle.RepairCycleTests.assessment
    finish = lifecycle.RepairCycleTests.finish
    ready = lifecycle.RepairCycleTests.ready

    def simulated_plan(self):
        source = quality.source_request(self.p, self.path, 'G01')
        plan = quality.compact_template(source)
        plan.update(preserves_story=True, checks_passed=True,
                    reviewed_shot_ids=[b['shot_id'] for b in source['blocks']],
                    checks={name: 'SIMULATED fixture judgment for ' + name
                            for name in quality.CHECKS})
        # Offline compilation fixture: explicitly retain every independent input
        # contribution. This tests bindings and export, not prose quality.
        for block in source['blocks']:
            if block['shot_id'] in quality.attention_shots(source):
                content = '。'.join(dict.fromkeys(quality.sources(block).values()))
                plan['edits'].append(dict(shot_id=block['shot_id'], content=content))
                plan['notes'][block['shot_id']] = 'SIMULATED: each source contribution retained for this fixture.'
        return plan

    def register_simulated_plan(self):
        self.p['repair_prompt_plans'] = {'G01': self.simulated_plan()}

    def cli(self, *args):
        with patch.object(sys, 'argv', ['repair_quality.py', *map(str, args)]), redirect_stdout(io.StringIO()):
            quality.main()

    def test_current_export_rejects_missing_or_unreviewed_plan_without_mutation(self):
        self.ready()
        output = self.path.parent / 'prompt/G01.md'
        before = copy.deepcopy(self.p)
        with self.assertRaisesRegex(ValueError, 'source-bound'):
            repair_export.export_prompt(self.p, self.path, 'G01', output)
        self.assertEqual(self.p, before)
        self.p['repair_prompt_plans'] = {'G01': quality.compact_template(
            quality.source_request(self.p, self.path, 'G01'))}
        with self.assertRaises(ValueError):
            repair_export.export_prompt(self.p, self.path, 'G01', output)
        self.assertFalse(output.parent.exists())
        self.assertNotIn('repair_prompt_exports', self.p)

    def test_prepare_and_finish_cli_bind_current_evidence_and_export_without_paid_calls(self):
        self.ready()
        repair.snapshot(self.p, self.path, self.path.parent / 'original', 'original')
        frozen = {f: core.sha(Path(f)) for f in self.p['repair_deliveries']['original']['files']}
        core.save(self.path, self.p)
        self.p = core.read(self.path)  # Compare the same JSON-normalized representation.
        plan_file = self.path.parent / 'internal/plan.json'
        output = self.path.parent / 'prompt/G01.md'
        with patch.object(repair, 'submit', side_effect=AssertionError('No paid submission')), \
             patch('workflow_tasks.FixedWorkflow', side_effect=AssertionError('No workflow client')):
            self.cli('prepare', self.path, 'G01', plan_file)
            self.assertFalse(core.read(plan_file)['checks_passed'])
            self.assertEqual(core.read(self.path), self.p)
            self.assertEqual(core.read(plan_file.with_name('plan.source.json')),
                             quality.source_request(self.p, self.path, 'G01'))
            plan = self.simulated_plan()
            core.save(plan_file, plan)
            self.cli('finish', self.path, 'G01', plan_file, '--output', output)
        current = core.read(self.path)
        self.assertEqual(current['repair_prompt_plans']['G01'], plan)
        record = current['repair_prompt_exports']['G01'][0]
        request = core.read(record['request_path'])
        self.assertEqual(request['prompt_version'], 6)
        self.assertEqual(request, repair.make_prompt(current, self.path, 'G01'))
        self.assertEqual(output.read_text(encoding='utf-8'), repair_export.render_prompt(current, request))
        self.assertEqual(current['tasks'], self.p['tasks'])
        self.assertEqual(frozen, {f: core.sha(Path(f)) for f in frozen})
        self.assertEqual(repair_export.export_prompt(current, self.path, 'G01', output), record)

    def test_changed_source_requires_new_plan_and_never_rewrites_delivery(self):
        self.ready()
        self.register_simulated_plan()
        output = self.path.parent / 'prompt/G01.md'
        record = repair_export.export_prompt(self.p, self.path, 'G01', output)
        old = output.read_bytes()
        self.p['repair_asset_style']['assets'][0]['guidance'] += ' CHANGED STYLE'
        repair.decide(self.p, self.path, 'G01')
        with self.assertRaisesRegex(ValueError, 'stale'):
            repair_export.export_prompt(self.p, self.path, 'G01', output)
        self.assertEqual(output.read_bytes(), old)
        self.assertEqual(self.p['repair_prompt_exports']['G01'], [record])

    def test_current_task_recovers_using_frozen_plan_without_resubmission(self):
        self.ready()
        self.register_simulated_plan()
        repair.snapshot(self.p, self.path, self.path.parent / 'original', 'original')
        api = lifecycle.FakeWorkflow()
        self.assertEqual(repair.submit(self.p, self.path, 'G01', api, True), 'QUEUED')
        key = next(k for k, task in self.p['tasks'].items() if task.get('repair_source_group'))
        task = self.p['tasks'][key]
        stored = copy.deepcopy(task['request'])
        self.p['repair_prompt_plans']['G01'] = {'unresolved': ['New unfinished draft']}
        repair.validate_stored_request(self.p, self.path, task)
        self.assertEqual(repair.resume(self.p, self.path, key, api), 'SUCCESS')
        self.assertEqual(task['request'], stored)
        self.assertEqual(api.submissions, 1)
        with patch('media.probe', return_value={'streams': [{'codec_type': 'video'}]}), \
             patch('media.duration', return_value=6):
            repair.install(self.p, self.path, key)
        self.assertIsNone(core.review_current(self.p, self.path, 'G01'))

    def test_version_five_task_recovers_under_current_default_without_new_plan(self):
        self.ready()
        repair.snapshot(self.p, self.path, self.path.parent / 'original', 'original')
        api = lifecycle.FakeWorkflow()
        with patch.object(repair_prompt, 'VERSION', 5):
            self.assertEqual(repair.submit(self.p, self.path, 'G01', api, True), 'QUEUED')
        key = next(k for k, task in self.p['tasks'].items() if task.get('repair_source_group'))
        self.assertEqual(repair_prompt.VERSION, 6)
        self.assertEqual(self.p['tasks'][key]['request']['prompt_version'], 5)
        self.assertNotIn('repair_prompt_plans', self.p)
        self.assertEqual(repair.resume(self.p, self.path, key, api), 'SUCCESS')
        self.assertEqual(api.submissions, 1)
