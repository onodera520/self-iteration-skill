"""Offline source-bound compilation regressions; no generation-quality claims."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ai-storyboard-previs' / 'scripts'))
import previs as core
import repair_cycle
import repair_export
import repair_prompt
import repair_quality as quality


def fixture():
    # Different causal patterns: ordinary handoff, mechanical result, empty shot.
    blocks = [
        dict(shot_id='S01', generation_text='甲把钥匙递给乙，乙接住钥匙。',
             correction='接收者为乙。', design='双人近景', duration=1.0,
             keyframe_target=dict(phase='exit', description='乙持有钥匙。'),
             must_have=['乙持有钥匙'], must_not_have=['甲仍持有钥匙']),
        dict(shot_id='S02', generation_text='机械臂按下开关，指示灯变绿。',
             design='设备近景', duration=1.0,
             critical_changes=['指示灯颜色由红变绿'], input_prompt_guidance=['保持设备表面金属质感。']),
        dict(shot_id='S03', generation_text='空房间里窗帘轻动。', design='固定全景', duration=1.0),
    ]
    for block in blocks:
        block['text'] = block['generation_text']
    source = dict(prompt_version=5, prompt='bound source', blocks=blocks,
                  assets=[dict(id='A01', path='reference.png', sha256='asset-hash')],
                  asset_style=dict(assets=[dict(asset_id='A01', guidance='遵循金属表面质感。')]),
                  visual_adaptations={}, previs_directive=repair_cycle.PREVIS_DIRECTIVE,
                  format_requirements=[], aspect_ratio='16:9', duration_seconds=3.0)
    p = dict(assets=[dict(id='A01', description='金属设备参考图')])
    plan = quality.template(source)
    plan['preserves_story'] = True
    contents = [
        '甲把钥匙递给乙，乙接住钥匙；终态乙持有钥匙，甲已松手。',
        '机械臂按下开关，指示灯由红变绿；设备表面保持金属质感。',
        '空房间里窗帘轻动。',
    ]
    events = ['乙接住钥匙', '指示灯由红变绿', '窗帘轻动']
    for row, content, event in zip(plan['shots'], contents, events):
        row.update(content=content, key_event=event,
                   visibility_basis='原景别内直接看到关键动作及其对象。',
                   timing=dict(status='feasible', basis='短距离局部动作，无长等待或跨场移动。'))
        for record in row['coverage']:
            record.update(output_excerpt=content, basis='该来源的动作、对象、顺序与结果保留在整合正文或终态标签。')
    for item in plan['checks'].values():
        item.update(status='pass', reason='核对三镜：短距离交接、开关结果和空镜，人物与设备没有跨镜身份替换。')
    return p, source, plan


class CompilationTests(unittest.TestCase):
    def test_general_scenes_preserve_source_and_phase_scope(self):
        p, source, plan = fixture()
        before = copy.deepcopy(source)
        request = quality.compile_request(plan, source, p)
        delivered = repair_export.render_prompt(p, request)
        self.assertEqual(source, before)
        self.assertEqual([b['text'] for b in request['blocks']], [b['text'] for b in source['blocks']])
        self.assertIn('甲把钥匙递给乙，乙接住钥匙；终态乙持有钥匙，甲已松手。', delivered)
        self.assertNotIn('以下必须／不得出现仅约束', delivered)
        self.assertEqual(request['blocks'][0]['keyframe_target'], source['blocks'][0]['keyframe_target'])
        self.assertIn('【本镜必须出现】乙持有钥匙', delivered)
        self.assertIn('【本镜不得出现】甲仍持有钥匙', delivered)
        self.assertNotIn('接收者为乙。', delivered)
        self.assertNotIn('指示灯颜色由红变绿', delivered)
        self.assertEqual(delivered.count('甲把钥匙递给乙'), 1)
        self.assertEqual(delivered.count('【时长】'), 3)
        self.assertEqual(request['duration_seconds'], 3.0)
        self.assertEqual(request['prompt_version'], 6)
        self.assertEqual(request['prompt_plan'], plan)

    def test_all_keyframe_phases_and_static_counterexample(self):
        for phase in ('entry', 'action', 'exit'):
            p, source, plan = fixture()
            source['blocks'][0]['keyframe_target']['phase'] = phase
            plan['source_fingerprint'] = core.digest(source)
            request = quality.compile_request(plan, source, p)
            delivered = repair_export.render_prompt(p, request)
            self.assertNotIn('以下必须／不得出现仅约束', delivered)
            self.assertEqual(request['blocks'][0]['keyframe_target']['phase'], phase)
            self.assertIn(plan['shots'][0]['content'], delivered)
            self.assertIn('【本镜必须出现】乙持有钥匙', delivered)
            self.assertIn('【本镜不得出现】甲仍持有钥匙', delivered)
            # The empty-room shot must not acquire a person, handoff or invented phase.
            self.assertEqual(request['blocks'][2]['compiled_content'], '空房间里窗帘轻动。')

    def test_missing_plan_and_stale_source_rejected(self):
        p, source, plan = fixture()
        with self.assertRaises(ValueError):
            quality.compile_request(None, source, p)
        source['blocks'][0]['correction'] = '接收者与原文发生变化。'
        with self.assertRaisesRegex(ValueError, 'stale'):
            quality.compile_request(plan, source, p)

    def test_independent_defects_collected(self):
        p, source, plan = fixture()
        plan['shots'][0]['coverage'].pop()
        plan['shots'][0]['content'] += '甲说话。'
        plan['shots'][1]['timing']['status'] = 'blocked'
        plan['checks']['assets_and_style']['status'] = 'pending'
        plan['unresolved'] = ['源要求需要等待三秒，与一秒冲突。']
        with self.assertRaises(ValueError) as caught:
            quality.compile_request(plan, source, p)
        for term in ['speech/audio/text', 'coverage record', 'one-second', 'assets_and_style', 'conflicts']:
            self.assertIn(term, str(caught.exception))

    def test_omitted_reordered_or_duplicate_shots_rejected(self):
        for mode in ['omit', 'reverse', 'duplicate']:
            p, source, plan = fixture()
            if mode == 'omit':
                plan['shots'].pop()
            elif mode == 'reverse':
                plan['shots'].reverse()
            else:
                plan['shots'].append(copy.deepcopy(plan['shots'][0]))
            with self.assertRaisesRegex(ValueError, 'original order'):
                quality.compile_request(plan, source, p)

    def test_false_output_excerpt_and_scope_leak_rejected(self):
        p, source, plan = fixture()
        plan['shots'][0]['coverage'][0]['output_excerpt'] = '正文未出现的动作'
        plan['shots'][2]['content'] += '【镜头内容】第二段'
        with self.assertRaises(ValueError) as caught:
            quality.compile_request(plan, source, p)
        self.assertIn('exact excerpt', str(caught.exception))
        self.assertIn('extra headers', str(caught.exception))

    def test_delivery_and_internal_body_are_same(self):
        p, source, plan = fixture()
        request = quality.compile_request(plan, source, p)
        plain = repair_export.render_prompt(p, request).strip()
        expected = repair_prompt.SILENT_DIRECTIVE + '\n' + plain.replace('【时长】1s。', '【生成时长】1.0s。') + '\n' + repair_prompt.SILENT_DIRECTIVE
        self.assertEqual(request['prompt'], expected)
        repair_prompt.validate(request, ['S01', 'S02', 'S03'])

    def test_historical_snapshot_does_not_follow_current_plan(self):
        p, source, plan = fixture()
        snapshot = copy.deepcopy(plan)
        p['repair_prompt_plans'] = {'G01': dict(unresolved=['changed current draft'])}
        old_compose = repair_cycle._compose_prompt

        def compose(*args, **kwargs):
            if args[3] == 5:
                return copy.deepcopy(source)
            return old_compose(*args, **kwargs)

        with patch.object(repair_cycle, '_compose_prompt', side_effect=compose):
            restored = old_compose(p, 'unused.json', 'G01', 6, plan_snapshot=snapshot)
            self.assertEqual(restored['prompt_plan'], snapshot)
            with self.assertRaises(ValueError):
                old_compose(p, 'unused.json', 'G01', 6)


if __name__ == '__main__':
    unittest.main()
