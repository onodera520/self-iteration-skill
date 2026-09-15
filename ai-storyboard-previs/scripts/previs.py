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
    return digest({"group": g, "shots": ss, "assets": asset_rows, "source": p["source_script"], "aspect_ratio": p.get("config", {}).get("aspect_ratio"), "video_input_mode": p.get("config", {}).get("video_input_mode", "anchors")})


def video_references(p, g):
    if p.get("config", {}).get("video_input_mode") == "assets":
        used = {aid for s in shots(p, g) for aid in s["asset_ids"]}
        return [a.get("path") for a in p["assets"] if a["id"] in used]
    return [s["reference"].get("path") for s in shots(p, g) if s["reference"]["mode"] == "anchor"]


def prompt(p, gid):
    from requirements import contexts, target_text
    resolved = contexts(p)
    g = group(p, gid)
    asset_mode = p.get("config", {}).get("video_input_mode") == "assets"
    lines = [BASE_PROMPT if not asset_mode else BASE_PROMPT.replace("参考已有分镜图", "参考提供的角色、场景和道具资产图"), "\n图片对应（按下列顺序上传）："]
    if asset_mode:
        used = {aid for s in shots(p, g) for aid in s["asset_ids"]}
        for n, a in enumerate((a for a in p["assets"] if a["id"] in used), 1):
            lines.append(f"图片{n} → 资产 {a['id']}：{a['description']}。仅作为身份/外观/空间依据，不是一张图对应一个镜头。")
        lines.append("视频用于提取分镜静帧；每镜保留清晰可选的构图和关键动作状态，全部镜头仍须依脚本出现。")
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
    candidates = [t for t in p.get("tasks", {}).values() if t.get("kind") == "video" and t.get("target_id") == g["id"] and t.get("status") == "SUCCESS" and t.get("outputs")]
    current = [t for t in candidates if t.get("group_fingerprint") == fp and t.get("version") == g["version"]]
    for t in reversed(current or (candidates if allow_old else [])):
        f = resolve(project_path, t["outputs"][0])
        if f.is_file() and t.get("output_hashes", [None])[0] == sha(f):
            return t, f
    return None, None


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
    if passing:
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
    for name in ("validate", "prompt", "render", "review", "repair", "split", "restore"):
        q = sub.add_parser(name)
        q.add_argument("project")
        if name in ("prompt", "split"):
            q.add_argument("group")
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
    mutation = args.cmd in ("review", "repair", "split", "restore")
    with locked(args.project) if mutation else contextlib.nullcontext():
        p = read(args.project)
        result = validate(p, args.project)
        if args.cmd == "prompt": result = prompt(p, args.group)
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
