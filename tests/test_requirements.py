"""Sourced state inheritance for current image references."""
import copy
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from storyboard_fixtures import ROOT
import previs as core
import requirements as req


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project.json"
        self.p = core.read(ROOT / "tests/fixtures/storyboard-states.json")
        self.p["config"].pop("video_source", None)
        self.p.pop("user_video_prompt", None)
        for g in self.p["groups"]: g.pop("video_prompt", None)
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

    def test_cycles_and_unexplained_continuity_crossing_rejected(self):
        self.p["shots"][0]["requirements"]["inherits_from"] = "S04"
        with self.assertRaisesRegex(ValueError, "earlier"):
            req.contexts(self.p)
        self.p["shots"][0]["requirements"]["inherits_from"] = None
        self.p["shots"][3]["continuity_id"] = "flashback"
        with self.assertRaisesRegex(ValueError, "continuity_id"):
            req.contexts(self.p)

    def test_source_conflict_or_unknown_cannot_silently_pass(self):
        self.p["shots"][2]["facts"][-1]["value"] = "girl"
        with self.assertRaisesRegex(ValueError, "source fact"):
            req.contexts(self.p)
        self.p["shots"][2]["facts"][-1].update(status="unknown", value=None)
        self.assertFalse(req.contexts(self.p)["S04"]["ready"])
