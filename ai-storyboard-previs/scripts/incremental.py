"""Read-only incremental review drafts; never approve or revive a stale review."""
from __future__ import annotations
import copy
from pathlib import Path

from evidence_runtime import evidence_operation, verified_read
from previs import digest, read, require, resolve, save, sha, video_context, review_current


def frame_key(frame):
    return (str(Path(frame["path"]).resolve()), frame["sha256"], frame["time"])


def checked_frames(project, evidence):
    for frame in evidence["frames"]:
        require(sha(resolve(project, frame["path"])) == frame["sha256"], "incremental evidence frame changed")
    return {frame_key(f) for f in evidence["frames"]}


def context_digest(ctx):
    return digest({k: v for k, v in ctx.items() if k not in ("context_fingerprint", "previous_review")})


def dependencies(p, review):
    graph = {s["id"]: set() for s in p["shots"]}
    for s in p["shots"]:
        parent = s.get("requirements", {}).get("inherits_from")
        if parent:
            graph[s["id"]].add(parent)
    # Include cross-group reference explanations and multi-shot issues, but never
    # promote these historic records to current approvals.
    latest = {}
    for r in p.get("reviews", []):
        latest[r["group_id"]] = r
    if review:
        latest[review["group_id"]] = review
    for r in latest.values():
        for field in ("reference_assessments", "asset_comparisons"):
            for row in r.get(field, []):
                if row["shot_id"] in graph:
                    graph[row["shot_id"]].update(row.get("basis_shot_ids", []))
        for issue in r.get("issues", []):
            ids = set(issue.get("shot_ids", []))
            for sid in ids & graph.keys():
                graph[sid].update(ids - {sid})
    return graph


def analyze(p, old, current, evidence, review):
    ids = [s["shot_id"] for s in current["shots"]]
    old_rows = {s["shot_id"]: s for s in old["shots"]}
    old_map = {s["shot_id"]: s for s in (old.get("mapping") or {}).get("shots", [])}
    new_map = {s["shot_id"]: s for s in (current.get("mapping") or {}).get("shots", [])}
    old_frames = {frame_key(f) for f in (old.get("extraction") or {}).get("frames", [])}
    fresh = [f for f in evidence["frames"] if frame_key(f) not in old_frames]
    reasons = {sid: [] for sid in ids}
    primary, neighbors = set(), set()
    source_changed = any(old.get(k) != current.get(k) for k in
                         ("video_sha256", "version", "group_fingerprint", "review_schema", "reference_policy_version", "review_scope"))
    assets = {a["id"]: a for a in current["assets"]}
    old_assets = {a["id"]: a for a in old["assets"]}
    for index, row in enumerate(current["shots"]):
        sid = row["shot_id"]
        if source_changed or old_rows.get(sid) != row or old_map.get(sid) != new_map.get(sid):
            reasons[sid].append("视频、规则、本镜要求、选帧或映射变化")
        if any(assets.get(a) != old_assets.get(a) for a in row.get("asset_ids", [])):
            reasons[sid].append("依赖资产变化")
        mapping = old_map.get(sid, {})
        # Candidate instants are not shot boundaries. Until precise boundaries are
        # visually established, use a conservative corridor between neighbor candidates.
        before = [c["time"] for other in ids[:index] for c in old_map.get(other, {}).get("candidates", [])]
        after = [c["time"] for other in ids[index+1:] for c in old_map.get(other, {}).get("candidates", [])]
        low, high = max(before, default=0), min(after, default=evidence["duration"])
        if fresh and (mapping.get("status") != "matched" or any(low <= f["time"] <= high for f in fresh)):
            reasons[sid].append("新增帧落在可能范围，或该镜尚未可靠定位")
        if reasons[sid]:
            primary.add(sid)
    for sid in primary:
        i = ids.index(sid)
        neighbors.update(ids[max(0, i-1):i] + ids[i+1:i+2])
    boundary_changes = []
    group_index = next(i for i, g in enumerate(p["groups"]) if g["id"] == current["group_id"])
    for boundary in current.get("boundaries", []):
        other_index = next(i for i, g in enumerate(p["groups"]) if g["id"] == boundary["group_id"])
        local_edge = ids[0] if other_index < group_index else ids[-1]
        previous = next((b for b in old.get("boundaries", []) if b["shot_id"] == boundary["shot_id"]), None)
        if boundary != previous or local_edge in primary:
            boundary_changes.append(boundary["shot_id"])
            neighbors.add(local_edge)
    touched = primary | neighbors | set(boundary_changes)
    graph = dependencies(p, review)
    dependent = set()
    while True:
        more = {sid for sid, basis in graph.items() if basis & (touched | dependent)} - touched - dependent
        if not more:
            break
        dependent.update(more)
    if old.get("narrative_plan") != current.get("narrative_plan"):
        dependent.update(set(ids) - touched)
    reusable = set(ids) - touched - dependent
    ordered = lambda values: [s["id"] for s in p["shots"] if s["id"] in values]
    return {"new_ranges": evidence.get("sampling", {}).get("dense_ranges", []),
            "new_frame_paths": [f["path"] for f in fresh],
            "primary": ordered(primary), "adjacent": ordered(neighbors - primary),
            "dependency_recheck": ordered(dependent), "boundary_recheck": boundary_changes,
            "reuse": ordered(reusable), "reasons": {sid: value for sid, value in reasons.items() if value},
            "note": "依赖复核先比较状态与推导依据，不自动重看图片；只有新矛盾或缺证才扩大视觉检查。"}


