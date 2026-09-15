"""Behavioral tests. Review fixtures are simulated records, not visual judgments."""
import copy
import itertools
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-storyboard-previs/scripts"))
import previs as core
import planner
import rh_tasks as rh


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "project.json"
        self.p = core.read(ROOT / "ai-storyboard-previs/assets/example-project.json")
        self.profile = core.read(ROOT / "ai-storyboard-previs/assets/example-model-profile.json")
        self.p["config"]["video_input_mode"] = "anchors"
        self.profile["max_images"] = 3
        for s in self.p["shots"]:
            if s["reference"]["mode"] == "anchor":
                f = self.path.parent / (s["id"] + ".png")
                f.write_bytes(b"mock-image-" + s["id"].encode())
                s["reference"]["path"] = f.name
        core.save(self.path, self.p)

    def video(self, gid="G01"):
        g = core.group(self.p, gid)
        path = self.path.parent / f"{gid}-v{g['version']}.mp4"
        path.write_bytes(b"simulated-output-" + str(g["version"]).encode())
        task = dict(kind="video", target_id=gid, version=g["version"], status="SUCCESS", outputs=[path.name], output_hashes=[core.sha(path)], group_fingerprint=core.group_fingerprint(self.p, self.path, g), duration=sum(s["duration"] for s in core.shots(self.p, g)))
        self.p["tasks"][path.stem] = task
        return task, path

    def review(self, gid="G01", verdict="PASS", category="story", problem="missing shot"):
        task, path = self.video(gid)
        ids = core.group(self.p, gid)["shot_ids"]
        t = 0
        spans = []
        evidence = []
        for s in core.shots(self.p, core.group(self.p, gid)):
            spans.append(dict(shot_id=s["id"], start=t, end=t+s["duration"]))
            evidence.append(dict(shot_id=s["id"], time=t+.1, observation="SIMULATED timed evidence"))
            t += s["duration"]
        r = dict(group_id=gid, version=task["version"], video_sha256=core.sha(path), checks={c: "PASS" for c in ("shot", "continuity", "story", "subtitles")}, coverage=dict(shot_ids=ids, mapping_verified=True, actual_shots=spans, limitations=[]), evidence=evidence, issues=[], uncertainties=[])
        r["checks"][category] = verdict
        if verdict == "FAIL":
            r["issues"] = [dict(id="issue1", shot_ids=[ids[0]], time_range=[0, .5], severity="high", problem=problem, expected="script condition", actual="contradicting visible condition", evidence=["SIMULATED frame 0.1s"], repair_target="video_shot", fix="restore the required result; keep passed shots")]
        if verdict == "uncertain": r["uncertainties"] = ["Need continuous playback"]
        return r


