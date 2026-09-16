"""Deterministic ordered partition and anchor selection over explicit sourced facts."""
from __future__ import annotations
import argparse
import copy
from decimal import Decimal
import itertools
from pathlib import Path
import sys
from previs import (read, save, locked, validate, require, number, digest, resolve,
                    group_fingerprint, current_video, video_context, review_current)

RULES = {
    "FIRST_IN_GROUP": "每组首镜提供进入条件",
    "LAST_IN_GROUP": "组尾保留锚点，使补足镜头位于同组两锚点之间",
    "SCENE_BOUNDARY": "场景首尾优先保留空间与状态基线",
    "FIRST_ENTITY": "人物首次出场保留身份依据",
    "CRITICAL_RESULT": "保护关键动作结果或叙事转折",
    "STATE_CHANGE": "保护关键状态变化",
    "UNKNOWN_CRITICAL": "关键事实未知或仅有推断，保守保留",
    "NOVEL_CRITICAL": "新增关键事实需要视觉依据",
    "LOCKED_ANCHOR": "用户指定或返修恢复的参考图已锁定",
    "SEMANTIC_UNAPPROVED": "没有明确的低风险语义补足评估",
    "ANCHOR_SELECTED": "在约束与成本比较中选择保留参考图",
    "BRACKETED_FILL": "低风险候选由同组前后锚点约束，仍须真实预演验证",
}


def sourced(value):
    return isinstance(value, dict) and value.get("kind") in ("script", "asset", "inference") and isinstance(value.get("ref"), str) and bool(value["ref"].strip())


def validate_facts(p):
    assets = {a["id"] for a in p["assets"]}
    for s in p["shots"]:
        require(isinstance(s.get("facts"), list) and s["facts"], "sourced facts required: " + s["id"])
        keys = []
        for f in s["facts"]:
            require(f.get("entity") in assets and isinstance(f.get("attribute"), str) and f["attribute"], "invalid fact entity/attribute")
            require(f.get("status") in ("known", "unknown") and f.get("phase") in ("static", "before", "after"), "fact status/phase required")
            require(type(f.get("critical")) is bool and sourced(f.get("source")), "fact critical/source required")
            require("value" in f and (f["value"] is not None or f["status"] == "unknown"), "known fact needs value")
            keys.append((f["entity"], f["attribute"], f["phase"]))
        require(len(keys) == len(set(keys)), "duplicate fact slot in " + s["id"])
        require(isinstance(s.get("state_changes"), list), "state_changes array required")
        for change in s["state_changes"]:
            require(change.get("entity") in assets and change.get("attribute") and all(k in change for k in ("before", "after")), "invalid state change")
            require(type(change.get("critical")) is bool and type(change.get("authorized")) is bool and sourced(change.get("source")), "state change provenance required")
        assessment = s.get("omission_assessment", {})
        require((type(assessment.get("allowed")) is bool or assessment.get("allowed") is None) and assessment.get("risk") in ("low", "medium", "high", "unknown"), "omission assessment required")
        require(sourced(assessment.get("source")) and assessment.get("rationale"), "omission rationale/source required")
        intent = s.get("intent", {})
        require(all(type(intent.get(k)) is bool for k in ("critical_result", "narrative_turn", "required_cut")), "explicit intent flags required")


def fact_key(f):
    return f["entity"] + "." + f["attribute"]


