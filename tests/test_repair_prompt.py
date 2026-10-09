"""Text-only regression examples; these cannot establish video-model compliance."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

import test_previs  # Adds the local scripts directory, as in the other regression tests.
import repair_prompt as prompt


class GenerationViewTests(unittest.TestCase):
    def view(self, raw, **fields):
        return prompt.generation_view(dict(id='S01', **fields), dict(text=raw, design='近景'), 1)

    def test_plain_content_and_explicit_body_marker_preserve_dialogue_and_action(self):
        body = '她说 {等3秒再走。}\n内心OS {别动！}，随后推门。'
        self.assertEqual(self.view(body)['generation_text'], body)
        self.assertEqual(self.view('【镜头内容】' + body)['generation_text'], body)

    def test_header_same_line_crlf_and_lf(self):
        for separator in ('', '\n', '\r\n'):
            with self.subTest(separator=separator):
                result = self.view('镜头1，【时长】2.5s，【镜头设计】近景。' + separator + '【镜头内容】他转身。')
                self.assertEqual(result, dict(generation_text='他转身。', design='近景'))

    def test_ambiguous_number_design_and_empty_content_block(self):
        cases = [
            ('镜头2，【时长】2s，【镜头设计】近景。【镜头内容】他转身。', {}),
            ('镜头1，【时长】2s，【镜头设计】近景。【镜头内容】他转身。', {'shot_design':'远景'}),
            ('镜头1，【时长】2s，【镜头设计】近景。【镜头内容】 ', {}),
            ('镜头1，【时长】2s，残缺头部，他转身。', {}),
            ('【镜头内容】他转身。【镜头内容】第二次重复。', {})]
        for raw, fields in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.view(raw, **fields)

    def test_full_rain_story_fixture_preserves_eight_bodies_and_source(self):
        project = json.loads((Path(__file__).parent/'fixtures/rain-chase-script.json').read_text(encoding='utf-8'))
        before = copy.deepcopy(project)
        for i, shot in enumerate(project['shots'], 1):
            original = dict(text=shot['script'], design=shot.get('shot_design') or shot.get('shot_size') or '未指定')
            view = prompt.generation_view(shot, original, i)
            self.assertEqual(view['generation_text'], shot['script'].split('【镜头内容】', 1)[1])
            self.assertNotIn('【时长】', view['generation_text'])
            self.assertNotIn('【镜头设计】', view['generation_text'])
        self.assertEqual(project, before)

    def test_header_and_phase_omissions_collected_together(self):
        shots = [dict(id='S01'), dict(id='S02')]
        originals = {s['id']:dict(text='【时长】3s 残缺头部', design='近景') for s in shots}
        requirements = {'S01':dict(ready=False, must_have=['手持钥匙'], keyframe={})}
        with self.assertRaises(ValueError) as caught:
            prompt.input_views(shots, originals, requirements, {'S01':1, 'S02':2})
        for text in ('S01:', 'S02:', 'provisional', 'phase'):
            self.assertIn(text, str(caught.exception))


class VisualOnlyTests(unittest.TestCase):
    @staticmethod
    def adaptation(source, visual='她皱眉，随后推门。'):
        return dict(source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(),
                    visual_text=visual, preserves_story=True, story_basis='原脚本已有皱眉与推门；通过这些动作承接剧情。')

    def test_visual_view_keeps_actions_without_rewriting_source(self):
        source = '她皱眉，开口问 {谁？}，随后推门。'
        row = self.adaptation(source)
        view = prompt.VisualOnly({'S01.generation_text': row})
        self.assertEqual(view.text('S01.generation_text', source), '她皱眉，随后推门。')
        view.finish()
        self.assertIn('开口问 {谁？}', source)
        self.assertEqual(view.used['S01.generation_text'], row)
        self.assertEqual(view.text('S01.design', '近景，等3秒后推近。'), '近景，等3秒后推近。')

    def test_missing_adaptations_report_every_dynamic_field(self):
        view = prompt.VisualOnly({})
        for path in ('S01.generation_text', 'S01.design', 'S01.correction', 'S01.must_have.0',
                     'S01.must_not_have.0', 'S01.keyframe_target.description', 'S01.critical_changes.0',
                     'asset.A01.description', 'asset.A01.guidance', 'format.0'):
            view.text(path, '她低语 {回来。}')
        with self.assertRaises(ValueError) as caught:
            view.finish()
        self.assertEqual(str(caught.exception).count('visual adaptation required'), 10)

    def test_stale_empty_risky_or_ungrounded_adaptation_rejected(self):
        source = '她开口问 {谁？}，随后推门。'
        for changes in (dict(source_sha256='0'*64), dict(visual_text=''),
                        dict(visual_text='她说 {别动。}'), dict(visual_text='内心OS：别动'),
                        dict(visual_text='响起雨声'), dict(story_basis=''), dict(preserves_story=False)):
            with self.subTest(changes=changes):
                row = dict(self.adaptation(source), **changes)
                view = prompt.VisualOnly({'S01.generation_text': row})
                view.text('S01.generation_text', source)
                with self.assertRaises(ValueError):
                    view.finish()

    def test_visual_source_cannot_be_rewritten_and_prohibitions_are_not_speech(self):
        source = '他转身，望向写有“入口”的木牌。'
        view = prompt.VisualOnly({'S01.generation_text': self.adaptation(source)})
        self.assertEqual(view.text('S01.generation_text', source), source)
        with self.assertRaisesRegex(ValueError, 'must remain unchanged'):
            view.finish()
        self.assertEqual(prompt.speech_signals('没有台词，没有音乐，不要出现字幕。'), [])
        self.assertEqual(prompt.speech_signals(source), [])
        for text in ('她说“别走”', '他开口', '内心OS {等3秒。}', '他对她说：别走', 'voiceover: hello'):
            self.assertTrue(prompt.speech_signals(text), text)


if __name__ == '__main__':
    unittest.main()