class PlannerTests(Base):
    def test_unknown_after_does_not_reuse_previous_holder(self):
        self.p["shots"][2]["facts"][-1].update(status="unknown", value=None)
        states = planner.analyze(self.p)
        self.assertIsNone(states[2]["expected_after"]["key.holder"]["value"])

    def test_deterministic_order_mapping_and_idempotence(self):
        a = planner.plan(self.p, self.path, self.profile)
        b = planner.plan(copy.deepcopy(self.p), self.path, self.profile)
        self.assertEqual(a, b)
        self.assertEqual([s for g in a["groups"] for s in g["shot_ids"]], ["S01", "S02", "S03", "S04"])
        self.assertEqual(a["decisions"][1]["bracket"], {"before": "S01", "after": "S03"})
        planner.apply_plan(self.p, self.path, a)
        self.assertEqual(planner.plan(self.p, self.path, self.profile), a)

    def test_zero_novelty_does_not_remove_critical_result(self):
        self.p["shots"][1]["intent"]["critical_result"] = True
        result = planner.plan(self.p, self.path, self.profile)
        self.assertEqual(result["decisions"][1]["novelty_ratio"], 0)
        self.assertEqual(result["decisions"][1]["mode"], "anchor")
        self.assertIn("CRITICAL_RESULT", result["decisions"][1]["rules"])

    def test_unknown_holder_is_protected(self):
        f = self.p["shots"][1]["facts"][-1]
        f.update(value=None, status="unknown")
        result = planner.plan(self.p, self.path, self.profile)
        self.assertIn("UNKNOWN_CRITICAL", result["decisions"][1]["rules"])
        self.assertEqual(result["decisions"][1]["mode"], "anchor")
        self.assertIsNone(result["analysis"][1]["expected_before"]["key.holder"]["value"])

    def test_unknown_semantics_not_eligible(self):
        self.p["shots"][1]["omission_assessment"].update(allowed=None, risk="unknown")
        result = planner.plan(self.p, self.path, self.profile)
        self.assertEqual(result["decisions"][1]["mode"], "anchor")

    def test_locked_anchor_cannot_be_redeleted(self):
        self.p["shots"][1]["reference"]["locked"] = True
        result = planner.plan(self.p, self.path, self.profile)
        self.assertIn("LOCKED_ANCHOR", result["decisions"][1]["rules"])
        self.assertEqual(result["decisions"][1]["mode"], "anchor")

    def test_authorized_state_not_applied_to_earlier_shots(self):
        states = planner.analyze(self.p)
        self.assertEqual(states[1]["expected_after"]["key.holder"]["value"], "girl")
        self.assertEqual(states[2]["expected_before"]["key.holder"]["value"], "girl")
        self.assertEqual(states[2]["expected_after"]["key.holder"]["value"], "boy")
        self.assertEqual(states[3]["expected_before"]["key.holder"]["value"], "boy")

    def test_conflicting_holder_stops_planning(self):
        self.p["shots"][1]["facts"][-1]["value"] = "boy"
        with self.assertRaisesRegex(ValueError, "state baseline conflict"):
            planner.plan(self.p, self.path, self.profile)

    def test_first_shot_cannot_fill(self):
        self.p["shots"][0]["omission_assessment"].update(allowed=True, risk="low")
        result = planner.plan(self.p, self.path, self.profile)
        self.assertIn("FIRST_IN_GROUP", result["decisions"][0]["rules"])
        self.assertEqual(result["decisions"][0]["mode"], "anchor")

    def test_discrete_duration_conflict_does_not_retime(self):
        self.profile["allowed_durations"] = [4]
        before = copy.deepcopy(self.p)
        with self.assertRaisesRegex(ValueError, "no feasible"):
            planner.plan(self.p, self.path, self.profile)
        self.assertEqual(self.p, before)

    def test_wrong_aspect_ratio_rejected(self):
        self.profile["aspect_ratios"] = ["9:16"]
        with self.assertRaisesRegex(ValueError, "aspect ratio"):
            planner.plan(self.p, self.path, self.profile)

    def test_image_limits_split_without_dropping_shots(self):
        self.profile["max_images"] = 1
        result = planner.plan(self.p, self.path, self.profile)
        self.assertEqual(len(result["groups"]), 4)
        self.assertEqual(sum(len(g["shot_ids"]) for g in result["groups"]), 4)

    def test_apply_refuses_generated_project(self):
        result = planner.plan(self.p, self.path, self.profile)
        self.video()
        with self.assertRaisesRegex(ValueError, "initial planning only"):
            planner.apply_plan(self.p, self.path, result)

    def test_plan_equals_independent_exhaustive_cost_oracle(self):
        # Enumerate every partition of four shots and every anchor bit-mask independently.
        # With fixture constraints S01,S03,S04 protected and S02 optional.
        for video_cost in (0, .5, 2, 10):
            self.profile["video_cost_cny"] = video_cost
            result = planner.plan(self.p, self.path, self.profile)
            costs = []
            for cuts in itertools.product((False, True), repeat=3):
                starts = [0] + [i+1 for i, c in enumerate(cuts) if c] + [4]
                for keep_s02 in (False, True):
                    anchor = {0, 2, 3} | ({1} if keep_s02 else set())
                    valid = True
                    for a, b in zip(starts, starts[1:]):
                        seq = self.p["shots"][a:b]
                        if a not in anchor or b-1 not in anchor or len({s["scene_id"] for s in seq}) != 1 or sum(s["duration"] for s in seq) > 6 or len(set(range(a,b)) & anchor) > 3:
                            valid = False
                    if valid:
                        costs.append((len(starts)-1)*video_cost + (1 if keep_s02 else 0))
            self.assertAlmostEqual(result["objective"]["estimated_cost_cny"], min(costs))