def analyze(p):
    """Novelty compares earlier known facts; state is chronological, never future-derived."""
    validate_facts(p)
    seen, seen_characters, expected, result = set(), set(), {}, []
    kinds = {a["id"]: a["kind"] for a in p["assets"]}
    for n, s in enumerate(p["shots"]):
        reasons, warnings = [], []
        if n == 0 or n == len(p["shots"])-1 or p["shots"][n-1]["scene_id"] != s["scene_id"] or (n+1 < len(p["shots"]) and p["shots"][n+1]["scene_id"] != s["scene_id"]):
            reasons.append("SCENE_BOUNDARY")
        characters = {a for a in s["asset_ids"] if kinds[a] == "character"}
        if characters - seen_characters:
            reasons.append("FIRST_ENTITY")
        seen_characters |= characters
        if s["reference"].get("locked"):
            reasons.append("LOCKED_ANCHOR")
        if s["intent"]["critical_result"] or s["intent"]["narrative_turn"]:
            reasons.append("CRITICAL_RESULT")
        new, known = [], []
        # Check all facts against the prior-shot set before adding this shot.
        for f in s["facts"]:
            uncertain = f["status"] == "unknown" or f["source"]["kind"] == "inference"
            if uncertain:
                if f["critical"]:
                    reasons.append("UNKNOWN_CRITICAL")
                warnings.append({"kind": "unconfirmed_fact", "fact": fact_key(f), "source": f["source"]})
                if f["phase"] in ("before", "static"):
                    expected[fact_key(f)] = {"value": None, "status": "unknown", "source": f["source"], "shot_id": s["id"]}
                continue
            token = digest([f["entity"], f["attribute"], f["value"]])
            known.append(token)
            if token not in seen:
                new.append(f)
                if f["critical"]:
                    reasons.append("NOVEL_CRITICAL")
            key = fact_key(f)
            if f["phase"] in ("before", "static"):
                baseline = expected.get(key)
                if baseline and baseline.get("status") != "unknown" and baseline["value"] != f["value"]:
                    warnings.append({"kind": "baseline_conflict", "fact": key, "previous": baseline, "declared": f})
                    reasons.append("UNKNOWN_CRITICAL")
                expected[key] = {"value": f["value"], "source": f["source"], "shot_id": s["id"]}
        before_state = copy.deepcopy(expected)
        changes = {c["entity"] + "." + c["attribute"]: c for c in s["state_changes"]}
        for key, c in changes.items():
            if c["critical"]:
                reasons.append("STATE_CHANGE")
            baseline = expected.get(key)
            if not c["authorized"] or c["source"]["kind"] == "inference" or c["before"] is None or c["after"] is None:
                warnings.append({"kind": "unconfirmed_change", "change": c})
                reasons.append("UNKNOWN_CRITICAL")
                expected[key] = {"value": None, "status": "unknown", "source": c["source"], "shot_id": s["id"]}
                continue
            if baseline and baseline.get("status") != "unknown" and baseline["value"] != c["before"]:
                warnings.append({"kind": "change_start_conflict", "fact": key, "previous": baseline, "change": c})
                reasons.append("UNKNOWN_CRITICAL")
            expected[key] = {"value": c["after"], "source": c["source"], "shot_id": s["id"]}
        for f in s["facts"]:
            if f["phase"] != "after":
                continue
            key = fact_key(f)
            if f["status"] != "known" or f["source"]["kind"] == "inference":
                expected[key] = {"value": None, "status": "unknown", "source": f["source"], "shot_id": s["id"]}
                continue
            baseline = expected.get(key)
            if baseline and baseline.get("status") != "unknown" and baseline["value"] != f["value"]:
                warnings.append({"kind": "unexplained_after_state", "fact": key, "previous": baseline, "declared": f})
                reasons.append("UNKNOWN_CRITICAL")
            expected[key] = {"value": f["value"], "source": f["source"], "shot_id": s["id"]}
        a = s["omission_assessment"]
        if a["allowed"] is not True or a["risk"] != "low":
            reasons.append("SEMANTIC_UNAPPROVED")
        seen.update(known)
        result.append({"shot_id": s["id"], "novel_known_facts": new,
                       "novelty_ratio": len(new)/len(known) if known else None,
                       "known_fact_count": len(known), "mandatory_rules": sorted(set(reasons)),
                       "expected_before": before_state, "expected_after": copy.deepcopy(expected),
                       "state_changes": copy.deepcopy(s["state_changes"]), "warnings": warnings})
    return result


