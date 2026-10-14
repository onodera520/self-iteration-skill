"""Fast first-look entry and verified reuse; visual judgments are simulated."""
import io
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import storyboard_fixtures as fixtures
import test_storyboard_images as existing
import previs as core
import script_input
import storyboard_inputs as images
import storyboard_overviews as overviews
import prepare_storyboards as batch


class InitialOverviewTests(fixtures.Base):
    review = existing.StoryboardImagesTests.review
    worklist = existing.StoryboardImagesTests.worklist
    compact_input = existing.StoryboardImagesTests.compact_input

    def setUp(self):
        existing.StoryboardImagesTests.setUp(self)

    def raw(self, count=14):
        script = self.path.parent / 'raw.txt'
        script.write_text('\n'.join(f'镜头{i}，【时长】1s。【镜头设计】中景。'
                                   f'【镜头内容】男孩站在门边，第{i}镜。' for i in range(1, count + 1)),
                          encoding='utf-8')
        supplied = [self.png(str(i), (i * 10, 20, 30)).name for i in range(1, count + 1)]
        return script, supplied

    def initial(self, name='initial'):
        return overviews.build_initial(self.compact_input(), self.path.parent / name)

    def test_cli_outputs_first_sheets_without_semantic_preparation(self):
        script, supplied = self.raw()
        mapping = self.path.parent / 'images.json'
        core.save(mapping, supplied)
        output = self.path.parent / 'first-look'
        delivery = self.path.parent / 'case'
        argv = ['prepare_storyboards.py', 'overview', str(script), '--images', str(mapping),
                '--output', str(output), '--delivery', str(delivery)]
        with patch('sys.argv', argv), patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                patch.object(batch, 'prepare', side_effect=AssertionError('No semantic preparation')), \
                patch.object(script_input, 'extract', side_effect=AssertionError('Do not change extract contract')):
            batch.main()
        result = json.loads(stdout.getvalue())
        self.assertFalse(delivery.exists())
        self.assertEqual(result['status'], 'unreviewed')
        self.assertEqual([p['shot_ids'] for p in result['pages']],
                         [[f'S{i:02d}' for i in range(1, 10)], [f'S{i:02d}' for i in range(10, 15)]])
        draft = core.read(result['input_draft'])
        self.assertNotIn('requirements', draft['shots'][0])
        self.assertNotIn('reviews', draft)
        self.assertNotIn('initial_overviews', draft)
        manifest = core.read(result['manifest']['path'])
        for page in manifest['pages']:
            with Image.open(page['path']) as picture:
                for tile in page['tiles']:
                    left, top, right, bottom = tile['image_rect']
                    self.assertEqual(picture.getpixel(((left + right) // 2, (top + bottom) // 2)),
                                     (int(tile['shot_id'][1:]) * 10, 20, 30))
            view = core.read(page['view']['path'])
            self.assertEqual([s['script'] for s in view['shots']],
                             [s['script'] for s in draft['shots'] if s['id'] in page['shot_ids']])

    def test_overview_rejects_internal_directory_inside_public_case_before_reading(self):
        delivery = self.path.parent / 'case'
        for output in (delivery, delivery / 'internal', self.path.parent):
            argv = ['prepare_storyboards.py', 'overview', 'unused.txt', '--images', 'unused.json',
                    '--output', str(output), '--delivery', str(delivery)]
            with self.subTest(output=output), patch('sys.argv', argv), \
                    patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                    patch.object(overviews, 'overview') as build, self.assertRaises(SystemExit) as caught:
                batch.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn('独立目录', stderr.getvalue())
            build.assert_not_called()
            self.assertFalse(delivery.exists())

    def test_overview_rejects_nonempty_delivery_before_first_look(self):
        delivery = self.path.parent / 'existing-case'
        delivery.mkdir()
        original = delivery / '01_分镜图审查.md'
        original.write_bytes(b'frozen')
        argv = ['prepare_storyboards.py', 'overview', 'unused.txt', '--images', 'unused.json',
                '--output', str(self.path.parent / 'first'), '--delivery', str(delivery)]
        with patch('sys.argv', argv), patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                patch.object(overviews, 'overview') as build, self.assertRaises(SystemExit) as caught:
            batch.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertIn('不覆盖', stderr.getvalue())
        build.assert_not_called()
        self.assertEqual(original.read_bytes(), b'frozen')
        self.assertFalse((self.path.parent / 'first').exists())

    def test_extract_keeps_no_decode_contract_and_existing_input_is_preserved(self):
        script, supplied = self.raw(1)
        image = self.path.parent / supplied[0]
        image.write_bytes(b'not an image')
        output = self.path.parent / 'INPUT.json'
        script_input.extract(script, supplied, output, image_base=self.path.parent)
        original = output.read_bytes()
        with self.assertRaises(OSError):
            overviews.overview(script, supplied, self.path.parent / 'bad', image_base=self.path.parent)
        self.assertEqual(output.read_bytes(), original)
        self.assertFalse((self.path.parent / 'bad').exists())

    def test_input_count_or_order_failure_creates_no_directory(self):
        script, supplied = self.raw(2)
        for bad in (supplied[:1], [dict(shot_id='S02', path=supplied[0]), dict(shot_id='S01', path=supplied[1])]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                overviews.overview(script, bad, self.path.parent / 'bad', image_base=self.path.parent)
            self.assertFalse((self.path.parent / 'bad').exists())

    def test_prepare_reuses_sheets_and_generates_current_formal_packets(self):
        initial = self.initial()
        before = [Path(p['path']).read_bytes() for p in initial['pages']]
        project = self.path.parent / 'new-project.json'
        with patch.object(overviews, '_pages', side_effect=AssertionError('Do not render storyboard sheets twice')):
            result = batch.prepare(project, None, self.path.parent / 'prepare', input_data=self.compact_input(),
                                   reuse_overviews=Path(initial['manifest']['path']).parent)
        self.assertTrue(result['review_overviews']['initial_reuse']['reused'])
        self.assertEqual([p['path'] for p in result['review_overviews']['pages']], [p['path'] for p in initial['pages']])
        self.assertEqual(before, [Path(p['path']).read_bytes() for p in initial['pages']])
        ctx = core.read(result['context'])
        packet = core.read(result['review_overviews']['review_batches'][0]['path'])
        self.assertTrue(packet['assets'])
        self.assertTrue(packet['shots'][0]['requirements'])
        self.assertNotIn('initial_overviews', core.read(project))
        overviews.validate(ctx, result['review_overviews']['manifest'])
        with self.assertRaisesRegex(ValueError, '新的内部工作目录'):
            batch.prepare(project, None, self.path.parent / 'prepare', reuse_overviews=initial['manifest'])

    def test_changed_initial_material_is_rebuilt_instead_of_reused(self):
        for kind in ('source', 'shot_script', 'image', 'order', 'sheet', 'view', 'manifest', 'missing'):
            with self.subTest(kind=kind):
                initial = self.initial('initial-' + kind)
                ctx = images.context(self.p, self.path, 'G01')
                source = self.p['source_script']
                receipt = core.read(initial['manifest']['path'])
                if kind == 'source':
                    source += '\n新脚本'
                elif kind == 'shot_script':
                    ctx['shots'][0]['script'] += ' changed'
                elif kind == 'image':
                    ctx['shots'][0]['image']['path'] = str(self.png('replacement', (255, 0, 0)))
                    ctx['shots'][0]['image']['sha256'] = core.sha(ctx['shots'][0]['image']['path'])
                elif kind == 'order':
                    ctx['shots'][:2] = reversed(ctx['shots'][:2])
                elif kind == 'sheet':
                    Image.new('RGB', overviews.PAGE, 'black').save(initial['pages'][0]['path'])
                elif kind == 'view':
                    core.save(receipt['pages'][0]['view']['path'], dict(status='PASS'))
                elif kind == 'manifest':
                    receipt['source_script_fingerprint'] = 'changed'
                    core.save(initial['manifest']['path'], receipt)
                else:
                    initial['manifest']['path'] = str(self.path.parent / 'missing.json')
                run = self.path.parent / ('prepare-' + kind)
                run.mkdir()
                result = overviews.build(ctx, run, self.path, initial=initial['manifest'], source_script=source)
                self.assertFalse(result['initial_reuse']['reused'])
                self.assertTrue(Path(result['pages'][0]['path']).is_relative_to(run))
                overviews.validate(ctx, result['manifest'])

    def test_semantic_changes_use_fresh_packets_without_rerendering_images(self):
        initial = self.initial()
        ctx = images.context(self.p, self.path, 'G01')
        ctx['shots'][0]['requirements']['must_have'].append('SIMULATED new explicit requirement')
        run = self.path.parent / 'prepare'
        run.mkdir()
        with patch.object(overviews, '_pages', side_effect=AssertionError('No image changes')):
            result = overviews.build(ctx, run, self.path, initial=initial['manifest'], source_script=self.p['source_script'])
        packet = core.read(result['review_batches'][0]['path'])
        self.assertIn('SIMULATED new explicit requirement', packet['shots'][0]['requirements']['must_have'])
        overviews.validate(ctx, result['manifest'])

    def test_inflight_source_changes_do_not_publish_an_input_draft(self):
        script, supplied = self.raw(1)
        build = overviews.build_initial
        def change_source(*args):
            result = build(*args)
            script.write_text(script.read_text(encoding='utf-8') + '\nchanged', encoding='utf-8')
            return result
        output = self.path.parent / 'first-look'
        with patch.object(overviews, 'build_initial', side_effect=change_source), self.assertRaisesRegex(ValueError, 'Evidence changed'):
            overviews.overview(script, supplied, output, image_base=self.path.parent)
        self.assertFalse((output / 'INPUT.draft.json').exists())

    def test_reused_pages_complete_freeze_and_tampering_blocks_resume(self):
        initial = self.initial()
        result = batch.prepare(self.path, None, self.path.parent / 'prepare', reuse_overviews=initial['manifest']['path'])
        self.p = core.read(self.path)
        work = self.worklist(self.review())
        work['overview_manifest'] = core.read(result['worklist'])['overview_manifest']
        core.save(result['worklist'], work)
        finished = batch.complete(self.path, result['worklist'], self.path.parent / 'delivery', self.path.parent / 'finish')
        self.assertEqual(finished['status'], 'complete')
        report = self.path.parent / 'delivery/01_分镜图审查.md'
        original = report.read_bytes()
        Image.new('RGB', overviews.PAGE, 'black').save(initial['pages'][0]['path'])
        with self.assertRaisesRegex(ValueError, '总览图已变化'):
            batch.resume(self.path, self.path.parent / 'prepare')
        self.assertEqual(report.read_bytes(), original)