def prepare(p, project, gid, evidence_file, output):
    """Capture valid old context before the batch remap; called by media extract."""
    with evidence_operation():
        ctx = video_context(p, project, gid)
        evidence_file = Path(evidence_file).resolve()
        evidence = read(evidence_file)
        require(evidence["video_sha256"] == ctx["video_sha256"], "incremental source video mismatch")
        new_keys = checked_frames(project, evidence)
        old_keys = checked_frames(project, ctx["extraction"]) if ctx["extraction"] else set()
        require(old_keys <= new_keys, "incremental extraction must retain all prior frames")
        review = review_current(p, project, gid)
        mapping_draft = {"group_id": gid, "video_sha256": ctx["video_sha256"],
                         "evidence_file": str(evidence_file),
                         "shots": copy.deepcopy((ctx.get("mapping") or {}).get("shots", []))}
        report = {"group_id": gid, "evidence_file": str(evidence_file), "evidence_sha256": sha(evidence_file),
                  "base_context": ctx, "base_review_id": review.get("id") if review else None,
                  "mapping_draft": mapping_draft,
                  "impact": analyze(p, ctx, ctx, evidence, review), "draft_only": True}
    save(output, report)
    return report


@verified_read
def resume_context(p, project, gid, report_file):
    """Merge eligible records into a partial draft after remapping; regular review validates all."""
    report = read(resolve(project, report_file))
    require(report.get("group_id") == gid, "incremental group mismatch")
    old = report["base_context"]
    require(context_digest(old) == old["context_fingerprint"], "incremental context snapshot changed")
    path = resolve(project, report["evidence_file"])
    require(sha(path) == report["evidence_sha256"], "incremental evidence manifest changed")
    evidence = read(path)
    keys = checked_frames(project, evidence)
    current = video_context(p, project, gid)
    require(evidence["video_sha256"] == current["video_sha256"], "incremental source video changed; rematch entire video")
    require(current.get("mapping") and resolve(project, current["mapping"]["evidence_file"]) == path,
            "batch map the new evidence before requesting incremental context")
    review = next((r for r in p.get("reviews", []) if r.get("id") == report.get("base_review_id")
                   and r.get("context_fingerprint") == old["context_fingerprint"] and not r.get("stale")), None)
    impact = analyze(p, old, current, evidence, review)
    same_rules = all(old.get(k) == current.get(k) for k in ("review_schema", "reference_policy_version", "review_scope"))
    reusable = set(impact["reuse"]) if review and same_rules else set()
    draft = {field: [copy.deepcopy(r) for r in (review or {}).get(field, []) if r["shot_id"] in reusable]
             for field in ("shot_reviews", "reference_assessments", "asset_comparisons")}
    draft["issues"] = [copy.deepcopy(i) for i in (review or {}).get("issues", []) if set(i["shot_ids"]) <= reusable]
    observations = [copy.deepcopy(e) for e in (review or {}).get("evidence", []) if frame_key(e) in keys]
    draft["evidence"] = [e for e in observations if e["shot_id"] in reusable]
    current["incremental"] = {"impact": impact, "reusable_observations": observations,
        "mapping_observations": copy.deepcopy((old.get("mapping") or {}).get("shots", [])),
        "review_draft": draft, "draft_only": True,
        "needs_review_rows": [s["shot_id"] for s in current["shots"] if s["shot_id"] not in reusable],
        "instruction": "复用事实不等于复用结论。补齐待复核行，重算整组 checks/coverage/issues/uncertainties、省图和边界；用当前 context_fingerprint 一次提交完整 review。禁止自动批准。"}
    return current
