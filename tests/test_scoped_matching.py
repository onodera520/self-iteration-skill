"""Scoped reads and matching IDs preserve legacy evidence and judgment gates."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_imported_review as imported
import test_previs as fixtures
import previs as core
import review_draft
import storyboard


class ScopedMatchingTests(fixtures.Base):
    png = imported.ImportedReviewTests.png
    select_mapping = imported.ImportedReviewTests.select_mapping
    mapping = imported.ImportedReviewTests.mapping

    def setUp(self):
        imported.ImportedReviewTests.setUp(self)

    def matching(self):
        legacy = self.mapping()
        self.p['board_mappings'] = []
        for shot in self.p['shots']:
            shot.pop('board', None)
        view = storyboard.matching_view(self.p, self.path, 'G01', legacy['evidence_file'])
        edits = storyboard.matching_worklist(view)
        for i, row in enumerate(edits['shots'], 1):
            row.update(status='matched', observation='SIMULATED shot located')
            row['candidates'] = [dict(frame_id=f'F{i:03d}', observation='SIMULATED single frame',
                                     visible_facts=['SIMULATED key visible'])]
            row['selection'] = dict(frame_id=f'F{i:03d}', reason='SIMULATED key state clear')
        return view, edits, legacy

    def reading(self):
        self.p['shots'][1]['event']['id'] = 'E02'
        self.p['shots'][2]['event']['id'] = 'E02'
        mapping = self.mapping()
        evidence = core.read(mapping['evidence_file'])
        for label, time in [('before', 0), ('between', .75), ('tail1', 5.1), ('tail2', 5.5)]:
            path = self.png(label, (15, 20, int(time*20)))
            evidence['frames'].append(dict(path=str(path), sha256=core.sha(path), time=time))
        evidence['frames'].sort(key=lambda frame: frame['time'])
        core.save(mapping['evidence_file'], evidence)
        mapping['shots'][0]['candidates'].append(dict(evidence['frames'][2]))
        storyboard.record_mapping(self.p, self.path, mapping)
        self.select_mapping('G01')
        core.save(self.path, self.p)
        root = self.path.parent
        review_draft.prepare(self.path, 'G01', root/'draft.json', root/'context.json',
                             root/'worklist.json', root/'view.json', compact=True)
        return root/'view.json', core.read(root/'view.json')

    def cli(self, module, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', str(Path(module.__file__)), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8', timeout=30)

    def test_index_explicitly_reports_unread_shots_candidates_frames_and_checks(self):
        path, full = self.reading()
        before = self.path.read_bytes()
        index = review_draft.read_view(self.path, path, index_only=True)
        self.assertEqual(index['shots'], [])
        self.assertEqual(index['frames'], [])
        self.assertEqual(index['required_coverage'], ['S01', 'S02', 'S03'])
        self.assertEqual(index['remaining_primary_shot_ids'], index['required_coverage'])
        self.assertEqual(index['unread_in_this_view']['shot_ids'], index['required_coverage'])
        self.assertEqual(index['unread_in_this_view']['frame_ids'], [f['id'] for f in full['frames']])
        self.assertEqual(index['required_checks']['shot'], sorted(storyboard.CHECKS))
        self.assertEqual(len(index['index'][0]['candidate_frame_ids']), 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_shot_scope_keeps_all_candidates_full_states_neighbors_and_continuous_frames(self):
        path, full = self.reading()
        result = review_draft.read_view(self.path, path, shot_ids=['S01'])
        self.assertEqual(result['primary_shot_ids'], ['S01'])
        self.assertEqual(result['adjacent_shot_ids'], ['S02'])
        self.assertEqual(result['shots'], full['shots'][:2])
        self.assertIn('entry_state', result['shots'][0]['requirements'])
        self.assertIn('exit_state', result['shots'][0]['requirements'])
        self.assertEqual(result['mapping']['shots'], full['mapping']['shots'][:2])
        self.assertEqual([f['time'] for f in result['frames']], [0, .25, .75, 2.25, 4.25])
        self.assertEqual(result['unread_in_this_view']['shot_ids'], ['S03'])
        self.assertEqual(result['unread_in_this_view']['frame_ids'], ['F006', 'F007'])
        self.assertEqual(result['evidence_ids'], [e for e in full['evidence_ids'] if e['shot_id'] != 'S03'])
        for field in ('assets', 'boundaries', 'review_scope', 'narrative_plan'):
            self.assertEqual(result[field], full[field])

    def test_event_scope_and_full_read_retain_original_ids_and_all_frames(self):
        path, full = self.reading()
        event = review_draft.read_view(self.path, path, event_id='E02')
        self.assertEqual(event['primary_shot_ids'], ['S02', 'S03'])
        self.assertEqual(event['adjacent_shot_ids'], ['S01'])
        self.assertEqual(event['remaining_primary_shot_ids'], ['S01'])
        result = review_draft.read_view(self.path, path)
        self.assertEqual(result['frames'], full['frames'])
        self.assertEqual(result['shots'], full['shots'])
        self.assertFalse(result['unread_in_this_view']['frame_ids'])
        self.assertEqual(result['source_view_digest'], full['view_digest'])

    def test_unknown_or_duplicate_read_scope_is_rejected(self):
        path, _ = self.reading()
        for kwargs in (dict(shot_ids=['S99']), dict(shot_ids=['S01', 'S01']),
                       dict(event_id='UNKNOWN'), dict(shot_ids=[], index_only=True)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                review_draft.read_view(self.path, path, **kwargs)

    def test_changed_frozen_view_or_context_cannot_be_read(self):
        path, full = self.reading()
        changed = copy.deepcopy(full)
        changed['mapping']['shots'][0]['candidates'].pop()
        core.save(path, changed)
        with self.assertRaisesRegex(ValueError, 'stale or changed'):
            review_draft.read_view(self.path, path, shot_ids=['S01'])
        core.save(path, full)
        context = core.read(full['full_context_file'])
        context['shots'][0]['requirements']['purpose'] = 'Changed requirement'
        core.save(full['full_context_file'], context)
        with self.assertRaisesRegex(ValueError, 'stale or changed'):
            review_draft.read_view(self.path, path, index_only=True)

    def test_changed_picture_rejects_even_index_read(self):
        path, full = self.reading()
        Path(full['frames'][0]['path']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            review_draft.read_view(self.path, path, index_only=True)

    def test_scoped_read_preserves_both_external_boundaries_and_rejects_changes(self):
        self.p['groups'] = [dict(id=f'G{i:02d}', version=1, shot_ids=[f'S{i:02d}'])
                            for i in range(1, 4)]
        for gid in ('G01', 'G02', 'G03'):
            self.mapping(gid=gid)
        core.save(self.path, self.p)
        root = self.path.parent
        review_draft.prepare(self.path, 'G02', root/'draft.json', root/'context.json',
                             root/'work.json', root/'view.json')
        full = core.read(root/'view.json')
        self.assertEqual([b['shot_id'] for b in full['boundaries']], ['S01', 'S03'])
        result = review_draft.read_view(self.path, root/'view.json', shot_ids=['S02'])
        self.assertEqual(result['boundaries'], full['boundaries'])
        index = review_draft.read_view(self.path, root/'view.json', index_only=True)
        self.assertEqual(index['unread_in_this_view']['boundary_shot_ids'], ['S01', 'S03'])
        self.assertEqual(result['required_checks']['group'], full['review_scope']['group_checks'])
        self.mapping(gid='G01', revision=2)
        core.save(self.path, self.p)
        with self.assertRaises(ValueError):
            review_draft.read_view(self.path, root/'view.json', shot_ids=['S02'])

    def test_matching_restores_exact_bindings_and_matches_legacy_state(self):
        view, edits, _ = self.matching()
        before = copy.deepcopy(self.p)
        expanded = storyboard.expand_matching(self.p, self.path, view, edits)
        evidence = core.read(view['evidence_file'])
        for row, frame in zip(expanded['shots'], evidence['frames']):
            for field in ('path', 'sha256', 'time'):
                self.assertEqual(row['candidates'][0][field], frame[field])
        legacy = copy.deepcopy(before)
        storyboard.record_mapping_batch(legacy, self.path, expanded)
        storyboard.record_matching_worklist(self.p, self.path, view, edits)
        self.assertEqual(self.p, legacy)
        self.assertFalse(self.p.get('reviews'))
        core.save(self.path, self.p)
        draft = review_draft.prepare(self.path, 'G01', self.path.parent/'draft.json')
        self.assertTrue(all(r['verdict'] == 'uncertain' for r in draft['shot_reviews']))
        self.assertEqual(draft['evidence'][0]['visible_facts'], ['SIMULATED key visible'])
        with self.assertRaises(ValueError):
            review_draft.check(self.path, draft)

    def test_blank_matching_worklist_cannot_register_a_decision(self):
        view, _, _ = self.matching()
        before = copy.deepcopy(self.p)
        with self.assertRaises(ValueError):
            storyboard.record_matching_worklist(self.p, self.path, view, storyboard.matching_worklist(view))
        self.assertEqual(self.p, before)

    def test_invalid_ids_fields_coverage_or_selection_reject_without_partial_write(self):
        view, edits, _ = self.matching()
        changes = ('unknown', 'duplicate', 'time', 'hash', 'path', 'missing', 'order', 'selection', 'reason', 'digest')
        for change in changes:
            bad = copy.deepcopy(edits)
            first = bad['shots'][0]
            if change == 'unknown':
                first['candidates'][0]['frame_id'] = 'F999'
            elif change == 'duplicate':
                first['candidates'].append(copy.deepcopy(first['candidates'][0]))
            elif change in ('time', 'hash', 'path'):
                first['candidates'][0][{'hash':'sha256'}.get(change, change)] = 'fake'
            elif change == 'missing':
                bad['shots'].pop()
            elif change == 'order':
                bad['shots'].reverse()
            elif change == 'selection':
                first['selection']['frame_id'] = 'F002'
            elif change == 'reason':
                first['selection']['reason'] = ''
            else:
                bad['base_digest'] = 'old'
            before = copy.deepcopy(self.p)
            with self.subTest(change=change), self.assertRaises(ValueError):
                storyboard.record_matching_worklist(self.p, self.path, view, bad)
            self.assertEqual(self.p, before)

    def test_absent_requires_full_rescan_and_uncertain_cannot_claim_candidates(self):
        view, edits, _ = self.matching()
        middle = edits['shots'][1]
        middle.update(status='absent', candidates=[], selection=None)
        with self.assertRaises(ValueError):
            storyboard.record_matching_worklist(self.p, self.path, view, edits)
        middle.update(full_rescan=True, rescan=dict(ranges=[[0, 6]], observation='SIMULATED full video checked'))
        storyboard.record_matching_worklist(self.p, self.path, view, edits)
        self.assertEqual(storyboard.current_mapping(self.p, self.path, 'G01')['shots'][1]['status'], 'absent')
        bad = copy.deepcopy(edits)
        bad['shots'][0]['status'] = 'uncertain'
        bad['shots'][0]['selection'] = None
        with self.assertRaises(ValueError):
            storyboard.record_matching_worklist(self.p, self.path, view, bad)

    def test_old_matching_ids_rejected_after_evidence_reorder_or_script_change(self):
        view, edits, _ = self.matching()
        evidence = core.read(view['evidence_file'])
        changed = copy.deepcopy(evidence)
        changed['frames'].reverse()
        core.save(view['evidence_file'], changed)
        with self.assertRaisesRegex(ValueError, 'stale matching'):
            storyboard.record_matching_worklist(self.p, self.path, view, edits)
        core.save(view['evidence_file'], evidence)
        self.p['shots'][0]['script'] += ' New visual action.'
        with self.assertRaises(ValueError):
            storyboard.record_matching_worklist(self.p, self.path, view, edits)

    def test_old_matching_ids_rejected_after_asset_or_video_replacement(self):
        view, edits, _ = self.matching()
        asset = Path(self.p['assets'][0]['path'])
        original = asset.read_bytes()
        asset.write_bytes(b'changed asset')
        with self.assertRaises(ValueError):
            storyboard.record_matching_worklist(self.p, self.path, view, edits)
        asset.write_bytes(original)
        Path(view['video']).write_bytes(b'changed source video')
        with self.assertRaises(ValueError):
            storyboard.record_matching_worklist(self.p, self.path, view, edits)

    def test_matching_rejects_modified_frame_or_view_without_partial_write(self):
        view, edits, _ = self.matching()
        before = copy.deepcopy(self.p)
        changed = copy.deepcopy(view)
        changed['shots'][0]['requirements']['purpose'] = 'tampered requirement'
        with self.assertRaisesRegex(ValueError, 'stale matching'):
            storyboard.record_matching_worklist(self.p, self.path, changed, edits)
        self.png(Path(view['frames'][0]['path']).stem, (255, 255, 255))
        with self.assertRaises(ValueError):
            storyboard.record_matching_worklist(self.p, self.path, view, edits)
        self.assertEqual(self.p, before)

    def assert_cli_roundtrip(self):
        view, edits, legacy = self.matching()
        core.save(self.path, self.p)
        before = self.path.read_bytes()
        root = self.path.parent
        prepared = self.cli(storyboard, 'prepare-map', self.path, legacy['evidence_file'], '--group', 'G01',
                            '--output', root/'match-view.json', '--worklist-output', root/'match-work.json')
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(core.read(root/'match-view.json'), view)
        self.assertEqual(self.path.read_bytes(), before)
        core.save(root/'match-work.json', edits)
        mapped = self.cli(storyboard, 'map', self.path, root/'match-work.json', '--view', root/'match-view.json')
        self.assertEqual(mapped.returncode, 0, mapped.stderr)
        review_draft.prepare(self.path, 'G01', root/'draft.json', root/'context.json',
                             root/'work.json', root/'view.json')
        read = self.cli(review_draft, 'read', self.path, root/'view.json', '--event', 'E01')
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout)['primary_shot_ids'], ['S01', 'S02', 'S03'])
        return root

    def test_cli_prepares_readonly_then_maps_and_reads_complete_scope(self):
        self.assert_cli_roundtrip()

    def test_input_groups_support_official_cli_roundtrip_and_still_reject_stale_views(self):
        self.p['input_shot_groups'] = 'A01:S01–S03'
        root = self.assert_cli_roundtrip()
        changed = core.read(self.path)
        changed['input_shot_groups'] = 'A02:S01–S03'
        core.save(self.path, changed)
        before = self.path.read_bytes()
        mapped = self.cli(storyboard, 'map', self.path, root/'match-work.json', '--view', root/'match-view.json')
        self.assertNotEqual(mapped.returncode, 0)
        self.assertIn('stale matching', mapped.stderr)
        read = self.cli(review_draft, 'read', self.path, root/'view.json', '--shots', 'S02')
        self.assertNotEqual(read.returncode, 0)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