class ReviewAndDisplayTests(Base):
    def test_reordered_or_missing_shot_rejected(self):
        self.p["groups"][0]["shot_ids"] = ["S03", "S01"]
        with self.assertRaisesRegex(ValueError, "source order"):
            core.validate(self.p, self.path)

    def test_prompt_keeps_omitted_shot_and_state_constraints(self):
        prompt = core.prompt(self.p, "G01")
        self.assertIn("S02 [2–3.5s]", prompt)
        self.assertIn("无独立图片", prompt)
        self.assertIn("图片2 → S03", prompt)
        self.assertIn("key.holder 从 girl 到 boy", prompt)

    def test_api_success_is_not_review_pass(self):
        self.video()
        self.assertIsNone(core.review_current(self.p, self.path, "G01"))

    def test_uncertain_cannot_trigger_repair(self):
        r = self.review(verdict="uncertain")
        core.record_review(self.p, self.path, r)
        with self.assertRaisesRegex(ValueError, "confirmed FAIL"):
            core.repair(self.p, self.path, ["G01"], "try again")

    def test_pass_needs_every_shot_and_complete_duration(self):
        r = self.review()
        r["coverage"]["actual_shots"] = r["coverage"]["actual_shots"][:-1]
        with self.assertRaisesRegex(ValueError, "actual ordered"):
            core.record_review(self.p, self.path, r)

    def test_pass_with_limitations_rejected(self):
        r = self.review()
        r["coverage"]["limitations"] = ["sparse frames cannot prove no subtitles"]
        with self.assertRaisesRegex(ValueError, "uncertain evidence"):
            core.record_review(self.p, self.path, r)

    def test_review_hash_and_prompt_change_invalidate_pass(self):
        r = self.review()
        core.record_review(self.p, self.path, r)
        self.assertIsNotNone(core.review_current(self.p, self.path, "G01"))
        core.group(self.p, "G01")["prompt_notes"] = "changed actual generation prompt"
        self.assertIsNone(core.review_current(self.p, self.path, "G01"))

    def test_wrong_person_prop_subtitle_cut_and_omission_are_located(self):
        for category, problem in (("shot", "wrong person"), ("continuity", "prop jumps"), ("subtitles", "unwanted subtitles"), ("story", "wrong transition"), ("story", "missing shot")):
            with self.subTest(problem=problem):
                r = self.review(verdict="FAIL", category=category, problem=problem)
                self.assertEqual(core.record_review(self.p, self.path, r), "FAIL")
                saved = self.p["reviews"][-1]
                self.assertEqual(saved["issues"][0]["time_range"], [0, .5])
                self.assertEqual(saved["issues"][0]["problem"], problem)

    def test_local_repair_preserves_neighbor_video_but_rechecks_review(self):
        core.record_review(self.p, self.path, self.review("G02"))
        core.record_review(self.p, self.path, self.review(verdict="FAIL"))
        old = copy.deepcopy(self.p["tasks"])
        core.repair(self.p, self.path, ["G01"], "restore missing close-up")
        self.assertEqual(core.group(self.p, "G01")["version"], 2)
        self.assertEqual(core.group(self.p, "G02")["version"], 1)
        self.assertEqual(self.p["tasks"], old)
        self.assertIsNone(core.review_current(self.p, self.path, "G02"))
        self.assertIsNotNone(core.current_video(self.p, self.path, core.group(self.p, "G02"))[0])
        core.restore(self.p, "S02", "confirmed missing close-up")
        self.assertTrue(self.p["shots"][1]["reference"]["locked"])

    def test_three_round_limit_and_split_preserve_order(self):
        for _ in range(3):
            core.record_review(self.p, self.path, self.review(verdict="FAIL"))
            core.repair(self.p, self.path, ["G01"], "confirmed problem")
        core.record_review(self.p, self.path, self.review(verdict="FAIL"))
        with self.assertRaisesRegex(ValueError, "limit reached"):
            core.repair(self.p, self.path, ["G01"], "again")
        core.split(self.p, "G01", "S03")
        self.assertEqual([s for g in self.p["groups"] for s in g["shot_ids"]], ["S01", "S02", "S03", "S04"])

    def test_render_preserves_shots_without_exporting_internal_records(self):
        self.p["title"] = '<script>alert("bad")</script>'
        result = planner.plan(self.p, self.path, self.profile)
        planner.apply_plan(self.p, self.path, result)
        out = self.path.parent / "delivery"
        document = Path(core.render(self.p, self.path, out))
        text = document.read_text(encoding="utf-8")
        self.assertNotIn("<script>", text)
        self.assertEqual(text.count("待补图"), 4)
        self.assertEqual([x.suffix for x in out.iterdir() if x.is_file()], [".md"])
        self.assertFalse((out / "images").exists())
        self.assertEqual(sorted(x.name for x in out.rglob("*.json")), [])
        self.assertEqual(sorted(x.name for x in out.rglob("*.html")), [])
        self.assertTrue(text.index("## S01") < text.index("## S02") < text.index("## S03") < text.index("## S04"))
        self.assertNotIn("input_fingerprint", text)


class FakeClient:
    base_url = "https://mock.invalid"
    def __init__(self, statuses=None, ambiguous=False):
        self.statuses = iter(statuses or ["SUCCESS"])
        self.submits = 0
        self.queries = []
        self.ambiguous = ambiguous
    def upload_file(self, path): return "https://mock.invalid/" + Path(path).name
    def submit(self, endpoint, payload):
        self.submits += 1
        if self.ambiguous: raise TimeoutError("simulated ambiguous submission")
        return "original-task-123"
    def _post_json(self, url, payload, retryable):
        self.queries.append(payload["taskId"])
        return {"status": next(self.statuses), "results": [{"url": "https://mock.invalid/out.mp4"}]}


