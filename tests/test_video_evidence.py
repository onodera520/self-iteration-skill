"""Video-evidence workflow tests. All semantic judgments are simulated, never visual proof."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from PIL import Image

import test_previs as fixtures
import previs as core
import planner
import storyboard as boards
import media
import requirements
import rh_tasks as rh


class VideoEvidenceTests(fixtures.Base):
    def setUp(self):
        super().setUp()
        self.p["config"].update(workflow="video_evidence", video_input_mode="assets")
        self.p["shots"] = self.p["shots"][:3]
        self.p["groups"] = self.p["groups"][:1]
        s = self.p["shots"][1]
        s.update(script="同场景中景观察，两人位置和女孩持钥匙的状态没有改变。",
                 shot_size="中景", required_result="观察关系明确，持物无关键变化。")
        s["requirements"].update(purpose="观察两人关系，无关键状态变化", must_have=["女孩仍持有钥匙", "同场景中景"])
        s["requirements"]["keyframe"]["description"] = "中景，两人在门厅观察对方，女孩仍握钥匙"
        s["requirements"]["provenance"][0]["source"] = "S02 同场景观察，无持物变化"
        self.p["source_script"] = " ".join(s["id"] + " " + s["script"] for s in self.p["shots"])
        self.p["user_video_prompt"] = "用户原始提示词：" + self.p["source_script"]
        self.profile["max_images"] = 4
        for i, asset in enumerate(self.p["assets"]):
            path = self.png(asset["id"], (i*50, 60, 90))
            asset["path"] = str(path)

    def png(self, name, color):
        path = self.path.parent / (name + ".png")
        Image.new("RGB", (64, 36), color).save(path)
        return path

    def mapping(self, gid="G01", statuses=None):
        task, video = self.video(gid)
        frames, rows, t = [], [], 0
        for i, s in enumerate(core.shots(self.p, core.group(self.p, gid))):
            path = self.png(f"{gid}-{s['id']}-v{task['version']}", (i*60, task["version"]*30, 60))
            frame = dict(path=str(path), sha256=core.sha(path), time=t+.25)
            frames.append(frame)
            status = (statuses or {}).get(s["id"], "matched")
            rows.append(dict(shot_id=s["id"], status=status, observation="SIMULATED " + status,
                full_rescan=status == "absent", candidates=[dict(path=str(path), time=frame["time"])] if status == "matched" else []))
            t += s["duration"]
        evidence = self.path.parent / f"{gid}-v{task['version']}-evidence.json"
        core.save(evidence, dict(video_sha256=core.sha(video), frames=frames, duration=t, verified=False))
        data = dict(group_id=gid, video_sha256=core.sha(video), evidence_file=str(evidence), shots=rows)
        boards.record_mapping(self.p, self.path, data)
        self.select_mapping(gid)
        return data

    def select_mapping(self, gid):
        for row in boards.current_mapping(self.p, self.path, gid)["shots"]:
            if row["status"] == "matched":
                f = row["candidates"][0]
                boards.select_image(self.p, self.path, dict(shot_id=row["shot_id"], path=f["path"],
                    source=dict(kind="frame", time=f["time"]), reason="SIMULATED keyframe selection"))

    def group_review(self, gid="G01", verdict="PASS"):
        ctx = core.video_context(self.p, self.path, gid)
        t, spans, evidence, assessments = 0, [], [], []
        for s, f in zip(core.shots(self.p, core.group(self.p, gid)), ctx["extraction"]["frames"]):
            spans.append(dict(shot_id=s["id"], start=t, end=t+s["duration"]))
            evidence.append(dict(f, shot_id=s["id"], observation="SIMULATED visible evidence; no actual semantic verification"))
            assessments.append(dict(shot_id=s["id"], decision="ai_fill" if s["id"] == "S02" else "anchor",
                reason="同场景观察无关键变化，前后持物承接" if s["id"] == "S02" else "保留人物和关键持物状态",
                evidence_times=[f["time"]]))
            t += s["duration"]
        r = dict(group_id=gid, version=ctx["version"], video_sha256=ctx["video_sha256"], context_fingerprint=ctx["context_fingerprint"],
            checks={c:"PASS" for c in ("shot", "continuity", "story", "subtitles")},
            coverage=dict(shot_ids=core.group(self.p, gid)["shot_ids"], actual_shots=spans, mapping_verified=True, limitations=[]),
            evidence=evidence, reference_assessments=assessments,
            boundary_checks=[dict(shot_id=b["shot_id"], verdict="PASS", observation="SIMULATED matched boundary") for b in ctx["boundaries"]],
            issues=[], uncertainties=[])
        r["checks"]["story"] = verdict
        if verdict == "uncertain":
            r["uncertainties"] = ["Need full rescan before claiming omission"]
        if verdict == "FAIL":
            r["issues"] = [dict(id="missing", shot_ids=[core.group(self.p, gid)["shot_ids"][-1]], time_range=[0, t],
                severity="high", problem="已补查确认视频缺少必要镜头", expected="完整脚本镜头", actual="必要镜头未出现",
                evidence=["SIMULATED full rescan"], repair_target="video_shot", fix="强化逐镜时间和内容或拆组")]
        return r

    def approve(self):
        self.mapping()
        core.record_review(self.p, self.path, self.group_review())
        proposal = planner.post_review_plan(self.p, self.path, self.profile)
        planner.store_aggregation(self.p, self.path, proposal)
        return proposal

    def test_three_shot_batch_to_two_images_without_mutating_tasks(self):
        contexts = requirements.contexts(self.p)
        self.assertEqual(contexts["S02"]["exit_state"]["key.holder"], "girl")
        self.assertEqual(contexts["S03"]["exit_state"]["key.holder"], "boy")
        text = core.prompt(self.p, "G01")
        self.assertIn(self.p["shots"][1]["script"], text)
        self.assertEqual(text, self.p["user_video_prompt"])
        self.mapping()
        core.record_review(self.p, self.path, self.group_review())
        original = copy.deepcopy(self.p)
        proposal = planner.post_review_plan(self.p, self.path, self.profile)
        self.assertEqual(self.p, original)
        self.assertEqual([d["mode"] for d in proposal["decisions"]], ["anchor", "ai_fill", "anchor"])
        self.assertEqual(proposal["decisions"][1]["bracket"], dict(before="S01", after="S03"))
        planner.store_aggregation(self.p, self.path, proposal)
        for key in ("shots", "groups", "tasks", "board_mappings", "config", "repair_round"):
            self.assertEqual(self.p[key], original[key])
        out = self.path.parent / "delivery"
        document = Path(boards.render(self.p, self.path, out)).read_text(encoding="utf-8")
        self.assertIn("建议省图，未验证", document)
        self.assertIn("| 检验通过 | 建议省图，未验证 | S01 + S03 |", document)
        self.assertIn(self.p["shots"][1]["script"], document)
        self.assertLess(document.index("| S01 |"), document.index("| S02 |"))
        self.assertLess(document.index("| S02 |"), document.index("| S03 |"))
        self.assertEqual(len(list(out.rglob("*.png"))), 6)
        self.assertEqual(len(list(out.rglob("thumb-*.png"))), 3)
        fill_row = next(line for line in document.splitlines() if "| S02 |" in line)
        self.assertNotIn("| 可推导生成 |", fill_row)
        self.assertIn("![", fill_row)
        self.assertTrue(list(out.glob("images/S02-*.png")))
        self.assertEqual({p.suffix for p in out.rglob("*") if p.is_file()}, {".png", ".md"})
        self.assertIn("](<images/", document)
        self.assertNotIn("fingerprint", document)

    def test_uncertain_or_absent_cannot_be_ai_fill(self):
        for status in ("uncertain", "absent"):
            with self.subTest(status=status):
                self.mapping(statuses={"S02": status})
                r = self.group_review(verdict="uncertain" if status == "uncertain" else "FAIL")
                # Even an incorrect ai_fill assessment cannot override failed evidence.
                core.record_review(self.p, self.path, r)
                proposal = planner.post_review_plan(self.p, self.path, self.profile)
                self.assertEqual(proposal["decisions"][1]["mode"], "pending")
                report = Path(boards.render(self.p, self.path, self.path.parent / ("report-" + status))).read_text(encoding="utf-8")
                row = next(line for line in report.splitlines() if "| S03 |" in line)
                self.assertIn("| 待检查 |" if status == "uncertain" else "| 需要重新生成 |", row)
                if status == "uncertain":
                    with self.assertRaisesRegex(ValueError, "confirmed FAIL"):
                        core.repair(self.p, self.path, ["G01"], "not authorized by uncertain")
                else:
                    core.repair(self.p, self.path, ["G01"], "confirmed absent")
                    self.assertEqual(self.p["repair_round"], 1)

    def test_absence_requires_rescan_and_pass_requires_matched(self):
        data = self.mapping(statuses={"S02": "uncertain"})
        data["shots"][1].update(status="absent", full_rescan=False)
        with self.assertRaisesRegex(ValueError, "rescan"):
            boards.record_mapping(self.p, self.path, data)
        with self.assertRaisesRegex(ValueError, "all shots matched"):
            core.record_review(self.p, self.path, self.group_review())

    def test_new_video_requires_whole_group_remapping_and_review(self):
        self.approve()
        core.record_review(self.p, self.path, self.group_review(verdict="FAIL"))
        core.repair(self.p, self.path, ["G01"], "confirmed problem")
        self.video()
        self.assertIsNone(planner.current_aggregation(self.p, self.path))
        self.assertIsNone(boards.current_mapping(self.p, self.path, "G01"))
        self.assertTrue(all(boards.current_frame(self.p, self.path, sid) is None for sid in ("S01", "S02", "S03")))
        old_output = Path(boards.render(self.p, self.path, self.path.parent / "pending")).read_text(encoding="utf8")
        self.assertIn("待检查", old_output)
        self.assertNotIn("**ai_fill", old_output)
        self.mapping()
        self.assertIsNone(core.review_current(self.p, self.path, "G01"))
        partial = self.group_review()
        partial["reference_assessments"] = partial["reference_assessments"][:1]
        with self.assertRaisesRegex(ValueError, "cover group"):
            core.record_review(self.p, self.path, partial)
        core.record_review(self.p, self.path, self.group_review())
        self.assertEqual(planner.post_review_plan(self.p, self.path, self.profile)["decisions"][1]["mode"], "ai_fill")

    def test_evidence_image_tampering_invalidates_review_and_aggregation(self):
        self.approve()
        item = boards.current_frame(self.p, self.path, "S02")
        core.resolve(self.path, item["path"]).write_bytes(b"tampered")
        self.assertIsNone(core.review_current(self.p, self.path, "G01"))
        self.assertIsNone(planner.current_aggregation(self.p, self.path))

    def test_evidence_file_tampering_invalidates_binding(self):
        self.approve()
        m = boards.current_mapping(self.p, self.path, "G01")
        data = core.read(m["evidence_file"])
        data["frames"][1]["time"] += .1
        core.save(m["evidence_file"], data)
        self.assertIsNone(core.review_current(self.p, self.path, "G01"))

    def test_asset_and_script_changes_invalidate_suggestions(self):
        self.approve()
        original = copy.deepcopy(self.p)
        self.p["shots"][1]["script"] += "新的脚本信息"
        self.assertIsNone(planner.current_aggregation(self.p, self.path))
        self.p = original
        Path(self.p["assets"][0]["path"]).write_bytes(b"new asset")
        self.assertIsNone(planner.current_aggregation(self.p, self.path))

    def test_user_prompt_passthrough_and_binding(self):
        self.approve()
        self.assertEqual(core.prompt(self.p, "G01"), self.p["user_video_prompt"])
        self.p["user_video_prompt"] += " 新的动作要求"
        self.assertIsNone(core.current_video(self.p, self.path, self.p["groups"][0])[0])
        self.assertIsNone(planner.current_aggregation(self.p, self.path))
        self.p["groups"] = [dict(id="G01", version=1, shot_ids=["S01"]), dict(id="G02", version=1, shot_ids=["S02", "S03"])]
        with self.assertRaisesRegex(ValueError, "group.video_prompt"):
            core.prompt(self.p, "G01")
        self.p["groups"][0]["video_prompt"] = "用户提示词中对应 S01 的片段"
        self.assertEqual(core.prompt(self.p, "G01"), self.p["groups"][0]["video_prompt"])

    def test_context_frame_and_coverage_forgery_rejected(self):
        self.mapping()
        for field in ("context", "hash", "time", "limitations"):
            with self.subTest(field=field):
                r = self.group_review()
                if field == "context": r["context_fingerprint"] = "old"
                if field == "hash": r["evidence"][0]["sha256"] = "wrong"
                if field == "time": r["coverage"]["actual_shots"][0]["end"] = .2; r["coverage"]["actual_shots"][1]["start"] = .2
                if field == "limitations": r["coverage"]["limitations"] = ["sparse frames cannot prove motion"]
                with self.assertRaises(ValueError): core.record_review(self.p, self.path, r)

    def test_critical_or_locked_middle_cannot_be_filled(self):
        for flag in ("critical", "locked", "unknown"):
            with self.subTest(flag=flag):
                if flag == "critical": self.p["shots"][1]["intent"]["critical_result"] = True
                if flag == "locked": self.p["shots"][1]["reference"]["locked"] = True
                if flag == "unknown": self.p["shots"][1]["facts"][-1].update(status="unknown", value=None)
                self.mapping()
                core.record_review(self.p, self.path, self.group_review(verdict="uncertain" if flag == "unknown" else "PASS"))
                self.assertEqual(planner.post_review_plan(self.p, self.path, self.profile)["decisions"][1]["mode"], "pending" if flag == "unknown" else "anchor")
                self.p["shots"][1]["intent"]["critical_result"] = False
                self.p["shots"][1]["reference"]["locked"] = False

    def test_infeasible_constraints_keep_every_shot(self):
        self.approve()
        self.profile["allowed_durations"] = [6]
        proposal = planner.post_review_plan(self.p, self.path, self.profile)
        self.assertFalse(proposal["feasible"])
        self.assertEqual([d["mode"] for d in proposal["decisions"]], ["anchor"]*3)
        self.assertEqual(proposal["groups"][0]["shot_ids"], ["S01", "S02", "S03"])

    def test_repair_only_invalidates_adjacent_group_boundaries(self):
        fourth = core.read(fixtures.ROOT / "ai-storyboard-previs/assets/example-project.json")["shots"][3]
        self.p["shots"].append(fourth)
        self.p["groups"] = [dict(id=f"G{i:02d}", version=1, shot_ids=[s["id"]]) for i,s in enumerate(self.p["shots"], 1)]
        for g in self.p["groups"]: self.mapping(g["id"])
        for g in self.p["groups"]: core.record_review(self.p, self.path, self.group_review(g["id"], "FAIL" if g["id"] == "G02" else "PASS"))
        original_tasks = copy.deepcopy(self.p["tasks"])
        last_review = core.review_current(self.p, self.path, "G04")
        core.repair(self.p, self.path, ["G02"], "confirmed failed middle group")
        self.assertEqual(self.p["tasks"], original_tasks)
        for gid in ("G01", "G02", "G03"): self.assertIsNone(core.review_current(self.p, self.path, gid))
        self.assertEqual(core.review_current(self.p, self.path, "G04"), last_review)
        self.mapping("G02")
        ctx = core.video_context(self.p, self.path, "G02")
        self.assertEqual([b["shot_id"] for b in ctx["boundaries"]], ["S01", "S03"])
        r = self.group_review("G02")
        r["boundary_checks"] = []
        with self.assertRaisesRegex(ValueError, "boundary checks"):
            core.record_review(self.p, self.path, r)
        for gid in ("G01", "G02", "G03"):
            core.record_review(self.p, self.path, self.group_review(gid))
            self.assertIsNotNone(core.review_current(self.p, self.path, gid))

    def test_three_round_stop_preserves_history(self):
        for _ in range(3):
            self.mapping()
            core.record_review(self.p, self.path, self.group_review(verdict="FAIL"))
            core.repair(self.p, self.path, ["G01"], "confirmed failure")
        self.mapping()
        core.record_review(self.p, self.path, self.group_review(verdict="FAIL"))
        before = copy.deepcopy(self.p)
        with self.assertRaisesRegex(ValueError, "round limit"):
            core.repair(self.p, self.path, ["G01"], "fourth retry")
        self.assertEqual(self.p, before)

    def test_cli_roundtrip_and_lock_and_apply_guard(self):
        self.approve()
        core.save(self.path, self.p)
        profile = self.path.parent / "profile.json"
        core.save(profile, self.profile)
        script_dir = fixtures.ROOT / "ai-storyboard-previs/scripts"
        context = subprocess.run([sys.executable, str(script_dir / "previs.py"), "context", str(self.path), "G01"], capture_output=True, text=True, encoding="utf8", check=True)
        self.assertEqual(len(json.loads(context.stdout)["shots"]), 3)
        args = [sys.executable, str(script_dir / "planner.py"), str(self.path), str(profile), "--post-review", "--output", str(self.path.parent / "aggregation.json")]
        with core.locked(self.path):
            self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)
        self.assertIsNotNone(planner.current_aggregation(core.read(self.path), self.path))
        self.assertNotEqual(subprocess.run(args+["--apply"], capture_output=True).returncode, 0)

    def test_new_mode_budget_and_submission_unknown_recovery(self):
        module, _ = rh.kit()
        registry = {"models":[{"endpoint":"test/video","params":[
            {"fieldKey":"prompt","type":"STRING","required":True},
            {"fieldKey":"images","type":"IMAGE","maxInputNum":4,"required":True}]}]}
        request = dict(id="G01-v1", kind="video", target_id="G01", version=1, endpoint="test/video", payload={},
                       prompt_field="prompt", reference_field="images", estimated_cost_cny=2)
        self.p["config"].update(max_submissions=2, budget_cny=1)
        client = fixtures.FakeClient(ambiguous=True)
        with self.assertRaisesRegex(ValueError, "budget reached"):
            rh.run(self.p, self.path, request, module, registry, client)
        self.assertEqual(client.submits, 0)
        self.p["config"]["budget_cny"] = 4
        self.assertEqual(rh.run(self.p, self.path, request, module, registry, client), "submission_unknown")
        self.p = core.read(self.path)
        with self.assertRaisesRegex(ValueError, "outcome unknown"):
            rh.run(self.p, self.path, request, module, registry, client)
        rh.attach(self.p, request["id"], "recovered-original")
        self.assertEqual(rh.resume(self.p, self.path, self.p["tasks"][request["id"]], client, module, 0, 0,
                         fixtures.TaskTests.download), "SUCCESS")
        self.assertEqual(client.submits, 1)
        self.assertEqual(client.queries, ["recovered-original"])

    def test_synthetic_three_cut_video_mapping_not_visual_acceptance(self):
        video = self.path.parent / "three-colors.mp4"
        cmd = [media.binary("ffmpeg"), "-v", "error"]
        for color, d in (("red",2), ("green",1.5), ("blue",2)):
            cmd += ["-f", "lavfi", "-i", f"color={color}:s=160x90:r=24:d={d}"]
        media.command(cmd + ["-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", video])
        spans = [dict(shot_id=sid, start=start, end=end) for sid,start,end in (("S01",0,2),("S02",2,3.5),("S03",3.5,5.5))]
        evidence = media.extract(video, self.path.parent / "real-frames", spans, .5)
        self.assertFalse(evidence["verified"])
        self.assertAlmostEqual(evidence["duration"], 5.5, places=1)
        self.p["config"]["video_source"] = "imported"
        for shot in self.p["shots"]:
            shot.pop("duration")
        before_tasks = copy.deepcopy(self.p.get("tasks", {}))
        core.save(self.path, self.p)
        imported = subprocess.run([sys.executable, str(fixtures.ROOT / "ai-storyboard-previs/scripts/previs.py"),
            "import-video", str(self.path), "G01", str(video)], capture_output=True, text=True, encoding="utf8")
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.p = core.read(self.path)
        extracted = subprocess.run([sys.executable, str(fixtures.ROOT / "ai-storyboard-previs/scripts/media.py"),
            "extract", str(video), str(self.path.parent / "cli-no-duration"), "--project", str(self.path), "--group", "G01"], capture_output=True, text=True, encoding="utf8")
        self.assertEqual(extracted.returncode, 0, extracted.stderr)
        cli_evidence = core.read(self.path.parent / "cli-no-duration/evidence.json")
        self.assertTrue(cli_evidence["frames"])
        self.assertEqual(cli_evidence["sampling"]["mode"], "sparse")
        self.assertEqual(cli_evidence["sampling"]["dense_ranges"], [])
        self.assertEqual(self.p.get("tasks", {}), before_tasks)
        self.assertEqual(self.p["imported_videos"][0]["source"], "user_video")
        self.assertAlmostEqual(self.p["imported_videos"][0]["duration"], 5.5, places=1)
        rows = []
        for span, channel in zip(spans, (0,1,2)):
            frame = min(evidence["frames"], key=lambda f: abs(f["time"] - (span["start"]+.5)))
            with Image.open(frame["path"]) as im:
                rgb = im.convert("RGB").getpixel((80,45))
            self.assertGreater(rgb[channel], max(rgb[c] for c in range(3) if c != channel))
            self.assertAlmostEqual(frame["time"], frame["frame_index"]/24, places=5)
            rows.append(dict(shot_id=span["shot_id"], status="matched", observation="Synthetic color/PTS mapping only, not script verification",
                             candidates=[dict(path=frame["path"], time=frame["time"])]))
        boards.record_mapping(self.p, self.path, dict(group_id="G01",video_sha256=core.sha(video),
            evidence_file=str(self.path.parent / "real-frames/evidence.json"),shots=rows))
        self.select_mapping("G01")
        proposal = planner.post_review_plan(self.p, self.path, self.profile)
        self.assertTrue(all(d["mode"] == "pending" for d in proposal["decisions"]))
        planner.store_aggregation(self.p,self.path,proposal)
        document = Path(boards.render(self.p,self.path,self.path.parent / "synthetic-output")).read_text(encoding="utf8")
        self.assertNotIn("视频校对通过", document)
        self.assertNotIn("**ai_fill", document)
        replacement = video.with_name("replacement.mp4")
        replacement.write_bytes(video.read_bytes())
        core.import_video(self.p, self.path, "G01", replacement)
        replacement.write_bytes(b"replaced input video")
        self.assertIsNone(core.current_video(self.p, self.path, self.p["groups"][0])[0])
        self.assertIsNone(planner.current_aggregation(self.p, self.path))


if __name__ == "__main__":
    unittest.main()
