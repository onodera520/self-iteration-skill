"""Image-only test data. All visual judgments are explicitly simulated."""
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ai-storyboard-previs/scripts'))
import previs as core
import repair_quality as quality


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'project.json'
        self.p = core.read(ROOT / 'tests/fixtures/storyboard-project.json')
        for i, a in enumerate(self.p['assets']):
            a['path'] = str(self.png(a['id'], (i * 50, 60, 90)))
        core.save(self.path, self.p)

    def png(self, name, colour=(50, 60, 90)):
        path = self.path.parent / (name + '.png')
        Image.new('RGB', (64, 36), colour).save(path)
        return path

    def simulated_plan(self):
        source = quality.source_request(self.p, self.path, 'G01')
        plan = quality.compact_template(source)
        plan.update(preserves_story=True, checks_passed=True,
                    reviewed_shot_ids=[b['shot_id'] for b in source['blocks']],
                    checks={name: 'SIMULATED fixture judgment for ' + name
                            for name in quality.CHECKS})
        # Offline compilation fixture: explicitly retain every independent input
        # contribution. This tests bindings and export, not prose quality.
        for block in source['blocks']:
            if block['shot_id'] in quality.attention_shots(source):
                content = '。'.join(dict.fromkeys(quality.sources(block).values()))
                plan['edits'].append(dict(shot_id=block['shot_id'], content=content))
                plan['notes'][block['shot_id']] = 'SIMULATED: each source contribution retained for this fixture.'
        return plan