def profile_validate(profile):
    require(profile.get("id") and sourced(profile.get("source")), "model profile ID/source required")
    for key in ("max_images", "max_shots_per_group"):
        require(type(profile.get(key)) is int and profile[key] > 0, "positive model limit required: " + key)
    require(profile["max_shots_per_group"] <= 12, "v1 exact enumeration supports at most 12 shots per group")
    require(type(profile.get("allow_multi_shot")) is bool and type(profile.get("max_fill_per_group")) is int and profile["max_fill_per_group"] >= 0, "multi-shot and fill bounds required")
    require(number(profile.get("min_duration")) and number(profile.get("max_duration")) and 0 < profile["min_duration"] <= profile["max_duration"], "duration bounds required")
    for key in ("video_cost_cny", "missing_anchor_cost_cny"):
        require(number(profile.get(key)) and profile[key] >= 0, "estimated cost required: " + key)
    require(isinstance(profile.get("aspect_ratios"), list) and profile["aspect_ratios"], "supported aspect ratios required")
    allowed = profile.get("allowed_durations")
    if allowed is not None:
        require(isinstance(allowed, list) and allowed and all(number(x) and x > 0 for x in allowed), "invalid discrete durations")


def input_fingerprint(p, project_path, profile):
    ss = copy.deepcopy(p["shots"])
    for s in ss:
        s.pop("board", None)
        # The planner's output never becomes an input to its next decision.
        r = s["reference"]
        s["reference"] = {k: r.get(k) for k in ("path", "role", "locked")}
        s["reference"]["exists"] = bool(r.get("path") and resolve(project_path, r["path"]).is_file())
    binding = {"source": p["source_script"], "assets": p["assets"], "shots": ss, "aspect_ratio": p.get("config", {}).get("aspect_ratio"), "video_input_mode": p.get("config", {}).get("video_input_mode", "anchors"), "profile": profile}
    if "narrative_plan" in p:
        binding["narrative_plan"] = p["narrative_plan"]
    return digest(binding)


def options(p, project_path, profile, analysis, start, end):
    ss = p["shots"][start:end]
    length = (sum(Decimal(str(s["duration"])) for s in ss) if not p.get("_content_review") or p.get("_narrative_ready") else Decimal(0))
    if "_narrative_ranges" in p and (start, end) not in p["_narrative_ranges"]:
        return []
    if p.get("_narrative_ready") and length > Decimal(15):
        return []
    if len(ss) > profile["max_shots_per_group"] or (len(ss) > 1 and not profile["allow_multi_shot"]):
        return []
    if not p.get("_content_review") and (length < Decimal(str(profile["min_duration"])) or length > Decimal(str(profile["max_duration"]))):
        return []
    if not p.get("_content_review") and profile.get("allowed_durations") and length not in [Decimal(str(x)) for x in profile["allowed_durations"]]:
        return []
    event_mode = p.get("_content_review") and "event" in ss[0]
    boundary_key = (lambda s: s["event"]["id"]) if event_mode else (lambda s: s["scene_id"])
    if "_narrative_ranges" not in p and any(boundary_key(s) != boundary_key(ss[0]) or s["continuity_id"] != ss[0]["continuity_id"] for s in ss):
        return []
    if p.get("_content_review") and any(start < boundary < end for boundary in p.get("_blocked_group_starts", [])):
        return []
    if p.get("config", {}).get("video_input_mode") == "assets":
        used = {aid for s in ss for aid in s["asset_ids"]}
        if not used or len(used) > profile["max_images"]:
            return []
        return [{"start": start, "end": end, "duration": float(length), "anchors": [],
                 "fill_count": 0, "missing_count": 0, "cost": Decimal(str(profile["video_cost_cny"]))}]
    must = {start, end-1} | {n for n in range(start, end) if analysis[n]["mandatory_rules"]}
    if len(must) > profile["max_images"]:
        return []
    optional = [n for n in range(start, end) if n not in must]
    result = []
    for bits in itertools.product((False, True), repeat=len(optional)):
        anchors = must | {n for n, keep in zip(optional, bits) if keep}
        fill = end-start-len(anchors)
        if len(anchors) > profile["max_images"] or fill > profile["max_fill_per_group"]:
            continue
        missing = sum(not p["shots"][n]["reference"].get("path") or not resolve(project_path, p["shots"][n]["reference"]["path"]).is_file() for n in anchors)
        cost = Decimal(str(profile["video_cost_cny"])) + (0 if p.get("_post_review") else missing) * Decimal(str(profile["missing_anchor_cost_cny"]))
        result.append({"start": start, "end": end, "duration": float(length), "anchors": sorted(anchors), "fill_count": fill, "missing_count": missing, "cost": cost})
    return result


