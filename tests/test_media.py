"""Real FFmpeg integration; synthetic colors prove tooling, not narrative quality."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-storyboard-previs/scripts"))
import previs
import media
import storyboard


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.path = cls.root / "project.json"
        cls.p = previs.read(ROOT / "ai-storyboard-previs/assets/example-project.json")
        for i, g in enumerate(cls.p["groups"]):
            path = cls.root / (g["id"] + ".mp4")
            color = "red" if i == 0 else "blue"
            size = "320x180" if i == 0 else "240x240"
            media.command([media.binary("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", f"color={color}:s={size}:r=24:d=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", path])
            cls.p["tasks"][g["id"]] = dict(kind="video", target_id=g["id"], version=g["version"], status="SUCCESS", outputs=[str(path)], output_hashes=[previs.sha(path)], group_fingerprint=previs.group_fingerprint(cls.p, cls.path, g))
        cls.output = cls.root / "silent.mp4"
        cls.delivery = media.assemble(cls.p, cls.path, cls.output)
        cls.evidence = media.extract(cls.output, cls.root / "evidence", [{"shot_id": "syntheticA", "start": 0, "end": 1}, {"shot_id": "syntheticB", "start": 1, "end": 2}], .25)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_audio_removed_and_aspect_duration_preserved(self):
        info = media.probe(self.output)
        self.assertEqual([s["codec_type"] for s in info["streams"]], ["video"])
        self.assertEqual((info["streams"][0]["width"], info["streams"][0]["height"]), (320, 180))
        self.assertAlmostEqual(media.duration(info), 2, places=1)
        self.assertEqual([s["group_id"] for s in self.delivery["segments"]], ["G01", "G02"])

    def test_actual_pts_and_color_order(self):
        self.assertFalse(self.evidence["verified"])
        self.assertTrue(any(abs(t-1) < .05 for t in self.evidence["candidate_cuts"]))
        for target, channel in ((.25, 0), (1.25, 2)):
            frame = min(self.evidence["frames"], key=lambda f: abs(f["time"]-target))
            with Image.open(frame["path"]) as image:
                rgb = image.convert("RGB").getpixel((160, 90))
            self.assertGreater(rgb[channel], 220)
            self.assertAlmostEqual(frame["time"], frame["frame_index"]/24, places=5)
            self.assertEqual(frame["sha256"], previs.sha(Path(frame["path"])))

    def test_real_extraction_to_matched_images_and_markdown(self):
        p = copy.deepcopy(self.p)
        p["shots"] = p["shots"][:2]
        p["groups"] = [dict(id="G01", shot_ids=["S01", "S02"], version=1)]
        g = p["groups"][0]
        p["tasks"] = {"synthetic": dict(kind="video", target_id="G01", version=1,
            status="SUCCESS", outputs=[str(self.output)], output_hashes=[previs.sha(self.output)],
            group_fingerprint=previs.group_fingerprint(p, self.path, g))}
        rows = []
        for sid, t in (("S01", .25), ("S02", 1.25)):
            frame = min(self.evidence["frames"], key=lambda f: abs(f["time"]-t))
            rows.append(dict(shot_id=sid, status="matched", observation="Synthetic red/blue color fixture, not script acceptance",
                candidates=[dict(path=frame["path"], time=frame["time"])]))
        storyboard.record_mapping(p, self.path, dict(group_id="G01", video_sha256=previs.sha(self.output),
            evidence_file=str(self.root / "evidence/evidence.json"), shots=rows))
        for row in rows:
            frame = row["candidates"][0]
            storyboard.select_image(p, self.path, dict(shot_id=row["shot_id"], path=frame["path"],
                source=dict(kind="frame", time=frame["time"]), reason="Synthetic tooling check only"))
        out = self.root / "storyboard-delivery"
        document = Path(storyboard.render(p, self.path, out)).read_text(encoding="utf8")
        self.assertEqual(document.count("未验证"), 2)
        self.assertEqual(len(list(out.rglob("*.png"))), 2)
        self.assertFalse(list(out.rglob("*.mp4")))

    def test_assembly_preserves_prior_files_and_rejects_stale_group(self):
        with self.assertRaisesRegex(ValueError, "new delivery"):
            media.assemble(self.p, self.path, self.output)
        p = copy.deepcopy(self.p)
        p["groups"][0]["version"] += 1
        with self.assertRaisesRegex(ValueError, "current successful"):
            media.assemble(p, self.path, self.root / "stale.mp4")


if __name__ == "__main__": unittest.main(verbosity=2)
