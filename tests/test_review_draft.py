"""Mechanical drafting must retain evidence fidelity and require real judgments."""
import copy
from pathlib import Path
import subprocess
import sys
import unittest
import test_imported_review as imported
import test_previs as fixtures
import previs as core
import review_draft
import storyboard
import test_repair_cycle as repair_fixtures
from validation import ValidationError


class ReviewDraftTests(fixtures.Base):
    png = imported.ImportedReviewTests.png
    select_mapping = imported.ImportedReviewTests.select_mapping
    mapping = imported.ImportedReviewTests.mapping
    review_data = imported.ImportedReviewTests.review_data

    def setUp(self):
        imported.ImportedReviewTests.setUp(self)

    def prepare(self, statuses=None):
        self.mapping(statuses)
        core.save(self.path, self.p)
        return review_draft.prepare(self.path, 'G01', self.path.parent / 'draft.json')

    def test_draft_copies_exact_times_and_provenance_but_cannot_commit(self):
        draft = self.prepare()
        before = self.path.read_bytes()
        ctx = core.video_context(self.p, self.path, 'G01')
        self.assertEqual(ctx['shots'][0]['requirements_provenance'], self.p['shots'][0]['requirements']['provenance'])
        for row, shot in zip(draft['evidence'], ctx['shots']):
            self.assertEqual(row['time'], shot['selected_frame']['source']['time'])
            self.assertEqual(row['sha256'], shot['selected_frame']['sha256'])
            self.assertEqual(row['observation'], '')
        self.assertTrue(all(r['verdict'] == 'uncertain' for r in draft['shot_reviews']))
        with self.assertRaises(ValueError):
            review_draft.check(self.path, draft)
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'new draft'):
            review_draft.prepare(self.path, 'G01', self.path.parent / 'draft.json')

    def test_absence_and_uncertainty_never_get_fabricated_frames(self):
        draft = self.prepare({'S02': 'absent', 'S03': 'uncertain'})
        self.assertEqual([r['verdict'] for r in draft['shot_reviews']], ['uncertain', 'absent', 'uncertain'])
        self.assertEqual([r['shot_id'] for r in draft['evidence']], ['S01'])
        self.assertEqual(draft['reference_assessments'][1]['derivable'], None)

    def test_candidate_notes_reused_without_approving_or_combining_frames(self):
        mapping = self.mapping()
        first = mapping['shots'][0]['candidates'][0]
        first.update(observation='SIMULATED hand beside key', visible_facts=['SIMULATED key on table'],
                     interpretation='DO NOT COPY', verdict='PASS')
        extra = self.png('extra', (20, 40, 60))
        frame = dict(path=str(extra), sha256=core.sha(extra), time=.75)
        extracted = core.read(mapping['evidence_file'])
        extracted['frames'].insert(1, frame)
        core.save(mapping['evidence_file'], extracted)
        mapping['shots'][0]['observation'] = 'Whole-shot summary: key was picked up'
        mapping['shots'][0]['candidates'].append(dict(
            frame, observation='SIMULATED later frame', visible_facts=['SIMULATED key in hand']))
        storyboard.record_mapping(self.p, self.path, mapping)
        self.select_mapping('G01')
        core.save(self.path, self.p)
        before = self.path.read_bytes()
        draft = review_draft.prepare(self.path, 'G01', self.path.parent / 'notes.json')
        notes = [e for e in draft['evidence'] if e['shot_id'] == 'S01']
        self.assertEqual([e['time'] for e in notes], [.25, .75])
        self.assertEqual([e['visible_facts'] for e in notes],
                         [['SIMULATED key on table'], ['SIMULATED key in hand']])
        self.assertTrue(all(e['interpretation'] == '' for e in notes))
        self.assertEqual(draft['shot_reviews'][0]['evidence_times'], [.25, .75])
        self.assertTrue(all(r['verdict'] == 'uncertain' for r in draft['shot_reviews']))
        self.assertTrue(all(r['decision'] == 'pending' for r in draft['reference_assessments']))
        self.assertEqual(draft['evidence'][2]['observation'], '')  # Legacy shot summaries are not frame facts.
        with self.assertRaises(ValueError):
            review_draft.check(self.path, draft)
        self.assertEqual(self.path.read_bytes(), before)
        # Draft edits cannot mutate the canonical notes.
        draft['evidence'][0]['visible_facts'].append('new draft fact')
        self.assertEqual(self.p['board_mappings'][-1]['shots'][0]['candidates'][0]['visible_facts'],
                         ['SIMULATED key on table'])

    def test_invalid_candidate_notes_and_stale_note_binding_rejected(self):
        mapping = self.mapping()
        for notes in ({'observation': 'summary only'}, {'visible_facts': ['fact']},
                      {'observation': 'summary', 'visible_facts': []},
                      {'observation': 'summary', 'visible_facts': 'not a list'}):
            bad = copy.deepcopy(mapping)
            bad['shots'][0]['candidates'][0].update(notes)
            count = len(self.p['board_mappings'])
            with self.assertRaisesRegex(ValueError, 'candidate observation'):
                storyboard.record_mapping(self.p, self.path, bad)
            self.assertEqual(len(self.p['board_mappings']), count)
        for changed in ({'sha256': 'old-frame'}, {'time': .2505}, {'sha256': None}):
            bad = copy.deepcopy(mapping)
            bad['shots'][0]['candidates'][0].update(
                observation='SIMULATED old fact', visible_facts=['SIMULATED old fact'], **changed)
            with self.assertRaisesRegex(ValueError, 'exact current frame'):
                storyboard.record_mapping(self.p, self.path, bad)
        ctx = core.video_context(self.p, self.path, 'G01')
        candidate = ctx['mapping']['shots'][0]['candidates'][0]
        candidate.update(observation='fact', visible_facts=['fact'], sha256='stale')
        with self.assertRaisesRegex(ValueError, 'current extraction'):
            review_draft.from_context(ctx)

    def test_context_and_draft_share_binding_keep_full_evidence_and_never_overwrite(self):
        self.mapping()
        core.save(self.path, self.p)
        output, context_output = self.path.parent / 'draft.json', self.path.parent / 'context.json'
        before = self.path.read_bytes()
        draft = review_draft.prepare(self.path, 'G01', output, context_output)
        ctx = core.read(context_output)
        expected = core.video_context(self.p, self.path, 'G01')
        self.assertEqual(ctx['context_fingerprint'], draft['context_fingerprint'])
        for field in ('extraction', 'mapping', 'shots', 'assets', 'boundaries', 'narrative_plan'):
            self.assertEqual(ctx[field], expected[field])
        self.assertNotIn('previous_review', ctx)
        self.assertEqual(self.path.read_bytes(), before)
        new_output = self.path.parent / 'new.json'
        with self.assertRaisesRegex(ValueError, 'distinct new context'):
            review_draft.prepare(self.path, 'G01', new_output, context_output)
        self.assertFalse(new_output.exists())
        with self.assertRaisesRegex(ValueError, 'distinct new context'):
            review_draft.prepare(self.path, 'G01', new_output, new_output)
        self.assertFalse(new_output.exists())

    def test_batch_diagnostics_and_valid_check_are_read_only(self):
        self.prepare()
        good = self.review_data()
        before = self.path.read_bytes()
        bad = copy.deepcopy(good)
        bad['evidence'][0]['time'] += .123456
        bad['evidence'][1]['sha256'] = 'wrong'
        bad['shot_reviews'][2]['reason'] = ''
        with self.assertRaises(ValidationError) as caught:
            review_draft.check(self.path, bad)
        paths = {r['path'] for r in caught.exception.errors}
        self.assertTrue({'evidence[0].time', 'evidence[1].sha256', 'shot_reviews[2].reason'} <= paths)
        self.assertTrue(review_draft.check(self.path, good)['valid'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_stale_context_and_changed_frame_rejected(self):
        self.prepare()
        review = self.review_data()
        review['context_fingerprint'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'stale'):
            review_draft.check(self.path, review)
        review = self.review_data()
        core.resolve(self.path, review['evidence'][0]['path']).write_bytes(b'changed frame')
        with self.assertRaises(ValueError):
            review_draft.check(self.path, review)

    def test_worklist_fills_semantics_without_changing_bindings(self):
        self.mapping()
        core.save(self.path, self.p)
        draft = review_draft.prepare(self.path, 'G01', self.path.parent / 'draft.json',
                                     self.path.parent / 'context.json', self.path.parent / 'worklist.json')
        edits = core.read(self.path.parent / 'worklist.json')
        self.assertEqual(review_draft.fill(draft, edits), draft)
        self.assertTrue(all(s['repair']['critical'] is None for s in edits['shots'].values()))
        good = self.review_data()
        for row in good['shot_reviews']:
            sid = row['shot_id']
            for k in edits['shots'][sid]['review']:
                edits['shots'][sid]['review'][k] = row.get(k, '')
        for row in good['reference_assessments']:
            for k in edits['shots'][row['shot_id']]['reference']:
                edits['shots'][row['shot_id']]['reference'][k] = row[k]
        for row, approved in zip(edits['evidence'], good['evidence']):
            for k in ('observation', 'visible_facts', 'interpretation'):
                row[k] = approved[k]
        for k in edits['group']:
            edits['group'][k] = good['coverage'][k] if k in ('mapping_verified', 'limitations') else good[k]
        before = self.path.read_bytes()
        result = review_draft.fill(draft, edits)
        self.assertTrue(review_draft.check(self.path, result)['valid'])
        self.assertEqual(self.path.read_bytes(), before)
        for a, b in zip(result['evidence'], draft['evidence']):
            self.assertEqual({k: a[k] for k in ('path', 'sha256', 'time')},
                             {k: b[k] for k in ('path', 'sha256', 'time')})
        bad = copy.deepcopy(edits)
        bad['evidence'][0]['time'] += .01
        with self.assertRaisesRegex(ValueError, 'bindings changed'):
            review_draft.fill(draft, bad)
        bad = copy.deepcopy(edits)
        bad['shots']['S01']['review']['shot_id'] = 'S02'
        with self.assertRaisesRegex(ValueError, 'mechanical fields'):
            review_draft.fill(draft, bad)
        draft['context_fingerprint'] = 'new context'
        with self.assertRaisesRegex(ValueError, 'stale worklist'):
            review_draft.fill(draft, edits)

    def test_all_missing_repair_fields_reported_before_registration(self):
        self.prepare()
        good = repair_fixtures.RepairCycleTests.assessment(self, self.review_data({'S01': 'FAIL', 'S02': 'FAIL'}))
        self.assertTrue(review_draft.check(self.path, good)['valid'])
        before = self.path.read_bytes()
        bad = copy.deepcopy(good)
        bad['repair_assessments'] = [dict(shot_id=sid) for sid in ('S01', 'S02')]
        with self.assertRaises(ValidationError) as caught:
            review_draft.check(self.path, bad)
        paths = {r['path'] for r in caught.exception.errors}
        for sid in ('S01', 'S02'):
            for field in ('critical', 'affects_story', 'script_quote', 'issue_ids', 'impact', 'correction', 'preserves_script'):
                self.assertIn(f'repair_assessments[{sid}].{field}', paths)
        legacy = copy.deepcopy(good)
        del legacy['repair_assessments']
        with self.assertRaises(ValidationError):
            review_draft.check(self.path, legacy)
        self.assertTrue(review_draft.check(self.path, legacy, delivery_only=True)['valid'])
        self.assertFalse(review_draft.check(self.path, legacy, delivery_only=True)['repair_readiness_checked'])
        self.assertEqual(self.path.read_bytes(), before)

    def compact_edits(self, draft, approved):
        edits = review_draft.worklist(draft, compact=True)
        rows = {r['shot_id']: r for r in approved['shot_reviews']}
        refs = {r['shot_id']: r for r in approved['reference_assessments']}
        repairs = {r['shot_id']: r for r in approved.get('repair_assessments', [])}
        for sid, values in edits['shots'].items():
            for k in values['review']:
                values['review'][k] = copy.deepcopy(rows[sid].get(k, ''))
            for k in values['reference']:
                values['reference'][k] = copy.deepcopy(refs[sid][k])
            if sid in repairs:
                values['repair'] = {k: copy.deepcopy(v) for k, v in repairs[sid].items() if k != 'shot_id'}
        for k in edits['group']:
            edits['group'][k] = copy.deepcopy(approved['coverage'][k] if k in ('mapping_verified', 'limitations') else approved[k])
        edits['evidence'] = [dict(id=f'E{i:03d}', **{k: copy.deepcopy(e[k]) for k in
                            ('observation', 'visible_facts', 'interpretation')})
                             for i, e in enumerate(approved['evidence'], 1)]
        return edits

    def test_compact_view_retains_every_candidate_state_and_boundary(self):
        self.mapping()
        core.save(self.path, self.p)
        root = self.path.parent
        draft = review_draft.prepare(self.path, 'G01', root / 'draft.json', root / 'context.json',
                                     root / 'worklist.json', root / 'view.json', compact=True)
        ctx, view = core.read(root / 'context.json'), core.read(root / 'view.json')
        self.assertEqual(view['context_fingerprint'], draft['context_fingerprint'])
        self.assertEqual(view['full_context_file'], str((root / 'context.json').resolve()))
        supplied_digest = view.pop('view_digest')
        self.assertEqual(supplied_digest, core.digest(view))
        frames = {r['id']: r for r in view['frames']}
        self.assertEqual(len(frames), len(ctx['extraction']['frames']))
        for original, normalized in zip(ctx['shots'], view['shots']):
            for key in original.keys() - {'selected_frame'}:
                self.assertEqual(original[key], normalized[key])
            selected = frames[normalized['selected_frame']['frame_id']]
            self.assertEqual(selected['time'], original['selected_frame']['source']['time'])
        for original, normalized in zip(ctx['mapping']['shots'], view['mapping']['shots']):
            for key in original.keys() - {'candidates'}:
                self.assertEqual(original[key], normalized[key])
            self.assertEqual(len(original['candidates']), len(normalized['candidates']))
            for a, b in zip(original['candidates'], normalized['candidates']):
                self.assertEqual(frames[b['frame_id']]['time'], a['time'])
                self.assertEqual(frames[b['frame_id']]['path'], a['path'])
        for field in ('boundaries', 'narrative_plan', 'review_scope', 'assets'):
            self.assertEqual(view[field], ctx[field])
        self.assertEqual([r['id'] for r in view['evidence_ids']],
                         [r['id'] for r in core.read(root / 'worklist.json')['evidence']])
        self.assertNotIn('previous_review', view)
        self.assertEqual(review_draft.fill(draft, core.read(root / 'worklist.json')), draft)
        with self.assertRaises(ValueError):
            review_draft.check(self.path, draft)  # No automatic approval.

    def test_compact_judgments_equal_legacy_and_keep_original_evidence_bindings(self):
        draft = self.prepare()
        approved = self.review_data()
        result = review_draft.fill(draft, self.compact_edits(draft, approved))
        self.assertTrue(review_draft.check(self.path, result)['valid'])
        for row, binding, expected in zip(result['evidence'], draft['evidence'], approved['evidence']):
            for key in ('shot_id', 'path', 'sha256', 'time'):
                self.assertEqual(row[key], binding[key])
            for key in ('observation', 'visible_facts', 'interpretation'):
                self.assertEqual(row[key], expected[key])
        for row, expected in zip(result['shot_reviews'], approved['shot_reviews']):
            for key in ('shot_id', 'verdict', 'checks', 'reason', 'identity_reason', 'evidence_times'):
                self.assertEqual(row[key], expected[key])
        legacy = review_draft.worklist(result)
        legacy['base_digest'] = core.digest(draft)
        self.assertEqual(review_draft.fill(draft, legacy), result)
        edits = self.compact_edits(draft, approved)
        self.assertTrue(all('repair' not in r for r in edits['shots'].values()))

    def test_cli_defaults_to_compact_and_registers_only_after_full_check(self):
        self.p.pop('repair_asset_style', None)  # Ordinary review does not need repair-only style work.
        self.mapping()
        core.save(self.path, self.p)
        before = self.path.read_bytes()
        root = self.path.parent
        draft, ctx, view, edits, completed = [root / (name + '.json') for name in
                                            ('draft', 'context', 'view', 'edits', 'completed')]

        def cli(script, *args):
            return subprocess.run([sys.executable, str(Path(script.__file__)), *map(str, args)],
                                  capture_output=True, text=True, encoding='utf-8', timeout=30)

        prepared = cli(review_draft, 'prepare', self.path, 'G01', draft, '--context-output', ctx,
                       '--view-output', view, '--worklist-output', edits)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(core.read(edits)['format'], 'review-worklist-2')
        self.assertEqual(core.read(view)['context_fingerprint'], core.read(draft)['context_fingerprint'])
        blocked = cli(review_draft, 'fill', self.path, draft, edits, completed)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertFalse(completed.exists())
        self.assertEqual(self.path.read_bytes(), before)
        core.save(edits, self.compact_edits(core.read(draft), self.review_data()))
        filled = cli(review_draft, 'fill', self.path, draft, edits, completed)
        self.assertEqual(filled.returncode, 0, filled.stderr)
        self.assertEqual(self.path.read_bytes(), before)  # Draft completion is not registration.
        registered = cli(core, 'review', self.path, completed)
        self.assertEqual(registered.returncode, 0, registered.stderr)
        self.assertIsNotNone(core.review_current(core.read(self.path), self.path, 'G01'))
        legacy = cli(review_draft, 'prepare', self.path, 'G01', root / 'legacy-draft.json',
                     '--worklist-output', root / 'legacy-edits.json', '--legacy-worklist')
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertNotIn('format', core.read(root / 'legacy-edits.json'))

    def test_compact_facts_reuse_requires_real_single_frame_notes(self):
        mapping = self.mapping()
        candidate = mapping['shots'][0]['candidates'][0]
        candidate.update(observation='SIMULATED neutral fact', visible_facts=['SIMULATED neutral fact'])
        storyboard.record_mapping(self.p, self.path, mapping)
        self.select_mapping('G01')
        core.save(self.path, self.p)
        draft = review_draft.prepare(self.path, 'G01', self.path.parent / 'draft.json')
        edits = review_draft.worklist(draft, compact=True)
        self.assertEqual(edits['evidence'][0], dict(id='E001', reuse_facts=True, interpretation=''))
        self.assertEqual(review_draft.fill(draft, edits), draft)
        edits['evidence'][1] = dict(id='E002', reuse_facts=True, interpretation='')
        with self.assertRaisesRegex(ValueError, 'recorded single-frame facts'):
            review_draft.fill(draft, edits)

    def test_compact_rejects_missing_checks_stale_digest_and_evidence_rebinding(self):
        draft = self.prepare()
        edits = self.compact_edits(draft, self.review_data())
        for change in ('missing', 'duplicate', 'unknown', 'hash', 'time', 'fake_reuse'):
            bad = copy.deepcopy(edits)
            if change == 'missing':
                bad['evidence'].pop()
            elif change == 'duplicate':
                bad['evidence'][1]['id'] = bad['evidence'][0]['id']
            elif change == 'unknown':
                bad['evidence'][0]['id'] = 'E999'
            elif change in ('hash', 'time'):
                bad['evidence'][0]['sha256' if change == 'hash' else 'time'] = 'edited'
            else:
                bad['evidence'][0]['reuse_facts'] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                review_draft.fill(draft, bad)
        bad = copy.deepcopy(edits)
        del bad['shots']['S01']['review']['checks']['identity']
        with self.assertRaises(ValueError):
            review_draft.check(self.path, review_draft.fill(draft, bad))
        bad = copy.deepcopy(edits)
        del bad['shots']['S02']
        with self.assertRaisesRegex(ValueError, 'exact shot IDs'):
            review_draft.fill(draft, bad)
        draft['context_fingerprint'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'stale worklist'):
            review_draft.fill(draft, edits)

    def test_compact_problems_require_same_full_repair_evidence(self):
        draft = self.prepare()
        approved = repair_fixtures.RepairCycleTests.assessment(
            self, self.review_data({'S01': 'FAIL'}, middle_derivable=False))
        edits = self.compact_edits(draft, approved)
        result = review_draft.fill(draft, edits)
        self.assertTrue(review_draft.check(self.path, result)['valid'])
        self.assertEqual(result['repair_assessments'], approved['repair_assessments'])
        del edits['shots']['S01']['repair']
        with self.assertRaisesRegex(ValueError, 'require repair'):
            review_draft.fill(draft, edits)
        edits = self.compact_edits(draft, approved)
        del edits['shots']['S01']['repair']['impact']
        with self.assertRaisesRegex(ValueError, 'repair fields'):
            review_draft.fill(draft, edits)
        edits = self.compact_edits(draft, approved)
        edits['shots']['S02']['repair'] = copy.deepcopy(edits['shots']['S01']['repair'])
        with self.assertRaisesRegex(ValueError, 'non-problem shots omit'):
            review_draft.fill(draft, edits)

    def test_compact_absent_never_gains_frame_or_pass_and_live_hash_gate_stays(self):
        draft = self.prepare({'S02': 'absent'})
        compact = review_draft.worklist(draft, compact=True)
        completed = review_draft.fill(draft, compact)
        self.assertEqual(completed['shot_reviews'], draft['shot_reviews'])
        with self.assertRaises(ValueError):
            review_draft.check(self.path, completed)
        self.assertEqual(compact['shots']['S02']['review']['verdict'], 'absent')
        self.assertIn('repair', compact['shots']['S02'])
        self.assertFalse(any(e['shot_id'] == 'S02' for e in draft['evidence']))
        core.resolve(self.path, draft['evidence'][0]['path']).write_bytes(b'replaced')
        with self.assertRaises(ValueError):
            review_draft.check(self.path, review_draft.fill(draft, compact))

    def test_view_output_preflight_never_overwrites_or_leaves_partial_draft(self):
        self.mapping()
        core.save(self.path, self.p)
        root = self.path.parent
        with self.assertRaisesRegex(ValueError, 'frozen full context'):
            review_draft.prepare(self.path, 'G01', root / 'draft.json', view_output=root / 'view.json')
        self.assertFalse((root / 'draft.json').exists())
        (root / 'view.json').write_text('keep', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'distinct new view'):
            review_draft.prepare(self.path, 'G01', root / 'draft.json', root / 'context.json',
                                 view_output=root / 'view.json')
        self.assertFalse((root / 'draft.json').exists())


if __name__ == '__main__':
    unittest.main()