def plan(p, project_path, profile):
    validate(p, project_path)
    profile_validate(profile)
    require(p.get("config", {}).get("aspect_ratio") in profile["aspect_ratios"], "aspect ratio unsupported; do not silently change user framing")
    require(len(p["shots"]) <= 200, "v1 planner supports up to 200 shots; partition long stories explicitly")
    analysis = analyze(p)
    # Conflicting sourced state declarations need correction; an extra anchor cannot fix them.
    conflicts = [a["shot_id"] for a in analysis if any(w["kind"] in ("baseline_conflict", "change_start_conflict", "unexplained_after_state") for w in a["warnings"])]
    require(not conflicts, "state baseline conflict; reconcile sources for " + ", ".join(conflicts))
    count = len(p["shots"])
    best = [None] * (count+1)
    best[0] = ((Decimal(0), 0, 0, 0, ()), [])
    feasible_count = 0
    for end in range(1, count+1):
        for start in range(max(0, end-profile["max_shots_per_group"]), end):
            if best[start] is None:
                continue
            for option in options(p, project_path, profile, analysis, start, end):
                feasible_count += 1
                old, chain = best[start]
                signature = old[4] + ((end, tuple(option["anchors"])),)
                # Hard rules + low-risk eligibility gate precede optimization.
                # Legacy: cost, fill exposure, image count. Post-review: cost, retained
                # image count, fill exposure, after the evidence/mandatory-anchor gates.
                a, b = (len(option["anchors"]), option["fill_count"]) if p.get("_post_review") else (option["fill_count"], len(option["anchors"]))
                score = (old[0]+option["cost"], old[1]+a, old[2]+b, old[3]+1, signature)
                if best[end] is None or score < best[end][0]:
                    best[end] = (score, chain+[option])
    require(best[count] is not None, "no feasible ordered plan: check asset/reference counts, same-scene boundaries, exact durations and model limits; shots were not removed")
    score, chain = best[count]
    groups, decisions = [], []
    for n, opt in enumerate(chain, 1):
        gid = f"G{n:02d}"
        groups.append({"id": gid, "shot_ids": [s["id"] for s in p["shots"][opt["start"]:opt["end"]]], "reason": "同场景连续区间；按模型限制和估算成本确定，组内保留逐镜硬切。", "version": 1, "planned_duration": opt["duration"]})
        for j in range(opt["start"], opt["end"]):
            s = p["shots"][j]
            if p.get("config", {}).get("video_input_mode") == "assets":
                decisions.append({"shot_id": s["id"], "group_id": gid, "mode": s["reference"]["mode"],
                                  "reason": "仅按模型约束试生成；抽帧审查后再确定聚合与省图建议。"})
                continue
            rules = list(analysis[j]["mandatory_rules"])
            if j == opt["start"]: rules.append("FIRST_IN_GROUP")
            if j == opt["end"]-1: rules.append("LAST_IN_GROUP")
            mode = "anchor" if j in opt["anchors"] else "ai_fill"
            rules.append("ANCHOR_SELECTED" if mode == "anchor" else "BRACKETED_FILL")
            exists = s["reference"].get("path") and resolve(project_path, s["reference"]["path"]).is_file()
            bracket = None
            if mode == "ai_fill":
                bracket = {"before": p["shots"][max(x for x in opt["anchors"] if x < j)]["id"], "after": p["shots"][min(x for x in opt["anchors"] if x > j)]["id"]}
            decisions.append({"shot_id": s["id"], "group_id": gid, "mode": mode, "status": ("anchor_available" if exists else "anchor_missing") if mode == "anchor" else "ai_fill_planned_unverified", "rules": sorted(set(rules)), "reason": "；".join(RULES[x] for x in sorted(set(rules))), "bracket": bracket, "novelty_ratio": analysis[j]["novelty_ratio"], "semantic_assessment": s["omission_assessment"]})
    result = {"planner_version": 1, "input_fingerprint": input_fingerprint(p, project_path, profile), "profile": copy.deepcopy(profile), "groups": groups, "decisions": decisions, "analysis": analysis, "objective": {"estimated_cost_cny": float(score[0]), "fill_count": score[1], "anchor_count": score[2], "video_tasks": score[3]}, "feasible_options_examined": feasible_count, "limitations": ["相同结构化输入与配置得到相同方案；事实抽取和低风险判断仍需语义核对。", "最优性仅针对本版同场景区间、保守首尾锚点和可加估价模型；不代表真实生成质量最优。", "本版优先最小估算成本，同价优先减少补足风险，再比较参考图数量。", "未执行真实生成，不代表省略参考图已验证。"]}

    if p.get("config", {}).get("video_input_mode") == "assets":
        result["objective"] = {"estimated_cost_cny": float(score[0]), "video_tasks": score[3],
                               "input_asset_images": sum(len({a for s in p["shots"] if s["id"] in g["shot_ids"] for a in s["asset_ids"]}) for g in groups)}
        result["limitations"] = ["相同结构化输入与模型配置得到相同分组。",
            "最小成本仅针对同场景连续区间、完整资产输入与固定单次估价；不保证模型生成质量。",
            "真实取图覆盖、分镜图质量与最终省图决定尚未验证。"]
    return result


