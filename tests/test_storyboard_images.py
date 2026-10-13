"""Real PNG inputs with simulated visual judgments; no AI/FFmpeg/network required."""
import copy
import os
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import storyboard_fixtures as fixtures
import previs as core
import planner
import storyboard_inputs as images
import prepare_storyboards as batch
import repair_cycle as repair
import repair_quality as quality
import repair_export
import repair_reference
import evidence_runtime
import finish_review


class StoryboardImagesTests(fixtures.Base):
    png = fixtures.Base.png
    simulated_plan = fixtures.Base.simulated_plan

    def setUp(self):
        fixtures.Base.setUp(self)
        self.p['config'].update(workflow='storyboard_images')
        self.p['storyboard_images'] = [dict(shot_id=s['id'], path=str(self.png('board-'+s['id'], (20*i, 70, 90))))
                                       for i, s in enumerate(self.p['shots'])]
        self.p['repair_asset_style'] = dict(preserves_story=True, assets=[dict(
            asset_id=a['id'], sha256=core.sha(Path(a['path'])), visible_style_facts=['SIMULATED flat colour'],
            guidance='SIMULATED style') for a in self.p['assets']])
        core.save(self.path, self.p)

    def review(self, fails=(), uncertain=(), omit=False, critical=False, affects_story=True):
        ctx = images.context(self.p, self.path, 'G01')
        r = images.draft(ctx)
        r.update(checks={k:'PASS' for k in r['checks']}, grouping_checked=True)
        for s, row, ref, evidence in zip(self.p['shots'], r['shot_reviews'], r['reference_assessments'], r['evidence']):
            sid = s['id']
            row.update(verdict='PASS', reason='SIMULATED entry reference fits script; motion unproven, not an error',
                       identity_reason='SIMULATED actor relationships visible', reference_phase='entry',
                       phase_reason='SIMULATED handoff has not started', checks={k:'PASS' for k in row['checks']})
            evidence.update(observation='SIMULATED visible actors and key', visible_facts=['SIMULATED key held by girl'],
                            interpretation='SIMULATED script-consistent entry phase')
            ref.update(decision='anchor', derivable=False, reason='SIMULATED necessary reference')
            if sid in fails:
                row.update(verdict='FAIL', reason='SIMULATED wrong key holder visible')
                row['checks']['props'] = 'FAIL'
                ref.update(decision='pending', derivable=None)
                r['checks']['story'] = 'FAIL'
                r['issues'].append(dict(id='issue-'+sid, shot_ids=[sid], severity='high', asset_ids=[], asset_comparison_ids=[],
                    problem='SIMULATED wrong holder', expected=s['script'], actual='SIMULATED key held by wrong person',
                    evidence=[evidence['path']], repair_target='storyboard_image', fix='修改该分镜图的钥匙持有者，保持脚本。'))
                r['repair_assessments'].append(dict(shot_id=sid, critical=critical,
                    critical_kind='wrong_transfer_result' if critical else None, affects_story=affects_story,
                    script_quote=s['script'], issue_ids=['issue-'+sid], impact='SIMULATED visible conflict',
                    correction='恢复脚本要求的钥匙持有者。', preserves_script=True))
            elif sid in uncertain:
                row.update(verdict='uncertain', reference_phase='unknown', followup='放大原图确认手部状态')
                row['checks']['props'] = 'uncertain'
                r['checks']['shot'] = 'uncertain'
                ref.update(decision='pending', derivable=None)
            elif omit and sid == 'S02':
                ref.update(decision='ai_fill', derivable=True, basis_shot_ids=['S01', 'S03'],
                           reason='两端与原资产能承接同场持物状态，没有新增关键剧情')
        return r

    def worklist(self, review):
        ctx = images.context(self.p, self.path, 'G01')
        result = batch.worklist(ctx)
        for key in ('checks','grouping_checked','issues','uncertainties','asset_comparisons','repair_assessments'):
            result[key] = copy.deepcopy(review[key])
        for item, row, ref, evidence in zip(result['shots'], review['shot_reviews'], review['reference_assessments'], review['evidence']):
            item.update({k:copy.deepcopy(v) for k,v in row.items() if k!='evidence_sha256'})
            item['reference'].update({k:v for k,v in ref.items() if k not in ('shot_id','evidence_sha256')})
            item['observation'].update({k:v for k,v in evidence.items() if k in item['observation']})
        return result

    def ready(self, **kwargs):
        r = self.review(**kwargs)
        core.record_review(self.p, self.path, r)
        planner.store_aggregation(self.p, self.path, planner.post_review_plan(self.p, self.path, {}))
        return repair.decide(self.p, self.path, 'G01')

    def compact_input(self):
        data = {k: copy.deepcopy(self.p[k]) for k in ('title', 'source_script', 'assets', 'shots')}
        data['input_version'] = 1
        data['input_shot_groups'] = [[s['id'] for s in data['shots']]]
        for shot, image in zip(data['shots'], self.p['storyboard_images']):
            shot['image'] = image['path']
            shot.pop('reference', None)
        return data

    def test_compact_input_validates_before_saving_and_preserves_state(self):
        data = self.compact_input()
        original = copy.deepcopy(data)
        project = self.path.parent / 'new-project.json'
        batch.prepare(project, None, self.path.parent/'compact-prep', input_data=data)
        p = core.read(project)
        self.assertEqual(data, original)
        self.assertEqual(p['source_script'], self.p['source_script'])
        self.assertEqual([s['script'] for s in p['shots']], [s['script'] for s in self.p['shots']])
        from requirements import contexts
        self.assertEqual(contexts(p), contexts(self.p))
        self.assertEqual(p['groups'][0]['shot_ids'], ['S01', 'S02', 'S03'])
        self.assertEqual(p['input_shot_groups'], data['input_shot_groups'])
        frozen = project.read_bytes()
        with self.assertRaisesRegex(ValueError, '不要覆盖'):
            batch.prepare(project, None, self.path.parent/'overwrite', input_data=data)
        self.assertEqual(project.read_bytes(), frozen)
        self.assertFalse((self.path.parent/'overwrite').exists())

    def shared_input(self):
        data = self.compact_input()
        scope = {key: data['shots'][0][key] for key in ('scene_id', 'continuity_id')}
        data['requirement_templates'] = {'common': dict(scope=scope,
            must_have=['SIMULATED shared key remains unique'], must_not_have=['SIMULATED second key'],
            provenance=[dict(field='must_have,must_not_have', status='script', source='SIMULATED shared script constraint')])}
        for shot in data['shots']:
            shot['requirements_template'] = 'common'
        return data

    def test_common_requirements_preserve_per_shot_states_and_sources(self):
        data = self.shared_input()
        original = copy.deepcopy(data)
        p = batch.project_input(data)
        for before, after in zip(data['shots'], p['shots']):
            for key in ('keyframe', 'entry_state', 'inherits_from'):
                self.assertEqual(after['requirements'][key], before['requirements'][key])
            for key in ('facts', 'state_changes', 'intent', 'script'):
                self.assertEqual(after[key], before[key])
            self.assertEqual(after['requirements']['must_have'][0], 'SIMULATED shared key remains unique')
            self.assertEqual(after['requirements']['provenance'][1:], before['requirements']['provenance'])
        p['shots'][0]['requirements']['must_have'].append('only-first')
        self.assertNotIn('only-first', p['shots'][1]['requirements']['must_have'])
        self.assertEqual(data, original)
        self.assertNotIn('requirement_templates', p)
        project = self.path.parent/'shared-project.json'
        batch.prepare(project, None, self.path.parent/'shared-prep', input_data=data)
        self.assertEqual(core.read(project)['shots'][1]['requirements'], batch.project_input(data)['shots'][1]['requirements'])

    def test_common_requirements_cannot_infer_scope_or_replace_story_judgments(self):
        for bad_kind in ('unknown', 'different-scene', 'different-continuity', 'wrong-assets', 'phase', 'state', 'empty-scope', 'missing-provenance'):
            data = self.shared_input()
            template = data['requirement_templates']['common']
            if bad_kind == 'unknown':
                data['shots'][0]['requirements_template'] = 'missing'
            elif bad_kind == 'different-scene':
                data['shots'][1]['scene_id'] = 'different-era'
            elif bad_kind == 'different-continuity':
                data['shots'][1]['continuity_id'] = 'different-era'
            elif bad_kind == 'wrong-assets':
                template['scope']['asset_ids'] = ['not-in-shot']
            elif bad_kind == 'empty-scope':
                template['scope'] = {}
            elif bad_kind == 'missing-provenance':
                del data['shots'][0]['requirements']['provenance']
            else:
                template['keyframe' if bad_kind == 'phase' else 'entry_state'] = {}
            with self.subTest(bad_kind=bad_kind), self.assertRaises(ValueError):
                batch.prepare(self.path.parent/'bad-shared.json', None, self.path.parent/'bad-shared-prep', input_data=data)
            self.assertFalse((self.path.parent/'bad-shared.json').exists())

    def test_compact_input_cannot_invent_missing_requirements_or_image(self):
        data = self.compact_input()
        for field in ('phase', 'provenance', 'image', 'duration_source', 'facts', 'intent'):
            bad = copy.deepcopy(data)
            if field == 'phase':
                del bad['shots'][0]['requirements']['keyframe']['phase']
            elif field == 'provenance':
                del bad['shots'][0]['requirements']['provenance']
            else:
                del bad['shots'][0][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                batch.prepare(self.path.parent/'invalid-new.json', None, self.path.parent/'bad-prep', input_data=bad)
            self.assertFalse((self.path.parent/'invalid-new.json').exists())
            self.assertFalse((self.path.parent/'bad-prep').exists())

    def test_compact_preflight_collects_source_and_enum_errors_before_image_decode(self):
        data = self.compact_input()
        data['shots'][0]['script'] = '原文已被替换'
        data['shots'][0]['facts'][0]['phase'] = 'current'
        data['shots'][1]['requirements']['keyframe']['phase'] = 'current'
        data['shots'][2].pop('duration_source')
        with patch.object(images, 'inputs', side_effect=AssertionError('must not decode invalid input')):
            with self.assertRaises(ValueError) as caught:
                batch.prepare(self.path.parent/'invalid-new.json', None, self.path.parent/'bad-prep', input_data=data)
        message = str(caught.exception)
        for field in ('shots[S01].script', 'shots[S01].facts[0].phase',
                      'shots[S02].requirements.keyframe.phase', 'shots[S03].duration_source'):
            self.assertIn(field, message)
        self.assertFalse((self.path.parent/'invalid-new.json').exists())
        self.assertFalse((self.path.parent/'bad-prep').exists())

    def test_prepare_checks_delivery_layout_before_creating_internal_files(self):
        root = self.path.parent
        for project, run, output in ((root/'case/PROJECT.json', root/'prep', root/'case'),
                                     (root/'new.json', root/'case/prep', root/'case'),
                                     (root/'new.json', root/'prep', root/'prep/case')):
            with self.subTest(project=project, run=run), self.assertRaisesRegex(ValueError, '独立目录'):
                batch.prepare(project, None, run, input_data=self.compact_input(), output=output)
            self.assertFalse(project.exists())
            self.assertFalse(run.exists())
        output = root/'existing-case'
        output.mkdir()
        (output/'frozen.md').write_text('frozen', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '不覆盖'):
            batch.prepare(root/'new.json', None, root/'prep', input_data=self.compact_input(), output=output)
        self.assertEqual((output/'frozen.md').read_text(encoding='utf-8'), 'frozen')
        self.assertFalse((root/'new.json').exists())

    def test_prepare_new_delivery_path_passes_preflight_without_creating_delivery(self):
        root = self.path.parent
        batch.prepare(root/'new.json', None, root/'prep', input_data=self.compact_input(), output=root/'case')
        self.assertTrue((root/'new.json').exists())
        self.assertTrue((root/'prep/WORKLIST.json').exists())
        self.assertFalse((root/'case').exists())

    def test_compact_template_cli_keeps_handoff_states_and_order(self):
        data = core.read(fixtures.ROOT / 'ai-storyboard-previs/assets/storyboard-input.json')
        for asset in data['assets']:
            asset['path'] = str(self.png(asset['id'], (60, 70, 80)))
        for shot in data['shots']:
            shot['image'] = str(self.png('template-'+shot['id'], (20, 40, 60)))
        manifest, project = self.path.parent/'input.json', self.path.parent/'template-project.json'
        core.save(manifest, data)
        with patch('sys.argv', ['prepare_storyboards.py', 'prepare', str(project), '--input', str(manifest),
                               '--run-dir', str(self.path.parent/'template-prep')]), patch('builtins.print'):
            batch.main()
        from requirements import contexts
        state = contexts(core.read(project))
        self.assertEqual(state['S01']['exit_state']['key.holder'], 'girl')
        self.assertEqual(state['S02']['entry_state']['key.holder'], 'girl')
        self.assertEqual(state['S02']['exit_state']['key.holder'], 'boy')
        self.assertEqual([s['shot_id'] for s in core.read(self.path.parent/'template-prep/WORKLIST.json')['shots']],
                         ['S01', 'S02'])
        # Simulated judgments exercise the complete public entry point, not vision.
        work = core.read(self.path.parent/'template-prep/WORKLIST.json')
        work['checks'] = dict.fromkeys(work['checks'], 'PASS')
        work['grouping_checked'] = True
        for row, shot in zip(work['shots'], data['shots']):
            row.update(verdict='PASS', reference_phase=shot['requirements']['keyframe']['phase'])
            row['checks'] = dict.fromkeys(row['checks'], 'PASS')
            row['reference'].update(decision='anchor', derivable=False, basis_shot_ids=[])
            row['observation']['visible_facts'] = ['SIMULATED：' + shot['requirements']['keyframe']['description']]
        workfile = self.path.parent/'template-prep/WORKLIST.json'
        core.save(workfile, work)
        result = batch.complete(project, workfile, self.path.parent/'template-delivery', self.path.parent/'template-finish')
        self.assertEqual(result['status'], 'complete')
        report = Path(result['delivery']).read_text(encoding='utf8')
        self.assertEqual(report.count('| 符合脚本 |'), 2)

    def test_compact_pass_reuses_one_observation_and_report_is_fixed(self):
        r = self.review(omit=True)
        work = self.worklist(r)
        for row in work['shots']:
            for key in ('reason', 'identity_reason', 'phase_reason', 'followup'):
                row.pop(key, None)
            if row['reference']['decision'] == 'anchor':
                row['reference'].pop('reason', None)
        ctx = images.context(self.p, self.path, 'G01')
        expanded = batch.expand(ctx, work)
        self.assertEqual([x['reason'] for x in expanded['shot_reviews']], ['符合脚本']*3)
        self.assertEqual(expanded['evidence'][0]['observation'], work['shots'][0]['observation']['visible_facts'][0])
        self.assertEqual(expanded['shot_reviews'][0]['phase_reason'], expanded['evidence'][0]['observation'])
        core.record_review(self.p, self.path, expanded)
        planner.store_aggregation(self.p, self.path, planner.post_review_plan(self.p, self.path, {}))
        repair.decide(self.p, self.path, 'G01')
        report = repair.snapshot(self.p, self.path, self.path.parent/'compact-delivery', 'original')
        rows = [line for line in Path(report).read_text(encoding='utf8').splitlines() if '| 检验通过 |' in line]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(line.endswith('| 符合脚本 |') for line in rows))
        self.assertIn('S01 + S03', rows[1])

    def test_compact_review_requires_checks_observation_phase_and_omission_reason(self):
        ctx = images.context(self.p, self.path, 'G01')
        good = self.worklist(self.review(omit=True))
        for field in ('checks', 'reference_phase', 'visible_facts', 'omission_reason'):
            bad = copy.deepcopy(good)
            if field == 'checks':
                bad['shots'][0]['checks'].pop('props')
            elif field == 'reference_phase':
                bad['shots'][0]['reference_phase'] = 'unknown'
            elif field == 'visible_facts':
                bad['shots'][0]['observation']['visible_facts'] = []
            else:
                bad['shots'][1]['reference']['reason'] = ''
            with self.subTest(field=field), self.assertRaises(ValueError):
                images.record_review(self.p, self.path, batch.expand(ctx, bad))
        with self.assertRaises(ValueError):
            images.record_review(self.p, self.path, batch.expand(ctx, batch.worklist(ctx)))

    def test_compact_fail_and_uncertainty_keep_details_and_issue_bindings(self):
        work = self.worklist(self.review(fails=['S01'], uncertain=['S02']))
        work['issues'][0].pop('evidence')
        work['issues'][0].pop('repair_target')
        ctx = images.context(self.p, self.path, 'G01')
        expanded = batch.expand(ctx, work)
        core.record_review(self.p, self.path, expanded)
        self.assertEqual(expanded['shot_reviews'][0]['reason'], work['shots'][0]['reason'])
        self.assertEqual(expanded['shot_reviews'][1]['followup'], '放大原图确认手部状态')
        self.assertEqual(expanded['issues'][0]['evidence'], [ctx['shots'][0]['image']['path']])
        bad = copy.deepcopy(work)
        bad['issues'][0]['evidence'] = [ctx['shots'][1]['image']['path']]
        with self.assertRaisesRegex(ValueError, '问题证据'):
            core.record_review(self.p, self.path, batch.expand(ctx, bad))

    def test_compact_asset_bindings_never_replace_supplied_wrong_hash(self):
        ctx = images.context(self.p, self.path, 'G01')
        work = self.worklist(self.review())
        aid = next(a['id'] for a in ctx['assets'] if a['kind'] == 'character')
        work['asset_comparisons'] = [dict(id='S01-actor', shot_id='S01', asset_id=aid, aspect='appearance',
            decision='PASS', stable_matches=['SIMULATED same visible actor'], story_requirement='SIMULATED required actor')]
        expanded = batch.expand(ctx, work)
        core.record_review(self.p, self.path, expanded)
        work['asset_comparisons'][0]['asset_sha256'] = 'wrong-hash'
        with self.assertRaises(ValueError):
            core.record_review(self.p, self.path, batch.expand(ctx, work))

    def test_version_one_worklist_remains_compatible(self):
        review = self.review(omit=True)
        work = self.worklist(review)
        work['worklist_version'] = 1
        for item, evidence in zip(work['shots'], review['evidence']):
            item['observation'] = {k: evidence[k] for k in ('observation', 'visible_facts', 'interpretation')}
        expanded = batch.expand(images.context(self.p, self.path, 'G01'), work)
        core.record_review(self.p, self.path, expanded)
        self.assertEqual(expanded['shot_reviews'][0]['reason'], review['shot_reviews'][0]['reason'])

    def test_entire_batch_no_video_tools_omitted_original_still_displayed(self):
        self.assertFalse(hasattr(core, 'current_video'))
        self.assertFalse(hasattr(repair, 'submit'))
        with patch('subprocess.run', side_effect=AssertionError('external process')):
            prepared = batch.prepare(self.path, None, self.path.parent/'prep')
            self.p = core.read(self.path)
            core.save(prepared['worklist'], self.worklist(self.review(omit=True)))
            result = batch.complete(self.path, prepared['worklist'], self.path.parent/'delivery', self.path.parent/'finish')
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['decision']['triggered'])
        self.assertEqual(result['validation'], dict(shot_count=3, thumbnail_count=3, table_count=1,
                         visual_review='existing evidence-bound review; no new visual approval'))
        text = Path(result['delivery']).read_text(encoding='utf8')
        self.assertEqual(Path(result['delivery']).name, '01_分镜图审查.md')
        self.assertIn('建议省图，未验证', text)
        self.assertEqual(text.count('| 符合脚本 |'), 3)
        self.assertNotIn('漏镜', text)
        self.assertNotIn('抽帧', text)
        self.assertEqual(len(list((Path(result['delivery']).parent/'images').glob('*.png'))), 6)
        for item in self.p['storyboard_images']:
            self.assertTrue(Path(item['path']).is_file())

    def test_invalid_inputs_are_not_reviews(self):
        original = self.path.read_bytes()
        rows = self.p['storyboard_images']
        for bad in (rows[:-1], [rows[0], rows[0], rows[2]], [dict(rows[0], path='absent.png'), *rows[1:]]):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, '输入问题'):
                batch.prepare(self.path, bad, self.path.parent/'invalid')
            self.assertEqual(self.path.read_bytes(), original)
            self.assertFalse((self.path.parent/'invalid').exists())
        Path(rows[0]['path']).write_bytes(b'broken PNG')
        with self.assertRaisesRegex(ValueError, '无法读取'):
            batch.prepare(self.path, rows, self.path.parent/'invalid')

    def test_uncertainty_is_pending_and_entry_phase_is_valid(self):
        self.ready(uncertain=['S02'])
        decisions = self.p['aggregation']['decisions']
        self.assertEqual([r['status'] for r in decisions], ['anchor_reviewed','pending','anchor_reviewed'])
        path = repair.snapshot(self.p, self.path, self.path.parent/'delivery', 'original')
        row = next(line for line in Path(path).read_text(encoding='utf8').splitlines() if '| S02 |' in line)
        self.assertIn('| — | 暂不省图 |', row)
        self.assertIn('![', row)
        r = self.review()
        r['shot_reviews'][0]['reference_phase'] = 'unknown'
        with self.assertRaisesRegex(ValueError, '明确阶段'):
            core.record_review(self.p, self.path, r)

    def test_threshold_whole_batch_two_of_ten_vs_eleven(self):
        for n in (10,11):
            with self.subTest(n=n):
                seed = copy.deepcopy(self.p['shots'][0])
                self.p['shots'] = [dict(copy.deepcopy(seed), id=f'S{i:02d}') for i in range(1,n+1)]
                ids = [s['id'] for s in self.p['shots']]
                self.p['source_script'] = '\n'.join(s['script'] for s in self.p['shots'])
                self.p['groups'] = [dict(id='G01', shot_ids=ids, version=1)]
                self.p['input_shot_groups'] = [ids[:5], ids[5:]]
                self.p['storyboard_images'] = [dict(shot_id=sid, path=str(self.png(sid, (20,50,60)))) for sid in ids]
                self.p.pop('repair_baseline', None)
                d = self.ready(fails=ids[:2], uncertain=[ids[-1]], affects_story=False)
                self.assertEqual(d['triggered'], n==10)
                self.assertEqual((d['error_count'],d['total']), (2,n))
                self.assertNotIn('necessary_missing_shot_ids',d)
                self.assertNotIn('missing_summary',self.p['aggregation'])

    def test_single_critical_and_severe_damage(self):
        self.assertTrue(self.ready(fails=['S02'], critical=True)['triggered'])
        r = self.review(fails=['S02'])
        r['repair_assessments'][0]['severe_visual_damage'] = dict(image_sha256=r['evidence'][1]['sha256'],
            damage_description='SIMULATED corrupt hands', obscured_content='SIMULATED required handoff')
        core.record_review(self.p,self.path,r)
        planner.store_aggregation(self.p,self.path,planner.post_review_plan(self.p,self.path,{}))
        self.assertEqual(repair.decide(self.p,self.path,'G01')['trigger'],'severe_visual_damage')

    def test_stale_image_script_assets_and_frozen_revision(self):
        prep = batch.prepare(self.path,None,self.path.parent/'prep')
        self.p = core.read(self.path)
        core.save(prep['worklist'],self.worklist(self.review()))
        result = batch.complete(self.path,prep['worklist'],self.path.parent/'old',self.path.parent/'done')
        self.p = core.read(self.path)
        frozen = self.p['repair_deliveries']['original']['files']
        saved = copy.deepcopy(self.p)
        self.p['shots'][0]['script'] += ' changed'
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        self.p = copy.deepcopy(saved)
        asset = Path(self.p['assets'][0]['path'])
        old_asset = asset.read_bytes()
        Image.new('RGB',(100,100),'red').save(asset)
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        asset.write_bytes(old_asset)
        image = Path(self.p['storyboard_images'][0]['path'])
        old_image = image.read_bytes()
        Image.new('RGB',(100,100),'red').save(image)
        self.assertIsNone(core.review_current(self.p,self.path,'G01'))
        self.assertIsNone(planner.current_aggregation(self.p,self.path))
        with self.assertRaises(ValueError):
            repair.current_decision(self.p,self.path,'G01')
        with self.assertRaisesRegex(ValueError,'依据已变化'):
            batch.expand(images.context(self.p,self.path,'G01'),core.read(prep['worklist']))
        prep2 = batch.prepare(self.path,None,self.path.parent/'prep2')
        self.p = core.read(self.path)
        core.save(prep2['worklist'],self.worklist(self.review()))
        batch.complete(self.path,prep2['worklist'],self.path.parent/'new',self.path.parent/'done2')
        self.assertEqual(frozen,{f:core.sha(Path(f)) for f in frozen})
        self.assertEqual(len(core.read(self.path)['repair_delivery_history']),1)
        image.write_bytes(old_image)
        self.assertIsNotNone(core.review_current(saved,self.path,'G01'))

    def test_common_aspect_and_full_audited_prompt_export(self):
        for row in self.p['storyboard_images']:
            Image.new('RGB',(160,90),'green').save(row['path'])
        self.ready(fails=['S02'],critical=True)
        request = quality.source_request(self.p,self.path,'G01')
        self.assertEqual(request['aspect_ratio'],'16:9')
        self.assertEqual([r['shot_id'] for r in request['blocks']],['S01','S02','S03'])
        output = self.path.parent/'prompt.md'
        quality.finish_plan(self.p,self.path,'G01',self.simulated_plan(),output)
        text = output.read_text(encoding='utf8')
        self.assertEqual(text.count('【时长】1s。'),3)
        self.assertIn('只生成无声画面',text)
        self.assertNotIn('输入视频画幅',text)
        self.assertFalse(hasattr(repair, 'submit'))

    def test_mixed_aspect_reviews_finish_before_target_is_required(self):
        Image.new('RGB',(90,160),'green').save(self.p['storyboard_images'][0]['path'])
        self.ready(fails=['S02'],critical=True)
        repair.snapshot(self.p,self.path,self.path.parent/'delivery','original')
        with self.assertRaisesRegex(ValueError,'混用画幅'):
            quality.source_request(self.p,self.path,'G01')
        self.p['storyboard_target_aspect']='9:16'
        self.assertEqual(quality.source_request(self.p,self.path,'G01')['aspect_ratio'],'9:16')
        with Image.open(self.p['storyboard_images'][1]['path']) as image:
            self.assertEqual(image.size,(64,36))

    def test_hashes_reused_and_concurrent_replacement_rejected(self):
        original = self.p['storyboard_images'][0]['path']
        with patch.object(evidence_runtime,'raw_sha',wraps=evidence_runtime.raw_sha) as calls:
            with evidence_runtime.evidence_operation():
                self.ready(omit=True)
                repair.snapshot(self.p,self.path,self.path.parent/'delivery','original')
        count = sum(Path(call.args[0])==Path(original) for call in calls.call_args_list)
        self.assertEqual(count,2)  # One initial read and mandatory end-of-operation recheck.
        stat = os.stat(original)
        with self.assertRaisesRegex(ValueError,'Evidence changed'):
            with evidence_runtime.evidence_operation():
                images.context(self.p,self.path,'G01')
                payload = bytearray(Path(original).read_bytes()); payload[-1] ^= 1
                Path(original).write_bytes(payload)
                os.utime(original,ns=(stat.st_atime_ns,stat.st_mtime_ns))

    def test_prepare_accepts_ordered_paths_and_preserves_video_history(self):
        paths = [r['path'] for r in self.p['storyboard_images']]
        self.p['config']['workflow'] = 'video_evidence'
        self.p.pop('storyboard_images')
        core.save(self.path, self.p)
        batch.prepare(self.path, paths, self.path.parent/'ordered')
        current = core.read(self.path)
        self.assertTrue(images.enabled(current))
        self.assertEqual([r['path'] for r in current['storyboard_images']], paths)
        self.assertNotIn('video_source', current['config'])
        self.p['imported_videos'] = [dict(source='SIMULATED historical video')]
        core.save(self.path, self.p)
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '已有视频项目'):
            batch.prepare(self.path, paths, self.path.parent/'blocked')
        self.assertEqual(self.path.read_bytes(), original)

    def test_complete_prepares_prompt_once_or_defers_only_mixed_aspect(self):
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                if mixed:
                    Image.new('RGB', (90,160), 'green').save(self.p['storyboard_images'][0]['path'])
                prep = batch.prepare(self.path, None, self.path.parent/f'prep-{mixed}')
                self.p = core.read(self.path)
                core.save(prep['worklist'], self.worklist(self.review(fails=['S02'], critical=True)))
                result = batch.complete(self.path, prep['worklist'], self.path.parent/f'delivery-{mixed}',
                                        self.path.parent/f'done-{mixed}')
                self.assertEqual(result['status'], 'complete')
                self.assertTrue(Path(result['delivery']).is_file())
                self.assertTrue(result['decision']['triggered'])
                self.p = core.read(self.path)
                if mixed:
                    self.assertEqual(result['prompt_status'], 'needs_preparation')
                    self.assertIn('混用画幅', result['prompt_next_action'])
                    self.p['storyboard_target_aspect'] = '9:16'
                    self.assertEqual(quality.source_request(self.p, self.path, 'G01')['aspect_ratio'], '9:16')
                else:
                    self.assertEqual(result['prompt_status'], 'needs_semantic_review')
                    self.assertEqual(core.read(result['prompt_plan']), quality.compact_template(
                        quality.source_request(self.p, self.path, 'G01')))

    def test_original_prompt_is_bound_to_images_and_script_without_changing_review(self):
        self.ready(fails=['S02'], critical=True)
        old_review = core.review_current(self.p, self.path, 'G01')['id']
        source = repair_reference.register(self.p, self.path, 'G01', '雨夜冷光。角色开口说话并配字幕。')
        bound = repair.current_decision(self.p, self.path, 'G01')['binding']
        self.p['repair_prompt_references'] = {'G01': dict(source_sha256=source['text_sha256'],
            source_fingerprint=source['source_fingerprint'], script_fingerprint=bound['script_fingerprint'],
            preserves_story=True, compatibility_reason='SIMULATED script-compatible lighting, exclude speech',
            selections=[dict(shot_id='S01', source_quote='雨夜冷光。', script_quote=self.p['shots'][0]['script'],
                             visual_text='雨夜冷光。')],
            excluded=[dict(source_quote='角色开口说话并配字幕。', reason='静音且不能增加字幕')])}
        self.assertNotIn('video_sha256', source)
        self.assertEqual(core.review_current(self.p, self.path, 'G01')['id'], old_review)
        plan = self.simulated_plan()
        output = self.path.parent/'prompt.md'
        quality.finish_plan(self.p, self.path, 'G01', plan, output)
        self.assertIn('雨夜冷光', output.read_text(encoding='utf8'))
        frozen = output.read_bytes()
        repair_reference.register(self.p, self.path, 'G01', '暖色晨光。')
        with self.assertRaises(ValueError):
            quality.finish_plan(self.p, self.path, 'G01', plan, self.path.parent/'stale-prompt.md')
        self.assertEqual(output.read_bytes(), frozen)

    def test_cli_never_opens_original_prompt_below_threshold(self):
        missing = self.path.parent/'never-open.txt'
        prepdir = self.path.parent/'deferred-prep'
        with patch('sys.argv', ['prepare_storyboards.py', 'prepare', str(self.path), '--run-dir', str(prepdir),
                               '--original-prompt', str(missing)]), patch('builtins.print'):
            batch.main()
        self.p = core.read(self.path)
        self.assertNotIn('source_storyboard_prompts', self.p)
        self.assertNotIn('deferred_storyboard_prompts', core.read(prepdir/'CONTEXT.json'))
        core.save(prepdir/'WORKLIST.json', self.worklist(self.review(fails=['S02'])))
        result = batch.complete(self.path, prepdir/'WORKLIST.json', self.path.parent/'deferred-delivery',
                                self.path.parent/'deferred-finish')
        self.assertEqual(result['prompt_status'], 'below_threshold')
        self.assertNotIn('source_storyboard_prompts', core.read(self.path))
        self.assertIn('无需再次人工', result['delivery_next_action'])
        with self.assertRaisesRegex(ValueError, '未达阈值'):
            batch.load_original_prompt(core.read(self.path), self.path, 'G01')

    def test_original_prompt_first_read_after_threshold_preserves_review(self):
        source = self.path.parent/'deferred.txt'
        source.write_text('old prompt', encoding='utf8')
        prep = batch.prepare(self.path, None, self.path.parent/'read-prep', original_prompt_file=source)
        self.p = core.read(self.path)
        source.write_text('雨夜冷光。', encoding='utf-8-sig')
        core.save(prep['worklist'], self.worklist(self.review(fails=['S02'], critical=True)))
        result = batch.complete(self.path, prep['worklist'], self.path.parent/'read-delivery', self.path.parent/'read-done')
        p = core.read(self.path)
        self.assertTrue(result['decision']['triggered'])
        self.assertEqual(p['source_storyboard_prompts']['G01']['text'], '雨夜冷光。')
        self.assertEqual(result['prompt_status'], 'needs_preparation')  # Still needs compatibility screening.
        self.assertNotIn('G01', p['deferred_storyboard_prompts'])
        self.assertIsNotNone(core.review_current(p, self.path, 'G01'))
        source.unlink()
        batch.load_original_prompt(p, self.path, 'G01')  # Already registered; no second file read.

    def test_missing_triggered_prompt_keeps_report_and_can_resume_prompt_preparation(self):
        source = self.path.parent/'missing-prompt.txt'
        prep = batch.prepare(self.path, None, self.path.parent/'missing-prep', original_prompt_file=source)
        self.p = core.read(self.path)
        core.save(prep['worklist'], self.worklist(self.review(fails=['S02'], critical=True)))
        result = batch.complete(self.path, prep['worklist'], self.path.parent/'missing-delivery', self.path.parent/'missing-done')
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['prompt_status'], 'needs_preparation')
        frozen = Path(result['delivery']).read_bytes()
        source.write_text('新增冷光参考。', encoding='utf8')
        with patch('sys.argv', ['repair_quality.py', 'prepare', str(self.path), 'G01', str(self.path.parent/'prompt.json')]), \
             self.assertRaisesRegex(ValueError, 'batch repair_prompt_references'):
            quality.main()
        p = core.read(self.path)
        self.assertEqual(p['source_storyboard_prompts']['G01']['text'], '新增冷光参考。')
        self.assertEqual(Path(result['delivery']).read_bytes(), frozen)
        self.assertIsNotNone(core.review_current(p, self.path, 'G01'))

    def test_delivery_rejects_incorrect_cells_even_with_fresh_file_hashes(self):
        self.ready(uncertain=['S02'])
        md = Path(repair.snapshot(self.p, self.path, self.path.parent/'checked', 'original'))
        original = md.read_text(encoding='utf8')
        record = self.p['repair_deliveries']['original']
        for index, replacement in ((0, 'wrong-group'), (2, '99 秒'), (3, 'wrong-script'), (5, '检验通过'),
                                   (6, '保留图'), (7, 'S01 + S03'), (8, '符合脚本')):
            lines = original.splitlines()
            line_no = next(i for i, line in enumerate(lines) if line.startswith('|') and '| S02 |' in line)
            cells = lines[line_no].split('|')
            cells[index+1] = ' ' + replacement + ' '
            lines[line_no] = '|'.join(cells)
            md.write_text('\n'.join(lines), encoding='utf8')
            record['files'][str(md)] = core.sha(md)
            with self.subTest(column=index), self.assertRaisesRegex(ValueError, 'content differs'):
                finish_review.validate_delivery(self.p, 'original', self.path)

    def test_delivery_rejects_swapped_links_originals_previews_and_extra_files(self):
        self.ready(omit=True)
        md = Path(repair.snapshot(self.p, self.path, self.path.parent/'checked', 'original'))
        record = self.p['repair_deliveries']['original']
        files = {Path(f): Path(f).read_bytes() for f in record['files']}
        first = next(f for f in files if f.name.startswith('S01-'))
        second = next(f for f in files if f.name.startswith('S02-'))
        thumb1 = next(f for f in files if f.name.startswith('thumb-S01-'))
        thumb2 = next(f for f in files if f.name.startswith('thumb-S02-'))
        for wrong in ('links', 'original', 'preview', 'extra'):
            for file, content in files.items():
                file.write_bytes(content)
                record['files'][str(file)] = core.sha(file)
            if wrong == 'links':
                md.write_text(md.read_text(encoding='utf8').replace(first.name, second.name), encoding='utf8')
                target = md
            elif wrong == 'original':
                first.write_bytes(second.read_bytes())
                target = first
            elif wrong == 'preview':
                thumb1.write_bytes(thumb2.read_bytes())
                target = thumb1
            else:
                target = md.parent/'INTERNAL.json'
                target.write_text('{}', encoding='utf8')
            record['files'][str(target)] = core.sha(target)
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                finish_review.validate_delivery(self.p, 'original', self.path)

    def test_failed_automatic_delivery_check_does_not_freeze_bad_output(self):
        import storyboard
        real_thumbnail = storyboard.thumbnail
        def wrong_thumbnail(source, destination, sid, label, warning=''):
            real_thumbnail(source, destination, sid, label, warning)
            if sid == 'S02':
                Image.new('RGB', (240, 168), 'red').save(destination)
        prep = batch.prepare(self.path, None, self.path.parent/'bad-render-prep')
        self.p = core.read(self.path)
        core.save(prep['worklist'], self.worklist(self.review()))
        with patch('storyboard.thumbnail', side_effect=wrong_thumbnail), self.assertRaisesRegex(ValueError, 'thumbnail does not match'):
            batch.complete(self.path, prep['worklist'], self.path.parent/'bad-render', self.path.parent/'bad-render-done')
        self.assertNotIn('original', core.read(self.path).get('repair_deliveries', {}))
        self.assertEqual(core.read(self.path.parent/'bad-render-done/FINISH_REPORT.json')['status'], 'failed')

    def test_exif_display_aspect_and_original_bytes_are_preserved(self):
        path = self.path.parent/'oriented.jpg'
        exif = Image.Exif(); exif[274] = 6
        Image.new('RGB', (160,90), 'green').save(path, exif=exif)
        original = path.read_bytes()
        self.p['storyboard_images'] = [dict(shot_id=s['id'], path=str(path)) for s in self.p['shots']]
        self.ready()
        source = images.context(self.p, self.path, 'G01')['source_fingerprint']
        self.assertEqual(images.source_aspect(self.p, self.path, source)['aspect_ratio'], '9:16')
        delivery = repair.snapshot(self.p, self.path, self.path.parent/'oriented-delivery', 'original')
        originals = list((Path(delivery).parent/'images').glob('*.jpg'))
        self.assertEqual(len(originals), 3)
        self.assertTrue(all(item.read_bytes() == original for item in originals))

    def test_visible_character_conflict_and_same_shot_image_evidence(self):
        r = self.review(fails=['S02'])
        row = r['shot_reviews'][1]
        row['checks'].update(identity='FAIL', props='PASS')
        asset = next(a for a in self.p['assets'] if a['kind'] == 'character'
                     and a['id'] in self.p['shots'][1]['asset_ids'])
        comparison = dict(id='identity-S02', shot_id='S02', asset_id=asset['id'], aspect='appearance',
            asset_sha256=core.sha(Path(asset['path'])), story_requirement='SIMULATED required adult character',
            story_impact='SIMULATED adult replaced by a child, required actor relationship changes',
            evidence_refs=[{k:r['evidence'][1][k] for k in ('path','sha256')}], condition_factors=[],
            stable_matches=[], stable_conflicts=[dict(feature='age', expected='adult', observed='child',
                environment_exclusion='SIMULATED clearly visible at full size')], decision='FAIL',
            unobservable_features=[], followup='', basis_shot_ids=[])
        r['asset_comparisons'] = [comparison]
        r['issues'][0].update(asset_ids=[asset['id']], asset_comparison_ids=[comparison['id']],
            problem='SIMULATED wrong actor', actual='SIMULATED child replaces required adult', fix='恢复脚本人物。')
        self.assertEqual(core.record_review(self.p, self.path, r), 'FAIL')
        for bad in ('borrowed', 'timestamp', 'issue-path'):
            with self.subTest(bad=bad):
                invalid = copy.deepcopy(r)
                if bad == 'borrowed':
                    invalid['asset_comparisons'][0]['evidence_refs'] = [
                        {k:r['evidence'][0][k] for k in ('path','sha256')}]
                elif bad == 'timestamp':
                    invalid['evidence'][1]['time'] = 1.0
                else:
                    invalid['issues'][0]['evidence'] = [r['evidence'][0]['path']]
                with self.assertRaises(ValueError):
                    core.record_review(self.p, self.path, invalid)
