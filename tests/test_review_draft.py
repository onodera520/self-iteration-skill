"""Mechanical drafting must retain evidence fidelity and require real judgments."""
import copy
import unittest
import test_imported_review as imported
import test_previs as fixtures
import previs as core
import review_draft
import storyboard
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


if __name__ == '__main__':
    unittest.main()