def aggregation_fingerprint(p, project_path, profile):
    from storyboard import current_frame
    rows = []
    for g in p["groups"]:
        task, _ = current_video(p, project_path, g)
        ctx = video_context(p, project_path, g["id"]) if task else None
        r = review_current(p, project_path, g["id"])
        rows.append([g["id"], group_fingerprint(p, project_path, g),
                     ctx["context_fingerprint"] if ctx else None, r,
                     [current_frame(p, project_path, sid) for sid in g["shot_ids"]]])
    binding = [input_fingerprint(p, project_path, profile), rows, p.get("config", {}).get("missing_policy", {})]
    if p.get("config", {}).get("video_source") == "imported":
        from grouping import POLICY_VERSION
        binding.append(POLICY_VERSION)
    return digest(binding)


def current_aggregation(p, project_path):
    result = p.get("aggregation")
    return result if result and result.get("evidence_fingerprint") == aggregation_fingerprint(p, project_path, result["profile"]) else None


def missing_summary(groups, decisions, config):
    """Only confirmed necessary missing shots count, once per input video."""
    policy = config.get("missing_policy", {})
    minimum, ratio = policy.get("min_count", 2), policy.get("min_ratio", .2)
    require(type(minimum) is int and minimum > 0 and number(ratio) and 0 <= ratio <= 1, "invalid missing policy")
    result = []
    for g in groups:
        bad = {d["shot_id"] for d in decisions if d["shot_id"] in g["shot_ids"] and d["status"] == "missing_required"}
        total = len(g["shot_ids"])
        result.append(dict(source_group_id=g["id"], bad_num=len(bad), total=total, ratio=len(bad)/total,
                           regenerate=len(bad) >= minimum and Decimal(len(bad))/Decimal(total) >= Decimal(str(ratio))))
    return result


