"""Display metadata and offline graph tests; no paid or remote API execution."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import test_previs as fixtures
import media
import previs as core
import repair_aspect


class DisplayShapeTests(unittest.TestCase):
    def shape(self, width=1920, height=1080, **extra):
        return repair_aspect.display_shape({'streams': [dict(
            codec_type='video', width=width, height=height, **extra)]})

    def test_landscape_portrait_and_aligned_resolution(self):
        for width, height, expected in [(1920, 1080, '16:9'), (1080, 1920, '9:16'),
                                        (1376, 768, '16:9'), (768, 1376, '9:16')]:
            with self.subTest(width=width, height=height):
                self.assertEqual(self.shape(width, height)['aspect_ratio'], expected)

    def test_pixel_aspect_and_display_rotation(self):
        self.assertEqual(self.shape(1440, 1080, sample_aspect_ratio='4:3')['aspect_ratio'], '16:9')
        for extra in [dict(side_data_list=[dict(rotation=-90)]), dict(tags={'rotate': '90'})]:
            with self.subTest(extra=extra):
                result = self.shape(**extra)
                self.assertEqual(result['aspect_ratio'], '9:16')
                self.assertIn(result['rotation'], (90, 270))
        self.assertEqual(self.shape(side_data_list=[dict(rotation=0)], tags={'rotate': '90'})['aspect_ratio'], '16:9')

    def test_missing_dimensions_or_unrecognized_ratio_stops(self):
        cases = [(0, 1080, {}), (True, 1080, {}), (1000, 1000, {}),
                 (1920, 1000, {}), (1920, 1080, dict(sample_aspect_ratio='bad')),
                 (1920, 1080, dict(sample_aspect_ratio='-1:1')),
                 (1920, 1080, dict(tags={'rotate': 45}))]
        for width, height, extra in cases:
            with self.subTest(width=width, height=height, extra=extra), self.assertRaises(ValueError):
                self.shape(width, height, **extra)
        with self.assertRaises(ValueError):
            repair_aspect.display_shape({'streams': []})

    def test_attached_cover_is_not_the_source_shape(self):
        info = {'streams': [dict(codec_type='video', width=1000, height=1000,
                                 disposition={'attached_pic': 1}),
                            dict(codec_type='audio'),
                            dict(codec_type='video', width=1080, height=1920)]}
        self.assertEqual(repair_aspect.display_shape(info)['aspect_ratio'], '9:16')

    def test_real_synthetic_video_probe(self):
        ffmpeg = os.environ.get('FFMPEG') or shutil.which('ffmpeg')
        if not ffmpeg or not (os.environ.get('FFPROBE') or shutil.which('ffprobe')):
            self.skipTest('FFmpeg/FFprobe unavailable')
        with tempfile.TemporaryDirectory() as directory:
            for width, height, aspect in [(320, 180, '16:9'), (180, 320, '9:16')]:
                path = Path(directory) / f'{width}x{height}.mp4'
                subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                    f'color=c=black:s={width}x{height}:r=24', '-t', '0.25',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(path)],
                    check=True, capture_output=True, timeout=30)
                self.assertEqual(repair_aspect.display_shape(media.probe(path))['aspect_ratio'], aspect)


class WorkflowAspectTests(unittest.TestCase):
    def test_one_off_override_in_prepare_and_simulated_submission(self):
        pwsh = shutil.which('pwsh')
        skill = Path(os.environ.get('USERPROFILE', '')) / '.codex/skills/runninghub-fixed-workflow/scripts/workflow.ps1'
        export = Path('C:/Users/admin/Downloads/minimax生成视频-仲月_api.json')
        if not pwsh or not skill.is_file() or not export.is_file():
            self.skipTest('Installed fixed workflow offline dependencies unavailable')
        original = export.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asset = root / 'asset.png'
            from PIL import Image
            Image.new('RGB', (16, 16), 'white').save(asset)
            captured = root / 'captured.json'
            wrapper = root / 'offline-workflow.ps1'
            # Reuse the real graph builder, replace all remote calls with strict local stubs.
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            wrapper.write_text(
                'param([string]$Action)\n'
                f'. {quote(skill)} -Action inspect | Out-Null\n'
                'function Get-Key { return "offline-test-key" }\n'
                'function Assert-CoinKey($key) {}\n'
                'function Get-ServerGraph($key) { Get-Content -LiteralPath $exportPath -Raw -Encoding UTF8 | ConvertFrom-Json }\n'
                'function Invoke-RestMethod {\n'
                '  param($Method, $Uri, $Headers, $Form, $TimeoutSec, $ContentType, $Body)\n'
                '  if ($Uri -eq "https://www.runninghub.cn/openapi/v2/media/upload/binary") {\n'
                '    return @{code=0; data=@{fileName="offline-asset.png"}}\n'
                '  }\n'
                '  if ($Uri -eq "https://www.runninghub.cn/task/openapi/create") {\n'
                '    $sent = $Body | ConvertFrom-Json\n'
                f'    $sent.workflow | Set-Content -LiteralPath {quote(captured)} -Encoding UTF8\n'
                '    return @{code=0; data=@{taskId="123456"}}\n'
                '  }\n'
                '  throw "Unexpected offline API call"\n'
                '}\n', encoding='utf-8')
            bridge = fixtures.ROOT / 'ai-storyboard-previs/scripts/workflow_bridge.ps1'
            child_env = dict(os.environ, RH_WORKFLOW_API_KEY='offline-test-key')
            for action, script in [('prepare', skill), ('submit', wrapper)]:
                for aspect in ('16:9', '9:16', '16:9'):
                    with self.subTest(action=action, aspect=aspect):
                        job = root / 'job.json'
                        core.save(job, dict(action=action, skill_script=str(script), request=dict(
                            workflow_id='2099403222661287938', instance_type='plus',
                            prompt='OFFLINE TEST', duration_seconds=3.0, aspect_ratio=aspect,
                            assets=[dict(path=str(asset), sha256=core.sha(asset))])))
                        result = subprocess.run([pwsh, '-NoProfile', '-File', str(bridge),
                            '-JobFile', str(job)], capture_output=True, text=True, encoding='utf-8',
                            env=child_env, timeout=30)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        data = json.loads(result.stdout)
                        if action == 'prepare':
                            self.assertTrue(data['prepared'])
                            self.assertFalse(data['submitted'])
                            self.assertEqual(data['aspectRatio'], aspect)
                        else:
                            self.assertEqual(data['taskId'], '123456')
                            graph = core.read(captured)
                            self.assertEqual(graph['115']['inputs']['aspect_ratio'].split()[0], aspect)
                            self.assertEqual(graph['136']['inputs']['width'], ['115', 0])
                            self.assertEqual(graph['136']['inputs']['height'], ['115', 1])
                            self.assertEqual(graph['132']['inputs']['value'], 3.0)
                        self.assertEqual(export.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