class TaskTests(Base):
    def test_mute_cannot_replace_script_prompt(self):
        request = self.request()
        request["mute_fields"] = {"prompt": "wrong script"}
        with self.assertRaisesRegex(ValueError, "cannot overwrite"):
            rh.prepare(self.p, self.path, request, self.module, self.registry)

    def test_success_without_outputs_is_not_success(self):
        request, client = self.request(), FakeClient()
        rh.run(self.p, self.path, request, self.module, self.registry, client, 0, 0, self.download)
        task = self.p["tasks"][request["id"]]
        task["raw_response"] = {"status": "SUCCESS", "results": []}
        self.assertEqual(rh.finish_outputs(self.p, self.path, task, self.module, self.download), "download_error")

    @classmethod
    def setUpClass(cls):
        cls.module, _ = rh.kit()
        cls.registry = {"models": [{"endpoint": "test/video", "params": [{"fieldKey": "prompt", "type": "STRING", "required": True}, {"fieldKey": "images", "type": "IMAGE", "maxInputNum": 3, "required": True}, {"fieldKey": "duration", "type": "FLOAT", "min": 1, "max": 6}]}]}

    def request(self):
        self.p["config"].update(max_submissions=3, budget_cny=5)
        return dict(id="G01-v1", kind="video", target_id="G01", version=1, endpoint="test/video", payload={"duration": 5.5}, prompt_field="prompt", reference_field="images", estimated_cost_cny=2)

    @staticmethod
    def download(url, path): path.write_bytes(b"simulated media bytes")

    def test_timeout_resume_queries_original_task_once(self):
        client = FakeClient(["RUNNING", "SUCCESS"])
        request = self.request()
        self.assertEqual(rh.run(self.p, self.path, request, self.module, self.registry, client, 0, 0, self.download), "timeout")
        self.p = core.read(self.path)
        self.assertEqual(rh.run(self.p, self.path, request, self.module, self.registry, client, 0, 0, self.download), "SUCCESS")
        self.assertEqual(client.submits, 1)
        self.assertEqual(client.queries, ["original-task-123"]*2)

    def test_ambiguous_submission_cannot_resubmit_and_can_attach(self):
        client = FakeClient(ambiguous=True)
        request = self.request()
        self.assertEqual(rh.run(self.p, self.path, request, self.module, self.registry, client, 0, 0, self.download), "submission_unknown")
        with self.assertRaisesRegex(ValueError, "outcome unknown"):
            rh.run(self.p, self.path, request, self.module, self.registry, client, 0, 0, self.download)
        self.assertEqual(client.submits, 1)
        rh.attach(self.p, request["id"], "recovered-original")
        self.assertEqual(rh.resume(self.p, self.path, self.p["tasks"][request["id"]], client, self.module, 0, 0, self.download), "SUCCESS")
        self.assertEqual(client.queries, ["recovered-original"])

    def test_budget_prevents_submission(self):
        request = self.request()
        self.p["config"]["budget_cny"] = 1
        client = FakeClient()
        with self.assertRaisesRegex(ValueError, "budget reached"):
            rh.run(self.p, self.path, request, self.module, self.registry, client)
        self.assertEqual(client.submits, 0)
        self.assertFalse(self.p["tasks"])

    def test_default_zero_submissions_is_enforced(self):
        request = self.request()
        self.p["config"]["max_submissions"] = 0
        client = FakeClient()
        with self.assertRaisesRegex(ValueError, "submission limit"):
            rh.run(self.p, self.path, request, self.module, self.registry, client)
        self.assertEqual(client.submits, 0)

    def test_download_failure_resume_does_not_regenerate(self):
        request, client = self.request(), FakeClient()
        def broken(url, path): raise OSError("simulated download interruption")
        self.assertEqual(rh.run(self.p, self.path, request, self.module, self.registry, client, 0, 0, broken), "download_error")
        self.assertEqual(rh.resume(self.p, self.path, self.p["tasks"][request["id"]], client, self.module, 0, 0, self.download), "SUCCESS")
        self.assertEqual(client.submits, 1)
        self.assertEqual(len(client.queries), 1)

    def test_dry_prepare_schema_and_missing_reference(self):
        request = self.request()
        request["payload"]["unknown_field"] = "bad"
        with self.assertRaises(Exception): rh.prepare(self.p, self.path, request, self.module, self.registry)
        del request["payload"]["unknown_field"]
        self.p["shots"][0]["reference"]["path"] = None
        with self.assertRaisesRegex(ValueError, "existing input images"):
            rh.prepare(self.p, self.path, request, self.module, self.registry)


if __name__ == "__main__":
    unittest.main(verbosity=2)
