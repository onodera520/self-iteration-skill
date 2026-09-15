"""Project integrity, prompt mapping, versioned review, local repair and readable Markdown."""
from __future__ import annotations
import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import uuid

BASE_PROMPT = "参考已有分镜图，严格按照分镜脚本生成一段快速切镜的视频，每个分镜不需要很大的动作幅度。没有台词，没有音乐，不要出现字幕。每个分镜硬切转场。"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


@contextlib.contextmanager
def locked(path):
    lock = Path(str(Path(path).resolve()) + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def resolve(project_path, value):
    return (Path(project_path).resolve().parent / value).resolve()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def group(p, gid):
    return next(g for g in p["groups"] if g["id"] == gid)


def shots(p, g):
    index = {s["id"]: s for s in p["shots"]}
    return [index[sid] for sid in g["shot_ids"]]


def validate(p, project_path):
    require(p.get("schema_version") == 1, "schema_version must be 1")
    require(isinstance(p.get("title"), str) and p["title"].strip(), "title required")
    require(isinstance(p.get("source_script"), str) and p["source_script"].strip(), "source_script required")
    for kind in ("assets", "shots", "groups"):
        require(isinstance(p.get(kind), list), kind + " must be array")
        ids = [x.get("id") for x in p[kind]]
        require(all(isinstance(i, str) and re.fullmatch(r"[\w-]+", i) for i in ids), "invalid IDs")
        require(len(ids) == len(set(ids)), "duplicate " + kind + " ID")
    require(p["shots"] and p["groups"], "shots and groups required")
    assets = {a["id"] for a in p["assets"]}
    missing = []
    for a in p["assets"]:
        require(a.get("kind") in ("character", "scene", "prop"), "invalid asset kind")
    for s in p["shots"]:
        require(number(s.get("duration")) and s["duration"] > 0, "positive shot duration required")
        require(all(isinstance(s.get(k), str) and s[k].strip() for k in ("script", "scene_id", "continuity_id", "required_result")), "shot narrative fields required")
        require(set(s.get("asset_ids", [])) <= assets, "unknown asset")
        r = s.get("reference", {})
        require(r.get("mode") in ("anchor", "ai_fill"), "invalid reference mode")
        require(r.get("role") in ("start", "representative", "end"), "invalid reference role")
        require(isinstance(r.get("reason"), str) and r["reason"].strip(), "reference reason required")
        if r["mode"] == "anchor" and (not r.get("path") or not resolve(project_path, r["path"]).is_file()):
            missing.append(s["id"])
    require([sid for g in p["groups"] for sid in g["shot_ids"]] == [s["id"] for s in p["shots"]], "groups must preserve every shot exactly once in source order")
    for g in p["groups"]:
        require(g["shot_ids"] and isinstance(g.get("version"), int) and g["version"] >= 1, "group version and shots required")
    c = p.get("config", {})
    require(c.get("workflow") in (None, "video_evidence"), "invalid workflow")
    require(c.get("video_input_mode", "anchors") in ("assets", "anchors"), "invalid video input mode")
    for key, default in (("max_repair_rounds", 3), ("max_submissions", 0)):
        require(type(c.get(key, default)) is int and c.get(key, default) >= 0, key + " must be nonnegative integer")
    require(type(p.get("repair_round", 0)) is int and p.get("repair_round", 0) >= 0, "invalid repair_round")
    if "budget_cny" in c:
        require(number(c["budget_cny"]) and c["budget_cny"] >= 0, "invalid budget")
    from requirements import contexts
    contexts(p)
    if c.get("video_input_mode") == "assets":
        used = {aid for s in p["shots"] for aid in s["asset_ids"]}
        missing_assets = [a["id"] for a in p["assets"] if a["id"] in used and (not a.get("path") or not resolve(project_path, a["path"]).is_file())]
        return {"shots": len(p["shots"]), "groups": len(p["groups"]), "missing_assets": missing_assets}
    return {"shots": len(p["shots"]), "groups": len(p["groups"]), "missing_anchors": missing}


def group_fingerprint(p, project_path, g):
    from requirements import contexts
    resolved = contexts(p)
    ss = copy.deepcopy(shots(p, g))
    for s in ss:
        s.pop("board", None)  # Extracted/edited outputs never invalidate their source video.
        if s["id"] in resolved:
            s["resolved_requirements"] = resolved[s["id"]]
        r = s["reference"]
        if r.get("path") and r["mode"] == "anchor":
            path = resolve(project_path, r["path"])
            r["content_sha256"] = sha(path) if path.is_file() else "MISSING"
    used = {a for s in ss for a in s["asset_ids"]}
    asset_rows = copy.deepcopy([a for a in p["assets"] if a["id"] in used])
    for a in asset_rows:
        if a.get("path"):
            path = resolve(project_path, a["path"])
            a["sha256"] = sha(path) if path.is_file() else "MISSING"
    binding = {"group": g, "shots": ss, "assets": asset_rows, "source": p["source_script"], "aspect_ratio": p.get("config", {}).get("aspect_ratio"), "video_input_mode": p.get("config", {}).get("video_input_mode", "anchors")}
    if "user_video_prompt" in p:
        binding["user_video_prompt"] = p["user_video_prompt"]
    return digest(binding)


def video_references(p, g):
    if p.get("config", {}).get("video_input_mode") == "assets":
        used = {aid for s in shots(p, g) for aid in s["asset_ids"]}
        return [a.get("path") for a in p["assets"] if a["id"] in used]
    return [s["reference"].get("path") for s in shots(p, g) if s["reference"]["mode"] == "anchor"]


def prompt(p, gid):
    g = group(p, gid)
    supplied = g.get("video_prompt")
    if supplied is None and len(p["groups"]) == 1:
        supplied = p.get("user_video_prompt")
    if supplied is not None or p.get("config", {}).get("workflow") == "video_evidence":
        require(isinstance(supplied, str) and supplied.strip(), "user video prompt required; multiple generation groups need group.video_prompt")
        return supplied + ("\n补充约束：" + g["prompt_notes"] if g.get("prompt_notes") else "")
    from requirements import contexts, target_text
    resolved = contexts(p)
    g = group(p, gid)
    asset_mode = p.get("config", {}).get("video_input_mode") == "assets"
    lines = [BASE_PROMPT if not asset_mode else BASE_PROMPT.replace("参考已有分镜图", "参考提供的角色、场景和道具资产图"), "\n图片对应（按下列顺序上传）："]
    if asset_mode:
        used = {aid for s in shots(p, g) for aid in s["asset_ids"]}
        for n, a in enumerate((a for a in p["assets"] if a["id"] in used), 1):
            lines.append(f"图片{n} → 资产 {a['id']}：{a['description']}。仅作为身份/外观/空间依据，不是一张图对应一个镜头。")
        lines.append("视频将按原脚本校对并抽帧；每镜保留清晰的构图和关键状态，同时完整表现关键动作及结果，不得用静帧停留替代交接过程。全部镜头须按顺序出现。")
    n = 0
    for s in ([] if asset_mode else shots(p, g)):
        r = s["reference"]
        if r["mode"] == "anchor":
            n += 1
            lines.append(f"图片{n} → {s['id']}，参考角色 {r['role']}。")
        else:
            lines.append(f"{s['id']}：无独立图片，由 AI 补足；必须出现此镜头。")
    lines.append("\n逐镜时间与内容（组内秒数，镜间硬切）：")
    t = 0.0
    for s in shots(p, g):
        end = t + s["duration"]
        lines.append(f"{s['id']} [{t:g}–{end:g}s] {s['script']} 必须可见的结果：{s['required_result']}")
        if s["id"] in resolved:
            lines.append(target_text(resolved[s["id"]], "video"))
        for f in s.get("facts", []):
            if f.get("status") == "known" and f.get("source", {}).get("kind") != "inference":
                lines.append(f"  状态约束 [{f['phase']}] {f['entity']}.{f['attribute']} = {json.dumps(f['value'], ensure_ascii=False)}")
        for c in s.get("state_changes", []):
            if c.get("authorized") and c.get("source", {}).get("kind") != "inference":
                lines.append(f"  本镜授权变化：{c['entity']}.{c['attribute']} 从 {c['before']} 到 {c['after']}。须表现过程与结果，勿提前发生。")
        t = end
    if g.get("prompt_notes"):
        lines.append("补充约束：" + g["prompt_notes"])
    return "\n".join(lines)


def current_video(p, project_path, g, allow_old=False):
    fp = group_fingerprint(p, project_path, g)
    if p.get("config", {}).get("video_source") == "imported":
        candidates = [v for v in p.get("imported_videos", []) if v["target_id"] == g["id"]]
        for v in reversed(candidates):
            path = resolve(project_path, v["outputs"][0])
            if (allow_old or (v["group_fingerprint"] == fp and v["version"] == g["version"])) and path.is_file() and sha(path) == v["output_hashes"][0]:
                return v, path
            if not allow_old:
                return None, None  # A broken replacement cannot silently revive older evidence.
        return None, None
    candidates = [t for t in p.get("tasks", {}).values() if t.get("kind") == "video" and t.get("target_id") == g["id"] and t.get("status") == "SUCCESS" and t.get("outputs")]
    current = [t for t in candidates if t.get("group_fingerprint") == fp and t.get("version") == g["version"]]
    for t in reversed(current or (candidates if allow_old else [])):
        f = resolve(project_path, t["outputs"][0])
        if f.is_file() and t.get("output_hashes", [None])[0] == sha(f):
            return t, f
    return None, None


def import_video(p, project_path, gid, video):
    """Register supplied media separately from paid task/submission accounting."""
    from media import probe, duration
    require(p.get("config", {}).get("video_source") == "imported", "set video_source: imported first")
    g = group(p, gid)
    path = Path(video).resolve()
    require(path.is_file(), "input video required")
    metadata = probe(path)
    require(any(s.get("codec_type") == "video" for s in metadata["streams"]), "video stream required")
    measured = duration(metadata)
    require(number(measured) and measured > 0, "positive video duration required")
    record = dict(target_id=gid, version=g["version"], source="user_video",
                  group_fingerprint=group_fingerprint(p, project_path, g),
                  outputs=[str(path)], output_hashes=[sha(path)], duration=measured)
    p.setdefault("imported_videos", []).append(record)
    return record


def video_context(p, project_path, gid):
    """One immutable group context, plus only the adjacent boundary shots."""
    from storyboard import current_mapping, current_frame
    from requirements import contexts
    resolved = contexts(p)
    g = group(p, gid)
    task, path = current_video(p, project_path, g)
    require(task, "current generated video required")
    mapping = current_mapping(p, project_path, gid)
    extraction = read(resolve(project_path, mapping["evidence_file"])) if mapping else None
    rows = [{"shot_id": s["id"], "script": s["script"], "shot_size": s.get("shot_size"),
             "requirements": resolved.get(s["id"]), "selected_frame": current_frame(p, project_path, s["id"])} for s in shots(p, g)]
    used_assets = {aid for s in shots(p, g) for aid in s["asset_ids"]}
    assets = [dict(a, sha256=sha(resolve(project_path, a["path"])) if a.get("path") and resolve(project_path, a["path"]).is_file() else "MISSING")
              for a in p["assets"] if a["id"] in used_assets]
    boundaries = []
    index = p["groups"].index(g)
    for n, edge in ((index-1, -1), (index+1, 0)):
        if not 0 <= n < len(p["groups"]):
            continue
        other = p["groups"][n]
        sid = other["shot_ids"][edge]
        ot, op = current_video(p, project_path, other)
        om = current_mapping(p, project_path, other["id"])
        boundaries.append({"group_id": other["id"], "shot_id": sid,
            "group_fingerprint": group_fingerprint(p, project_path, other),
            "video_sha256": sha(op) if ot else None,
            "requirements": resolved.get(sid),
            "mapping": next(r for r in om["shots"] if r["shot_id"] == sid) if om else None})
    result = {"group_id": gid, "version": g["version"], "video_sha256": sha(path),
              "group_fingerprint": group_fingerprint(p, project_path, g), "video": str(path),
              "duration": task.get("duration"), "assets": assets, "shots": rows, "mapping": mapping,
              "extraction": extraction, "boundaries": boundaries}
    result["context_fingerprint"] = digest(result)
    result["previous_review"] = next((copy.deepcopy(r) for r in reversed(p.get("reviews", [])) if r["group_id"] == gid), None)
    return result


def review_current(p, project_path, gid):
    if gid == "__delivery__":
        d = p.get("delivery") or {}
        if not delivery_current(p, project_path):
            return None
        version, path, fp = d["revision"], resolve(project_path, d["path"]), d["fingerprint"]
    else:
        g = group(p, gid)
        task, path = current_video(p, project_path, g)
        if not task:
            return None
        version, fp = g["version"], group_fingerprint(p, project_path, g)
    for r in reversed(p.get("reviews", [])):
        if r["group_id"] == gid and r["version"] == version and r["video_sha256"] == sha(path) and r.get("fingerprint") == fp and not r.get("stale"):
            if r.get("context_fingerprint") and (gid == "__delivery__" or r["context_fingerprint"] != video_context(p, project_path, gid)["context_fingerprint"]):
                return None
            return r
    return None


def delivery_fingerprint(p, project_path):
    rows = []
    for g in p["groups"]:
        t, path = current_video(p, project_path, g)
        if not t:
            return None
        rows.append([g["id"], group_fingerprint(p, project_path, g), sha(path)])
    return digest(rows)


def delivery_current(p, project_path):
    d = p.get("delivery") or {}
    if not d.get("path"):
        return False
    path = resolve(project_path, d["path"])
    return path.is_file() and sha(path) == d.get("sha256") and d.get("fingerprint") == delivery_fingerprint(p, project_path)


def record_review(p, project_path, r):
    gid = r["group_id"]
    if gid == "__delivery__":
        require(delivery_current(p, project_path), "delivery missing or stale")
        d = p["delivery"]
        version, path, fp = d["revision"], resolve(project_path, d["path"]), d["fingerprint"]
        ids = [s["id"] for s in p["shots"]]
        duration = d["duration"]
    else:
        g = group(p, gid)
        task, path = current_video(p, project_path, g)
        require(task is not None, "current generated video required")
        version, fp, ids = g["version"], group_fingerprint(p, project_path, g), g["shot_ids"]
        duration = task.get("duration")
    require(r.get("version") == version and r.get("video_sha256") == sha(path), "review video/version mismatch")
    evidence_mode = p.get("config", {}).get("workflow") == "video_evidence" or "reference_assessments" in r
    ctx = None
    if evidence_mode:
        require(gid != "__delivery__", "video evidence review is per generation group")
        ctx = video_context(p, project_path, gid)
        require(r.get("context_fingerprint") == ctx["context_fingerprint"], "review context changed; reload group evidence")
        require(ctx["mapping"] and ctx["extraction"], "review needs current extraction and mapping")
    checks = r.get("checks", {})
    require(set(checks) == {"shot", "continuity", "story", "subtitles"}, "all four review checks required")
    require(all(v in ("PASS", "FAIL", "uncertain") for v in checks.values()), "invalid verdict")
    coverage = r.get("coverage", {})
    require(coverage.get("shot_ids") == ids, "review must account for every shot in order")
    require(isinstance(coverage.get("limitations"), list), "coverage limitations required")
    evidence = r.get("evidence", [])
    require(evidence and all(e.get("shot_id") in ids and number(e.get("time")) and e["time"] >= 0 and e.get("observation") for e in evidence), "visible timed evidence required")
    if duration:
        require(all(e["time"] <= duration for e in evidence), "evidence beyond video duration")
    issues = r.get("issues", [])
    for i in issues:
        require(all(i.get(k) for k in ("id", "shot_ids", "time_range", "problem", "expected", "actual", "evidence", "repair_target", "fix")), "incomplete issue")
        require(set(i["shot_ids"]) <= set(ids), "unknown issue shot")
        require(i.get("severity") in ("low", "medium", "high", "critical"), "invalid severity")
        require(i["repair_target"] in ("storyboard_image", "video_shot", "editing", "unresolved"), "invalid repair target")
        tr = i["time_range"]
        require(len(tr) == 2 and all(number(v) for v in tr) and 0 <= tr[0] <= tr[1] and (not duration or tr[1] <= duration), "invalid issue time range")
    failed = "FAIL" in checks.values()
    require(not failed or issues, "FAIL needs actionable evidence-backed issue")
    passing = all(v == "PASS" for v in checks.values())
    if ctx:
        frames = {str(resolve(project_path, f["path"])): f for f in ctx["extraction"]["frames"]}
        for e in evidence:
            frame = frames.get(str(resolve(project_path, e.get("path", ""))))
            require(frame and frame["sha256"] == e.get("sha256") and abs(frame["time"] - e["time"]) < .001,
                    "review evidence must bind an unchanged extracted frame and actual time")
        assessments = r.get("reference_assessments", [])
        require([a.get("shot_id") for a in assessments] == ids, "reference assessments must cover group in order")
        for a in assessments:
            require(a.get("decision") in ("anchor", "ai_fill", "pending") and a.get("reason"), "reference decision and reason required")
            times = a.get("evidence_times", [])
            require(times and all(any(e["shot_id"] == a["shot_id"] and e["time"] == t for e in evidence) for t in times), "reference assessment needs same-shot evidence")
        boundary_checks = r.get("boundary_checks", [])
        require([b.get("shot_id") for b in boundary_checks] == [b["shot_id"] for b in ctx["boundaries"]], "all adjacent boundary checks required")
        for b, source in zip(boundary_checks, ctx["boundaries"]):
            require(b.get("verdict") in ("PASS", "FAIL", "uncertain") and b.get("observation"), "boundary observation required")
            if b["verdict"] == "PASS":
                require(source["mapping"] and source["mapping"]["status"] == "matched", "boundary PASS needs matched neighboring evidence")
                require(source["requirements"] and source["requirements"]["ready"], "boundary PASS needs ready requirements")
            require(b["verdict"] != "FAIL" or checks["continuity"] == "FAIL", "boundary failure must fail continuity")
            require(b["verdict"] != "uncertain" or checks["continuity"] != "PASS", "uncertain boundary cannot pass continuity")
    if passing:
        if ctx:
            require(all(s["requirements"] and s["requirements"]["ready"] for s in ctx["shots"]), "ready requirements required for video PASS")
            require(all(s["status"] == "matched" for s in ctx["mapping"]["shots"]), "PASS needs all shots matched")
        require(not r.get("uncertainties") and not coverage["limitations"], "uncertain evidence cannot PASS")
        require(not any(i["severity"] != "low" for i in issues), "unresolved substantial issue cannot PASS")
        require(coverage.get("mapping_verified") is True and {e["shot_id"] for e in evidence} == set(ids), "PASS needs verified mapping and every-shot evidence")
        spans = coverage.get("actual_shots", [])
        require([s.get("shot_id") for s in spans] == ids, "PASS needs actual ordered shot spans")
        last = 0.0
        for s in spans:
            require(number(s.get("start")) and number(s.get("end")) and abs(s["start"] - last) <= .1 and s["end"] > s["start"], "invalid actual shot timing")
            last = s["end"]
        require(duration and abs(last - duration) <= .15, "PASS needs probed duration and complete actual timing")
        if ctx:
            for span in spans:
                require(any(e["shot_id"] == span["shot_id"] and span["start"] <= e["time"] < span["end"] for e in evidence),
                        "PASS needs evidence inside each actual shot span")
    r = copy.deepcopy(r)
    r.update(fingerprint=fp, verdict="FAIL" if failed else ("PASS" if passing else "uncertain"), id=uuid.uuid4().hex)
    p.setdefault("reviews", []).append(r)
    return r["verdict"]


def repair(p, project_path, gids, reason):
    require(reason.strip() and gids and len(set(gids)) == len(gids), "reason and unique groups required")
    require(p.get("repair_round", 0) < p.get("config", {}).get("max_repair_rounds", 3), "repair round limit reached; retain best result")
    for gid in gids:
        r = review_current(p, project_path, gid)
        require(r and r["verdict"] == "FAIL", "repair requires current confirmed FAIL: " + gid)
    p["repair_round"] = p.get("repair_round", 0) + 1
    indexes = [n for n, g in enumerate(p["groups"]) if g["id"] in gids]
    affected = {p["groups"][j]["id"] for n in indexes for j in (n-1, n, n+1) if 0 <= j < len(p["groups"])}
    for gid in gids:
        g = group(p, gid)
        g["version"] += 1
        g["repair_round"] = p["repair_round"]
    for r in p.get("reviews", []):
        if r["group_id"] in affected or r["group_id"] == "__delivery__":
            r["stale"] = True
    p.setdefault("repairs", []).append({"round": p["repair_round"], "groups": gids, "reason": reason, "recheck": sorted(affected)})


def split(p, gid, before):
    g = group(p, gid)
    require(g.get("repair_round") == p.get("repair_round", 0) and p.get("repair_round", 0) > 0, "split requires active repair round")
    n = g["shot_ids"].index(before)
    require(n > 0, "split cannot create empty group")
    ids = {x["id"] for x in p["groups"]}
    require(gid + "_a" not in ids and gid + "_b" not in ids, "split IDs already exist")
    a, b = copy.deepcopy(g), copy.deepcopy(g)
    a.update(id=gid + "_a", shot_ids=g["shot_ids"][:n])
    b.update(id=gid + "_b", shot_ids=g["shot_ids"][n:])
    # Parent wording covers a different interval; never submit it for both children.
    for child in (a, b):
        child.pop("video_prompt", None)
    index = p["groups"].index(g)
    p["groups"][index:index+1] = [a, b]
    p["repairs"][-1].setdefault("splits", []).append({"from": gid, "to": [a["id"], b["id"]]})


def restore(p, shot_id, reason):
    s = next(s for s in p["shots"] if s["id"] == shot_id)
    g = next(g for g in p["groups"] if shot_id in g["shot_ids"])
    require(p.get("repair_round", 0) > 0 and g.get("repair_round") == p["repair_round"], "restore requires active repair for the affected group")
    require(reason.strip(), "restoration reason required")
    s["reference"].update(mode="anchor", locked=True, reason=reason)
    p["repairs"][-1].setdefault("restored_references", []).append({"shot_id": shot_id, "reason": reason})


def render(p, project_path, out):
    from storyboard import render as render_boards
    return render_boards(p, project_path, out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "prompt", "context", "render", "review", "repair", "split", "restore", "import-video"):
        q = sub.add_parser(name)
        q.add_argument("project")
        if name in ("prompt", "context", "split", "import-video"):
            q.add_argument("group")
        if name == "import-video": q.add_argument("video")
        if name == "split": q.add_argument("before")
        if name == "render": q.add_argument("output")
        if name == "review": q.add_argument("review_file")
        if name == "repair":
            q.add_argument("groups", nargs="+")
            q.add_argument("--reason", required=True)
        if name == "restore":
            q.add_argument("shot")
            q.add_argument("--reason", required=True)
    args = ap.parse_args()
    mutation = args.cmd in ("review", "repair", "split", "restore", "import-video")
    with locked(args.project) if mutation else contextlib.nullcontext():
        p = read(args.project)
        result = validate(p, args.project)
        if args.cmd == "prompt": result = prompt(p, args.group)
        if args.cmd == "import-video": result = import_video(p, args.project, args.group, args.video)
        if args.cmd == "context": result = video_context(p, args.project, args.group)
        if args.cmd == "render": result = render(p, args.project, args.output)
        if args.cmd == "review": result = record_review(p, args.project, read(args.review_file))
        if args.cmd == "repair": repair(p, args.project, args.groups, args.reason)
        if args.cmd == "split": split(p, args.group, args.before)
        if args.cmd == "restore": restore(p, args.shot, args.reason)
        if mutation:
            validate(p, args.project)
            save(args.project, p)
        print(json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, StopIteration, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
