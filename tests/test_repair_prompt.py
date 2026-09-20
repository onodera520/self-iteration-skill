"""Text-only regression examples; these cannot establish video-model compliance."""
import copy
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


if __name__ == '__main__':
    unittest.main()
