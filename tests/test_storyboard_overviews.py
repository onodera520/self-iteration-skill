"""Observable sheet order, source preservation and stale-evidence rejection."""
import copy

from PIL import Image
import storyboard_fixtures as fixtures
import previs as core
import storyboard_overviews as overviews


class StoryboardOverviewsTests(fixtures.Base):
    def context(self, count=14):
        shots = []
        for index in range(count):
            # Deliberately use names whose lexical order differs from input order.
            path = self.png(str(index + 1), (index * 10, 80, 100))
            shots.append(dict(shot_id=f'S{index + 1:02d}', image=dict(path=str(path), sha256=core.sha(path))))
        return dict(shots=shots, source_fingerprint=core.digest(shots), context_fingerprint='test-context')

    def test_fourteen_images_keep_order_across_nine_and_five(self):
        ctx = self.context()
        originals = [core.sha(s['image']['path']) for s in ctx['shots']]
        result = overviews.build(ctx, self.path.parent)
        self.assertEqual([p['shot_ids'] for p in result['pages']],
                         [[f'S{i:02d}' for i in range(1, 10)], [f'S{i:02d}' for i in range(10, 15)]])
        manifest = core.read(result['manifest']['path'])
        for page in manifest['pages']:
            with Image.open(page['path']) as image:
                self.assertEqual(image.size, overviews.PAGE)
                for tile in page['tiles']:
                    x1, y1, x2, y2 = tile['image_rect']
                    index = int(tile['shot_id'][1:]) - 1
                    self.assertEqual(image.getpixel(((x1 + x2) // 2, (y1 + y2) // 2)), (index * 10, 80, 100))
        with Image.open(manifest['pages'][1]['path']) as image:
            self.assertEqual(image.getpixel((overviews.PAGE[0] - 50, overviews.PAGE[1] - 50)), (255, 255, 255))
        self.assertEqual([core.sha(s['image']['path']) for s in ctx['shots']], originals)
        overviews.validate(ctx, result['manifest'])

    def test_nine_images_produce_exactly_one_page(self):
        result = overviews.build(self.context(9), self.path.parent)
        self.assertEqual(len(result['pages']), 1)
        self.assertEqual(len(result['pages'][0]['shot_ids']), 9)

    def test_portrait_and_exif_rotation_keep_full_bounds(self):
        ctx = self.context(2)
        first, second = [s['image'] for s in ctx['shots']]
        portrait = Image.new('RGB', (100, 200), 'red')
        portrait.paste('blue', (0, 160, 100, 200))
        portrait.save(first['path'])
        rotated = Image.new('RGB', (200, 100), 'green')
        exif = rotated.getexif()
        exif[274] = 6
        rotated.save(second['path'], exif=exif)
        for image in (first, second):
            image['sha256'] = core.sha(image['path'])
        result = overviews.build(ctx, self.path.parent)
        page = core.read(result['manifest']['path'])['pages'][0]
        with Image.open(page['path']) as image:
            for tile in page['tiles']:
                x1, y1, x2, y2 = tile['image_rect']
                self.assertEqual((x2 - x1, y2 - y1), (180, 360))
            x1, y1, x2, y2 = page['tiles'][0]['image_rect']
            self.assertEqual(image.getpixel(((x1 + x2) // 2, y1 + 5)), (255, 0, 0))
            self.assertEqual(image.getpixel(((x1 + x2) // 2, y2 - 5)), (0, 0, 255))

    def test_modified_sheet_or_manifest_is_rejected(self):
        ctx = self.context(1)
        result = overviews.build(ctx, self.path.parent)
        page = result['pages'][0]['path']
        Image.new('RGB', overviews.PAGE, 'black').save(page)
        with self.assertRaisesRegex(ValueError, '总览图已变化'):
            overviews.validate(ctx, result['manifest'])
        manifest = core.read(result['manifest']['path'])
        manifest['pages'][0]['sha256'] = core.sha(page)
        core.save(result['manifest']['path'], manifest)
        with self.assertRaisesRegex(ValueError, '清单已变化'):
            overviews.validate(ctx, result['manifest'])

    def test_new_context_cannot_use_old_sheet_and_old_worklists_remain_supported(self):
        ctx = self.context(1)
        result = overviews.build(ctx, self.path.parent)
        changed = copy.deepcopy(ctx)
        changed['source_fingerprint'] = 'different-source'
        with self.assertRaisesRegex(ValueError, '来源已变化'):
            overviews.validate(changed, result['manifest'])
        overviews.validate(ctx, None)