def imported_post_review_plan(p, project_path, profile):
    from storyboard import current_frame, mapping_row
    from grouping import partition
    validate(p, project_path)
    # Narrative partitioning precedes anchor optimization; no paid model profile.
    effective = dict(id="content-review", source={"kind": "inference", "ref": "剧情初分、相邻合并、短段复核；15秒与12镜上限"},
                     max_images=12, max_shots_per_group=12, max_fill_per_group=10, allow_multi_shot=True,
                     min_duration=.001, max_duration=15, video_cost_cny=0, missing_anchor_cost_cny=0,
                     aspect_ratios=[p["config"].get("aspect_ratio")])
    working, states, reviews = copy.deepcopy(p), {}, {}
    working.update(_post_review=True, _content_review=True)
    working["config"]["video_input_mode"] = "anchors"
    for g in p["groups"]:
        review = review_current(p, project_path, g["id"])
        reviews[g["id"]] = review
        rows = {r["shot_id"]: r for r in (review or {}).get("shot_reviews", [])}
        assessments = {r["shot_id"]: r for r in (review or {}).get("reference_assessments", [])}
        for sid in g["shot_ids"]:
            row, frame = mapping_row(p, project_path, sid), current_frame(p, project_path, sid)
            verdict = rows.get(sid, {}).get("verdict", "uncertain")
            assessment = assessments.get(sid, {})
            eligible = verdict in ("PASS", "absent") and assessment.get("decision") == "ai_fill" and assessment.get("derivable") is True
            states[sid] = dict(verdict=verdict, assessment=assessment, eligible=eligible, frame=frame,
                               mapping_status=(row or {}).get("status", "uncertain"), source_group_id=g["id"],
                               reason=assessment.get("reason", "证据不足或已失效，待检查。"),
                               issues=[i for i in (review or {}).get("issues", []) if sid in i["shot_ids"]])
    working["_blocked_group_starts"] = []
    for left, right in zip(p["groups"], p["groups"][1:]):
        a, b = left["shot_ids"][-1], right["shot_ids"][0]
        boundaries_pass = all(any(check["shot_id"] == neighbor and check["verdict"] == "PASS"
                                  for check in (reviews[gid] or {}).get("boundary_checks", []))
                              for gid, neighbor in ((left["id"], b), (right["id"], a)))
        if not boundaries_pass or any(states[sid]["verdict"] != "PASS" for sid in (a, b)):
            working["_blocked_group_starts"].append(next(i for i, s in enumerate(p["shots"]) if s["id"] == b))
    protected = {sid for state in states.values() if state["eligible"] for sid in state["assessment"]["basis_shot_ids"]}
    for s in working["shots"]:
        state = states[s["id"]]
        s["reference"]["path"] = state["frame"]["path"] if state["frame"] else None
        if s["id"] in protected:
            s["reference"]["locked"] = True
        s["omission_assessment"] = dict(allowed=state["eligible"], risk="low" if state["eligible"] else "unknown",
            rationale=state["reason"], source={"kind": "inference", "ref": "逐镜审查与原视频补查：" + state["source_group_id"]})
    narrative = partition(p, working["_blocked_group_starts"])
    working["_narrative_ready"] = narrative["feasible"]
    # Pending input stays visible without inventing timing or a compliant group.
    working["_narrative_ranges"] = narrative["ranges"] if narrative["feasible"] else [(i, i+1) for i in range(len(p["shots"]))]
    result = plan(working, project_path, effective)
    required = {r['shot_id'] for r in result['analysis']
                if set(r['mandatory_rules']) - {'SEMANTIC_UNAPPROVED'}}
    original_shots = {s["id"]: s for s in p["shots"]}
    for n, g in enumerate(result["groups"], 1):
        old_id = g["id"]
        reason = narrative["reasons"][n-1] if narrative["feasible"] else '待分组：' + '；'.join(narrative["limitations"])
        g.update(id=f"A{n:02d}" if narrative["feasible"] else f"P{n:02d}", reason=reason,
                 planning_status="ready" if narrative["feasible"] else "pending",
                 duration_has_suggestion=any(original_shots[sid].get("duration_source", {}).get("kind") == "inference" for sid in g["shot_ids"]))
        if not narrative["feasible"]:
            g["planned_duration"] = None
        g["source_group_ids"] = list(dict.fromkeys(states[sid]["source_group_id"] for sid in g["shot_ids"]))
        for d in result["decisions"]:
            if d["group_id"] != old_id:
                continue
            state = states[d["shot_id"]]
            a, verdict = state["assessment"], state["verdict"]
            d.update(group_id=g["id"], source_group_id=state["source_group_id"], frame=state["frame"],
                     mapping_status=state["mapping_status"], review_verdict=verdict, issues=state["issues"])
            can_fill = d["mode"] == "ai_fill" and state["eligible"] and all(b in g["shot_ids"] for b in a["basis_shot_ids"])
            if can_fill:
                d.update(mode="ai_fill", status="absent_fill_suggested_unverified" if verdict == "absent" else "ai_fill_suggested_unverified",
                         bracket=dict(zip(("before", "after"), a["basis_shot_ids"])), reason=state["reason"])
            elif verdict == "PASS":
                d.update(mode="anchor", status="anchor_reviewed", bracket=None,
                         reason=state["reason"] + ("；保留组首尾或关键状态作为参考。" if a.get("decision") == "ai_fill" else ""))
            else:
                status = "mismatch" if verdict == "FAIL" else "pending"
                if verdict == "absent" and (a.get("derivable") is False or
                        (a.get("derivable") is True and (narrative["feasible"] or d['shot_id'] in required))):
                    status = "missing_required"
                note = ""
                if status == "missing_required":
                    note = "；必要锚点或分组约束要求保留此镜。" if a.get("derivable") is True else "；已确认缺失，无法由已有镜头可靠推导。"
                d.update(mode="pending", status=status, bracket=None, reason=state["reason"] + note)
    by_id = {d["shot_id"]: d for d in result["decisions"]}
    for d in result["decisions"]:
        if d["mode"] == "ai_fill":
            require(all(by_id[b]["status"] == "anchor_reviewed" for b in d["bracket"].values()), "inference basis is not a retained passed anchor")
    result.update(stage="post_review", feasible=narrative["feasible"], profile=copy.deepcopy(profile),
                  grouping_trace=narrative["trace"],
                  evidence_fingerprint=aggregation_fingerprint(p, project_path, profile),
                  missing_summary=missing_summary(p["groups"], result["decisions"], p["config"]),
                  limitations=narrative["limitations"] + ["省图是推导建议，未经生成验证；视频漏镜仍保留漏镜结论。"],
                  objective={"anchor_count": sum(d["mode"] == "anchor" for d in result["decisions"]),
                             "fill_count": sum(d["mode"] == "ai_fill" for d in result["decisions"]),
                             "pending_count": sum(d["mode"] == "pending" for d in result["decisions"]),
                             "group_count": len(result["groups"])})
    return result


