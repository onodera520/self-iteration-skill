"""State/prompt contracts with simulated facts; these are not vision tests."""
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
import requirements as req
import rh_tasks as rh


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project.json"
        self.p = core.read(ROOT / "ai-storyboard-previs/assets/example-project.json")
        for a in self.p["assets"]:
            a["path"] = str(self.path.parent / (a["id"] + ".png"))
            Image.new("RGB", (32, 32), "red").save(a["path"])
        for i, s in enumerate(self.p["shots"]):
            s["requirements"] = dict(version=1, status="ready", purpose=s["required_result"],
                inherits_from=self.p["shots"][i-1]["id"] if i else None,
                entry_state={} if i else {"key.holder": "girl", "girl.coat_worn": False},
                keyframe=dict(phase="exit", description=s["required_result"], state={}),
                must_have=[s["required_result"]], must_not_have=["第二把钥匙"],
                provenance=[dict(field="keyframe", status="script", source=s["id"])])

    def test_static_before_handoff_and_video_complete_action(self):
        s = self.p["shots"][2]
        s["requirements"]["keyframe"].update(phase="entry", description="女孩仍握着钥匙")
        s["requirements"]["must_have"] = ["女孩仍握着钥匙"]
        c = req.contexts(self.p)["S03"]
        self.assertEqual(c["keyframe"]["state"]["key.holder"], "girl")
        self.assertEqual(c["exit_state"]["key.holder"], "boy")
        image = req.target_text(c, "image")
        self.assertNotIn('"key.holder": "boy"', image)
        video = core.prompt(self.p, "G01")
        self.assertIn('"key.holder": "boy"', video)
        self.assertIn(s["script"], video)

    def test_reverse_angle_projection_does_not_change_world_or_hand(self):
        a, b = self.p["shots"][:2]
        a["requirements"]["entry_state"].update({"girl.world_position": "door", "girl.holding_hand": "right"})
        a["requirements"]["keyframe"]["state"] = {"girl.screen_position": "left"}
        b["requirements"]["keyframe"]["state"] = {"girl.screen_position": "right"}
        c = req.contexts(self.p)["S02"]
        self.assertEqual(c["keyframe"]["state"]["girl.screen_position"], "right")
        self.assertEqual(c["exit_state"]["girl.world_position"], "door")
        self.assertEqual(c["exit_state"]["girl.holding_hand"], "right")
        self.assertNotIn("girl.screen_position", c["exit_state"])

    def test_offscreen_clothing_and_prop_survive_scene_and_group_change(self):
        c = req.contexts(self.p)["S04"]
        self.assertNotIn("girl", self.p["shots"][3]["asset_ids"])
        self.assertFalse(c["entry_state"]["girl.coat_worn"])
        self.assertEqual(c["entry_state"]["key.holder"], "boy")

    def test_wrong_phase_and_silent_hand_switch_are_rejected(self):
        self.p["shots"][0]["requirements"]["entry_state"]["girl.holding_hand"] = "right"
        self.p["shots"][1]["requirements"]["entry_state"]["girl.holding_hand"] = "left"
        with self.assertRaisesRegex(ValueError, "inherited"):
            req.contexts(self.p)
        self.p["shots"][1]["requirements"]["entry_state"] = {}
        self.p["shots"][2]["requirements"]["keyframe"]["state"] = {"key.holder": "girl"}
        with self.assertRaisesRegex(ValueError, "selected phase"):
            req.contexts(self.p)

    def test_nonlocal_state_change_invalidates_review_and_group_mapping(self):
        old_review = boards.review_fingerprint(self.p, self.path, "S04")
        old_video = core.group_fingerprint(self.p, self.path, self.p["groups"][1])
        self.p["shots"][0]["requirements"]["entry_state"]["girl.coat_worn"] = True
        self.assertNotEqual(old_review, boards.review_fingerprint(self.p, self.path, "S04"))
        self.assertNotEqual(old_video, core.group_fingerprint(self.p, self.path, self.p["groups"][1]))

    def test_presentation_change_with_same_exit_preserves_distant_review(self):
        before = boards.review_fingerprint(self.p, self.path, "S04")
        self.p["shots"][0]["requirements"]["keyframe"]["description"] = "SIMULATED revised framing"
        self.p["shots"][0]["requirements"]["version"] += 1
        self.assertEqual(before, boards.review_fingerprint(self.p, self.path, "S04"))

    def test_cycles_and_unexplained_continuity_crossing_rejected(self):
        self.p["shots"][0]["requirements"]["inherits_from"] = "S04"
        with self.assertRaisesRegex(ValueError, "earlier"):
            req.contexts(self.p)
        self.p["shots"][0]["requirements"]["inherits_from"] = None
        self.p["shots"][3]["continuity_id"] = "flashback"
        with self.assertRaisesRegex(ValueError, "continuity_id"):
            req.contexts(self.p)

    def test_provisional_parent_blocks_generation_and_image_approval(self):
        self.p["shots"][0]["requirements"]["status"] = "provisional"
        with self.assertRaisesRegex(ValueError, "provisional"):
            core.prompt(self.p, "G02")
        for s in self.p["shots"]:
            boards.select_image(self.p, self.path, dict(shot_id=s["id"], path=self.p["assets"][0]["path"],
                source=dict(kind="provided"), reason="SIMULATED selection"))
        with self.assertRaisesRegex(ValueError, "provisional"):
            boards.record_review(self.p, self.path, dict(shot_id="S04",
                image_sha256=boards.selected(self.p, self.path, "S04")["sha256"],
                fingerprint=boards.review_fingerprint(self.p, self.path, "S04"),
                checks={c: "PASS" for c in boards.CHECKS}, observation="SIMULATED", expected="SIMULATED"))

    def test_image_request_gets_same_target_and_rejects_prompt_override(self):
        module, _ = rh.kit()
        registry = {"models": [{"endpoint": "test/image", "params": [
            {"fieldKey": "prompt", "type": "STRING", "required": True}]}]}
        request = dict(id="S03-image", kind="image", target_id="S03", version=1, endpoint="test/image",
            payload={"prompt": "KEEP 构图；CHANGE 仅修钥匙。"}, prompt_field="prompt", estimated_cost_cny=1)
        before = copy.deepcopy(self.p)
        data = rh.prepare(self.p, self.path, request, module, registry)
        self.assertIn(req.target_text(req.contexts(self.p)["S03"], "image"), data["payload"]["prompt"])
        self.assertEqual(self.p, before)
        request["mute_fields"] = {"prompt": "overwrite"}
        with self.assertRaisesRegex(ValueError, "overwrite"):
            rh.prepare(self.p, self.path, request, module, registry)

    def test_requirements_do_not_leak_into_user_markdown(self):
        doc = Path(boards.render(self.p, self.path, self.path.parent / "delivery")).read_text(encoding="utf8")
        self.assertNotIn("inherits_from", doc)
        self.assertNotIn("provenance", doc)
        self.assertEqual(doc.count("待补图"), 4)

    def test_source_conflict_or_unknown_cannot_silently_pass(self):
        self.p["shots"][2]["facts"][-1]["value"] = "girl"
        with self.assertRaisesRegex(ValueError, "source fact"):
            req.contexts(self.p)
        self.p["shots"][2]["facts"][-1].update(status="unknown", value=None)
        self.assertFalse(req.contexts(self.p)["S04"]["ready"])

    def test_legacy_project_without_requirements_remains_readable(self):
        for s in self.p["shots"]:
            s.pop("requirements")
        self.assertEqual(req.contexts(self.p), {})
        core.validate(self.p, self.path)
        self.assertIn(self.p["shots"][2]["script"], core.prompt(self.p, "G01"))


if __name__ == "__main__":
    unittest.main()
