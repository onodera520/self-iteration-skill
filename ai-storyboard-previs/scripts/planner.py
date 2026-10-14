"""Ordered image grouping and anchor selection over explicit sourced facts."""
from __future__ import annotations
import argparse
import copy
from decimal import Decimal
import itertools
from pathlib import Path
import sys
from evidence_runtime import verified_read
from previs import (read, save, locked, validate, require, number, digest, resolve,
                    group_fingerprint, review_current)

# Unconfirmed facts/changes remain warnings; only contradictory states block planning.
STATE_CONFLICTS = frozenset({
    "baseline_conflict", "change_start_conflict", "unexplained_after_state",
})

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
    "ANCHOR_SELECTED": "在省图约束内选择保留参考图",
    "BRACKETED_FILL": "低风险候选由同组前后锚点约束，仍须真实预演验证",
}


def sourced(value):
    return isinstance(value, dict) and value.get("kind") in ("script", "asset", "inference") and isinstance(value.get("ref"), str) and bool(value["ref"].strip())


def entity_error(value, assets):
    return (f'invalid entity {value!r}; entity must match assets[].id; allowed IDs: '
            + ', '.join(sorted(assets))
            + '. Use the actual owning asset ID; do not invent IDs or add fake assets. '
              'Keep unrepresented narrative requirements in requirements with provenance.')


def validate_facts(p, report=None, present_only=False):
    from validation import Report, text, shot_path
    own = report is None
    report = report if report is not None else Report()
    assets = {a['id'] for a in p['assets']}
    for i, s in enumerate(p['shots']):
        path = shot_path(s, i)
        # Prepared image projects may omit optional planner fields; supplied fields must be valid.
        facts = s.get('facts')
        if not present_only or 'facts' in s:
            if report.kind(facts, list, path + '.facts'):
                report.check(bool(facts), path + '.facts', 'sourced facts required: ' + s['id'])
                keys = set()
                for j, f in enumerate(facts):
                    where = f'{path}.facts[{j}]'
                    if not report.kind(f, dict, where):
                        continue
                    entity_ok = report.check(text(f.get('entity')) and f['entity'] in assets, where + '.entity', entity_error(f.get('entity'), assets))
                    attr_ok = report.check(text(f.get('attribute')), where + '.attribute', 'fact attribute must be nonempty text')
                    report.check(f.get('status') in ('known', 'unknown'), where + '.status', 'fact status/phase required')
                    phase_ok = report.check(f.get('phase') in ('static', 'before', 'after'), where + '.phase', 'fact status/phase required')
                    report.check(type(f.get('critical')) is bool, where + '.critical', 'fact critical/source required')
                    report.check(sourced(f.get('source')), where + '.source', 'fact critical/source required')
                    report.check('value' in f and (f['value'] is not None or f.get('status') == 'unknown'), where + '.value', 'known fact needs value')
                    if entity_ok and attr_ok and phase_ok:
                        key = (f['entity'], f['attribute'], f['phase'])
                        report.check(key not in keys, where, 'duplicate fact slot in ' + s['id'])
                        keys.add(key)
        if not present_only or 'state_changes' in s:
            rows = s.get('state_changes')
            if report.kind(rows, list, path + '.state_changes'):
                for j, change in enumerate(rows):
                    where = f'{path}.state_changes[{j}]'
                    if not report.kind(change, dict, where):
                        continue
                    report.check(text(change.get('entity')) and change['entity'] in assets, where + '.entity', entity_error(change.get('entity'), assets))
                    report.check(text(change.get('attribute')), where + '.attribute', 'state change attribute must be nonempty text')
                    for name in ('before', 'after'):
                        report.check(name in change, where + '.' + name, 'invalid state change')
                    for name in ('critical', 'authorized'):
                        report.check(type(change.get(name)) is bool, where + '.' + name, 'state change provenance required')
                    report.check(sourced(change.get('source')), where + '.source', 'state change provenance required')
        if not present_only or 'omission_assessment' in s:
            assessment = s.get('omission_assessment', {})
            if report.kind(assessment, dict, path + '.omission_assessment'):
                report.check(type(assessment.get('allowed')) is bool or assessment.get('allowed') is None, path + '.omission_assessment.allowed', 'omission assessment required')
                report.check(assessment.get('risk') in ('low', 'medium', 'high', 'unknown'), path + '.omission_assessment.risk', 'omission assessment required')
                report.check(sourced(assessment.get('source')), path + '.omission_assessment.source', 'omission rationale/source required')
                report.check(text(assessment.get('rationale')), path + '.omission_assessment.rationale', 'omission rationale/source required')
        if not present_only or 'intent' in s:
            intent = s.get('intent', {})
            if report.kind(intent, dict, path + '.intent'):
                for name in ('critical_result', 'narrative_turn', 'required_cut'):
                    report.check(type(intent.get(name)) is bool, path + '.intent.' + name, 'explicit intent flags required')
    if own:
        report.finish()