def post_review_plan(p, project_path, profile):
    """Replan a copy: never replace actual task groups or promote suggestions to proof."""
    if p.get("config", {}).get("video_source") == "imported":
        return imported_post_review_plan(p, project_path, profile)
    from storyboard import current_frame, mapping_row
    validate(p, project_path)
    profile_validate(profile)
    working = copy.deepcopy(p)
    working["config"]["video_input_mode"] = "anchors"
    working["_post_review"] = True
    states = {}
    for g in p["groups"]:
        r = review_current(p, project_path, g["id"])
        assessments = {a["shot_id"]: a for a in (r or {}).get("reference_assessments", [])}
        for sid in g["shot_ids"]:
            row, frame = mapping_row(p, project_path, sid), current_frame(p, project_path, sid)
            a = assessments.get(sid)
            ready = bool(r and r.get("context_fingerprint") and r["verdict"] == "PASS"
                         and row and row["status"] == "matched" and frame and a and a["decision"] != "pending")
            problems = [i["problem"] for i in (r or {}).get("issues", []) if sid in i["shot_ids"]]
            states[sid] = {"ready": ready, "assessment": a, "source_group_id": g["id"], "frame": frame,
                           "reason": a["reason"] if ready else ("待检查：" + "；".join(problems) if problems else "当前视频、匹配、选帧或审查尚未通过，待检查；不批准省图。")}
    for s in working["shots"]:
        state = states[s["id"]]
        a = state["assessment"]
        s["reference"]["path"] = state["frame"]["path"] if state["frame"] else None
        # The observation is an inference about omission, never an upgrade of sourced facts.
        s["omission_assessment"] = {"allowed": bool(state["ready"] and a["decision"] == "ai_fill"),
            "risk": "low" if state["ready"] and a["decision"] == "ai_fill" else "unknown",
            "rationale": state["reason"], "source": {"kind": "inference", "ref": "当前视频组级审查：" + state["source_group_id"]}}
    try:
        result = plan(working, project_path, profile)
        feasible = True
    except ValueError as exc:
        if not str(exc).startswith("no feasible ordered plan"):
            raise
        # Keep every shot visible even when model limits prevent an anchor proposal.
        result = {"groups": copy.deepcopy(p["groups"]), "decisions": [
            {"shot_id": sid, "group_id": g["id"], "mode": "anchor", "rules": [], "bracket": None}
            for g in p["groups"] for sid in g["shot_ids"]]}
        feasible = False
    for n, g in enumerate(result["groups"], 1):
        g["id"] = f"A{n:02d}"
        g["source_group_ids"] = list(dict.fromkeys(states[sid]["source_group_id"] for sid in g["shot_ids"]))
        for d in result["decisions"]:
            if d["shot_id"] not in g["shot_ids"]:
                continue
            state = states[d["shot_id"]]
            d["group_id"] = g["id"]
            d["source_group_id"] = state["source_group_id"]
            d["frame"] = copy.deepcopy(state["frame"])
            if not state["ready"]:
                d.update(mode="pending", status="pending", bracket=None, reason=state["reason"])
            else:
                d["status"] = "ai_fill_suggested_unverified" if d["mode"] == "ai_fill" else "anchor_reviewed"
                d["reason"] = state["reason"] + ("；" + d.get("reason", "") if d["mode"] == "anchor" else "；前后锚点承接，省图效果尚未验证。")
    # No fill may depend on a pending/missing bracket, including a failed adjacent group.
    by_id = {d["shot_id"]: d for d in result["decisions"]}
    for d in result["decisions"]:
        if d["mode"] == "ai_fill" and any(by_id[sid]["status"] != "anchor_reviewed" for sid in d["bracket"].values()):
            d.update(mode="anchor", status="anchor_reviewed", bracket=None, reason="前后必要锚点尚未通过，保留此图。")
    result.update(profile=copy.deepcopy(profile), stage="post_review", feasible=feasible,
        evidence_fingerprint=aggregation_fingerprint(p, project_path, profile),
        limitations=["聚合与 ai_fill 是建议，未专项试生成，不代表省图已验证。"] + ([] if feasible else ["模型约束下没有可行参考图方案；保留试生成分组展示，需调整模型配置后重规划。"]),
        objective={"anchor_count": sum(d["mode"] == "anchor" for d in result["decisions"]),
                   "fill_count": sum(d["mode"] == "ai_fill" for d in result["decisions"]),
                   "pending_count": sum(d["mode"] == "pending" for d in result["decisions"]),
                   "group_count": len(result["groups"])})
    return result


