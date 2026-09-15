"""Storyboard acceptance tests. All judgments below are explicit simulated fixtures."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-storyboard-previs/scripts"))
import previs as core
import storyboard as boards
import planner
import rh_tasks as rh


class StoryboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project.json"
        self.p = core.read(ROOT / "ai-storyboard-previs/assets/example-project.json")
        self.profile = core.read(ROOT / "ai-storyboard-previs/assets/example-model-profile.json")
        for n, asset in enumerate(self.p["assets"]):
            asset["path"] = self.png(asset["id"], (20+n*40, 70, 90)).name

    def png(self, name, color):
        path = self.path.parent / (name + ".png")
        Image.new("RGB", (64, 36), color).save(path)
        return path

    def select(self, sid, color="red", kind="provided"):
        path = self.png(sid + "-" + str(color), color)
        boards.select_image(self.p, self.path, dict(shot_id=sid, path=str(path),
            source=dict(kind=kind), reason="SIMULATED image selection"))
        return path

    def all_images(self):
        for sid in ("S01", "S02", "S03", "S04"):
            self.select(sid)

    def review(self, sid, verdict="PASS"):
        return dict(shot_id=sid, image_sha256=boards.selected(self.p, self.path, sid)["sha256"],
            fingerprint=boards.review_fingerprint(self.p, self.path, sid),
            checks={c: verdict for c in boards.CHECKS}, observation="SIMULATED visible evidence",
            expected="SIMULATED script expectation",
            problems=["SIMULATED wrong key state"] if verdict == "FAIL" else [],
            uncertainties=["SIMULATED occluded prop"] if verdict == "uncertain" else [])

    def mapping(self):
        g = self.p["groups"][0]
        video = self.path.parent / "source.mp4"
        video.write_bytes(b"SIMULATED video; not actual visual evidence")
        self.p["tasks"]["video"] = dict(kind="video", target_id=g["id"], version=g["version"],
            status="SUCCESS", outputs=[str(video)], output_hashes=[core.sha(video)],
            group_fingerprint=core.group_fingerprint(self.p, self.path, g))
        frames = []
        for n, sid in enumerate(g["shot_ids"]):
            path = self.png("frame-" + sid, (n*70, 60, 90))
            frames.append(dict(path=str(path), sha256=core.sha(path), time=n+.25))
        evidence = self.path.parent / "evidence.json"
        core.save(evidence, dict(video_sha256=core.sha(video), frames=frames))
        return dict(group_id=g["id"], video_sha256=core.sha(video), evidence_file=str(evidence),
            shots=[dict(shot_id=sid, status="matched", observation="SIMULATED match",
                candidates=[dict(path=f["path"], time=f["time"])])
                for sid, f in zip(g["shot_ids"], frames)])

    def test_asset_plan_does_not_require_input_storyboard_images(self):
        a = planner.plan(self.p, self.path, self.profile)
        self.assertEqual(a, planner.plan(copy.deepcopy(self.p), self.path, self.profile))
        self.assertEqual([sid for g in a["groups"] for sid in g["shot_ids"]], ["S01", "S02", "S03", "S04"])
        planner.apply_plan(self.p, self.path, a)
        self.assertEqual(core.validate(self.p, self.path)["missing_assets"], [])
        self.profile["max_images"] = 3
        with self.assertRaisesRegex(ValueError, "no feasible"):
            planner.plan(self.p, self.path, self.profile)

    def test_asset_order_matches_model_payload_and_prompt(self):
        module, _ = rh.kit()
        registry = {"models": [{"endpoint": "test/video", "params": [
            {"fieldKey": "prompt", "type": "STRING", "required": True},
            {"fieldKey": "images", "type": "IMAGE", "maxInputNum": 4, "required": True}]}]}
        request = dict(id="G01-v1", kind="video", target_id="G01", version=1,
            endpoint="test/video", payload={}, prompt_field="prompt", reference_field="images", estimated_cost_cny=2)
        data = rh.prepare(self.p, self.path, request, module, registry)
        self.assertEqual(data["files"]["images"], [a["path"] for a in self.p["assets"]])
        prompt = data["payload"]["prompt"]
        self.assertTrue(prompt.index("girl") < prompt.index("boy") < prompt.index("hall") < prompt.index("key"))
        self.assertIn("S02", prompt)
        self.assertIn("硬切", prompt)

    def test_matching_evidence_can_select_without_invalidating_video(self):
        data = self.mapping()
        boards.record_mapping(self.p, self.path, data)
        row = data["shots"][0]
        fp = core.group_fingerprint(self.p, self.path, self.p["groups"][0])
        boards.select_image(self.p, self.path, dict(shot_id="S01", path=row["candidates"][0]["path"],
            source=dict(kind="frame", time=.25), reason="SIMULATED best frame"))
        self.assertEqual(core.group_fingerprint(self.p, self.path, self.p["groups"][0]), fp)
        self.assertIsNotNone(core.current_video(self.p, self.path, self.p["groups"][0])[0])
        self.assertIsNone(boards.current_review(self.p, self.path, "S01"))

    def test_absence_needs_rescan_and_uncertainty_cannot_trigger_paid_repair(self):
        data = self.mapping()
        data["shots"][1].update(status="absent", candidates=[])
        with self.assertRaisesRegex(ValueError, "rescan"):
            boards.record_mapping(self.p, self.path, data)
        data["shots"][1]["status"] = "uncertain"
        boards.record_mapping(self.p, self.path, data)
        operation = dict(shot_id="S02", action="generate_image", reason="SIMULATED")
        with self.assertRaisesRegex(ValueError, "confirmed"):
            boards.repair(self.p, self.path, dict(operations=[operation]))
        data["shots"][1].update(status="absent", full_rescan=True)
        boards.record_mapping(self.p, self.path, data)
        boards.repair(self.p, self.path, dict(operations=[operation]))
        self.assertEqual(self.p["repair_round"], 1)

    def test_mapping_rejects_missing_shots_wrong_time_and_modified_frame(self):
        base = self.mapping()
        for mutate, error in (
            (lambda d: d["shots"].pop(), "every shot"),
            (lambda d: d["shots"][0]["candidates"][0].update(time=8), "timestamp"),
            (lambda d: d["shots"][0].update(candidates=base["shots"][2]["candidates"]), "script order"),
        ):
            data = copy.deepcopy(base)
            mutate(data)
            with self.assertRaisesRegex(ValueError, error):
                boards.record_mapping(self.p, self.path, data)
        Image.new("RGB", (64,36), "white").save(base["shots"][0]["candidates"][0]["path"])
        with self.assertRaisesRegex(ValueError, "unchanged extraction"):
            boards.record_mapping(self.p, self.path, base)

    def test_neighbor_change_invalidates_only_affected_reviews(self):
        self.all_images()
        for sid in ("S01", "S04"):
            boards.record_review(self.p, self.path, self.review(sid))
        self.select("S02", "blue")
        self.assertIsNone(boards.current_review(self.p, self.path, "S01"))
        self.assertEqual(boards.current_review(self.p, self.path, "S04")["verdict"], "PASS")

    def test_image_task_output_is_unverified_until_visual_review(self):
        path = self.png("generated", "green")
        data = dict(shot_id="S01", path=str(path), source=dict(kind="generated", request_id="image1"), reason="SIMULATED")
        with self.assertRaisesRegex(ValueError, "successful image task"):
            boards.select_image(self.p, self.path, data)
        self.p["tasks"]["image1"] = dict(kind="image", target_id="S01", status="SUCCESS",
            outputs=[str(path)], output_hashes=[core.sha(path)])
        boards.select_image(self.p, self.path, data)
        self.assertIsNone(boards.current_review(self.p, self.path, "S01"))
        with self.assertRaisesRegex(ValueError, "neighboring images"):
            boards.record_review(self.p, self.path, self.review("S01"))

    def test_critical_omission_forbidden_and_input_ai_fill_does_not_omit_output(self):
        data = dict(shot_id="S03", reason="SIMULATED", context_evidence="SIMULATED", preserves_story=True)
        with self.assertRaisesRegex(ValueError, "critical"):
            boards.omit_image(self.p, self.path, data)
        self.assertEqual(self.p["shots"][1]["reference"]["mode"], "ai_fill")
        self.assertIsNone(boards.omitted(self.p, self.path, "S02"))
        data["shot_id"] = "S02"
        boards.omit_image(self.p, self.path, data)
        doc = Path(boards.render(self.p, self.path, self.path.parent / "delivery")).read_text(encoding="utf8")
        self.assertIn("## S02", doc)
        self.assertIn(self.p["shots"][1]["script"], doc)
        self.assertIn("无需单独配图：", doc)

    def test_local_image_repair_preserves_video_and_passing_other_images(self):
        self.all_images()
        self.mapping()
        boards.record_review(self.p, self.path, self.review("S01", "FAIL"))
        boards.record_review(self.p, self.path, self.review("S04", "PASS"))
        fp = core.group_fingerprint(self.p, self.path, self.p["groups"][0])
        boards.repair(self.p, self.path, dict(operations=[dict(shot_id="S01", action="edit_image", reason="SIMULATED")]))
        self.assertEqual(core.group_fingerprint(self.p, self.path, self.p["groups"][0]), fp)
        self.assertEqual(boards.current_review(self.p, self.path, "S04")["verdict"], "PASS")
        self.assertEqual(self.p["repairs"][-1]["recheck"], ["S01", "S02"])

    def test_omission_must_be_rechecked_when_context_image_changes(self):
        self.all_images()
        boards.omit_image(self.p, self.path, dict(shot_id="S02", reason="SIMULATED redundant transition",
            context_evidence="SIMULATED neighboring images cover this event", preserves_story=True))
        self.assertIsNotNone(boards.omitted(self.p, self.path, "S02"))
        self.select("S03", "blue")
        self.assertIsNone(boards.omitted(self.p, self.path, "S02"))

    def test_paid_round_limit_and_free_rematching(self):
        self.all_images()
        boards.record_review(self.p, self.path, self.review("S01", "FAIL"))
        data = dict(operations=[dict(shot_id="S01", action="edit_image", reason="SIMULATED")])
        for _ in range(3):
            boards.repair(self.p, self.path, data)
        with self.assertRaisesRegex(ValueError, "round limit"):
            boards.repair(self.p, self.path, data)
        boards.repair(self.p, self.path, dict(operations=[dict(shot_id="S01", action="rematch", reason="SIMULATED")]))
        self.assertEqual(self.p["repair_round"], 3)
        self.assertIsNotNone(boards.selected(self.p, self.path, "S01"))

    def test_regenerate_group_requires_reason_and_preserves_existing_images(self):
        self.all_images()
        boards.record_review(self.p, self.path, self.review("S01", "FAIL"))
        op = dict(shot_id="S01", action="regenerate_group", reason="SIMULATED")
        with self.assertRaisesRegex(ValueError, "individual image"):
            boards.repair(self.p, self.path, dict(operations=[op]))
        op["why_not_image_repair"] = "SIMULATED whole group composition unusable"
        boards.repair(self.p, self.path, dict(operations=[op]))
        self.assertEqual([g["version"] for g in self.p["groups"]], [2,1])
        self.assertTrue(all(boards.selected(self.p, self.path, sid) for sid in ("S01","S02","S03","S04")))

    def test_restore_best_image_with_original_provenance(self):
        old = self.select("S01")
        self.select("S01", "blue")
        boards.restore_image(self.p, self.path, dict(shot_id="S01", history_index=0))
        self.assertEqual(boards.selected(self.p, self.path, "S01")["sha256"], core.sha(old))
        self.assertEqual(len(self.p["shots"][0]["board"]["history"]), 2)

    def test_render_only_images_markdown_in_order_ignores_old_video_delivery(self):
        self.all_images()
        self.p["delivery"] = {"path": "private.mp4"}
        self.p["config"]["delivery_mode"] = "legacy"
        out = self.path.parent / "delivery"
        doc = Path(core.render(self.p, self.path, out)).read_text(encoding="utf8")
        self.assertEqual(len(list(out.rglob("*.png"))), 4)
        self.assertEqual({p.suffix for p in out.rglob("*") if p.is_file()}, {".md", ".png"})
        self.assertEqual(doc.count("![S"), 4)
        self.assertNotIn("private.mp4", doc)
        self.assertEqual(doc.count("未验证"), 4)
        self.assertTrue(doc.index("## S01") < doc.index("## S02") < doc.index("## S03") < doc.index("## S04"))
        self.select("S01", "blue")
        with self.assertRaisesRegex(ValueError, "new delivery"):
            boards.render(self.p, self.path, out)

    def test_illustration_cannot_pass_and_old_video_folder_cannot_be_reused(self):
        self.all_images()
        self.select("S01", "red", kind="illustration")
        with self.assertRaisesRegex(ValueError, "illustrative"):
            boards.record_review(self.p, self.path, self.review("S01"))
        out = self.path.parent / "legacy"
        out.mkdir()
        (out / "old.mp4").write_bytes(b"SIMULATED")
        with self.assertRaisesRegex(ValueError, "clean storyboard"):
            boards.render(self.p, self.path, out)


if __name__ == "__main__":
    unittest.main()
