"""Publish accepted image judgments with every original and a local thumbnail."""
from __future__ import annotations
import html
from pathlib import Path
import shutil
from evidence_runtime import verified_read
from previs import require, resolve, digest

CHECKS = {'identity', 'scene', 'props', 'composition', 'key_state', 'continuity', 'cleanliness'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}


def image_path(project, value):
    path = resolve(project, value)
    require(path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES, "existing storyboard image required")
    # Verify file contents as well as the extension; never publish a video as an image.
    from PIL import Image
    with Image.open(path) as im:
        im.verify()
    return path


def current_image(p, project, sid):
    from storyboard_inputs import current_image as provided_image
    return provided_image(p, project, sid)


def thumbnail(source, destination, sid, label, warning=""):
    """Local preview/card with a baked-in shot caption; no HTML or image API."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    fonts = [Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font_path = next((f for f in fonts if f.is_file()), None)
    font = ImageFont.truetype(str(font_path), 14) if font_path else ImageFont.load_default()
    card = Image.new("RGB", (240, 168), "#edf0f4")
    if source:
        with Image.open(source) as im:
            preview = ImageOps.contain(ImageOps.exif_transpose(im).convert("RGB"), (240, 135))
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


def delivery_note(decision, review, sid, issues):
    def join(parts):
        cleaned = (' '.join(str(part).split()).replace('待检查', '需补证据').strip('；。 ')
                   for part in parts if part)
        return '；'.join(dict.fromkeys(part for part in cleaned if part))
    row = next((r for r in (review or {}).get('shot_reviews', []) if r['shot_id'] == sid), {})
    if issues:
        parts = [join([i['problem'], i['fix']]) for i in issues]
        if row.get('verdict') == 'uncertain': parts.append(row.get('followup'))
        return join(parts)
    if row.get('verdict') == 'uncertain': return join([row.get('reason'), row.get('followup')])
    return join([row.get('reason'), decision.get('reason')]) or '缺少当前有效审查，需核对本镜。'


def delivery_escape(value):
    text = html.escape(str(value), quote=False).replace("\\", "\\\\")
    for char in "|`*[]_#":
        text = text.replace(char, "\\" + char)
    return " ".join(text.splitlines())


def delivery_row(p, shot, decision, groups, review):
    sid = shot['id']
    group = decision.get('group_id') or next((g['id'] for g in groups
            if isinstance(g.get('shot_ids'), list) and sid in g['shot_ids']), '—')
    issues = [i for i in (review or {}).get('issues', []) if sid in i['shot_ids']]
    code = decision.get('status')
    status = {'anchor_reviewed': '检验通过', 'ai_fill_suggested_unverified': '检验通过',
              'mismatch': '分镜图不符合'}.get(code, '—')
    reason = '符合脚本' if status == '检验通过' else delivery_note(decision, review, sid, issues)
    treatment, basis, label = '暂不省图', '—', '暂无有效画面'
    if decision.get('mode') == 'ai_fill':
        treatment, label = '建议省图，未验证', '可推导生成'
        bracket = decision['bracket']
        basis = f"{bracket['before']} + {bracket['after']}"
    elif code == 'anchor_reviewed':
        treatment = '保留图'
    timing = seconds(shot.get('duration'), shot.get('duration_source', {}).get('kind') == 'inference')
    cells = [delivery_escape(group), delivery_escape(sid), timing, delivery_escape(shot['script']), None,
             status, treatment, delivery_escape(basis), delivery_escape(reason)]
    return cells, label


@verified_read
def render_aggregation(p, project, out):
    from planner import current_aggregation
    proposal = current_aggregation(p, project)
    from repair_cycle import current_decision
    repair_decisions = [current_decision(p, project, g['id']) for g in p['groups']
                        if g['id'] in p.get('repair_decisions', {})]
    from grouping import has_input_groups, parse_input_groups
    groups = proposal["groups"] if proposal else (parse_input_groups(p['input_shot_groups'], [s['id'] for s in p['shots']])
                                                if has_input_groups(p) else p["groups"])
    decisions = {d["shot_id"]: d for d in proposal["decisions"]} if proposal else {}
    chosen = {}
    for s in p["shots"]:
        sid = s["id"]
        item = current_image(p, project, sid)
        if item:
            chosen[sid] = (item, False)
    out = Path(out).resolve()
    names = {sid: "images/" + sid + "-" + item["sha256"][:12] + Path(item["path"]).suffix.lower()
             for sid, (item, _) in chosen.items()}
    thumbnails = {s["id"]: "images/thumb-" + s["id"] + "-" + digest([decisions.get(s["id"]), chosen.get(s["id"])])[:12] + ".png"
                  for s in p["shots"]}
    expected = {"分镜说明.md", *names.values(), *thumbnails.values()}
    require(not out.exists() or all(f.relative_to(out).as_posix() in expected for f in out.rglob("*") if f.is_file()),
            "choose a new delivery folder to preserve previous files and exclude internal records")
    out.mkdir(parents=True, exist_ok=True)
    esc = delivery_escape
    lines = ['# ' + esc(p['title']), '', f"共 {len(p['shots'])} 镜。", '',
             '全部输入原图均展示并链接保存。省图仅建议减少生成参考图，未经生成验证，脚本镜头仍保留。', '',
             '时长采用脚本计划值，每组4–15秒；建议值单独标注。对白不作逐字或口型同步检查。', '']
    if not proposal:
        label = '用户输入分组' if has_input_groups(p) else '整批图片'
        lines += [f"聚合建议尚未生成或依据已变化，以下按{label}展示，需检查。", ""]
    elif not proposal["feasible"]:
        if proposal.get("grouping_mode") == "input":
            lines += ["输入分组存在冲突，原分组保留；受影响镜头暂不批准省图。", ""]
            lines += ["分组冲突：" + esc("；".join(proposal["limitations"][:-1])), ""]
        else:
            lines += ["聚合尚未完成；P 编号仅为待分组占位，不代表已符合4–15秒及剧情边界要求。", ""]
    from previs import review_current
    reviews = {g["id"]: review_current(p, project, g["id"]) for g in p["groups"]}
    lines += ["## 逐镜审查与取舍", "", "| 分组 | 原镜号 | 镜头时长 | 脚本描述 | 小分镜图 | 检验结果 | 图片处理 | 推导依据镜号 | 问题或修改建议 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    # Always emit original script order once, even for malformed supplied groups.
    for s in p["shots"]:
        sid = s["id"]
        decision = decisions.get(sid, {})
        source_group = next(x for x in p["groups"] if sid in x["shot_ids"])
        review = reviews[source_group["id"]]
        code = decision.get("status")
        cells, label = delivery_row(p, s, decision, groups, review)
        status = cells[5]
        source = None
        historical = False
        if sid in chosen:
            item, historical = chosen[sid]
            source = image_path(project, item["path"])
            dest = out / names[sid]
            dest.parent.mkdir(exist_ok=True)
            if source != dest:
                shutil.copy2(source, dest)
        thumb = out / thumbnails[sid]
        thumbnail(source, thumb, sid, label, '需修改分镜图' if code == 'mismatch' else '')
        picture = f"![{esc(sid)} · {esc(label if source is None else status)}](<{thumbnails[sid]}>)"
        if source:
            picture = f"[{picture}](<{names[sid]}>)"
        cells[4] = picture
        lines.append('| ' + ' | '.join(cells) + ' |')
    for decision in repair_decisions:
        if decision['triggered']:
            reasons = {'critical': '已确认关键剧情错误', 'severe_visual_damage': '严重画面损坏遮挡必要内容',
                       'cumulative': '普通明确错误涉及至少两镜且占整批至少20%'}
            lines += ['', f"整批达到新视频提示词导出阈值：{reasons[decision['trigger']]}。"]
    lines += ['', '未达阈值不代表全部图片通过；待核查项需放大原图或澄清后再判断。', '']
    path = out / "分镜说明.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)
