"""Compact single-write conclusions with simulated judgments and real input images."""
import copy
from pathlib import Path

import storyboard_fixtures as fixtures
import test_storyboard_images as existing
import test_single_pass_review as single
import previs as core
import prepare_storyboards as batch
import storyboard_conclusions as concise
import storyboard_inputs as images
import planner
import repair_cycle as repair


class ConclusionTests(fixtures.Base):
    setUp = single.SinglePassTests.setUp
    compact_input = existing.StoryboardImagesTests.compact_input

    def work(self, ctx):
        result = concise.draft(ctx)
        result['grouping_checked'] = True
        for row in result['shots']:
            row.update(verdict='PASS', reference_phase='entry', match_level=2)
            row['observation']['visible_facts'] = ['SIMULATED actors and required key visible before handoff']
        return result

    def fail(self, ctx, work, index=0, kind='ordinary'):
        work['shots'][index].update(verdict='FAIL', match_level=None)
        finding = dict(check='props', script_quote=ctx['shots'][index]['script'],
            actual='SIMULATED wrong key holder visible', fix='修改该分镜图的钥匙持有者，保持脚本。',
            kind=kind, affects_story=kind != 'ordinary', preserves_script=True)
        if kind != 'ordinary':
            finding['impact'] = 'SIMULATED necessary handoff result is contradicted or obscured'
        if kind == 'severe_visual_damage':
            finding.update(check='cleanliness', damage_description='SIMULATED corrupt hands and key',
                           obscured_content='SIMULATED required holder relationship')
        work['shots'][index]['findings'] = [finding]
        return finding

    def decide(self, ctx, work):
        images.record_review(self.p, self.path, batch.expand(ctx, work))
        planner.store_aggregation(self.p, self.path, planner.post_review_plan(self.p, self.path, {}))
        return repair.decide(self.p, self.path, 'G01')

    def crop_and_facing_input(self):
        data = self.compact_input()
        for aid, description in [('trophy', '奖杯'), ('box', '木箱')]:
            data['assets'].append(dict(id=aid, kind='prop', description=description,
                                       path=str(self.png(aid))))
        scripts = ['女孩高举奖杯。', '女孩站在木箱上。', '女孩面朝门口站立。']
        data['source_script'] = '\n'.join(scripts)
        data['shots'] = [dict(id=old['id'], script=script, image=old['image'],
            duration=old['duration'], duration_source=old['duration_source'],
            scene_id='hall', continuity_id='ceremony', required_result=script,
            intent=dict(critical_result=False, narrative_turn=False, required_cut=False),
            asset_ids=['girl', 'hall'] + (['trophy'] if i == 0 else ['box'] if i == 1 else []),
            requirements=dict(status='ready', keyframe=dict(phase='entry', description=script),
                provenance=[dict(field='purpose,keyframe', status='script', source=script)]))
            for i, (old, script) in enumerate(zip(data['shots'], scripts))]
        return data

    def test_offscreen_prop_and_support_pass_but_wrong_facing_is_delivered_as_failure(self):
        data = self.crop_and_facing_input()
        root = self.path.parent
        project = root / 'cropped-project.json'
        prepared = batch.prepare(project, None, root / 'cropped-prepare', input_data=data,
                                 output=root / 'cropped-delivery', concise=True)
        ctx = core.read(prepared['context'])
        work = self.work(ctx)
        work['overview_manifest'] = core.read(prepared['worklist'])['overview_manifest']
        observations = [
            ['SIMULATED 双臂高举，双手与上方物体在画面外；未见奖杯本体'],
            ['SIMULATED 女孩站立，上身姿态正常；双脚和下方支撑物在画面外'],
            ['SIMULATED 女孩背对门口，脸朝向室内后墙'],
        ]
        for row, facts in zip(work['shots'], observations):
            row['observation']['visible_facts'] = facts
            row['match_level'] = 3
        work['shots'][2].update(verdict='FAIL', match_level=None, findings=[dict(
            check='composition', script_quote='面朝门口', actual='背对门口，脸朝向室内后墙',
            fix='将女孩改为面朝门口，保留其他脚本内容。', kind='ordinary',
            affects_story=False, preserves_script=True)])
        core.save(prepared['worklist'], work)
        result = batch.complete(project, prepared['worklist'], root / 'cropped-delivery', root / 'cropped-finish')
        saved = core.read(project)
        rows = saved['reviews'][-1]['shot_reviews']
        self.assertEqual([row['verdict'] for row in rows], ['PASS', 'PASS', 'FAIL'])
        self.assertEqual(rows[0]['checks']['props'], 'PASS')
        self.assertEqual(rows[1]['checks']['scene'], 'PASS')
        self.assertEqual(rows[2]['checks']['composition'], 'FAIL')
        self.assertFalse(result['decision']['triggered'])
        self.assertEqual(result['decision']['error_count'], 1)
        evidence = saved['reviews'][-1]['evidence']
        self.assertEqual([row['visible_facts'] for row in evidence], observations)
        report = Path(result['delivery']).read_text(encoding='utf-8')
        self.assertEqual(report.count('| 符合脚本 |'), 2)
        self.assertIn('将女孩改为面朝门口', report)
        self.assertEqual(len(list((root / 'cropped-delivery/images').glob('S*.png'))), 3)

    def test_visible_conflicts_and_unknown_facing_keep_distinct_verdicts(self):
        for index, check, actual, fix in [
            (0, 'props', 'SIMULATED 双手完整入画且明确空手', '补回脚本奖杯'),
            (1, 'scene', 'SIMULATED 双脚完整入画并直接踩在地板上', '恢复站在木箱上'),
        ]:
            script = self.crop_and_facing_input()['shots'][index]['script']
            shot = dict(shot_id='S01', script=script)
            row = dict(shot_id='S01', verdict='FAIL', reference_phase='entry', match_level=None,
                observation=dict(visible_facts=[actual]), unresolved=[], findings=[dict(
                    check=check, script_quote=script, actual=actual, fix=fix,
                    kind='ordinary', affects_story=True, preserves_script=True)])
            with self.subTest(check=check):
                target, checks, issues, assessment = concise.row_records(shot, row)
                self.assertEqual(target['verdict'], 'FAIL')
                self.assertEqual(checks[check], 'FAIL')
                self.assertEqual(target['reference']['decision'], 'pending')
        shot = dict(shot_id='S03', script='女孩面朝门口站立。')
        row = dict(shot_id='S03', verdict='uncertain', reference_phase='entry', match_level=None,
            observation=dict(visible_facts=['SIMULATED 门口未入画，人物与门的朝向关系无法确定']),
            findings=[], unresolved=[dict(check='composition', reason='无法确定人物是否面朝门口')])
        target, checks, issues, assessment = concise.row_records(shot, row)
        self.assertEqual(checks['composition'], 'uncertain')
        self.assertEqual(target['reference']['decision'], 'pending')
        self.assertEqual(issues, [])
        self.assertIsNone(assessment)

    def test_camera_angle_can_pass_but_recorded_facing_error_cannot_be_relaxed(self):
        shot = dict(shot_id='S03', script='女孩面朝门口站立。')
        row = dict(shot_id='S03', verdict='PASS', reference_phase='entry', match_level=1,
            observation=dict(visible_facts=['SIMULATED 机位反打后人物投影左右改变，但脸仍朝门口']),
            findings=[], unresolved=[])
        target, checks, issues, assessment = concise.row_records(shot, row)
        self.assertEqual(target['verdict'], 'PASS')
        self.assertEqual(issues, [])
        row['findings'] = [dict(check='composition', script_quote='面朝门口', actual='SIMULATED 明确背向门口',
            fix='改为面朝门口', kind='ordinary', affects_story=False, preserves_script=True)]
        for level in range(4):
            row['match_level'] = level
            with self.subTest(level=level), self.assertRaises(ValueError):
                concise.row_records(shot, row)

    def test_pre_policy_review_fingerprint_is_rejected_without_changing_project(self):
        ctx = images.context(self.p, self.path, 'G01')
        old = copy.deepcopy(ctx)
        old['review_scope'].pop('offscreen_rule')
        old['review_scope'].pop('facing_rule')
        old.pop('context_fingerprint')
        old['context_fingerprint'] = core.digest(old)
        review = batch.expand(old, self.work(old))
        before = copy.deepcopy(self.p)
        with self.assertRaisesRegex(ValueError, 'context_fingerprint'):
            images.record_review(self.p, self.path, review)
        self.assertEqual(self.p, before)

    def test_pass_fail_uncertain_complete_from_one_error_record(self):
        prepared = batch.prepare(self.path, None, self.run, concise=True)
        ctx = core.read(prepared['context'])
        work = self.work(ctx)
        work['overview_manifest'] = core.read(prepared['worklist'])['overview_manifest']
        self.fail(ctx, work)
        work['shots'][1].update(verdict='uncertain', match_level=None, reference_phase='unknown',
            unresolved=[dict(check='props', reason='SIMULATED holder is concealed')])
        self.assertNotIn('issues', work)
        self.assertNotIn('repair_assessments', work)
        expanded = batch.expand(ctx, work)
        self.assertEqual(expanded['issues'][0]['actual'], work['shots'][0]['findings'][0]['actual'])
        self.assertEqual(expanded['repair_assessments'][0]['correction'], work['shots'][0]['findings'][0]['fix'])
        core.save(prepared['worklist'], work)
        resumed = batch.resume(self.path, self.run, page=1)
        self.assertEqual(resumed['progress']['incomplete_record_shot_ids'], [])
        self.assertEqual(resumed['view']['images_to_open'], [])
        self.assertEqual(resumed['unresolved_items'][0]['reason'], 'SIMULATED holder is concealed')
        result = batch.complete(self.path, prepared['worklist'], self.path.parent / 'delivery', self.path.parent / 'finish')
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['decision']['triggered'])
        report = Path(result['delivery']).read_text(encoding='utf-8')
        self.assertIn('修改该分镜图的钥匙持有者', report)
        self.assertIn('SIMULATED holder is concealed', report)
        self.assertIn('| — | 暂不省图 |', report)
        self.assertEqual(len([line for line in report.splitlines() if line.startswith('|')]), 5)
        self.assertEqual(len(list((self.path.parent / 'delivery/images').glob('S*.png'))), 3)
        self.assertEqual({item.name for item in (self.path.parent / 'delivery').iterdir()},
                         {'01_分镜图审查.md', 'images'})

    def test_optional_planner_facts_complete_once_with_pass_fail_uncertain(self):
        data = self.compact_input()
        for shot in data['shots']:
            shot.pop('facts')
            shot.pop('omission_assessment', None)
        root = self.path.parent
        project, output = root / 'minimal.json', root / 'empty-delivery'
        output.mkdir()
        prepared = batch.prepare(project, None, root / 'minimal-prep', input_data=data,
                                 output=output, concise=True)
        p = core.read(project)
        self.assertTrue(all(s['facts'] == [] for s in p['shots']))
        ctx = core.read(prepared['context'])
        work = self.work(ctx)
        work['overview_manifest'] = core.read(prepared['worklist'])['overview_manifest']
        self.fail(ctx, work, index=1)
        work['shots'][2].update(verdict='uncertain', match_level=None, reference_phase='unknown',
            unresolved=[dict(check='props', reason='SIMULATED necessary prop concealed')])
        core.save(prepared['worklist'], work)
        result = batch.complete(project, prepared['worklist'], output, root / 'minimal-finish')
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['decision']['triggered'])
        self.assertEqual(result['decision']['error_count'], 1)
        report = Path(result['delivery']).read_text(encoding='utf-8')
        self.assertIn('符合脚本', report)
        self.assertIn('修改该分镜图的钥匙持有者', report)
        self.assertIn('SIMULATED necessary prop concealed', report)
        for shot in data['shots']:
            saved = next((output / 'images').glob(shot['id'] + '*.png'))
            self.assertEqual(saved.read_bytes(),
                             Path(shot['image']).read_bytes())
        aggregation = core.read(project)['aggregation']
        self.assertTrue(all(s['mode'] != 'ai_fill' for s in aggregation['decisions']))

    def test_missing_planner_facts_never_approve_omission(self):
        self.p['shots'][1]['facts'] = []
        ctx = images.context(self.p, self.path, 'G01')
        work = self.work(ctx)
        work['shots'][1]['reference'] = dict(decision='ai_fill', derivable=True,
            basis_shot_ids=['S01', 'S03'], reason='SIMULATED two-sided matching state')
        images.record_review(self.p, self.path, batch.expand(ctx, work))
        plan = planner.post_review_plan(self.p, self.path, {})
        row = next(s for s in plan['decisions'] if s['shot_id'] == 'S02')
        self.assertEqual(row['mode'], 'anchor')
        self.assertIn('FACTS_UNRECORDED', row['rules'])

    def test_minimal_input_template_delivers_without_state_bookkeeping(self):
        data = core.read(fixtures.ROOT / 'ai-storyboard-previs/assets/storyboard-input-minimal.json')
        for asset in data['assets']:
            asset['path'] = str(self.png('minimal-' + asset['id']))
        for shot in data['shots']:
            shot['image'] = str(self.png('minimal-' + shot['id']))
        root = self.path.parent
        project = root / 'template-project.json'
        prepared = batch.prepare(project, None, root / 'template-prepare', input_data=data,
                                 output=root / 'template-delivery', concise=True)
        ctx = core.read(prepared['context'])
        work = self.work(ctx)
        work['overview_manifest'] = core.read(prepared['worklist'])['overview_manifest']
        for shot, row in zip(data['shots'], work['shots']):
            row['reference_phase'] = shot['requirements']['keyframe']['phase']
            row['observation']['visible_facts'] = ['SIMULATED: ' + shot['requirements']['keyframe']['description']]
        core.save(prepared['worklist'], work)
        result = batch.complete(project, prepared['worklist'], root / 'template-delivery', root / 'template-finish')
        self.assertEqual(result['status'], 'complete')
        self.assertFalse(result['decision']['triggered'])
        report = Path(result['delivery']).read_text(encoding='utf-8')
        self.assertEqual(report.count('| 符合脚本 |'), 2)
        self.assertIn('男孩接住钥匙，女孩松手', report)
        self.assertEqual(len(list((root / 'template-delivery/images').glob('S*.png'))), 2)

    def test_omission_keeps_existing_two_sided_requirements(self):
        ctx = images.context(self.p, self.path, 'G01')
        good = self.work(ctx)
        good['shots'][1]['reference'] = dict(decision='ai_fill', derivable=True,
            basis_shot_ids=['S01', 'S03'], reason='同组双侧锚点与原资产支撑同场可见状态，无新增必要剧情')
        images.record_review(self.p, self.path, batch.expand(ctx, good))
        self.assertEqual(self.p['reviews'][-1]['reference_assessments'][1]['decision'], 'ai_fill')
        for kind in ('one_side', 'reason', 'failed_anchor', 'uncertain_target', 'cross_group'):
            bad = copy.deepcopy(good)
            if kind == 'one_side':
                bad['shots'][1]['reference']['basis_shot_ids'] = ['S01']
            elif kind == 'reason':
                bad['shots'][1]['reference'].pop('reason')
            elif kind == 'failed_anchor':
                self.fail(ctx, bad)
            elif kind == 'uncertain_target':
                bad['shots'][1].update(verdict='uncertain', match_level=None,
                    unresolved=[dict(check='props', reason='SIMULATED invisible holder')])
            else:
                self.p['input_shot_groups'] = [dict(id='A01', shot_ids=['S01', 'S02']),
                                              dict(id='A02', shot_ids=['S03'])]
                ctx = images.context(self.p, self.path, 'G01')
                bad['context_fingerprint'] = ctx['context_fingerprint']
                images.record_review(self.p, self.path, batch.expand(ctx, bad))
                plan = planner.post_review_plan(self.p, self.path, {})
                target = next(item for item in plan['decisions'] if item['shot_id'] == 'S02')
                self.assertNotEqual(target['mode'], 'ai_fill')
                continue
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                images.record_review(self.p, self.path, batch.expand(ctx, bad))

    def test_empty_facts_unknown_phase_and_unfinished_verdict_never_approve(self):
        ctx = images.context(self.p, self.path, 'G01')
        for kind in ('facts', 'phase', 'verdict', 'level', 'groups', 'silent_failure'):
            bad = self.work(ctx)
            if kind == 'facts':
                bad['shots'][0]['observation']['visible_facts'] = []
            elif kind == 'phase':
                bad['shots'][0]['reference_phase'] = 'unknown'
            elif kind == 'verdict':
                bad['shots'][0]['verdict'] = None
            elif kind == 'level':
                bad['shots'][0]['match_level'] = 4
            elif kind == 'groups':
                bad['reviewed_groups'] = ['content']
            else:
                self.fail(ctx, bad)
                bad['shots'][0]['verdict'] = 'PASS'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                images.record_review(self.p, self.path, batch.expand(ctx, bad))

    def test_error_evidence_and_severity_remain_explicit(self):
        ctx = images.context(self.p, self.path, 'G01')
        for field in ('check', 'script_quote', 'actual', 'fix', 'kind', 'affects_story', 'preserves_script'):
            bad = self.work(ctx)
            self.fail(ctx, bad).pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                batch.expand(ctx, bad)
        bad = self.work(ctx)
        self.fail(ctx, bad)['script_quote'] = 'SIMULATED invented quote absent from script'
        with self.assertRaises(ValueError):
            batch.expand(ctx, bad)

    def test_threshold_boundary_with_grouping_and_uncertainty(self):
        seed = copy.deepcopy(self.p['shots'][0])
        for count in (10, 11):
            with self.subTest(count=count):
                self.p['shots'] = [dict(copy.deepcopy(seed), id=f'S{i:02d}') for i in range(1, count + 1)]
                ids = [s['id'] for s in self.p['shots']]
                self.p['source_script'] = '\n'.join(s['script'] for s in self.p['shots'])
                self.p['groups'] = [dict(id='G01', shot_ids=ids, version=1)]
                self.p['input_shot_groups'] = [dict(id='A01', shot_ids=ids[:5]), dict(id='A02', shot_ids=ids[5:])]
                self.p['storyboard_images'] = [dict(shot_id=sid, path=str(self.png(sid))) for sid in ids]
                self.p.pop('repair_baseline', None)
                ctx = images.context(self.p, self.path, 'G01')
                work = self.work(ctx)
                self.fail(ctx, work, 0)
                self.fail(ctx, work, 1)
                work['shots'][-1].update(verdict='uncertain', match_level=None,
                    unresolved=[dict(check='props', reason='SIMULATED concealed prop')])
                decision = self.decide(ctx, work)
                self.assertEqual(decision['triggered'], count == 10)
                self.assertEqual((decision['error_count'], decision['total']), (2, count))

    def test_critical_and_severe_damage_each_trigger_with_bound_original(self):
        ctx = images.context(self.p, self.path, 'G01')
        for kind in ('wrong_transfer_result', 'severe_visual_damage'):
            with self.subTest(kind=kind):
                work = self.work(ctx)
                finding = self.fail(ctx, work, kind=kind)
                decision = self.decide(ctx, work)
                self.assertEqual(decision['trigger'], 'critical' if kind == 'wrong_transfer_result' else kind)
                if kind == 'severe_visual_damage':
                    damage = self.p['reviews'][-1]['repair_assessments'][0]['severe_visual_damage']
                    self.assertEqual(damage['image_sha256'], ctx['shots'][0]['image']['sha256'])
                finding.pop('impact')
                with self.assertRaises(ValueError):
                    batch.expand(ctx, work)

    def test_source_changes_invalidate_compact_conclusions(self):
        ctx = images.context(self.p, self.path, 'G01')
        work = self.work(ctx)
        seed = copy.deepcopy(self.p)
        for kind in ('image', 'asset', 'script', 'requirement', 'group'):
            self.p = copy.deepcopy(seed)
            path, content = None, None
            if kind in ('image', 'asset'):
                path = Path(self.p['storyboard_images'][0]['path'] if kind == 'image' else self.p['assets'][0]['path'])
                content = path.read_bytes()
                self.png(path.stem, (255, 20, 40))
            elif kind == 'script':
                self.p['shots'][0]['script'] += ' changed'
            elif kind == 'requirement':
                self.p['shots'][0]['requirements']['must_have'].append('SIMULATED new visible requirement')
            else:
                self.p['input_shot_groups'] = [dict(id='A01', shot_ids=['S01', 'S02', 'S03'])]
            try:
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    batch.expand(images.context(self.p, self.path, 'G01'), work)
            finally:
                if path:
                    path.write_bytes(content)

    def test_clean_delivery_keeps_group_diagnostics_internal(self):
        self.p['input_shot_groups'] = [dict(id='A01', shot_ids=['S01', 'S02']),
                                      dict(id='A01', shot_ids=['S03'])]
        core.save(self.path, self.p)
        prepared = batch.prepare(self.path, None, self.run, concise=True)
        work = self.work(core.read(prepared['context']))
        work['overview_manifest'] = core.read(prepared['worklist'])['overview_manifest']
        core.save(prepared['worklist'], work)
        result = batch.complete(self.path, prepared['worklist'], self.path.parent / 'delivery', self.path.parent / 'finish')
        report = Path(result['delivery']).read_text(encoding='utf-8')
        for phrase in ('全部输入原图', '时长采用脚本计划值', '分组冲突：', '输入分组存在冲突', '需放大原图'):
            self.assertNotIn(phrase, report)
        self.assertLess(report.index('共 3 镜。'), report.index('| 分组 |'))
        project = core.read(self.path)
        self.assertFalse(project['aggregation']['feasible'])
        self.assertTrue(project['aggregation']['limitations'])
        self.assertNotIn('建议省图', report)

    def test_first_facts_reuse_and_partial_resume_do_not_approve(self):
        import storyboard_overviews as overviews
        first = overviews.build_initial(self.compact_input(), self.path.parent / 'first')
        observations = core.read(first['observations'])
        observations['shots'][0]['visible_facts'] = ['SIMULATED already viewed image']
        core.save(first['observations'], observations)
        prepared = batch.prepare(self.path, None, self.run, concise=True, reuse_overviews=self.path.parent / 'first')
        self.assertEqual(prepared['worklist_version'], 4)
        work = core.read(prepared['worklist'])
        self.assertIsNone(work['shots'][0]['verdict'])
        resumed = batch.resume(self.path, self.run, page=1)
        self.assertEqual(resumed['progress']['recorded_shot_ids'], ['S01'])
        self.assertEqual(resumed['progress']['incomplete_record_shot_ids'], ['S01', 'S02', 'S03'])
        with self.assertRaises(ValueError):
            batch.expand(core.read(prepared['context']), work)
