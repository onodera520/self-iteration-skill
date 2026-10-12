"""Viewing crops preserve the original evidence; no visual judgments are automated."""
from pathlib import Path
import subprocess
import sys

from PIL import Image
import test_previs as fixtures
import crop


class CropTests(fixtures.Base):
    def source(self):
        path = self.path.parent/'frame.png'
        image = Image.new('RGB', (6, 4), 'red')
        image.paste('blue', (3, 0, 6, 4))
        image.save(path)
        return path

    def test_crop_pixels_size_and_source_are_preserved(self):
        source = self.source()
        before = source.read_bytes()
        output = self.path.parent/'internal/crops/detail.png'
        self.assertEqual(crop.crop(source, output, [3, 0, 6, 4], 2), output.resolve())
        with Image.open(output) as image:
            self.assertEqual(image.size, (6, 8))
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 255))
            self.assertEqual(image.getpixel((5, 7)), (0, 0, 255))
        self.assertEqual(source.read_bytes(), before)

    def test_bad_coordinates_and_scale_create_no_output(self):
        source = self.source()
        output = self.path.parent/'detail.png'
        for box, scale in [([-1, 0, 3, 4], 2), ([0, 0, 7, 4], 2), ([3, 0, 3, 4], 2),
                           ([0, 0, 6, 5], 2), ([0, 0, 6], 2), ([0, 0, 6.0, 4], 2),
                           ([0, 0, 6, 4], 0), ([0, 0, 6, 4], -1),
                           ([0, 0, 6, 4], float('nan')), ([0, 0, 6, 4], float('inf'))]:
            with self.subTest(box=box, scale=scale), self.assertRaises(ValueError):
                crop.crop(source, output, box, scale)
            self.assertFalse(output.exists())

    def test_original_and_existing_output_cannot_be_overwritten(self):
        source = self.source()
        original = source.read_bytes()
        output = self.path.parent/'existing.png'
        output.write_bytes(b'keep existing')
        for target in (source, output):
            with self.subTest(target=target), self.assertRaises(ValueError):
                crop.crop(source, target, [0, 0, 6, 4])
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(output.read_bytes(), b'keep existing')

    def test_cli_creates_view_and_rejects_reuse(self):
        source = self.source()
        output = self.path.parent/'cli.png'
        command = [sys.executable, '-X', 'utf8', str(Path(crop.__file__)), str(source),
                   '--box', '3', '0', '6', '4', '--scale', '1', '--output', str(output)]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = output.read_bytes()
        repeated = subprocess.run(command, capture_output=True, text=True, encoding='utf8', timeout=30)
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn('new file', repeated.stderr)
        self.assertEqual(output.read_bytes(), before)
