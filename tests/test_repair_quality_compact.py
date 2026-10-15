"""Compact audit regressions: real gates, offline fixtures, no case export."""
import contextlib
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_repair_quality import fixture
import previs as core
import repair_cycle
import repair_export
import repair_quality as quality


def compact_fixture():
    p, source, detailed = fixture()
    source.update(decision_fingerprint='decision-fixture', binding={'review': 'fixture'})
    detailed['source_fingerprint'] = core.digest(source)
    plan = quality.compact_template(source)
    plan.update(preserves_story=True, checks_passed=True,
                reviewed_shot_ids=[b['shot_id'] for b in source['blocks']],
                edits=[dict(shot_id=row['shot_id'], content=row['content'])
                       for row in detailed['shots'][:2]],
                notes={'S01': '交接明确乙接住及甲松手，终态约束仍只作用于终态。',
                       'S02': '同一局部按键动作保留灯由红变绿和金属表面。'},
                checks={name: name + ': 三镜分别核对交接、设备状态及空镜。'
                        for name in quality.CHECKS})
    return p, source, detailed, plan


class CompactTests(unittest.TestCase):
    def test_grouped_plan_preserves_output_with_four_judgments_and_no_duplicate_notes(self):
        p, source, _, plan = compact_fixture()
        grouped = copy.deepcopy(plan)
        grouped.update(plan_version=3, notes={}, checks={name: 'SIMULATED resolved fixture ' + name
                                                       for name in quality.CHECK_GROUPS})
        self.assertEqual(repair_export.render_prompt(p, quality.compile_request(grouped, source, p)),
                         repair_export.render_prompt(p, quality.compile_request(plan, source, p)))
        for field in quality.CHECK_GROUPS:
            invalid = copy.deepcopy(grouped)
            invalid['checks'].pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                quality.compile_request(invalid, source, p)

    def test_reading_view_omits_header_only_differences_but_retains_actual_adaptations(self):
        p, source, _, _ = compact_fixture()
        for i, block in enumerate(source['blocks'], 1):
            block['text'] = f'镜头{i}，【时长】3s。【镜头设计】{block["design"]}。【镜头内容】{block["generation_text"]}'
        view = quality.reading_view(source, p)
        self.assertFalse(any('original_text' in b for b in view['blocks']))
        source['blocks'][0]['text'] += '甲说 {不要走。}'
        view = quality.reading_view(source, p)
        self.assertEqual(view['blocks'][0]['original_text'], source['blocks'][0]['generation_text']+'甲说 {不要走。}')
        self.assertNotIn('original_text', view['blocks'][1])

    def test_retains_unedited_source_and_same_delivery_as_detailed(self):
        p, source, detailed, plan = compact_fixture()
        before = copy.deepcopy(source)
        compiled = quality.compile_request(plan, source, p)
        legacy = quality.compile_request(detailed, source, p)
        self.assertEqual(repair_export.render_prompt(p, compiled),
                         repair_export.render_prompt(p, legacy))
        self.assertEqual(compiled['blocks'][2]['compiled_content'], source['blocks'][2]['generation_text'])
        self.assertEqual(source, before)
        for old, new in zip(source['blocks'], compiled['blocks']):
            for field in ('text', 'design', 'must_have', 'must_not_have', 'keyframe_target'):
                self.assertEqual(old.get(field), new.get(field))

    def test_no_edits_can_preserve_a_complete_source(self):
        p, source, _, plan = compact_fixture()
        for block in source['blocks']:
            for name in ('correction', 'keyframe_target', 'must_have', 'must_not_have',
                         'critical_changes', 'input_prompt_guidance'):
                block.pop(name, None)
        plan.update(source_fingerprint=core.digest(source), edits=[], notes={})
        self.assertEqual(quality.attention_shots(source), [])
        result = quality.compile_request(plan, source, p)
        self.assertEqual([b['compiled_content'] for b in result['blocks']],
                         [b['generation_text'] for b in source['blocks']])

    def test_notes_required_for_supplements_and_every_edit(self):
        p, source, _, plan = compact_fixture()
        self.assertEqual(quality.attention_shots(source), ['S01', 'S02'])
        plan['notes'].pop('S02')
        plan['edits'].append(dict(shot_id='S03', content='空房间里，窗帘轻动。'))
        with self.assertRaises(ValueError) as caught:
            quality.compile_request(plan, source, p)
        self.assertIn('S02, S03', str(caught.exception))

    def test_missing_reordered_duplicate_reviews_and_unknown_edits_rejected(self):
        for mode in ('omit', 'reverse', 'duplicate', 'unknown_edit', 'duplicate_edit'):
            p, source, _, plan = compact_fixture()
            if mode == 'omit':
                plan['reviewed_shot_ids'].pop()
            elif mode == 'reverse':
                plan['reviewed_shot_ids'].reverse()
            elif mode == 'duplicate':
                plan['reviewed_shot_ids'].append('S01')
            elif mode == 'unknown_edit':
                plan['edits'][0]['shot_id'] = 'S99'
            else:
                plan['edits'].append(copy.deepcopy(plan['edits'][0]))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                quality.compile_request(plan, source, p)

    def test_changed_source_and_unreviewed_template_rejected(self):
        p, source, _, plan = compact_fixture()
        with self.assertRaises(ValueError) as caught:
            quality.compile_request(quality.compact_template(source), source, p)
        for term in ('preserve the visible story', 'dialogue meaning is excluded',
                     'original order', 'story_coverage', 'resolution note'):
            self.assertIn(term, str(caught.exception))
        source['asset_style']['assets'][0]['guidance'] = '改为陶瓷表面。'
        with self.assertRaisesRegex(ValueError, 'stale'):
            quality.compile_request(plan, source, p)

    def test_conflicts_speech_headers_and_pending_checks_collect(self):
        p, source, _, plan = compact_fixture()
        plan['edits'][0]['content'] += '甲说话。【镜头内容】额外段'
        plan['checks']['timing_and_density'] = ''
        plan['unresolved'] = ['长等待无法兼容一秒。']
        with self.assertRaises(ValueError) as caught:
            quality.compile_request(plan, source, p)
        for term in ('speech/audio/text', 'extra headers', 'timing_and_density', 'conflicts'):
            self.assertIn(term, str(caught.exception))

    def test_malformed_compact_fields_rejected(self):
        for field, bad in [('plan_version', True), ('plan_version', 3), ('checks_passed', False), ('edits', [None]),
                           ('notes', []), ('notes', {'S99': '未知镜头'}),
                           ('checks', {}), ('model_risks', '不是列表')]:
            p, source, _, plan = compact_fixture()
            plan[field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                quality.compile_request(plan, source, p)

    def test_view_preserves_contributions_and_only_deduplicates_exact_text(self):
        p, source, _, _ = compact_fixture()
        block = source['blocks'][0]
        block['critical_changes'] = [block['correction']]
        block['input_prompt_guidance'] = ['接收者为乙，但保持侧面构图。']
        block['text'] = '原始脚本中含有需要视觉转换的独立信息。'
        source['asset_style']['assets'][0]['visible_style_facts'] = ['金属反光']
        source['visual_adaptations'] = {'asset.A01.description': {'visual_text': '设备的金属外壳'}}
        before = copy.deepcopy(source)
        view = quality.reading_view(source, p)
        self.assertEqual(view['source_fingerprint'], core.digest(source))
        self.assertEqual([b['shot_id'] for b in view['blocks']], ['S01', 'S02', 'S03'])
        for original, row in zip(source['blocks'], view['blocks']):
            reconstructed = {path: item['text'] for item in row['sources'] for path in item['paths']}
            self.assertEqual(reconstructed, quality.sources(original))
        self.assertEqual(len(view['blocks'][0]['sources']), len(quality.sources(block)) - 1)
        self.assertEqual(view['blocks'][0]['original_text'], block['text'])
        self.assertEqual(view['blocks'][0]['target_phase'], 'exit')
        self.assertEqual(view['assets'][0]['description'], '设备的金属外壳')
        self.assertEqual(view['asset_style'][0]['visible_style_facts'], ['金属反光'])
        self.assertNotIn('prompt', view)
        self.assertEqual(source, before)

    def test_compact_historical_snapshot_ignores_current_draft(self):
        p, source, _, plan = compact_fixture()
        p['repair_prompt_plans'] = {'G01': {'unresolved': ['新的未完成草稿']}}
        old_compose = repair_cycle._compose_prompt

        def compose(*args, **kwargs):
            if args[3] == 5:
                return copy.deepcopy(source)
            return old_compose(*args, **kwargs)

        with patch.object(repair_cycle, '_compose_prompt', side_effect=compose):
            restored = old_compose(p, 'unused.json', 'G01', 6, plan_snapshot=plan)
        self.assertEqual(restored['prompt_plan'], plan)

    def test_finish_rebuilds_once_and_exports_same_prompt(self):
        p, source, _, plan = compact_fixture()
        expected = repair_export.render_prompt(p, quality.compile_request(plan, source, p))
        with tempfile.TemporaryDirectory() as tmp:
            project, draft = Path(tmp) / 'PROJECT.json', Path(tmp) / 'plan.json'
            output = Path(tmp) / 'delivery' / 'prompt.md'
            core.save(project, p)
            core.save(draft, plan)
            argv = ['repair_quality.py', 'finish', str(project), 'G01', str(draft), '--output', str(output)]
            with patch.object(sys, 'argv', argv), patch.object(quality, 'source_request', return_value=source) as build:
                with contextlib.redirect_stdout(io.StringIO()):
                    quality.main()
                build.assert_called_once()
            saved = core.read(project)
            self.assertEqual(saved['repair_prompt_plans']['G01'], plan)
            self.assertEqual(output.read_text(encoding='utf-8'), expected)
            record = saved['repair_prompt_exports']['G01'][0]
            self.assertEqual(core.read(record['request_path'])['prompt_plan'], plan)
            self.assertNotIn('tasks', saved)
            self.assertFalse(Path(str(project) + '.lock').exists())

    def test_finish_failure_leaves_project_and_frozen_delivery_unchanged(self):
        for mode in ('stale', 'conflict', 'frozen', 'different_output'):
            p, source, _, plan = compact_fixture()
            with tempfile.TemporaryDirectory() as tmp:
                project, draft = Path(tmp) / 'PROJECT.json', Path(tmp) / 'plan.json'
                output = Path(tmp) / 'delivery' / 'prompt.md'
                if mode == 'stale':
                    plan['source_fingerprint'] = 'old'
                elif mode == 'conflict':
                    plan['unresolved'] = ['时长硬冲突']
                elif mode == 'frozen':
                    p['repair_deliveries'] = {'original': {'path': str(output.parent / 'report.md')}}
                else:
                    output.parent.mkdir()
                    output.write_text('已有交付不能被覆盖', encoding='utf-8')
                core.save(project, p)
                core.save(draft, plan)
                before = project.read_bytes()
                argv = ['repair_quality.py', 'finish', str(project), 'G01', str(draft), '--output', str(output)]
                with patch.object(sys, 'argv', argv), patch.object(quality, 'source_request', return_value=source):
                    with self.subTest(mode=mode), self.assertRaises(ValueError):
                        quality.main()
                self.assertEqual(project.read_bytes(), before)
                self.assertFalse((Path(tmp) / '.repair').exists())
                self.assertFalse(Path(str(project) + '.lock').exists())
                if mode == 'different_output':
                    self.assertEqual(output.read_text(encoding='utf-8'), '已有交付不能被覆盖')
                else:
                    self.assertFalse(output.exists())

    def test_prepare_defaults_to_unapproved_compact_view_without_project_mutation(self):
        p, source, _, _ = compact_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            project, draft = Path(tmp) / 'PROJECT.json', Path(tmp) / 'plan.json'
            core.save(project, p)
            before = project.read_bytes()
            argv = ['repair_quality.py', 'prepare', str(project), 'G01', str(draft)]
            with patch.object(sys, 'argv', argv), patch.object(quality, 'source_request', return_value=source):
                with contextlib.redirect_stdout(io.StringIO()):
                    quality.main()
            prepared = core.read(draft)
            self.assertEqual(prepared['plan_version'], 2)
            self.assertEqual(prepared['reviewed_shot_ids'], [])
            self.assertFalse(prepared['preserves_story'])
            self.assertFalse(prepared['checks_passed'])
            self.assertEqual(core.read(draft.with_suffix('.source.json')), source)
            self.assertEqual(core.read(draft.with_suffix('.view.json')), quality.reading_view(source, p))
            self.assertEqual(project.read_bytes(), before)
            self.assertFalse((Path(tmp) / '.repair').exists())

    def test_multiline_visual_body_is_preserved_in_rendered_form(self):
        p, source, _, plan = compact_fixture()
        source['blocks'][2]['generation_text'] = '空房间里，\n窗帘轻动。\n'
        source['blocks'][2]['text'] = source['blocks'][2]['generation_text']
        plan['source_fingerprint'] = core.digest(source)
        request = quality.compile_request(plan, source, p)
        self.assertEqual(request['blocks'][2]['compiled_content'], source['blocks'][2]['generation_text'])
        self.assertIn('空房间里， 窗帘轻动。', repair_export.render_prompt(p, request))


if __name__ == '__main__':
    unittest.main()
