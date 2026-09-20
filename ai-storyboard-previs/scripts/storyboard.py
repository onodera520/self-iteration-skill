"""Select storyboard images, bind visual reviews, route bounded repairs, publish Markdown."""
from __future__ import annotations
import argparse
import copy
import html
import json
import os
from pathlib import Path
import shutil
import sys
from evidence_runtime import verified_read, memo_read, evidence_operation
from validation import text, text_array
from previs import (read, save, locked, validate, require, number, resolve, sha, digest,
                    group, current_video, group_fingerprint)

CHECKS = {"identity", "scene", "props", "composition", "key_state", "continuity", "cleanliness"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def shot(p, sid):
    return next(s for s in p["shots"] if s["id"] == sid)


def image_path(project, value):
    path = resolve(project, value)
    require(path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES, "existing storyboard image required")
    # Verify file contents as well as the extension; never publish a video as an image.
    from PIL import Image
    with Image.open(path) as im:
        im.verify()
    return path


def selected(p, project, sid):
    item = shot(p, sid).get("board", {}).get("selected")
    if not item:
        return None
    path = resolve(project, item["path"])
    if path.is_file() and sha(path) == item["sha256"]:
        return item
    return None


def narrative(p, project, sid):
    from requirements import contexts
    s = copy.deepcopy(shot(p, sid))
    s.pop("board", None)
    s.pop("reference", None)  # Video conditioning is independent of final image acceptance.
    resolved = contexts(p)
    if sid in resolved:
        s["resolved_requirements"] = resolved[sid]
    assets = copy.deepcopy([a for a in p["assets"] if a["id"] in s["asset_ids"]])
    for a in assets:
        if a.get("path"):
            path = resolve(project, a["path"])
            a["sha256"] = sha(path) if path.is_file() else "MISSING"
    return digest([s, assets, p["source_script"], p.get("config", {}).get("aspect_ratio")])


def omitted(p, project, sid):
    decision = shot(p, sid).get("board", {}).get("omission")
    return decision if decision and decision.get("context") == omission_context(p, project, sid) else None


def neighbors(p, sid):
    ids = [s["id"] for s in p["shots"]]
    n = ids.index(sid)
    return ids[max(0, n-1):n] + ids[n+1:n+2]


def omission_context(p, project, sid):
    rows = [[sid, narrative(p, project, sid)]]
    for n in neighbors(p, sid):
        item = selected(p, project, n)
        rows.append([n, narrative(p, project, n), item["sha256"] if item else None])
    return digest(rows)


def review_fingerprint(p, project, sid):
    context = []
    for other in [sid] + neighbors(p, sid):
        item = selected(p, project, other)
        context.append([other, narrative(p, project, other),
                        item["sha256"] if item else None, omitted(p, project, other)])
    return digest(context)


def current_review(p, project, sid):
    if not selected(p, project, sid):
        return None
    fp = review_fingerprint(p, project, sid)
    return next((r for r in reversed(p.get("board_reviews", []))
                 if r["shot_id"] == sid and r["fingerprint"] == fp), None)


def has_frame_observation(candidate):
    """Optional neutral notes belong to one candidate, never a whole-shot summary."""
    if not {'observation', 'visible_facts'} & candidate.keys():
        return False
    require(text(candidate.get('observation')) and text_array(candidate.get('visible_facts'))
            and candidate['visible_facts'], 'candidate observation needs nonempty observation and visible_facts')
    return True


def record_mapping(p, project, data):
    """Agent supplies observations after inspecting frames/video, not similarity alone."""
    gid, rows = data["group_id"], data["shots"]
    g = group(p, gid)
    task, video = current_video(p, project, g)
    require(task and data.get("video_sha256") == sha(video), "mapping needs current source video")
    evidence = read(resolve(project, data["evidence_file"]))
    require(evidence["video_sha256"] == sha(video), "evidence video mismatch")
    if p.get("config", {}).get("video_source") == "imported":
        require(number(evidence.get("duration")) and abs(evidence["duration"] - task["duration"]) < .001,
                "extraction must cover the measured source video")
    require([r.get("shot_id") for r in rows] == g["shot_ids"], "mapping must include every shot in order")
    frames = {str(Path(f["path"]).resolve()): f for f in evidence["frames"]}
    last_time = -1.0
    for row in rows:
        require(row.get("status") in ("matched", "absent", "uncertain"), "invalid mapping status")
        require(isinstance(row.get("observation"), str) and row["observation"].strip(), "mapping needs visible observations")
        candidates = row.get("candidates", [])
        if "independent_visual_unit" in row:
            require(type(row["independent_visual_unit"]) is bool, "independent_visual_unit must be boolean")
        if row["status"] == "matched":
            require(candidates, "matched shot needs candidate frames")
            require(row.get("independent_visual_unit") is not False,
                    "matched cannot reuse a previous visual unit when the required independent shot is missing; use uncertain then rescan")
        else:
            require(not candidates, "unmatched shot cannot claim matched candidates")
        if row["status"] == "absent":
            require(row.get("full_rescan") is True, "absence requires rewatch/rescan of source video")
            if p.get("config", {}).get("video_source") == "imported":
                scan = row.get("rescan", {})
                require(scan.get("observation") and scan.get("ranges"), "absence requires rescan ranges and observations")
                covered = 0.0
                for span in scan["ranges"]:
                    require(len(span) == 2 and all(number(t) for t in span) and 0 <= span[0] <= covered + .001 and span[0] < span[1] <= evidence["duration"] + .001,
                            "rescan ranges must cover source video without gaps")
                    covered = max(covered, span[1])
                require(covered >= evidence["duration"] - .001, "absence requires full source video coverage")
        for c in candidates:
            noted = has_frame_observation(c)
            path = image_path(project, c["path"])
            frame = frames.get(str(path))
            require(frame and frame.get("sha256") == sha(path), "candidate not in unchanged extraction evidence")
            require(number(c.get("time")) and abs(c["time"] - frame["time"]) < .001, "candidate timestamp mismatch")
            if noted:
                require(c.get('sha256') == frame['sha256'] and c['time'] == frame['time'],
                        'candidate observation needs exact current frame SHA256 and timestamp; inspect changed evidence')
            require(c["time"] > last_time, "candidate frames must follow script order; rematch or use uncertain")
            last_time = c["time"]
            c["sha256"] = sha(path)
    item = copy.deepcopy(data)
    item["group_fingerprint"] = group_fingerprint(p, project, g)
    item["evidence_sha256"] = sha(resolve(project, data["evidence_file"]))
    p.setdefault("board_mappings", []).append(item)


def record_mapping_batch(p, project, data):
    """Register one mapping and its selections atomically, without new judgments."""
    staged = copy.deepcopy(p)
    with evidence_operation():
        mapping = {k: v for k, v in data.items() if k != "selections"}
        record_mapping(staged, project, mapping)
        selections = data.get("selections", [])
        require(isinstance(selections, list), "selections must be a list")
        ids = [item["shot_id"] for item in selections]
        require(len(set(ids)) == len(ids) and set(ids) <= set(group(staged, data["group_id"])["shot_ids"]),
                "selections must be unique shots from the mapped group")
        for item in selections:
            require(item.get("source", {}).get("kind") == "frame", "mapping selections must use extracted frames")
            select_image(staged, project, item)
    p.clear()
    p.update(staged)


@verified_read
def current_mapping(p, project, gid):
    index = _current_mapping_index(p, project, gid)
    # Preserve the existing API's live project-record reference.
    return p["board_mappings"][index] if index is not None else None


@memo_read
def _current_mapping_index(p, project, gid):
    g = group(p, gid)
    task, video = current_video(p, project, g)
    if not task:
        return None
    fp = group_fingerprint(p, project, g)
    mappings = p.get("board_mappings", [])
    for index in reversed(range(len(mappings))):
        m = mappings[index]
        if m["group_id"] == g["id"] and m["group_fingerprint"] == fp and m["video_sha256"] == sha(video):
            evidence_path = resolve(project, m["evidence_file"])
            if not evidence_path.is_file() or (m.get("evidence_sha256") and sha(evidence_path) != m["evidence_sha256"]):
                return None
            evidence = read(evidence_path)
            if any(not resolve(project, f["path"]).is_file() or sha(resolve(project, f["path"])) != f["sha256"] for f in evidence["frames"]):
                return None
            return index
    return None


def mapping_row(p, project, sid):
    g = next(g for g in p["groups"] if sid in g["shot_ids"])
    mapping = current_mapping(p, project, g["id"])
    return next(r for r in mapping["shots"] if r["shot_id"] == sid) if mapping else None


def current_frame(p, project, sid):
    item, row = selected(p, project, sid), mapping_row(p, project, sid)
    if item and item["source"]["kind"] == "frame" and row and row["status"] == "matched":
        if any(resolve(project, c["path"]) == resolve(project, item["path"]) and c["sha256"] == item["sha256"]
               and c["time"] == item["source"].get("time") for c in row["candidates"]):
            return item
    return None


def select_image(p, project, data):
    sid = data["shot_id"]
    s = shot(p, sid)
    path = image_path(project, data["path"])
    source = data.get("source", {})
    require(source.get("kind") in ("frame", "generated", "edited", "provided", "illustration"), "image provenance required")
    require(isinstance(data.get("reason"), str) and data["reason"].strip(), "selection reason required")
    if source["kind"] == "frame":
        row = mapping_row(p, project, sid)
        require(row and row["status"] == "matched", "select only from current matched candidates")
        require(any(resolve(project, c["path"]) == path and c["sha256"] == sha(path)
                    and c["time"] == source.get("time") for c in row["candidates"]), "selected frame/time not in matching candidates")
    if source["kind"] in ("generated", "edited"):
        task = p.get("tasks", {}).get(source.get("request_id"), {})
        require(task.get("kind") == "image" and task.get("target_id") == sid and task.get("status") == "SUCCESS", "successful image task for this shot required")
        require(any(resolve(project, f) == path and h == sha(path) for f, h in zip(task.get("outputs", []), task.get("output_hashes", []))), "image is not an unchanged task output")
    board = s.setdefault("board", {})
    if board.get("selected"):
        board.setdefault("history", []).append(copy.deepcopy(board["selected"]))
    if board.get("omission"):
        board.setdefault("omission_history", []).append(board.pop("omission"))
    board["selected"] = {"path": os.path.relpath(path, Path(project).resolve().parent), "sha256": sha(path),
                         "source": copy.deepcopy(source), "reason": data["reason"]}
    # Selection does not imply visual approval. Prior reviews remain bound to their images.


def omit_image(p, project, data):
    s = shot(p, data["shot_id"])
    require(data.get("reason") and data.get("context_evidence") and data.get("preserves_story") is True,
            "omission needs narrative/context justification")
    require(not s.get("intent", {}).get("critical_result") and not s.get("intent", {}).get("narrative_turn")
            and not any(c.get("critical") for c in s.get("state_changes", [])), "critical story state needs an image")
    b = s.setdefault("board", {})
    if b.get("selected"):
        b.setdefault("history", []).append(b.pop("selected"))
    b["omission"] = dict(reason=data["reason"], context_evidence=data["context_evidence"],
                         context=omission_context(p, project, s["id"]))


def restore_image(p, project, data):
    b = shot(p, data["shot_id"]).get("board", {})
    require(type(data.get("history_index")) is int and 0 <= data["history_index"] < len(b.get("history", [])), "existing history index required")
    item = copy.deepcopy(b["history"][data["history_index"]])
    require(sha(image_path(project, item["path"])) == item["sha256"], "historical image changed")
    if b.get("selected"):
        b["history"].append(copy.deepcopy(b["selected"]))
    b["selected"] = item
    b.pop("omission", None)


def record_review(p, project, data):
    sid = data["shot_id"]
    item = selected(p, project, sid)
    require(item and data.get("image_sha256") == item["sha256"], "review needs selected unchanged image")
    require(data.get("fingerprint") == review_fingerprint(p, project, sid), "review context changed; inspect current neighbors")
    checks = data.get("checks", {})
    require(set(checks) == CHECKS and all(v in ("PASS", "FAIL", "uncertain") for v in checks.values()), "all image checks required")
    require(data.get("observation") and data.get("expected"), "review needs actual visible observation and script expectation")
    for field in ("problems", "uncertainties"):
        require(isinstance(data.get(field, []), list) and all(isinstance(x, str) and x.strip() for x in data.get(field, [])), "problems and uncertainties must be lists of concrete statements")
    verdict = "FAIL" if "FAIL" in checks.values() else ("uncertain" if "uncertain" in checks.values() else "PASS")
    if verdict == "FAIL":
        require(data.get("problems"), "FAIL requires concrete problems")
    if verdict == "PASS":
        from requirements import contexts
        requirement = contexts(p).get(sid)
        require(not requirement or requirement["ready"], "provisional requirements cannot PASS")
        require(not data.get("problems") and not data.get("uncertainties"), "unresolved evidence cannot PASS")
        require(item["source"]["kind"] != "illustration", "illustrative demo cannot claim production acceptance")
        require(all(selected(p, project, n) or omitted(p, project, n) for n in neighbors(p, sid)), "continuity needs neighboring images or justified omissions")
    r = copy.deepcopy(data)
    r["verdict"] = verdict
    p.setdefault("board_reviews", []).append(r)
    return verdict


def repair(p, project, data):
    operations = data["operations"]
    require(operations and len({o["shot_id"] for o in operations}) == len(operations), "unique nonempty repair targets required")
    paid = False
    groups = set()
    for op in operations:
        sid, action = op["shot_id"], op["action"]
        require(action in ("rematch", "edit_image", "generate_image", "regenerate_group") and op.get("reason"), "explicit repair action and reason required")
        shot(p, sid)
        if action == "rematch":
            continue
        r, m = current_review(p, project, sid), mapping_row(p, project, sid)
        require((r and r["verdict"] == "FAIL") or (m and m["status"] == "absent" and not omitted(p, project, sid)), "paid repair requires confirmed failure or missing required image")
        require(not r or r["verdict"] != "PASS", "preserve passing images")
        if action == "edit_image":
            require(selected(p, project, sid), "editing requires existing selected image")
        if action == "regenerate_group":
            require(op.get("why_not_image_repair"), "explain why individual image repair is unsuitable")
            groups.add(next(g["id"] for g in p["groups"] if sid in g["shot_ids"]))
        paid = True
    if paid:
        require(p.get("repair_round", 0) < p.get("config", {}).get("max_repair_rounds", 3), "repair round limit reached; retain best images")
        p["repair_round"] = p.get("repair_round", 0) + 1
        for gid in groups:
            g = group(p, gid)
            g["version"] += 1
            g["repair_round"] = p["repair_round"]
    p.setdefault("repairs", []).append({"round": p.get("repair_round", 0), "operations": copy.deepcopy(operations),
                                       "groups": sorted(groups), "recheck": sorted({n for o in operations for n in [o["shot_id"]] + neighbors(p, o["shot_id"])})})


@verified_read
def render(p, project, out):
    validate(p, project)
    if p.get("config", {}).get("workflow") == "video_evidence" or "aggregation" in p:
        return render_aggregation(p, project, out)
    out = Path(out).resolve()
    # A reused old video delivery folder must not silently leak legacy deliverables.
    allowed = {".md"} | IMAGE_SUFFIXES
    require(not out.exists() or all(f.suffix.lower() in allowed for f in out.rglob("*") if f.is_file()),
            "choose a clean storyboard delivery folder; old videos/internal records are present")
    expected = {"分镜说明.md"}
    for s in p["shots"]:
        item = selected(p, project, s["id"])
        if item and not omitted(p, project, s["id"]):
            expected.add("images/" + s["id"] + "-" + item["sha256"][:12] + Path(item["path"]).suffix.lower())
    require(not out.exists() or all(f.relative_to(out).as_posix() in expected for f in out.rglob("*") if f.is_file()),
            "choose a new delivery folder to preserve previous image versions")
    out.mkdir(parents=True, exist_ok=True)
    def esc(value):
        text = html.escape(str(value), quote=False).replace("\\", "\\\\")
        for c in "|`*[]_":
            text = text.replace(c, "\\" + c)
        return " ".join(text.splitlines())
    reviews = {s["id"]: current_review(p, project, s["id"]) for s in p["shots"]}
    passed = sum(bool(r and r["verdict"] == "PASS") for r in reviews.values())
    skipped = sum(bool(omitted(p, project, s["id"])) for s in p["shots"])
    total = sum(s["duration"] for s in p["shots"])
    lines = [f"# {esc(p['title'])}", "", f"共 {len(p['shots'])} 个镜头，计划总时长 {total:g} 秒。已检查通过 {passed} 镜；无需单独配图 {skipped} 镜。", ""]
    if passed + skipped != len(p["shots"]):
        lines += ["当前还有图片需要补齐或检查，具体见各镜头。", ""]
    notes = []
    for s in p["shots"]:
        sid = s["id"]
        lines += [f"## {esc(sid)} · 计划 {s['duration']:g} 秒", "", esc(s["script"]), ""]
        omission = omitted(p, project, sid)
        item = selected(p, project, sid)
        if omission:
            lines += ["无需单独配图：" + esc(omission["reason"]), ""]
        elif item:
            path = image_path(project, item["path"])
            dest = out / "images" / (sid + "-" + item["sha256"][:12] + path.suffix.lower())
            dest.parent.mkdir(exist_ok=True)
            if path != dest:
                shutil.copy2(path, dest)
            r = reviews[sid]
            state = {"PASS": "已检查通过", "FAIL": "待修正", "uncertain": "待确认"}.get((r or {}).get("verdict"), "未验证")
            if item["source"]["kind"] == "illustration":
                state = "构图示意，非模型生成 · 未验证"
            lines += [f"![{esc(sid)} 分镜图](<{dest.as_posix()}>)", "", state, ""]
            if r:
                for problem in r.get("problems", []) + r.get("uncertainties", []):
                    notes.append(f"{sid}：{problem}")
        else:
            lines += ["待补图" if not s.get("board", {}).get("selected") else "图片已变化或缺失，待重新检查", ""]
    if notes:
        lines += ["## 需要留意", ""] + ["- " + esc(x) for x in dict.fromkeys(notes)] + [""]
    path = out / "分镜说明.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def thumbnail(source, destination, sid, label, warning=""):
    """Local preview/card with a baked-in shot caption; no HTML or image API."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    fonts = [Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font_path = next((f for f in fonts if f.is_file()), None)
    font = ImageFont.truetype(str(font_path), 14) if font_path else ImageFont.load_default()
    card = Image.new("RGB", (240, 168), "#edf0f4")
    if source:
        with Image.open(source) as im:
            preview = ImageOps.contain(im.convert("RGB"), (240, 135))
            card.paste(preview, ((240-preview.width)//2, (135-preview.height)//2))
    draw = ImageDraw.Draw(card)
    if not source:
        draw.text((120, 65), label, fill="#485566", font=font, anchor="mm")
    draw.rectangle((0, 135, 239, 167), fill="white")
    draw.text((120, 151), sid + (" · " + warning if warning else ""), fill="#8b2222" if warning else "#253044", font=font, anchor="mm")
    destination.parent.mkdir(parents=True, exist_ok=True)
    card.save(destination)


def seconds(value, suggested=False):
    if value is None:
        return "待确定"
    from decimal import Decimal
    return format(Decimal(str(value)).normalize(), 'f') + " 秒" + ("（建议）" if suggested else "")


@verified_read
def render_aggregation(p, project, out):
    from planner import current_aggregation
    proposal = current_aggregation(p, project)
    groups = proposal["groups"] if proposal else p["groups"]
    decisions = {d["shot_id"]: d for d in proposal["decisions"]} if proposal else {}
    chosen = {}
    for s in p["shots"]:
        sid = s["id"]
        if decisions.get(sid, {}).get("mode") == "ai_fill":
            continue
        if decisions.get(sid, {}).get("mapping_status") == "absent":
            continue
        item = current_frame(p, project, sid)
        historical = False
        if not item:
            # Best retained older frame can be shown, but never carries current acceptance.
            board = s.get("board", {})
            for old in [board.get("selected")] + list(reversed(board.get("history", []))):
                if not old or old["source"].get("kind") != "frame":
                    continue
                path = resolve(project, old["path"])
                if not path.is_file() or sha(path) != old["sha256"]:
                    continue
                if any(row["shot_id"] == sid and any(resolve(project, c["path"]) == path and c["sha256"] == old["sha256"]
                       and c["time"] == old["source"].get("time") for c in row.get("candidates", []))
                       for m in p.get("board_mappings", []) for row in m["shots"]):
                    item, historical = old, True
                    break
        if item:
            chosen[sid] = (item, historical)
    out = Path(out).resolve()
    names = {sid: "images/" + sid + "-" + item["sha256"][:12] + Path(item["path"]).suffix.lower()
             for sid, (item, _) in chosen.items()}
    thumbnails = {s["id"]: "images/thumb-" + s["id"] + "-" + digest([decisions.get(s["id"]), chosen.get(s["id"])])[:12] + ".png"
                  for s in p["shots"] if decisions.get(s["id"], {}).get("mode") != "ai_fill"}
    expected = {"分镜说明.md", *names.values(), *thumbnails.values()}
    require(not out.exists() or all(f.relative_to(out).as_posix() in expected for f in out.rglob("*") if f.is_file()),
            "choose a new delivery folder to preserve previous files and exclude internal records")
    out.mkdir(parents=True, exist_ok=True)
    def esc(value):
        text = html.escape(str(value), quote=False).replace("\\", "\\\\")
        for char in "|`*[]_#":
            text = text.replace(char, "\\" + char)
        return " ".join(text.splitlines())
    lines = ["# " + esc(p["title"]), "", f"共 {len(p['shots'])} 镜。", "",
             "“可推导生成”仅表示建议省去独立参考图，脚本镜头仍保留；不表示已生成或已验证。", ""]
    if p.get("config", {}).get("video_source") == "imported":
        lines += ["时长采用脚本计划值，每组不超过15秒；建议值单独标注。对白不作逐字或口型同步检查。", ""]
    if not proposal:
        lines += ["聚合建议尚未生成或依据已变化，以下按视频来源分组展示，需检查。", ""]
    elif not proposal["feasible"]:
        lines += ["聚合尚未完成；P 编号仅为待分组占位，不代表已符合15秒上限。", ""]
    from previs import review_current
    reviews = {g["id"]: review_current(p, project, g["id"]) for g in p["groups"]}
    lines += ["## 分组结果", "", "| 分组编号 | 镜头顺序 | 总时长 | 简短分组理由 |", "| --- | --- | --- | --- |"]
    for g in groups:
        total = seconds(g.get('planned_duration')) if proposal and proposal['feasible'] else '待规划'
        if proposal and proposal['feasible'] and g.get('duration_has_suggestion'):
            total += '（含建议值）'
        lines.append(f"| {esc(g['id'])} | {' → '.join(esc(sid) for sid in g['shot_ids'])} | {total} | {esc(g.get('reason', '视频来源分组，待确认聚合。'))} |")
    lines += ["", "## 逐镜审查与取舍", "", "| 分组 | 原镜号 | 镜头时长 | 脚本描述 | 小分镜图 | 检验结果 | 图片处理 | 推导依据镜号 | 问题或修改建议 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for g in groups:
        for sid in g["shot_ids"]:
            s, decision = shot(p, sid), decisions.get(sid, {})
            source_group = next(x for x in p["groups"] if sid in x["shot_ids"])
            review = reviews[source_group["id"]]
            issues = [i for i in (review or {}).get("issues", []) if sid in i["shot_ids"]]
            code = decision.get("status")
            status = {"anchor_reviewed": "检验通过", "ai_fill_suggested_unverified": "检验通过",
                      "absent_fill_suggested_unverified": "视频漏镜", "missing_required": "必要漏镜，需补生成",
                      "mismatch": "该镜需重新生成"}.get(code, "待检查")
            # Legacy group-only reviews remain conservative and cannot imply per-shot PASS.
            if p.get("config", {}).get("video_source") != "imported" and review and review["verdict"] == "FAIL" and issues:
                status = "需要重新生成"
            if decision.get("review_verdict") == "absent" and code == "pending":
                status = "视频漏镜；推导待检查"
            reason = decision.get("reason", "当前证据不足或已失效，需补查。")
            if issues:
                reason += "；" + "；".join(f"{i['time_range']} 秒：{i['problem']}；建议：{i['fix']}" for i in issues)
            treatment, basis, label = "暂不省图", "—", "待检查"
            if decision.get("mode") == "ai_fill":
                treatment, label = "建议省图，未验证", "可推导生成"
                bracket = decision["bracket"]
                basis = f"{bracket['before']} + {bracket['after']}"
                reason += "；建议省图，未验证"
            elif code == "anchor_reviewed":
                treatment = "保留图"
            elif code == "missing_required":
                label = "必要漏镜"
            source = None
            historical = False
            if sid in chosen:
                item, historical = chosen[sid]
                source = image_path(project, item["path"])
                dest = out / names[sid]
                dest.parent.mkdir(exist_ok=True)
                if source != dest:
                    shutil.copy2(source, dest)
            if decision.get("mode") == "ai_fill":
                picture = "可推导生成"
            else:
                thumb = out / thumbnails[sid]
                thumbnail(source, thumb, sid, label, "历史抽帧 · 待检查" if historical else ("需重新生成" if status in ("该镜需重新生成", "需要重新生成") else ""))
                picture = f"![{esc(sid)} · {esc(label if source is None else status)}](<{thumbnails[sid]}>)"
                if source:
                    picture = f"[{picture}](<{names[sid]}>)"
            timing = seconds(s.get('duration'), s.get('duration_source', {}).get('kind') == 'inference')
            if s.get('duration') is not None and not s.get('duration_source') and p.get('config', {}).get('video_source') == 'imported':
                timing += '（来源待确认）'
            if s.get('duration', 0) and s['duration'] > 15 and p.get('config', {}).get('video_source') == 'imported':
                reason += '；单镜超过15秒，需拆分或调整计划时长。'
            lines.append(f"| {esc(g['id'])} | {esc(sid)} | {timing} | {esc(s['script'])} | {picture} | {status} | {treatment} | {esc(basis)} | {esc(reason)} |")
    for summary in (proposal or {}).get("missing_summary", []):
        if summary["regenerate"]:
            source_group = group(p, summary["source_group_id"])
            _, video = current_video(p, project, source_group)
            name = f"{source_group['id']}（{video.name}）" if video else source_group["id"]
            lines += ["", f"建议重新生成视频 {esc(name)}，原因是必要漏镜达到阈值。"]
    lines += ["", "重新生成仅为建议，本流程不调用 API；待检查先补证据。", ""]
    path = out / "分镜说明.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=("map", "select", "restore", "omit", "review", "repair", "context", "render"))
    ap.add_argument("project")
    ap.add_argument("input", help="JSON path, shot ID for context, or directory for render")
    args = ap.parse_args()
    with locked(args.project):
        p = read(args.project)
        validate(p, args.project)
        if args.command == "render":
            print(render(p, args.project, args.input))
        elif args.command == "context":
            from requirements import contexts
            item = selected(p, args.project, args.input)
            print(json.dumps({"fingerprint": review_fingerprint(p, args.project, args.input), "image_sha256": item["sha256"] if item else None,
                              "requirements": contexts(p).get(args.input)}, ensure_ascii=False))
        else:
            fn = {"map": record_mapping_batch, "select": select_image, "restore": restore_image, "omit": omit_image,
                  "review": record_review, "repair": repair}[args.command]
            fn(p, args.project, read(args.input))
            save(args.project, p)
            print("Saved internal storyboard state.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, StopIteration) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
