"""Image-project validation, evidence-bound review and Markdown delivery."""
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
from evidence_runtime import sha, read_json, verified_read, memo_read


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read(path):
    return read_json(path)


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


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def group(p, gid):
    return next(g for g in p["groups"] if g["id"] == gid)


def shots(p, g):
    index = {s["id"]: s for s in p["shots"]}
    return [index[sid] for sid in g["shot_ids"]]


def validate(p, project_path):
    from validation import Report, text, text_array, sourced, shot_path, style_shape
    report = Report()
    check = report.check
    if not report.kind(p, dict, '$'):
        report.finish()
    check(p.get("schema_version") == 1, "schema_version", "schema_version must be 1")
    check(text(p.get("title")), "title", "title required")
    check(text(p.get("source_script")), "source_script", "source_script required")
    valid_collections = {}
    for kind in ("assets", "shots", "groups"):
        valid = report.kind(p.get(kind), list, kind)
        seen = set()
        for i, row in enumerate(p[kind] if valid else []):
            if not report.kind(row, dict, f'{kind}[{i}]'):
                valid = False
                continue
            rid = row.get('id')
            if not check(isinstance(rid, str) and re.fullmatch(r'[\w-]+', rid), f'{kind}[{i}].id', 'invalid IDs'):
                valid = False
            elif not check(rid not in seen, f'{kind}[{i}].id', 'duplicate ' + kind + ' ID'):
                valid = False
            else:
                seen.add(rid)
        valid_collections[kind] = valid
    asset_rows = [a for a in p.get('assets', []) if isinstance(a, dict)] if isinstance(p.get('assets'), list) else []
    shot_rows = [s for s in p.get('shots', []) if isinstance(s, dict)] if isinstance(p.get('shots'), list) else []
    group_rows = [g for g in p.get('groups', []) if isinstance(g, dict)] if isinstance(p.get('groups'), list) else []
    check(bool(shot_rows) and bool(group_rows), 'shots/groups', 'shots and groups required')
    assets = {a['id'] for a in asset_rows if isinstance(a.get('id'), str)}
    c = p.get('config', {})
    config_ok = report.kind(c, dict, 'config')
    if not config_ok:
        c = {}  # Diagnostic scope only; no project defaults are written.
    event_shots = [s for s in shot_rows if "event" in s]
    from grouping import has_input_groups
    check(has_input_groups(p) or not event_shots or len(event_shots) == len(shot_rows), 'shots.event', "event blocks must cover every shot when supplied")
    event_summaries = {}
    for s in event_shots:
        path = shot_path(s, shot_rows.index(s)) + '.event'
        event = s["event"]
        if not report.kind(event, dict, path):
            continue
        id_ok = check(isinstance(event.get('id'), str) and re.fullmatch(r'[\w-]+', event['id']), path + '.id', 'invalid event ID')
        summary_ok = check(text(event.get('summary')), path + '.summary', 'event summary required')
        check(sourced(event.get('source')), path + '.source', 'event source required')
        if id_ok and summary_ok:
            check(event['id'] not in event_summaries or event_summaries[event['id']] == event['summary'], path + '.summary', 'same event ID needs the same summary')
            event_summaries[event['id']] = event['summary']
    for i, a in enumerate(asset_rows):
        check(a.get("kind") in ("character", "scene", "prop"), f'assets[{i}].kind', "invalid asset kind")
        if a.get('path') is not None:
            check(text(a['path']), f'assets[{i}].path', 'asset path must be text')
    for i, s in enumerate(shot_rows):
        path = shot_path(s, i)
        if config_ok:
            check(number(s.get("duration")) and s["duration"] > 0, path + '.duration', "positive shot duration required")
        for key in ('script', 'scene_id', 'continuity_id', 'required_result'):
            check(text(s.get(key)), path + '.' + key, 'shot narrative fields required')
        if check(text_array(s.get('asset_ids', [])), path + '.asset_ids', 'asset_ids must be text array'):
            if valid_collections['assets']:
                check(set(s.get('asset_ids', [])) <= assets, path + '.asset_ids', 'unknown asset')
            else:
                report.block(path + '.asset_ids', 'asset IDs invalid; cannot resolve references')
        r = s.get("reference", {})
        if report.kind(r, dict, path + '.reference'):
            check(r.get('mode') in ('anchor', 'ai_fill'), path + '.reference.mode', 'invalid reference mode')
            check(r.get('role') in ('start', 'representative', 'end'), path + '.reference.role', 'invalid reference role')
            check(text(r.get('reason')), path + '.reference.reason', 'reference reason required')
            if r.get('path') is not None:
                check(text(r['path']), path + '.reference.path', 'reference path must be text')
    sequence_ok = valid_collections['shots'] and valid_collections['groups']
    for i, g in enumerate(group_rows):
        path = f'groups[{g.get("id", i)}]'
        sequence_ok = check(text_array(g.get('shot_ids')) and bool(g.get('shot_ids')), path + '.shot_ids', 'group shots must be nonempty text array') and sequence_ok
        check(type(g.get('version')) is int and g['version'] >= 1, path + '.version', 'group version and shots required')
    if sequence_ok:
        check([sid for g in group_rows for sid in g['shot_ids']] == [s['id'] for s in shot_rows], 'groups.shot_ids', 'groups must preserve every shot exactly once in source order')
    else:
        report.block('groups.shot_ids', 'invalid shot/group IDs or lists; cannot check source order')
    if config_ok:
        check(c.get('workflow') == 'storyboard_images', 'config.workflow', 'invalid workflow')
        check(c.get('video_input_mode', 'anchors') in ('assets', 'anchors'), 'config.video_input_mode', 'invalid video input mode')
    style_shape(p, report)
    from requirements import contexts
    from grouping import validate_metadata
    from planner import validate_facts, validate_ledger
    if valid_collections['shots'] and valid_collections['assets']:
        validate_facts(p, report=report, present_only=True)
    else:
        report.block('shots.facts', 'invalid shot/asset IDs; cannot resolve sourced facts')
    if valid_collections['shots']:
        contexts(p, report=report)
        validate_metadata(p, report=report)
        if valid_collections['assets']:
            validate_ledger(p, report)
    else:
        report.block('shots', 'invalid shot IDs/objects; cannot resolve states or narrative metadata')
    # No file checks, partial success, or mutation until all in-memory checks pass.
    report.finish()
    if c.get("video_input_mode") == "assets":
        used = {aid for s in p["shots"] for aid in s.get("asset_ids", [])}
        missing_assets = [a["id"] for a in p["assets"] if a["id"] in used and (not a.get("path") or not resolve(project_path, a["path"]).is_file())]
        return {"shots": len(p["shots"]), "groups": len(p["groups"]), "missing_assets": missing_assets}
    missing = [s['id'] for s in p['shots'] if s['reference']['mode'] == 'anchor'
               and (not s['reference'].get('path') or not resolve(project_path, s['reference']['path']).is_file())]
    return {"shots": len(p["shots"]), "groups": len(p["groups"]), "missing_anchors": missing}


