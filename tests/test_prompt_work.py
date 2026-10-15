"""Single-submission regressions with simulated judgments and real image files."""
import contextlib
import copy
import io
import os
from pathlib import Path
from unittest.mock import patch

import storyboard_fixtures as fixtures
import test_storyboard_images as image_fixtures
import previs as core
import prepare_storyboards as batch
import prompt_work
import repair_export
import repair_quality as quality
import finish_review
from PIL import Image


class PromptWorkTests(fixtures.Base):
    setUp = image_fixtures.StoryboardImagesTests.setUp
    review = image_fixtures.StoryboardImagesTests.review
    worklist = image_fixtures.StoryboardImagesTests.worklist
    ready = image_fixtures.StoryboardImagesTests.ready

    def complete(self, missing=False):
        if missing:
            self.p.pop('repair_asset_style')
            self.p['shots'][0]['script'] += '女孩说 {镇上仓库今晚倒塌。}'
            self.p['source_script'] = '\n'.join(s['script'] for s in self.p['shots'])
            self.p.pop('repair_baseline', None)
            Image.new('RGB', (90,160), 'green').save(self.p['storyboard_images'][0]['path'])
        core.save(self.path, self.p)
        prep = batch.prepare(self.path, None, self.path.parent/'prepare',
                             original_prompt='SIMULATED old lighting' if missing else None)
        self.p = core.read(self.path)
        core.save(prep['worklist'], self.worklist(self.review(fails=['S02'], critical=True)))
        result = batch.complete(self.path, prep['worklist'], self.path.parent/'case', self.path.parent/'finish')
        self.p = core.read(self.path)
        return result

    def filled(self, result):
        work, view = core.read(result['prompt_work']), core.read(result['prompt_work_view'])
        prep = work['preparation']
        for row in prep.get('assets', {}).values():
            row.update(visible_style_facts=['SIMULATED solid-colour reference'], guidance='SIMULATED original style')
        for path in prep.get('visual_text', {}):
            sid, field = path.split('.', 1)
            block = next(b for b in view['blocks'] if b['shot_id'] == sid)
            text = next(text for paths, text in block['sources'].items() if field in paths.split(','))
            prep['visual_text'][path] = text.replace('女孩说 {镇上仓库今晚倒塌。}', '')
        if 'visual_basis' in prep:
            prep['visual_basis'] = 'SIMULATED all existing visible actions retained; dialogue-only information omitted.'
        if 'reference' in prep:
            prep['reference'].update(compatibility_reason='SIMULATED redundant guidance excluded',
                excluded=[dict(source_quote=view['original_prompt'], reason='SIMULATED no additional visual requirement')])
        plan = work['plan']
        plan.update(preserves_story=True, checks_passed=True,
            reviewed_shot_ids=[b['shot_id'] for b in view['blocks']],
            checks={name: 'SIMULATED concrete fixture review for ' + name for name in quality.CHECK_GROUPS})
        for block in view['blocks']:
            if block['shot_id'] not in view['focus_shot_ids']:
                continue
            values = []
            for paths, text in block['sources'].items():
                for path in paths.split(','):
                    text = prep.get('visual_text', {}).get(block['shot_id']+'.'+path, text)
                values.append(text)
            plan['edits'].append(dict(shot_id=block['shot_id'], content='。'.join(dict.fromkeys(values))))
        return work

    def test_one_submission_prepares_and_exports_into_case_without_changing_review(self):
        result = self.complete(missing=True)
        summary = core.read(self.path.parent/'finish/FINISH.view.json')
        self.assertEqual(summary['prompt_work'], result['prompt_work'])
        work = self.filled(result)
        old = copy.deepcopy(self.p)
        frozen = {path: Path(path).read_bytes() for path in self.p['repair_deliveries']['original']['files']}
        self.assertNotIn('source_fingerprint', work['plan'])
        self.assertEqual(len(work['plan']['checks']), 4)
        self.assertEqual(work['plan']['notes'], {})
        self.assertTrue(work['preparation']['assets'])
        core.save(result['prompt_work'], work)
        argv = ['repair_quality.py', 'finish', str(self.path), 'G01', result['prompt_work'],
                '--output', result['prompt_output']]
        with patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()), \
                patch.object(quality, 'source_request', wraps=quality.source_request) as sources:
            quality.main()
        self.assertEqual(sources.call_count, 2)  # One packet check and one prepared request, no prepare command.
        saved = core.read(self.path)
        self.assertEqual(saved['reviews'], old['reviews'])
        self.assertEqual(saved['aggregation'], old['aggregation'])
        self.assertEqual(saved['source_script'], old['source_script'])
        self.assertEqual({path: Path(path).read_bytes() for path in frozen}, frozen)
        text = Path(result['prompt_output']).read_text(encoding='utf8')
        self.assertEqual(text.count('【时长】1s。'), 3)
        self.assertIn('16:9', text)
        self.assertNotIn('仓库', text)
        self.assertEqual(finish_review.validate_delivery(saved, 'original', self.path)['shot_count'], 3)
        request = core.read(saved['repair_prompt_exports']['G01'][0]['request_path'])
        self.assertEqual(request['prompt_plan']['plan_version'], 3)
        self.assertTrue(all(a['sha256'] for a in request['asset_style']['assets']))

    def test_ready_work_uses_single_source_build_and_rejects_unapproved_work(self):
        result = self.complete()
        draft = core.read(result['prompt_work'])
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            prompt_work.finish(self.p, self.path, 'G01', draft, result['prompt_output'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(result['prompt_output']).exists())
        work = self.filled(result)
        with patch.object(quality, 'source_request', wraps=quality.source_request) as sources:
            record, saved = prompt_work.finish(self.p, self.path, 'G01', work, result['prompt_output'])
        self.assertEqual(sources.call_count, 1)
        self.assertTrue(Path(record['path']).is_file())
        self.assertEqual(saved['repair_prompt_plans']['G01']['notes'], {})

    def test_failed_submission_never_commits_preparation_or_outputs(self):
        result = self.complete(missing=True)
        good = self.filled(result)
        before, state = self.path.read_bytes(), copy.deepcopy(self.p)
        for mode in ('stale', 'blank_check', 'conflict', 'speech', 'extra_preparation', 'missing_asset'):
            work = copy.deepcopy(good)
            if mode == 'stale': work['input_fingerprint'] = 'old'
            elif mode == 'blank_check': work['plan']['checks']['generation'] = ''
            elif mode == 'conflict': work['plan']['unresolved'] = ['SIMULATED unresolved action order']
            elif mode == 'speech': work['plan']['edits'][0]['content'] += '人物说话。'
            elif mode == 'extra_preparation': work['preparation']['script'] = '修改剧情'
            else: work['preparation']['assets'].pop(next(iter(work['preparation']['assets'])))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                prompt_work.finish(self.p, self.path, 'G01', work, result['prompt_output'])
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(self.p, state)
            self.assertFalse(Path(result['prompt_output']).exists())
            self.assertFalse((self.path.parent/'.repair').exists())

    def test_changed_image_and_in_operation_replacement_reject_work(self):
        result = self.complete()
        work = self.filled(result)
        original = Path(self.p['storyboard_images'][0]['path'])
        payload, stat = original.read_bytes(), original.stat()
        def replace():
            changed = bytearray(payload); changed[-1] ^= 1
            original.write_bytes(changed)
            os.utime(original, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        compile_request = quality.compile_request
        def replace_after_compile(*args):
            compiled = compile_request(*args); replace(); return compiled
        with patch.object(quality, 'compile_request', side_effect=replace_after_compile), \
                self.assertRaisesRegex(ValueError, 'Evidence changed'):
            prompt_work.finish(self.p, self.path, 'G01', work, result['prompt_output'])
        self.assertFalse(Path(result['prompt_output']).exists())
        with self.assertRaises(ValueError):
            prompt_work.finish(self.p, self.path, 'G01', work, result['prompt_output'])

    def test_case_exports_remain_registered_immutable_and_protected(self):
        result = self.complete()
        work = self.filled(result)
        record, saved = prompt_work.finish(self.p, self.path, 'G01', work, result['prompt_output'])
        root = Path(result['delivery']).parent
        frozen = saved['repair_deliveries']['original']
        for target in (Path(frozen['path']), root/'images/new.md'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                repair_export.check_output(saved, target)
        self.assertEqual(finish_review.validate_delivery(saved, 'original', self.path)['shot_count'], 3)
        Path(record['path']).write_text('tampered', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'Immutable prompt export'):
            finish_review.validate_delivery(saved, 'original', self.path)
