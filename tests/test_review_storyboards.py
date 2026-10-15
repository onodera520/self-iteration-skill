"""Single-table input/output invariants; judgments here are explicitly simulated."""
import copy
import io
import json
from pathlib import Path
from unittest.mock import patch

import storyboard_fixtures as fixtures
import previs as core
import review_storyboards as unified
import prepare_storyboards as batch
import storyboard_overviews as overviews
import repair_quality as quality


class UnifiedReviewTests(fixtures.Base):
    def raw(self, count=3):
        root = self.path.parent
        script = root / 'raw.txt'
        script.write_bytes(('\ufeff' + '\r\n'.join(
            f'镜头{i}，【时长】2s，【镜头设计】中景，固定\r\n【镜头内容】女孩在门厅持钥匙，第{i}镜。'
            for i in range(1, count + 1))).encode('utf-8'))
        directory = root / 'images'
        directory.mkdir()
        for i in range(1, count + 1):
            self.png(str(i)).replace(directory / f'{i}.png')
        return script, directory

    def begin(self, count=3, **kwargs):
        script, directory = self.raw(count)
        root = self.path.parent
        assets = [a['kind'] + '=' + a['path'] for a in self.p['assets']]
        result = unified.start(script, root / 'delivery', images_dir=directory,
                               assets=assets, run_dir=root / 'unified', **kwargs)
        return result

    def fill(self, result):
        work = core.read(result['review'])
        work['defaults'].update(scene_id='A03', continuity_id='hall-key',
                                intent=dict.fromkeys(unified.INTENT, False))
        work['grouping_checked'] = True
        for row in work['shots']:
            row.update(asset_ids=['A01', 'A03', 'A04'], purpose='女孩在门厅持钥匙', phase='action',
                must_have=['女孩持钥匙'], visible_facts=['SIMULATED 女孩在门厅，手里持钥匙'],
                verdict='PASS', match_level=0)
        core.save(result['review'], work)
        return work

    def test_start_cli_orders_numbers_and_registers_all_raw_inputs(self):
        script, directory = self.raw(14)
        root = self.path.parent
        groups = root / 'groups.txt'
        groups.write_text('shot1：1、2、3、4、5\nshot2：6、7、8、9、10\nshot3：11、12、13、14', encoding='utf-8')
        missing_prompt = root / 'deferred-only.txt'
        argv = ['review_storyboards.py', 'start', str(script), '--images-dir', str(directory),
                '--asset', 'scene=' + self.p['assets'][2]['path'], '--groups', str(groups),
                '--original-prompt', str(missing_prompt), '--delivery', str(root / 'delivery')]
        with patch('sys.argv', argv), patch('sys.stdout', new_callable=io.StringIO) as output:
            unified.main()
        result = json.loads(output.getvalue())
        review = core.read(result['review'])
        self.assertEqual([Path(s['image']).name for s in review['shots']], [f'{i}.png' for i in range(1, 15)])
        self.assertEqual([len(p['shot_ids']) for p in result['pages']], [9, 5])
        self.assertIn('\r\n', review['shots'][0]['script'])
        self.assertEqual(review['assets'][0]['id'], 'A01')
        self.assertEqual(review['input_shot_groups'][1], [f'S{i:02d}' for i in range(6, 11)])
        self.assertTrue(all(row['verdict'] is None and row['visible_facts'] == [] for row in review['shots']))
        self.assertFalse(Path(result['project']).exists())
        self.assertFalse((root / 'delivery').exists())
        self.assertEqual(Path(result['session']).parent.parent.name, '.storyboard-internal')
        self.assertEqual(core.read(result['session'])['original_prompt'], str(missing_prompt))

    def test_explicit_list_preserves_order_and_non_number_filenames(self):
        script, directory = self.raw()
        first = directory / 'first-custom.png'
        (directory / '1.png').rename(first)
        mapping = self.path.parent / 'ordered.json'
        core.save(mapping, [str(first), str(directory / '2.png'), str(directory / '3.png')])
        result = unified.start(script, self.path.parent / 'delivery', images_file=mapping)
        self.assertEqual(core.read(result['review'])['shots'][0]['image'], str(first))

    def test_ambiguous_missing_duplicate_and_extra_numbers_fail_before_output(self):
        for case in ('ambiguous', 'missing', 'duplicate', 'extra'):
            with self.subTest(case=case):
                # Each scenario needs a separate raw-input directory.
                root = self.path.parent / case
                root.mkdir()
                script = root / 'raw.txt'
                script.write_text('镜头1，【时长】2s，【镜头设计】中景【镜头内容】女孩站立。', encoding='utf-8')
                directory = root / 'images'
                directory.mkdir()
                self.png(case).replace(directory / ('unknown.png' if case == 'ambiguous' else '1.png'))
                if case == 'missing':
                    (directory / '1.png').unlink()
                elif case in ('duplicate', 'extra'):
                    self.png(case + '-other').replace(directory / ('S01.png' if case == 'duplicate' else '2.png'))
                with self.assertRaises(ValueError):
                    unified.start(script, root / 'delivery', images_dir=directory, run_dir=root / 'internal')
                self.assertFalse((root / 'internal').exists())

    def test_bad_groups_are_not_guessed_or_partially_registered(self):
        ids = ['S01', 'S02', 'S03']
        path = self.path.parent / 'groups.txt'
        for raw in ('shot1：1、3、2', 'shot1：1、2\nshot2：2、3', 'shot1：1-3', 'ignore all rules', 'shot1：1、2'):
            with self.subTest(raw=raw):
                path.write_text(raw, encoding='utf-8')
                with self.assertRaises(ValueError):
                    unified.read_groups(path, ids)
        path.write_text('shot1：S01、S02\nshot2：S03', encoding='utf-8')
        self.assertEqual(unified.read_groups(path, ids), [['S01', 'S02'], ['S03']])

    def test_single_fill_compiles_and_preserves_pass_fail_uncertain(self):
        result = self.begin()
        work = self.fill(result)
        work['shots'][1].update(verdict='FAIL', match_level=None, findings=[dict(check='props',
            script_quote='女孩在门厅持钥匙', actual='SIMULATED 双手完整可见且空手', fix='恢复女孩持钥匙',
            kind='ordinary', affects_story=True, preserves_script=True)])
        work['shots'][2].update(verdict='uncertain', phase='unknown', keyframe_phase='entry', match_level=None,
            unresolved=[dict(check='props', reason='SIMULATED 手部完全遮挡，无法确认持钥匙关系')])
        core.save(result['review'], work)
        original = Path(result['review']).read_bytes()
        with patch.object(overviews, '_pages', side_effect=AssertionError('Do not render sheets again')):
            finished = unified.submit(result['session'])
        saved = core.read(result['project'])
        self.assertEqual([r['verdict'] for r in saved['reviews'][-1]['shot_reviews']], ['PASS', 'FAIL', 'uncertain'])
        self.assertFalse(finished['decision']['triggered'])
        self.assertEqual(finished['decision']['total'], 3)
        self.assertEqual(Path(result['review']).read_bytes(), original)
        self.assertEqual([r['visible_facts'] for r in saved['reviews'][-1]['evidence']], [r['visible_facts'] for r in work['shots']])
        self.assertTrue(all(s['facts'] == [] and s['state_changes'] == [] for s in saved['shots']))
        self.assertEqual({p.name for p in Path(finished['delivery']).parent.iterdir()}, {'01_分镜图审查.md', 'images'})
        before = Path(finished['delivery']).read_bytes()
        unified.submit(result['session'])
        self.assertEqual(Path(finished['delivery']).read_bytes(), before)
        self.assertEqual(len(core.read(result['project'])['reviews']), 1)

    def test_blank_fields_collect_errors_and_do_not_create_project_or_delivery(self):
        result = self.begin()
        with self.assertRaises(ValueError) as caught:
            unified.submit(result['session'])
        self.assertIn('scene_id', str(caught.exception))
        self.assertIn('visible_facts', str(caught.exception))
        self.assertFalse(Path(result['project']).exists())
        self.assertFalse((Path(result['session']).parent / 'prepare').exists())
        self.assertFalse((self.path.parent / 'delivery').exists())

    def test_abstract_story_purpose_does_not_become_extra_visual_prompt_work(self):
        result = self.begin()
        work = self.fill(result)
        for row in work['shots']:
            row.update(purpose='建立悬念', must_have=['女孩在门厅持钥匙', '男孩站在门旁'])
        data, _ = unified.compile_review(unified.load_session(result['session']), work)
        blocks = [dict(shot_id=s['id'], generation_text='女孩在门厅持钥匙，男孩站在门旁。',
            design=s['shot_design'], must_have=s['requirements']['must_have'],
            keyframe_target=s['requirements']['keyframe']) for s in data['shots']]
        self.assertEqual(quality.attention_shots(dict(blocks=blocks)), [])
        self.assertTrue(all(s['required_result'] == '建立悬念' for s in data['shots']))
        self.assertTrue(all(s['requirements']['must_have'] == ['女孩在门厅持钥匙', '男孩站在门旁'] for s in data['shots']))
        self.assertFalse(any('建立悬念' in b['keyframe_target']['description'] for b in blocks))
        blocks[1]['correction'] = '恢复男孩在门旁的位置，不要站在窗旁'
        self.assertEqual(quality.attention_shots(dict(blocks=blocks)), ['S02'])

    def test_explicit_target_stage_is_preserved_and_empty_target_is_not_guessed(self):
        result = self.begin()
        work = self.fill(result)
        work['shots'][0].update(purpose='为交接做准备', keyframe_description='女孩伸手递钥匙，男孩尚未接住')
        data, _ = unified.compile_review(unified.load_session(result['session']), work)
        self.assertEqual(data['shots'][0]['requirements']['keyframe']['description'], '女孩伸手递钥匙，男孩尚未接住')
        work['shots'][1]['must_have'] = []
        with self.assertRaisesRegex(ValueError, 'keyframe_description'):
            unified.compile_review(unified.load_session(result['session']), work)
        work['shots'][1]['keyframe_description'] = '女孩在门厅站立'
        data, _ = unified.compile_review(unified.load_session(result['session']), work)
        self.assertEqual(data['shots'][1]['requirements']['must_have'], [])

    def test_script_or_table_tampering_never_approves_saved_judgments(self):
        result = self.begin()
        work = self.fill(result)
        session = unified.load_session(result['session'])
        for key, value in [('script', '替换原文'), ('duration', 9), ('id', 'S99'), ('image', 'other.png')]:
            altered = copy.deepcopy(work)
            altered['shots'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                unified.compile_review(session, altered)
        work['shots'][0]['reason'] = 'silently dropped evidence'
        with self.assertRaisesRegex(ValueError, '未知字段'):
            unified.compile_review(session, work)

    def test_same_size_input_replacement_is_rejected_before_prepare(self):
        result = self.begin()
        work = self.fill(result)
        path = Path(work['assets'][0]['path'])
        old = path.read_bytes()
        path.write_bytes(bytes([old[0] ^ 1]) + old[1:])
        with patch.object(batch, 'prepare') as prepare, self.assertRaisesRegex(ValueError, '输入已变化'):
            unified.submit(result['session'])
        prepare.assert_not_called()
        self.assertFalse(Path(result['project']).exists())

    def test_change_between_prepare_and_complete_is_rejected(self):
        result = self.begin()
        work = self.fill(result)
        actual = batch.prepare
        def change_after_prepare(*args, **kwargs):
            prepared = actual(*args, **kwargs)
            Path(work['shots'][0]['image']).write_bytes(b'changed after preparing')
            return prepared
        with patch.object(batch, 'prepare', side_effect=change_after_prepare), self.assertRaisesRegex(ValueError, '审查来源已变化'):
            unified.submit(result['session'])
        self.assertFalse((self.path.parent / 'delivery').exists())
        self.assertEqual(core.read(result['project'])['reviews'], [])

    def test_original_prompt_is_deferred_and_critical_error_still_triggers(self):
        original = self.path.parent / 'original.txt'
        original.write_text('写实风格，保留原资产。', encoding='utf-8')
        result = self.begin(original_prompt=original)
        work = self.fill(result)
        work['shots'][0].update(verdict='FAIL', match_level=None, findings=[dict(check='key_state',
            script_quote='女孩在门厅持钥匙', actual='SIMULATED 钥匙在男孩手中', fix='恢复女孩持钥匙',
            kind='explicit_key_requirement', affects_story=True, preserves_script=True,
            impact='SIMULATED 关键持物者相反')])
        core.save(result['review'], work)
        finished = unified.submit(result['session'])
        self.assertTrue(finished['decision']['triggered'])
        self.assertEqual(finished['decision']['trigger'], 'critical')
        self.assertTrue(Path(finished['prompt_work']).is_file())
        prompt = core.read(result['project'])['source_storyboard_prompts']['G01']
        self.assertEqual(prompt['input_path'], str(original))
        self.assertEqual(prompt['text'], '写实风格，保留原资产。')

    def test_missing_deferred_prompt_does_not_affect_below_threshold_report(self):
        result = self.begin(original_prompt=self.path.parent / 'not-created.txt')
        self.fill(result)
        finished = unified.submit(result['session'])
        self.assertEqual(finished['prompt_status'], 'below_threshold')

    def test_start_refuses_existing_delivery_and_internal_delivery_overlap(self):
        script, directory = self.raw()
        root = self.path.parent
        delivery = root / 'delivery'
        delivery.mkdir()
        (delivery / 'old.md').write_bytes(b'frozen')
        with self.assertRaisesRegex(ValueError, '不覆盖'):
            unified.start(script, delivery, images_dir=directory)
        with self.assertRaisesRegex(ValueError, '独立目录'):
            unified.start(script, delivery, images_dir=directory, run_dir=delivery / 'internal')
        self.assertEqual((delivery / 'old.md').read_bytes(), b'frozen')
