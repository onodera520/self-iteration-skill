"""Mechanical drafting must retain evidence fidelity and require real judgments."""
import copy
import unittest
import test_imported_review as imported
import test_previs as fixtures
import previs as core
import review_draft
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
