"""Preparation preserves narrative inputs and stops before dependent mutations."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-storyboard-previs/scripts'))
import previs as core
import planner
import prepare_imported as prep


class PrepareImportedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'PROJECT.json'
        self.video = self.root / 'video.mp4'
        self.video.write_bytes(b'SIMULATED media')
        self.p = core.read(ROOT / 'ai-storyboard-previs/assets/imported-project.json')
        for a in self.p['assets']:
            path = self.root / (a['id'] + '.png')
            path.write_bytes(b'SIMULATED asset')
            a['path'] = str(path)
        core.save(self.project, self.p)
        self.output, self.run = self.root / 'evidence', self.root / 'run'

    def prepare(self):
        return prep.prepare(self.project, 'G01', self.video, self.output, self.run)

    def mock_media(self):
        probe = patch.object(prep.media, 'probe', return_value={
            'streams': [{'codec_type': 'video'}], 'format': {'duration': '3'}})
        extraction = patch.object(prep.media, 'extract', return_value={
            'video_sha256': core.sha(self.video), 'duration': 3, 'frames': [], 'contact_sheets': []})
        probe.start()
        self.addCleanup(probe.stop)
        mocked = extraction.start()
        self.addCleanup(extraction.stop)
        return mocked

    def test_preflight_reports_all_missing_and_empty_files(self):
        empty = self.root / 'empty.png'
        empty.touch()
        with patch.object(prep.media, 'probe', side_effect=AssertionError('too early')):
            with self.assertRaises(ValueError) as caught:
                prep.check_files([('script', self.root / 'lost.txt'), ('video', self.root), ('asset', empty)])
        for label in ('script:', 'video:', 'asset:'):
            self.assertIn(label, str(caught.exception))

    def test_preflight_does_not_substitute_same_named_file(self):
        with self.assertRaisesRegex(ValueError, 'file not found'):
            prep.check_files([('video', self.root / 'missing' / self.video.name)])

    def test_invalid_entities_all_report_actual_and_allowed_without_mutation(self):
        self.p['shots'][0]['facts'][0]['entity'] = 'oxygen'
        self.p['shots'][2]['state_changes'][0]['entity'] = 'terminal'
        before = copy.deepcopy(self.p)
        with self.assertRaises(ValueError) as caught:
            planner.validate_facts(self.p)
        for text in ('oxygen', 'terminal', 'assets[].id', '.facts[0].entity', '.state_changes[0].entity'):
            self.assertIn(text, str(caught.exception))
        for a in self.p['assets']:
            self.assertIn(a['id'], str(caught.exception))
        self.assertEqual(self.p, before)

    def test_validation_failure_leaves_project_untouched(self):
        self.p['title'] = ''
        core.save(self.project, self.p)
        before = self.project.read_bytes()
        with patch.object(core, 'import_video', side_effect=AssertionError('must not import')):
            with self.assertRaises(ValueError):
                self.prepare()
        self.assertEqual(self.project.read_bytes(), before)
        self.assertEqual(core.read(self.run / 'PREPARE_REPORT.json')['stages'][0]['status'], 'failed')
        self.assertFalse(Path(str(self.project) + '.lock').exists())

    def test_missing_assets_stop_even_when_validate_returns_normally(self):
        Path(self.p['assets'][0]['path']).unlink()
        self.assertTrue(core.validate(self.p, self.project)['missing_assets'])
        with patch.object(core, 'import_video', side_effect=AssertionError('must not import')):
            with self.assertRaisesRegex(ValueError, 'missing_assets'):
                self.prepare()
        self.assertEqual(core.read(self.project), self.p)

    def test_failed_import_stops_baseline_and_extraction(self):
        with patch.object(prep.media, 'probe', side_effect=ValueError('bad video')):
            with patch.object(prep.repair_cycle, 'baseline', side_effect=AssertionError('must not freeze')):
                with self.assertRaisesRegex(ValueError, 'bad video'):
                    self.prepare()
        self.assertEqual(core.read(self.project), self.p)

    def test_baseline_failure_preserves_import_and_stops_extraction(self):
        extraction = self.mock_media()
        self.p['source_script'] = 'not the shot text'
        core.save(self.project, self.p)
        with self.assertRaisesRegex(ValueError, 'exact excerpt'):
            self.prepare()
        saved = core.read(self.project)
        self.assertEqual(len(saved['imported_videos']), 1)
        self.assertNotIn('repair_baseline', saved)
        extraction.assert_not_called()

    def test_success_preserves_inputs_sparse_defaults_and_lock(self):
        extraction = self.mock_media()
        def extract(*args):
            self.assertTrue(Path(str(self.project) + '.lock').exists())
            saved = core.read(self.project)
            self.assertIn('repair_baseline', saved)
            self.assertEqual(saved['imported_videos'][0]['output_hashes'], [core.sha(self.video)])
            return {'video_sha256': core.sha(self.video), 'duration': 3, 'frames': [], 'contact_sheets': []}
        extraction.side_effect = extract
        report = self.prepare()
        self.assertEqual(report['status'], 'complete')
        self.assertFalse(report['verified'])
        self.assertEqual([r['name'] for r in report['stages']], ['validate', 'paths', 'import-video', 'baseline', 'extract'])
        extraction.assert_called_once_with(self.video, self.output)
        saved = core.read(self.project)
        for key, value in self.p.items():
            self.assertEqual(saved[key], value, key)

    def test_extraction_failure_retry_reuses_only_valid_registration(self):
        extraction = self.mock_media()
        extraction.side_effect = ValueError('extract failed')
        with self.assertRaisesRegex(ValueError, 'extract failed'):
            self.prepare()
        self.run = self.root / 'retry'
        extraction.side_effect = None
        self.prepare()
        self.assertEqual(len(core.read(self.project)['imported_videos']), 1)
        self.video.write_bytes(b'changed video')
        self.run = self.root / 'changed'
        extraction.return_value['video_sha256'] = core.sha(self.video)
        self.prepare()
        self.assertEqual(len(core.read(self.project)['imported_videos']), 2)

    def test_existing_lock_or_output_prevents_any_write(self):
        before = self.project.read_bytes()
        with core.locked(self.project):
            with self.assertRaises(FileExistsError):
                self.prepare()
        self.assertFalse(self.run.exists())
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'new evidence directory'):
            self.prepare()
        self.assertEqual(self.project.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