def fact_key(f):
    return f["entity"] + "." + f["attribute"]


def validate_ledger(p, report):
    """Bring the existing planner gate forward for complete, well-shaped inputs."""
    fields = {'facts', 'state_changes', 'intent', 'omission_assessment', 'asset_ids',
              'scene_id', 'reference'}
    if not all(fields <= set(s) for s in p['shots']):
        return  # Legacy inputs retain their existing planning-time requirements.
    if any(r['path'].startswith(('shots', 'assets')) for r in report.errors):
        return  # Do not interpret malformed upstream facts.
    for row in analyze(p):
        for warning in row['warnings']:
            if warning['kind'] in STATE_CONFLICTS:
                report.check(False, f"shots[{row['shot_id']}].facts/state_changes",
                             f"state baseline conflict: {warning['kind']}: {warning['fact']}; "
                             f"previous={warning['previous']['value']!r}; "
                             "reconcile source, phase and authorized change; do not rename the attribute to hide it")


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
    if p.get("input_shot_groups") is not None:
        binding["input_shot_groups"] = p["input_shot_groups"]
    return digest(binding)


def options(p, project_path, profile, analysis, start, end):
    ss = p["shots"][start:end]
    length = (sum(Decimal(str(s["duration"])) for s in ss) if not p.get("_content_review") or p.get("_narrative_ready") else Decimal(0))
    if "_narrative_ranges" in p and (start, end) not in p["_narrative_ranges"]:
        return []
    if p.get("_narrative_ready") and not Decimal(4) <= length <= Decimal(15):
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
    conflicts = [a["shot_id"] for a in analysis if any(w["kind"] in STATE_CONFLICTS for w in a["warnings"])]
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
                # Minimize retained images after the evidence and mandatory-anchor gates.
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

    return result


@verified_read
def aggregation_fingerprint(p, project_path, profile):
    from storyboard import current_image
    from previs import review_context
    from grouping import POLICY_VERSION
    rows = []
    for g in p['groups']:
        ctx = review_context(p, project_path, g['id'])
        rows.append([g['id'], group_fingerprint(p, project_path, g), ctx['context_fingerprint'],
                     review_current(p, project_path, g['id']),
                     [current_image(p, project_path, sid) for sid in g['shot_ids']]])
    return digest([input_fingerprint(p, project_path, profile), rows, POLICY_VERSION])


def current_aggregation(p, project_path):
    result = p.get("aggregation")
    return result if result and result.get("evidence_fingerprint") == aggregation_fingerprint(p, project_path, result["profile"]) else None


