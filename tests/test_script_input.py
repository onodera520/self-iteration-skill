"""Raw-script extraction regressions; no visual review or generation."""
import copy
import io
from pathlib import Path
from unittest.mock import patch

import storyboard_fixtures as fixtures
import previs as core
import prepare_storyboards as batch
import script_input


class ScriptInputTests(fixtures.Base):
    def raw(self, separator='，', newline='\n'):
        return (f'原脚本标题{newline}'
                f'镜头1，【时长】3s{separator}【镜头设计】中景，固定。{newline}'
                f'【镜头内容】男孩站在门边。{newline}右手拿着钥匙。{newline}{newline}'
                f'镜头2，【时长】2.5秒{separator}【镜头设计】特写。{newline}'
                f'【镜头内容】女孩接住钥匙。{newline}')

    def test_duration_separators_and_multiline_content_preserve_original(self):
        for separator in ('，', ',', '。', '.', '；', ';', ' ', '\n', ''):
            source = self.raw(separator)
            with self.subTest(separator=separator):
                rows = script_input.parse(source)
                self.assertEqual([s['id'] for s in rows], ['S01', 'S02'])
                self.assertEqual([s['duration'] for s in rows], [3, 2.5])
                self.assertTrue(all(s['script'] in source for s in rows))
                self.assertIn('【镜头内容】男孩站在门边。\n右手拿着钥匙。', rows[0]['script'])

    def test_bom_crlf_and_image_order_survive_cli_extraction(self):
        script = self.path.parent / '脚本.txt'
        source = self.raw(newline='\r\n')
        script.write_bytes(b'\xef\xbb\xbf' + source.encode('utf-8'))
        manifest = self.path.parent / 'images.json'
        core.save(manifest, [self.png('first').name, self.png('second').name])
        output = self.path.parent / 'input.json'
        argv = ['prepare_storyboards.py', 'extract', str(script), '--images', str(manifest), '--output', str(output)]
        with patch('sys.argv', argv), patch('sys.stdout', new_callable=io.StringIO):
            batch.main()
        result = core.read(output)
        self.assertEqual(result['source_script'], source)
        self.assertIn('\r\n右手拿着钥匙。', result['shots'][0]['script'])
        self.assertEqual([s['image'] for s in result['shots']],
                         [str(self.path.parent / 'first.png'), str(self.path.parent / 'second.png')])
        self.assertEqual(script.read_bytes(), b'\xef\xbb\xbf' + source.encode('utf-8'))
        self.assertNotIn('requirements', result['shots'][0])
        self.assertNotIn('intent', result['shots'][0])
        with self.assertRaises(ValueError):
            batch.prepare(self.path.parent / 'draft-project.json', None, self.path.parent / 'draft-prep', input_data=result)
        self.assertFalse((self.path.parent / 'draft-project.json').exists())
        self.assertFalse((self.path.parent / 'draft-prep').exists())

    def test_missing_fields_are_collected_by_shot_and_line(self):
        bad = self.raw().replace('【镜头设计】', '【错误字段】')
        with self.assertRaises(ValueError) as caught:
            script_input.parse(bad, 'raw.txt')
        self.assertIn('raw.txt:镜头1（行2）', str(caught.exception))
        self.assertIn('raw.txt:镜头2（行6）', str(caught.exception))

    def test_number_errors_do_not_renumber_or_reorder(self):
        for number in ('0', '1', '3'):
            with self.subTest(number=number), self.assertRaisesRegex(ValueError, '镜号须'):
                script_input.parse(self.raw().replace('镜头2，', f'镜头{number}，'))
        self.assertEqual([s['id'] for s in script_input.parse(self.raw().replace('镜头2，', '镜头8，').replace('镜头1，', '镜头7，'))],
                         ['S07', 'S08'])

    def test_invalid_duration_or_empty_content_is_rejected(self):
        for value in ('0s', '-1s', 'infs', '3', '三秒'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                script_input.parse(self.raw().replace('3s', value))
        with self.assertRaisesRegex(ValueError, '字段内容不能为空'):
            script_input.parse('镜头1，【时长】1s。【镜头设计】特写。【镜头内容】\n')

    def test_image_count_and_order_errors_write_nothing(self):
        script = self.path.parent / 'raw.txt'
        script.write_text(self.raw(), encoding='utf-8')
        output = self.path.parent / 'input.json'
        first, second = str(self.png('first')), str(self.png('second'))
        for supplied in ([first], [first, second, first],
                         [dict(shot_id='S02', path=first), dict(shot_id='S01', path=second)]):
            before = copy.deepcopy(supplied)
            with self.subTest(supplied=supplied), self.assertRaises(ValueError):
                script_input.extract(script, supplied, output)
            self.assertFalse(output.exists())
            self.assertFalse(Path(str(output) + '.lock').exists())
            self.assertEqual(supplied, before)

    def test_existing_draft_is_preserved_and_shared_image_is_allowed(self):
        script = self.path.parent / 'raw.txt'
        script.write_text(self.raw(), encoding='utf-8')
        image = str(self.png('same'))
        output = self.path.parent / 'input.json'
        script_input.extract(script, [image, image], output)
        frozen = output.read_bytes()
        with self.assertRaisesRegex(ValueError, '不要覆盖'):
            script_input.extract(script, [image, image], output)
        self.assertEqual(output.read_bytes(), frozen)

    def test_cli_failure_stops_with_clear_message_and_no_outputs(self):
        output = self.path.parent / 'input.json'
        manifest = self.path.parent / 'images.json'
        core.save(manifest, [])
        argv = ['prepare_storyboards.py', 'extract', str(self.path.parent / 'missing.txt'),
                '--images', str(manifest), '--output', str(output)]
        with patch('sys.argv', argv), patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit) as caught:
                batch.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('extract 失败', stderr.getvalue())
        self.assertIn('不继续运行依赖其输出', stderr.getvalue())
        self.assertFalse(output.exists())