def store_aggregation(p, project_path, result):
    require(result.get("stage") == "post_review" and result["evidence_fingerprint"] == aggregation_fingerprint(p, project_path, result["profile"]), "aggregation evidence changed")
    if p.get("aggregation"):
        p.setdefault("aggregation_history", []).append(copy.deepcopy(p["aggregation"]))
    p["aggregation"] = copy.deepcopy(result)



def apply_plan(p, project_path, result):
    require(not p.get("tasks") and not p.get("reviews") and not p.get("board_reviews") and not p.get("repair_round", 0) and not p.get("delivery") and not any(s.get("board") for s in p["shots"]), "initial planning only; preserve generated projects and use local repair")
    require(result["input_fingerprint"] == input_fingerprint(p, project_path, result["profile"]), "planning inputs changed")
    p["groups"] = copy.deepcopy(result["groups"])
    for s, d in zip(p["shots"], result["decisions"]):
        require(s["id"] == d["shot_id"], "decision ordering mismatch")
        s["reference"].update(mode=d["mode"], reason=d["reason"])
    p["planning"] = copy.deepcopy(result)
    validate(p, project_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project")
    ap.add_argument("profile")
    ap.add_argument("--output", required=True)
    ap.add_argument("--apply", action="store_true", help="Apply only to an ungenerated project")
    ap.add_argument("--post-review", action="store_true", help="Save evidence-backed aggregation separately; never change task groups")
    args = ap.parse_args()
    with locked(args.project):
        p = read(args.project)
        require(not (args.post_review and args.apply), "post-review cannot apply over generation groups")
        result = (post_review_plan if args.post_review else plan)(p, args.project, read(args.profile))
        require(Path(args.output).resolve() != Path(args.project).resolve(), "plan output must not overwrite project")
        save(args.output, result)
        if args.apply:
            apply_plan(p, args.project, result)
            save(args.project, p)
        if args.post_review:
            store_aggregation(p, args.project, result)
            save(args.project, p)
        print(result["objective"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
