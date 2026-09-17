"""Cache parity tests; synthetic observations do not constitute visual acceptance."""
import contextlib
import copy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_imported_review as fixtures
import evidence_runtime as runtime
import previs as core
import planner
import storyboard as boards


class EvidenceRuntimeTests(unittest.TestCase):
    def fixture(self, status='matched', verdicts=None):
        case = fixtures.ImportedReviewTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.mapping({'S02': status})
        core.record_review(case.p, case.path, case.review_data(verdicts))
        return case

    def test_context_plan_and_delivery_identical_with_fewer_file_hashes(self):
        case = self.fixture()
        results, counts = [], []
        for cached in (False, True):
            project = copy.deepcopy(case.p)
            scope = contextlib.nullcontext() if cached else patch.object(runtime, 'evidence_operation', contextlib.nullcontext)
            with scope, patch.object(runtime, 'raw_sha', wraps=runtime.raw_sha) as raw:
                ctx = core.video_context(project, case.path, 'G01')
                proposal = planner.post_review_plan(project, case.path, {})
                planner.store_aggregation(project, case.path, proposal)
                output = case.path.parent / ('cached' if cached else 'uncached')
                boards.render(project, case.path, output)
                files = {f.relative_to(output).as_posix(): f.read_bytes() for f in output.rglob('*') if f.is_file()}
                results.append((ctx, proposal, files))
                counts.append(raw.call_count)
        self.assertEqual(results[0], results[1])
        self.assertLess(counts[1], counts[0] // 2)
        print(f'\nEvidence SHA256 reads, identical context/plan/MD/images: {counts[0]} -> {counts[1]}')

    def test_absent_uncertain_and_failed_delivery_parity(self):
        for status in ('absent', 'uncertain', 'FAIL'):
            with self.subTest(status=status):
                case = self.fixture('matched', {'S02': 'FAIL'}) if status == 'FAIL' else self.fixture(status)
                outputs = []
                for cached in (False, True):
                    project = copy.deepcopy(case.p)
                    scope = contextlib.nullcontext() if cached else patch.object(runtime, 'evidence_operation', contextlib.nullcontext)
                    with scope:
                        result = planner.post_review_plan(project, case.path, {})
                        planner.store_aggregation(project, case.path, result)
                        out = case.path.parent / str(cached)
                        boards.render(project, case.path, out)
                        outputs.append((result, {f.relative_to(out).as_posix(): f.read_bytes() for f in out.rglob('*') if f.is_file()}))
                self.assertEqual(outputs[0], outputs[1])

    def test_same_size_restored_timestamp_change_aborts_scope(self):
        case = self.fixture()
        video = Path(case.p['imported_videos'][0]['outputs'][0])
        before = video.stat()
        original = video.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Evidence changed'):
            with runtime.evidence_operation():
                core.video_context(case.p, case.path, 'G01')
                video.write_bytes(b'X' * len(original))
                os.utime(video, ns=(before.st_atime_ns, before.st_mtime_ns))
                core.video_context(case.p, case.path, 'G01')
        self.assertIsNone(runtime._active.get())
        self.assertIsNone(core.review_current(case.p, case.path, 'G01'))
        video.write_bytes(original)
        self.assertIsNotNone(core.review_current(case.p, case.path, 'G01'))

    def test_no_cache_survives_between_operations(self):
        for target in ('asset', 'frame', 'evidence'):
            with self.subTest(target=target):
                case = self.fixture()
                ctx = core.video_context(case.p, case.path, 'G01')
                path = Path({'asset': ctx['assets'][0]['path'],
                             'frame': ctx['extraction']['frames'][0]['path'],
                             'evidence': ctx['mapping']['evidence_file']}[target])
                before = path.stat()
                content = path.read_bytes()
                path.write_bytes(b'X' * len(content))
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                self.assertIsNone(core.review_current(case.p, case.path, 'G01'))

    def test_memory_changes_and_return_value_edits_do_not_reuse_context(self):
        case = self.fixture()
        with runtime.evidence_operation():
            first = core.video_context(case.p, case.path, 'G01')
            expected = copy.deepcopy(first)
            first['shots'][0]['script'] = 'caller edit'
            self.assertEqual(core.video_context(case.p, case.path, 'G01'), expected)
            case.p['shots'][0]['duration'] += 1
            self.assertIsNone(core.review_current(case.p, case.path, 'G01'))

    def test_existing_record_reference_contract_is_preserved(self):
        case = self.fixture()
        with runtime.evidence_operation():
            self.assertIs(boards.current_mapping(case.p, case.path, 'G01'), case.p['board_mappings'][-1])
            current = core.review_current(case.p, case.path, 'G01')
            self.assertIs(current, case.p['reviews'][-1])
            current['review_schema'] = 3
            self.assertIsNone(core.review_current(case.p, case.path, 'G01'))

    def test_read_json_isolation_and_deleted_dependency(self):
        case = self.fixture()
        path = case.path.parent / 'test.json'
        core.save(path, {'items': [1]})
        with self.assertRaises(OSError):
            with runtime.evidence_operation():
                core.read(path)['items'].append(2)
                self.assertEqual(core.read(path), {'items': [1]})
                path.unlink()
        self.assertIsNone(runtime._active.get())

    def test_parsed_json_must_match_previously_hashed_bytes(self):
        case = self.fixture()
        path = case.path.parent / 'test.json'
        core.save(path, {'items': [1]})
        with self.assertRaisesRegex(ValueError, 'Evidence changed'):
            with runtime.evidence_operation():
                core.sha(path)
                core.save(path, {'items': [2]})
                core.read(path)


if __name__ == '__main__':
    unittest.main()
