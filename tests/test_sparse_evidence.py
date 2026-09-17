"""Synthetic media/registration regressions; not a real-story visual acceptance."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import test_imported_review as fixtures
import previs as core
import media
import storyboard as boards
import planner


class SparseMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.video = cls.root / 'synthetic.mp4'
        cmd = [media.binary('ffmpeg'), '-v', 'error']
        for color in ('red', 'green', 'blue'):
            cmd += ['-f', 'lavfi', '-i', f'color={color}:s=160x90:r=25:d=4']
        media.command(cmd + ['-filter_complex',
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0,drawbox=x=5:y=5:w=20:h=20:color=white:t=fill:enable='between(t,6.32,6.48)'[v]",
            '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', cls.video])
        cls.sparse = media.extract(cls.video, cls.root / 'sparse')
        cls.full = media.extract(cls.video, cls.root / 'full', dense_step=.5)

    def test_sparse_covers_cuts_and_segments_without_default_dense(self):
        data = self.sparse
        self.assertEqual(data['sampling']['mode'], 'sparse')
        self.assertEqual(data['sampling']['dense_ranges'], [])
        self.assertFalse(data['verified'])
        self.assertLess(len(data['frames']), len(self.full['frames']))
        times = [f['time'] for f in data['frames']]
        self.assertEqual(times[0], 0)
        self.assertGreater(times[-1], 11.9)
        # Scene detection proposes boundaries; it does not guarantee every cut.
        targets = data['candidate_cuts'] + [(s['start'] + s['end']) / 2 for s in data['candidate_segments']]
        self.assertTrue(data['candidate_cuts'])
        for target in targets:
            self.assertLess(min(abs(t-target) for t in times), .05)
        for frame in data['frames']:
            self.assertAlmostEqual(frame['time'], frame['frame_index']/25, places=5)
            with Image.open(frame['path']) as im:
                rgb = im.convert('RGB').getpixel((80, 45))
                channel = min(2, int(frame['time']//4))
                self.assertGreater(rgb[channel], max(v for i,v in enumerate(rgb) if i != channel))
        self.assertEqual([p for sheet in data['contact_sheets'] for p in sheet['frame_paths']],
                         [f['path'] for f in data['frames']])
        print(f'\nSynthetic 12s first-pass frames: explicit .5s={len(self.full["frames"])}; sparse={len(data["frames"])}')

    def test_local_cli_merges_ranges_reuses_frames_and_finds_brief_marker(self):
        base = self.root / 'sparse/evidence.json'
        before = base.read_bytes()
        out = self.root / 'local'
        result = subprocess.run([sys.executable, media.__file__, 'extract', str(self.video), str(out),
            '--base-evidence', str(base), '--dense-range', '6.2:6.5', '--dense-range', '6.4:6.6',
            '--dense-range', '9.2:9.4', '--dense-step', '.04'], capture_output=True, text=True, encoding='utf8')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = core.read(out / 'evidence.json')
        self.assertEqual(data['sampling']['dense_ranges'], [[6.2,6.6],[9.2,9.4]])
        self.assertEqual(base.read_bytes(), before)
        old = {f['frame_index']:f for f in self.sparse['frames']}
        new = {f['frame_index']:f for f in data['frames']}
        self.assertEqual(len(new), len(data['frames']))
        for n, f in old.items():
            self.assertEqual(new[n], f)
            self.assertEqual(core.sha(f['path']), f['sha256'])
        for n in new.keys() - old.keys():
            self.assertTrue(6.18 <= new[n]['time'] <= 6.62 or 9.18 <= new[n]['time'] <= 9.42)
        def marker(frame):
            with Image.open(frame['path']) as im:
                return min(im.convert('RGB').getpixel((10,10))) > 200
        self.assertFalse(any(marker(f) for f in self.sparse['frames']))
        self.assertTrue(any(marker(f) for f in data['frames']))
        self.assertFalse(data['verified'])
        displayed = [p for sheet in data['contact_sheets'] for p in sheet['frame_paths']]
        self.assertEqual(data['contact_sheet_scope'], 'new_frames')
        self.assertEqual(displayed, data['new_frame_paths'])
        self.assertEqual(set(displayed), {new[n]['path'] for n in new.keys() - old.keys()})
        self.assertEqual(data['full_contact_sheets'], [])
        context = [p for sheet in data['context_contact_sheets'] for p in sheet['frame_paths']]
        self.assertTrue(context)
        self.assertTrue(set(context) <= {f['path'] for f in old.values()})
        # All requested points already exist: no second image extraction or scene scan.
        with patch.object(media, 'command', wraps=media.command) as commands:
            again = media.extract(self.video, self.root / 'local-again', ranges=[[6.2,6.5],[6.4,6.6],[9.2,9.4]],
                                  dense_step=.04, base_evidence=out / 'evidence.json')
        self.assertEqual(again['sampling']['new_frames'], 0)
        self.assertEqual(again['frames'], data['frames'])
        self.assertEqual(again['contact_sheets'], [])
        self.assertEqual(again['context_contact_sheets'], [])
        self.assertFalse(any(Path(str(c.args[0][0])).stem.lower() == 'ffmpeg' for c in commands.call_args_list))

    def test_local_default_step_and_optional_full_contact_sheet(self):
        data = media.extract(self.video, self.root / 'default-local', ranges=[[6.2,6.6]],
                             base_evidence=self.root / 'sparse/evidence.json', full_contact_sheet=True)
        self.assertEqual(data['sampling']['dense_step'], .2)
        self.assertEqual([p for s in data['contact_sheets'] for p in s['frame_paths']], data['new_frame_paths'])
        self.assertEqual([p for s in data['full_contact_sheets'] for p in s['frame_paths']],
                         [f['path'] for f in data['frames']])
        self.assertTrue(all(Path(s['path']).is_file() for s in data['full_contact_sheets']))

    def test_project_cli_emits_incremental_report_without_changing_mapping(self):
        c = fixtures.ImportedReviewTests()
        c.setUp()
        self.addCleanup(c.doCleanups)
        g = c.p['groups'][0]
        c.p['imported_videos'] = [dict(target_id=g['id'],version=g['version'],source='user_video',
            group_fingerprint=core.group_fingerprint(c.p,c.path,g), outputs=[str(self.video)],
            output_hashes=[core.sha(self.video)],duration=12)]
        frames = self.sparse['frames']
        candidates = [frames[0],frames[len(frames)//2],frames[-1]]
        data = dict(group_id=g['id'],video_sha256=core.sha(self.video),evidence_file=str(self.root/'sparse/evidence.json'),
            shots=[dict(shot_id=sid,status='matched',observation='SIMULATED candidate only',
                candidates=[dict(path=f['path'],time=f['time'])]) for sid,f in zip(g['shot_ids'],candidates)])
        boards.record_mapping_batch(c.p,c.path,data)
        core.save(c.path,c.p)
        before = copy.deepcopy(c.p['board_mappings'])
        out = c.path.parent/'local-evidence'
        result = subprocess.run([sys.executable,media.__file__,'extract',str(self.video),str(out),
            '--project',str(c.path),'--group','G01','--base-evidence',str(self.root/'sparse/evidence.json'),
            '--dense-range','6.2:6.6'],capture_output=True,text=True,encoding='utf8')
        self.assertEqual(result.returncode,0,result.stderr)
        report = core.read(out/'incremental_review.json')
        self.assertTrue(report['draft_only'])
        self.assertTrue(report['impact']['new_frame_paths'])
        self.assertEqual(report['mapping_draft']['shots'],before[-1]['shots'])
        self.assertEqual(core.read(c.path)['board_mappings'],before)
        self.assertEqual(core.read(c.path).get('reviews',[]),[])

    def test_reject_invalid_ranges_steps_and_overwrite(self):
        for i, options in enumerate((dict(ranges=[[-1,1]]), dict(ranges=[[1,13]]),
                dict(ranges=[[2,1]]), dict(ranges=[[0,float('nan')]]), dict(dense_step=0),
                dict(dense_step=float('inf')), dict(dense_step=.0001))):
            with self.subTest(options=options), self.assertRaises(ValueError):
                media.extract(self.video, self.root / f'invalid-{i}', **options)
        with self.assertRaisesRegex(ValueError, 'new evidence directory'):
            media.extract(self.video, self.root / 'sparse')

    def test_reject_changed_video_frames_or_timestamp(self):
        original = core.read(self.root / 'sparse/evidence.json')
        for field in ('video', 'frame', 'time'):
            data = copy.deepcopy(original)
            if field == 'video':
                data['video_sha256'] = 'wrong'
            elif field == 'frame':
                frame = data['frames'][0]
                replacement = self.root / 'changed.png'
                Image.new('RGB',(160,90),'black').save(replacement)
                frame['path'] = str(replacement)
            else:
                data['frames'][0]['time'] += .1
            base = self.root / f'bad-{field}.json'
            core.save(base, data)
            with self.subTest(field=field), self.assertRaises(ValueError):
                media.extract(self.video, self.root / f'reject-{field}', ranges=[[1,2]], base_evidence=base)


class BatchMappingTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.ImportedReviewTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.data = self.case.mapping()

    def batch(self):
        data = copy.deepcopy(self.data)
        data['selections'] = [dict(shot_id=r['shot_id'], path=r['candidates'][0]['path'],
            source=dict(kind='frame', time=r['candidates'][0]['time']), reason='SIMULATED key state')
            for r in data['shots']]
        return data

    def test_batch_equals_sequential_through_review_plan_and_delivery(self):
        c = self.case
        base = copy.deepcopy(c.p)
        base['board_mappings'] = []
        for s in base['shots']:
            s.pop('board', None)
        result = []
        for batch in (False, True):
            c.p = copy.deepcopy(base)
            data = self.batch()
            if batch:
                boards.record_mapping_batch(c.p, c.path, data)
            else:
                boards.record_mapping(c.p, c.path, self.data)
                for selection in data['selections']:
                    boards.select_image(c.p, c.path, selection)
            core.record_review(c.p, c.path, c.review_data())
            c.p['reviews'][-1]['id'] = 'SIMULATED same review id'
            proposal = planner.post_review_plan(c.p, c.path, {})
            planner.store_aggregation(c.p, c.path, proposal)
            out = c.path.parent / f'delivery-{batch}'
            boards.render(c.p, c.path, out)
            result.append((c.p, {f.relative_to(out).as_posix():f.read_bytes() for f in out.rglob('*') if f.is_file()}))
        self.assertEqual(result[0], result[1])

    def test_failed_selection_rolls_back_entire_batch(self):
        data = self.batch()
        data['selections'][-1]['source']['time'] += 1
        before = copy.deepcopy(self.case.p)
        with self.assertRaisesRegex(ValueError, 'selected frame/time'):
            boards.record_mapping_batch(self.case.p, self.case.path, data)
        self.assertEqual(self.case.p, before)

    def test_batch_cli_one_save_with_existing_lock_and_selection_guards(self):
        c = self.case
        core.save(c.path, c.p)
        data = c.path.parent / 'batch.json'
        core.save(data, self.batch())
        cmd = [sys.executable, boards.__file__, 'map', str(c.path), str(data)]
        with core.locked(c.path):
            self.assertNotEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf8')
        self.assertEqual(result.returncode, 0, result.stderr)
        updated = core.read(c.path)
        self.assertEqual(len(updated['board_mappings']), len(c.p['board_mappings']) + 1)
        self.assertTrue(all(boards.current_frame(updated, c.path, s['id']) for s in updated['shots']))

    def test_local_rescan_cannot_establish_absence(self):
        data = copy.deepcopy(self.data)
        row = data['shots'][1]
        row.update(status='absent', candidates=[], full_rescan=True,
                   rescan=dict(ranges=[[0,2]], observation='SIMULATED local inspection only'))
        with self.assertRaisesRegex(ValueError, 'full source video coverage'):
            boards.record_mapping_batch(self.case.p, self.case.path, data)
        row['rescan']['ranges'] = [[0,6]]
        row['rescan']['observation'] = 'SIMULATED full video reviewed; no independent visual unit'
        row['independent_visual_unit'] = False
        boards.record_mapping_batch(self.case.p, self.case.path, data)
        self.assertEqual(boards.current_mapping(self.case.p,self.case.path,'G01')['shots'][1]['status'], 'absent')

    def test_previous_visual_unit_cannot_be_matched_as_missing_independent_shot(self):
        data = copy.deepcopy(self.data)
        row = data['shots'][1]
        row.update(independent_visual_unit=False, observation='仍是上一镜，没有所需独立镜头')
        with self.assertRaisesRegex(ValueError, 'previous visual unit'):
            boards.record_mapping_batch(self.case.p, self.case.path, data)
        row.update(status='uncertain', candidates=[])
        boards.record_mapping_batch(self.case.p, self.case.path, data)
        self.assertIsNone(boards.current_frame(self.case.p, self.case.path, 'S02'))


if __name__ == '__main__':
    unittest.main()
