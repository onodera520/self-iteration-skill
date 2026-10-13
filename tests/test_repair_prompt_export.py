"""Text-only delivery contracts; simulated judgments are not visual acceptance."""
import copy
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
import unittest

import test_previs as fixtures
import test_repair_cycle as repair_fixtures
import previs as core
import repair_cycle as repair
import repair_export
import repair_prompt
import finish_review


class PromptExportTests(fixtures.Base):
    setUp = repair_fixtures.RepairCycleTests.setUp
    png = repair_fixtures.RepairCycleTests.png
    select_mapping = repair_fixtures.RepairCycleTests.select_mapping
    mapping = repair_fixtures.RepairCycleTests.mapping
    review_data = repair_fixtures.RepairCycleTests.review_data
    assessment = repair_fixtures.RepairCycleTests.assessment
    finish = repair_fixtures.RepairCycleTests.finish
    ready = repair_fixtures.RepairCycleTests.ready

    def export(self, name='prompts/G01_新视频提示词.md'):
        return repair_export.export_prompt(self.p, self.path, 'G01', self.path.parent / name)

    def test_complete_prompt_assets_and_parameters_without_paid_calls(self):
        self.ready()
        before = copy.deepcopy(self.p)
        expected = repair.make_prompt(self.p, self.path, 'G01')
        with patch.object(repair, 'prepare', side_effect=AssertionError('No paid preflight')), \
             patch.object(repair, 'submit', side_effect=AssertionError('No submission')), \
             patch('workflow_tasks.FixedWorkflow', side_effect=AssertionError('No workflow client')):
            record = self.export()
        text = Path(record['path']).read_text(encoding='utf-8')
        self.assertEqual(text, repair_export.render_prompt(self.p, expected))
        self.assertTrue(text.startswith('图1是'))
        self.assertIn('以下内容是具体的分镜脚本：', text)
        self.assertIn('画幅以输入视频的 16:9 为准', text)
        self.assertIn(repair_prompt.SILENT_DIRECTIVE, text)
        self.assertEqual([b['shot_id'] for b in expected['blocks']], ['S01', 'S02', 'S03'])
        positions = [text.index(f'镜头{i},【时长】1s。') for i in range(1, 4)]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count('【镜头设计】'), 3)
        self.assertEqual(text.count('【镜头内容】'), 3)
        for block in expected['blocks']:
            self.assertIn(block['generation_text'], text)
            if block.get('correction'):
                self.assertIn(block['correction'], text)
        for extra in ('# G01', '```', '[原资产图]', '【必要漏镜补齐】',
                      '【仅本镜返修补充】', '【原提示词参考】', '【生成时长】'):
            self.assertNotIn(extra, text)
        for asset in expected['assets']:
            self.assertNotIn(asset['path'], text)
        self.assertEqual(core.read(record['request_path']), expected)
        self.assertEqual(record['sha256'], core.sha(Path(record['path'])))
        self.assertEqual(record['decision_fingerprint'], self.p['repair_decisions']['G01']['fingerprint'])
        actual = copy.deepcopy(self.p)
        actual.pop('repair_prompt_exports')
        self.assertEqual(actual, before)

    def test_layout_preserves_actions_and_phase_scoped_constraints(self):
        self.ready()
        request = repair.make_prompt(self.p, self.path, 'G01')
        block = request['blocks'][1]
        # Historical version-5 renderer only: retain the stored text exactly.
        # New prompts must pass the version-6 timing/conflict audit first.
        body = '人物停3秒再走，保持钥匙在右手，沿走廊走到门口后停住。'
        block.update(generation_text=body, correction='交接结果为乙持有钥匙。',
                     input_prompt_guidance=['冷光照亮门框。'],
                     critical_changes=['key.holder 由 甲 变为 乙'],
                     keyframe_target={'phase': 'exit', 'description': '乙持钥匙'},
                     must_have=['乙持钥匙'], must_not_have=['甲持钥匙'])
        text = repair_export.render_prompt(self.p, request)
        middle = text.split('镜头2,')[1].split('镜头3,')[0]
        for expected in (body, '交接结果为乙持有钥匙', '冷光照亮门框',
                         'key.holder 由 甲 变为 乙', '终态画面：乙持钥匙',
                         '【本镜必须出现】乙持钥匙',
                         '【本镜不得出现】甲持钥匙'):
            self.assertIn(expected, middle)
        self.assertNotIn('以下必须／不得出现仅约束', text)
        self.assertEqual(block['keyframe_target'], {'phase': 'exit', 'description': '乙持钥匙'})
        self.assertNotIn('交接结果为乙持有钥匙', text.split('镜头2,')[0])
        self.assertNotIn('照片级写实', text)
        self.assertIn('SIMULATED asset style', text)

    def test_zero_allowance_budget_and_provider_limits_do_not_block_text(self):
        self.ready()
        self.p['config'].update(max_submissions=0, budget_cny=0,
                                fixed_workflow_limits={'max_duration_seconds': 1})
        with patch.dict('os.environ', {}, clear=True):
            record = self.export()
        self.assertTrue(Path(record['path']).is_file())
        self.assertEqual(self.p['config']['max_submissions'], 0)
        with self.assertRaisesRegex(ValueError, 'workflow duration'):
            repair.prepare(self.p, self.path, 'G01')

    def test_unknown_paid_task_keeps_state_and_allowance(self):
        self.ready()
        repair.snapshot(self.p, self.path, self.path.parent / 'original', 'original')
        api = repair_fixtures.FakeWorkflow()
        api.create_error = True
        repair.submit(self.p, self.path, 'G01', api, True)
        self.assertEqual(api.submissions, 1)
        self.assertTrue(any(t['status'] == 'submission_unknown' for t in self.p['tasks'].values()))
        tasks, decision, config = (copy.deepcopy(self.p[k]) for k in ('tasks', 'repair_decisions', 'config'))
        with patch.object(repair, 'resume', side_effect=AssertionError('No implicit recovery')):
            self.export()
        self.assertEqual(self.p['tasks'], tasks)
        self.assertEqual(self.p['repair_decisions'], decision)
        self.assertEqual(self.p['config'], config)
        self.assertEqual(api.submissions, 1)
        self.assertEqual(api.queries, 0)

    def test_below_threshold_does_not_create_prompt(self):
        self.ready({'S02': 'FAIL'}, critical=False)
        with self.assertRaisesRegex(ValueError, 'threshold not reached'):
            self.export()
        self.assertFalse((self.path.parent / 'prompts').exists())
        self.assertNotIn('repair_prompt_exports', self.p)

    def test_stale_source_or_asset_evidence_blocks_export(self):
        for kind in ('video', 'asset', 'script'):
            with self.subTest(kind=kind):
                self.ready()
                if kind == 'script':
                    self.p['source_script'] += ' CHANGED'
                    restore = lambda: None
                else:
                    target = (Path(self.p['imported_videos'][-1]['outputs'][0]) if kind == 'video'
                              else Path(self.p['assets'][0]['path']))
                    old = target.read_bytes()
                    target.write_bytes(b'CHANGED')
                    restore = lambda: target.write_bytes(old)
                try:
                    with self.assertRaises(ValueError):
                        self.export()
                    self.assertFalse((self.path.parent / 'prompts').exists())
                finally:
                    restore()

    def test_missing_asset_style_is_not_silently_filled(self):
        self.ready()
        del self.p['repair_asset_style']
        repair.decide(self.p, self.path, 'G01')
        with self.assertRaisesRegex(ValueError, 'Asset style'):
            self.export()
        self.assertFalse((self.path.parent / 'prompts').exists())

    def test_idempotent_and_immutable_exports_outside_frozen_deliveries(self):
        self.ready()
        frozen = Path(repair.snapshot(self.p, self.path, self.path.parent / 'original', 'original'))
        record = self.export()
        first = Path(record['path']).read_bytes()
        self.assertEqual(self.export(), record)
        self.assertEqual(len(self.p['repair_prompt_exports']['G01']), 1)
        self.assertEqual(Path(record['path']).read_bytes(), first)
        with self.assertRaisesRegex(ValueError, 'outside frozen deliveries'):
            repair_export.export_prompt(self.p, self.path, 'G01', frozen.parent / 'prompt.md')
        self.assertFalse((frozen.parent / 'prompt.md').exists())
        self.p['repair_delivery_history'] = [{'record': self.p['repair_deliveries'].pop('original')}]
        with self.assertRaisesRegex(ValueError, 'outside frozen deliveries'):
            repair_export.export_prompt(self.p, self.path, 'G01', frozen.parent / 'nested/prompt.md')
        Path(record['path']).write_text('Do not overwrite', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'different content'):
            self.export()
        self.assertEqual(Path(record['path']).read_text(encoding='utf-8'), 'Do not overwrite')
        second = self.export('prompts-v2/G01_新视频提示词.md')
        self.assertEqual(Path(second['path']).read_bytes(), first)

    def test_cli_persists_export_without_creating_paid_tasks(self):
        self.ready()
        core.save(self.path, self.p)
        output = self.path.parent / 'prompts/G01_新视频提示词.md'
        argv = ['repair_cycle.py', 'export-prompt', str(self.path), 'G01', '--output', str(output)]
        stream = io.StringIO()
        with patch.object(sys, 'argv', argv), redirect_stdout(stream), \
             patch('workflow_tasks.FixedWorkflow', side_effect=AssertionError('No workflow client')):
            repair.main()
        actual = core.read(self.path)
        self.assertEqual(stream.getvalue().strip(), str(output.resolve()))
        self.assertEqual(actual['tasks'], self.p['tasks'])
        self.assertEqual(actual['repair_decisions'], self.p['repair_decisions'])
        self.assertEqual(actual['repair_prompt_exports']['G01'][0]['sha256'], core.sha(output))

    def test_finish_threshold_delivers_original_report_then_requests_text_only(self):
        self.ready()
        core.save(self.path, self.p)
        with patch.object(repair, 'submit', side_effect=AssertionError('No paid submission')), \
             patch('workflow_tasks.FixedWorkflow', side_effect=AssertionError('No workflow client')):
            result = finish_review.finish(self.path, {}, self.path.parent / 'original', self.path.parent / 'run')
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['decisions']['G01']['decision']['triggered'])
        self.assertIn('export-prompt', result['next_action'])
        self.assertIn('Do not submit or generate a video', result['next_action'])
        self.assertEqual(result['validation']['table_count'], 1)
        current = core.read(self.path)
        self.assertEqual(current['tasks'], self.p['tasks'])
        self.assertNotIn('repaired', current['repair_deliveries'])
        self.assertNotIn('repair_prompt_exports', current)
        self.p = current
        self.export()
        finish_review.intact(current['repair_deliveries']['original'])


if __name__ == '__main__':
    unittest.main()