@memo_read
def group_fingerprint(p, project_path, g):
    from requirements import contexts
    resolved = contexts(p)
    ss = copy.deepcopy(shots(p, g))
    for s in ss:
        s.pop("board", None)  # Only source images and accepted requirements bind the review.
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
    if "narrative_plan" in p:
        binding["narrative_plan"] = p["narrative_plan"]
    if p.get('config', {}).get('workflow') == 'storyboard_images':
        from storyboard_inputs import inputs
        binding['storyboard_images'] = inputs(p, project_path)
    return digest(binding)


def review_context(p, project_path, gid):
    from storyboard_inputs import enabled, context
    require(enabled(p), 'Only paired storyboard images are supported; prepare the image project first')
    return context(p, project_path, gid)


@verified_read
def review_current(p, project_path, gid):
    from storyboard_inputs import enabled, current_review
    return current_review(p, project_path, gid) if enabled(p) else None


def record_review(p, project_path, review):
    from storyboard_inputs import enabled, record_review as record_images
    require(enabled(p), 'Only paired storyboard images are supported')
    return record_images(p, project_path, review)


def render(p, project_path, out):
    from storyboard import render_aggregation
    return render_aggregation(p, project_path, out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('validate', 'context', 'render', 'review'):
        q = sub.add_parser(name)
        q.add_argument('project')
        if name == 'context': q.add_argument('group')
        if name == 'render': q.add_argument('output')
        if name == 'review': q.add_argument('review_file')
    args = ap.parse_args()
    with locked(args.project) if args.cmd == 'review' else contextlib.nullcontext():
        p = read(args.project)
        result = validate(p, args.project)
        if args.cmd == 'context': result = review_context(p, args.project, args.group)
        if args.cmd == 'render': result = render(p, args.project, args.output)
        if args.cmd == 'review':
            result = record_review(p, args.project, read(args.review_file))
            save(args.project, p)
        print(json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result)


if __name__ == '__main__':
    main()