@verified_read
def image_post_review_plan(p, project_path, profile):
    from storyboard import current_image
    from grouping import partition, clip_group_list, input_partition
    validate(p, project_path)
    # Narrative partitioning precedes anchor optimization; no paid model profile.
    effective = dict(id="content-review", source={"kind": "inference", "ref": "Beat内剧情初分、相邻合并、短段复核；4–15秒与12镜上限"},
                     max_images=12, max_shots_per_group=12, max_fill_per_group=10, allow_multi_shot=True,
                     min_duration=4, max_duration=15, video_cost_cny=0, missing_anchor_cost_cny=0,
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
            frame = current_image(p, project_path, sid)
            verdict = rows.get(sid, {}).get("verdict", "uncertain")
            assessment = assessments.get(sid, {})
            eligible = verdict == "PASS" and assessment.get("decision") == "ai_fill" and assessment.get("derivable") is True
            states[sid] = dict(verdict=verdict, assessment=assessment, eligible=eligible, frame=frame,
                               source_group_id=g["id"],
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
            rationale=state["reason"], source={"kind": "inference", "ref": "分镜图校对：" + state["source_group_id"]})
    supplied = input_partition(p, working["_blocked_group_starts"])
    if supplied is not None:
        effective['source']['ref'] = '用户指定相邻分组；4–15秒、12镜、Beat及来源边界检查'
        valid_ranges = [tuple(span) for span in supplied['valid_ranges'].values()]
        covered = {j for a, b in valid_ranges for j in range(a, b)}
        # These singleton intervals are only an internal anchor-solver fallback.
        # The public result below preserves the user's exact partition, including
        # conflicts. They must never create necessary missing shots by themselves.
        solver_ranges = sorted(valid_ranges + [(i, i+1) for i in range(len(p['shots'])) if i not in covered])
        narrative = dict(feasible=supplied['feasible'], ranges=solver_ranges,
                         reasons=[], trace=[dict(stage='input', conflicts=supplied['conflicts'])],
                         limitations=supplied['limitations'])
    else:
        narrative = partition(p, working["_blocked_group_starts"])
    working["_narrative_ready"] = narrative["feasible"]
    # Pending input stays visible without inventing timing or a compliant group.
    working["_narrative_ranges"] = narrative["ranges"] if supplied is not None or narrative["feasible"] else [(i, i+1) for i in range(len(p["shots"]))]
    result = plan(working, project_path, effective)
    required = {r['shot_id'] for r in result['analysis']
                if set(r['mandatory_rules']) - {'SEMANTIC_UNAPPROVED'}}
    original_shots = {s["id"]: s for s in p["shots"]}
    for n, g in enumerate(result["groups"], 1):
        fixed_group = next((x for x in supplied['groups'] if g['shot_ids'][0] in x['shot_ids']), None) if supplied is not None else None
        group_ready = (bool(fixed_group and fixed_group['planning_status'] == 'ready' and fixed_group['shot_ids'] == g['shot_ids'])
                       if supplied is not None else narrative['feasible'])
        reason = ('用户指定分组；不自动改组。' if group_ready else '分组冲突，暂不批准省图。') if supplied is not None else (
            narrative["reasons"][n-1] if narrative["feasible"] else '待分组：' + '；'.join(narrative["limitations"]))
        gid = (fixed_group['id'] if fixed_group else '—') if supplied is not None else (f"A{n:02d}" if narrative["feasible"] else f"P{n:02d}")
        g.update(id=gid, reason=reason,
                 planning_status="ready" if group_ready else "pending",
                 duration_has_suggestion=any(original_shots[sid].get("duration_source", {}).get("kind") == "inference" for sid in g["shot_ids"]))
        if supplied is not None:
            g['planned_duration'] = fixed_group.get('planned_duration') if fixed_group else None
        elif not narrative["feasible"]:
            g["planned_duration"] = None
        g["source_group_ids"] = list(dict.fromkeys(states[sid]["source_group_id"] for sid in g["shot_ids"]))
        g["beat_id"] = original_shots[g["shot_ids"][0]].get("beat", {}).get("id")
        for d in result["decisions"]:
            if d["shot_id"] not in g["shot_ids"]:
                continue
            state = states[d["shot_id"]]
            a, verdict = state["assessment"], state["verdict"]
            d.update(group_id=g["id"], source_group_id=state["source_group_id"], frame=state["frame"],
                     review_verdict=verdict, issues=state["issues"])
            if supplied is not None and not group_ready:
                d['grouping_conflicts'] = fixed_group['conflicts'] if fixed_group else ['输入分组未包含此镜']
            can_fill = group_ready and d["mode"] == "ai_fill" and state["eligible"] and all(b in g["shot_ids"] for b in a["basis_shot_ids"])
            if can_fill:
                d.update(mode="ai_fill", status="ai_fill_suggested_unverified",
                         bracket=dict(zip(("before", "after"), a["basis_shot_ids"])), reason=state["reason"])
            elif verdict == "PASS":
                d.update(mode="anchor", status="anchor_reviewed", bracket=None,
                         reason=state["reason"] + ("；保留组首尾或关键状态作为参考。" if a.get("decision") == "ai_fill" else ""))
            else:
                status = "mismatch" if verdict == "FAIL" else "pending"
                d.update(mode="pending", status=status, bracket=None, reason=state["reason"])
    if supplied is not None:
        # No solver-created split/merge escapes into the final partition.
        result['groups'] = copy.deepcopy(supplied['groups'])
        result['grouping_mode'] = 'input'
        result['input_group_conflicts'] = supplied['conflicts']
        for g in result['groups']:
            g['source_group_ids'] = list(dict.fromkeys(states[s]['source_group_id'] for s in g['shot_ids'] if s in states))
        for d in result['decisions']:
            if d.get('grouping_conflicts') and d['mode'] == 'anchor':
                d['reason'] += '；分组冲突，暂不批准省图。'
    by_id = {d["shot_id"]: d for d in result["decisions"]}
    for d in result["decisions"]:
        if d["mode"] == "ai_fill":
            require(all(by_id[b]["status"] == "anchor_reviewed" for b in d["bracket"].values()), "inference basis is not a retained passed anchor")
    result.update(stage="post_review", feasible=narrative["feasible"], profile=copy.deepcopy(profile),
                  clipGroupList=clip_group_list(p, narrative["ranges"]) if narrative["feasible"] else [],
                  grouping_trace=narrative["trace"],
                  evidence_fingerprint=aggregation_fingerprint(p, project_path, profile),
                  limitations=narrative["limitations"] + ["省图为生成参考建议，未经生成验证；脚本镜头与全部输入原图保留。"],
                  objective={"anchor_count": sum(d["mode"] == "anchor" for d in result["decisions"]),
                             "fill_count": sum(d["mode"] == "ai_fill" for d in result["decisions"]),
                             "pending_count": sum(d["mode"] == "pending" for d in result["decisions"]),
                             "group_count": len(result["groups"])})
    if supplied is not None and narrative['feasible']:
        for row, g in zip(result['clipGroupList'], supplied['groups']):
            row['shotId'] = g['id']
    for decision in result['decisions']:
        decision['image'] = decision.pop('frame')
    return result


@verified_read
def post_review_plan(p, project_path, profile):
    return image_post_review_plan(p, project_path, profile)


def store_aggregation(p, project_path, result):
    require(result.get("stage") == "post_review" and result["evidence_fingerprint"] == aggregation_fingerprint(p, project_path, result["profile"]), "aggregation evidence changed")
    if p.get("aggregation"):
        p.setdefault("aggregation_history", []).append(copy.deepcopy(p["aggregation"]))
    p["aggregation"] = copy.deepcopy(result)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    with locked(args.project):
        p = read(args.project)
        result = post_review_plan(p, args.project, {})
        require(Path(args.output).resolve() != Path(args.project).resolve(), 'Plan output must not overwrite project')
        save(args.output, result)
        store_aggregation(p, args.project, result)
        save(args.project, p)
    print(result['objective'])


if __name__ == '__main__':
    main()
