"""Resolve lightweight shot requirements; no visual inference or automatic approval."""
from __future__ import annotations
import copy
import json


def contexts(p, report=None):
    from validation import Report, text, text_array, shot_path
    own = report is None
    report = report if report is not None else Report()
    result, invalid, seen = {}, set(), set()
    # Preflight every shot before attempting inherited-state arithmetic.
    for i, s in enumerate(p["shots"]):
        r = s.get("requirements")
        if r is None:
            continue
        path = shot_path(s, i) + '.requirements'
        state_paths = tuple(shot_path(s, i) + '.' + name for name in
                            ('requirements', 'facts', 'state_changes', 'continuity_id'))
        if any(row['path'].startswith(state_paths) for row in report.errors):
            invalid.add(s['id'])
        start = len(report.errors)
        report.check(text(s.get('continuity_id')), shot_path(s, i) + '.continuity_id', 'continuity_id required for state inheritance')
        if not report.kind(r, dict, path):
            invalid.add(s['id'])
            continue
        report.check(type(r.get('version')) is int and r['version'] > 0, path + '.version', 'requirements version required')
        report.check(r.get('status') in ('ready', 'provisional'), path + '.status', 'requirements status required')
        report.check(text(r.get('purpose')), path + '.purpose', 'shot purpose required')
        parent = r.get('inherits_from')
        report.check(parent is None or text(parent), path + '.inherits_from', 'state parent must be an earlier shot with requirements')
        report.kind(r.get('entry_state', {}), dict, path + '.entry_state')
        k = r.get('keyframe', {})
        if report.kind(k, dict, path + '.keyframe'):
            report.check(k.get('phase') in ('entry', 'action', 'exit'), path + '.keyframe.phase', 'keyframe phase must be entry/action/exit')
            report.check(text(k.get('description')), path + '.keyframe.description', 'keyframe description required')
            report.kind(k.get('state', {}), dict, path + '.keyframe.state')
        for name in ('must_have', 'must_not_have'):
            report.check(text_array(r.get(name)), path + '.' + name, name + ' must be text array')
        if text_array(r.get('must_have')) and text_array(r.get('must_not_have')):
            report.check(not set(r['must_have']) & set(r['must_not_have']), path, 'opposing keyframe requirements')
        evidence = r.get('provenance', [])
        if report.kind(evidence, list, path + '.provenance'):
            report.check(bool(evidence), path + '.provenance', 'requirements provenance required')
            for j, item in enumerate(evidence):
                report.check(isinstance(item, dict) and item.get('field') and item.get('source') and
                             item.get('status') in ('observed', 'user_provided', 'script', 'assumed', 'unknown'),
                             f'{path}.provenance[{j}]', 'invalid requirements provenance')
        # State resolution can be called directly, without the project validator.
        for name in ('facts', 'state_changes'):
            rows = s.get(name, [])
            if not report.kind(rows, list, shot_path(s, i) + '.' + name):
                continue
            for j, row in enumerate(rows):
                where = f'{shot_path(s, i)}.{name}[{j}]'
                if not report.kind(row, dict, where):
                    continue
                report.check(text(row.get('entity')) and text(row.get('attribute')), where, 'state entity/attribute must be text')
                report.kind(row.get('source', {}), dict, where + '.source')
                required = ('before', 'after') if name == 'state_changes' else ('value',)
                for key in required:
                    report.check(key in row, where + '.' + key, 'state value required')
        if len(report.errors) != start:
            invalid.add(s['id'])
    for i, s in enumerate(p['shots']):
        if s.get('requirements') is None:
            continue
        sid = s['id']
        path = shot_path(s, i) + '.requirements'
        r = s['requirements']
        parent = r.get('inherits_from') if isinstance(r, dict) else None
        if isinstance(parent, str) and parent in seen and parent not in result:
            report.block(path + '.inherits_from', f'upstream state {parent} invalid; cannot compute entry/exit state')
        elif sid not in invalid:
            try:
                _resolve_one(p, s, result)
            except ValueError as exc:
                report.check(False, path, str(exc))
        seen.add(sid)
    if own:
        report.finish()
    return result


def _resolve_one(p, s, result):
    from previs import require
    r = s["requirements"]
    require(isinstance(r, dict), "requirements must be an object")
    require(type(r.get("version")) is int and r["version"] > 0, "requirements version required")
    require(r.get("status") in ("ready", "provisional"), "requirements status required")
    require(isinstance(r.get("purpose"), str) and r["purpose"].strip(), "shot purpose required")
    parent = r.get("inherits_from")
    require(parent is None or parent in result, "state parent must be an earlier shot with requirements")
    if parent:
        previous = next(x for x in p["shots"] if x["id"] == parent)
        require(previous["continuity_id"] == s["continuity_id"], "state parent must share continuity_id")
    ready = r["status"] == "ready" and (not parent or result[parent]["ready"])
    entry = copy.deepcopy(result[parent]["exit_state"] if parent else {})
    seeds = r.get("entry_state", {})
    require(isinstance(seeds, dict), "entry_state must be an object")
    for key, value in seeds.items():
        require(key not in entry or entry[key] == value, "entry state contradicts inherited state: " + key)
        entry[key] = copy.deepcopy(value)
    end = copy.deepcopy(entry)
    for change in s.get("state_changes", []):
        if not change.get("authorized"):
            continue
        require(change.get("source", {}).get("kind") == "script" and change["source"].get("ref"),
                "authorized state change needs script source")
        key = change["entity"] + "." + change["attribute"]
        require(key in end and end[key] == change["before"], "state change needs matching entry state: " + key)
        end[key] = copy.deepcopy(change["after"])
    for fact in s.get("facts", []):
        key = fact["entity"] + "." + fact["attribute"]
        baseline = end if fact.get("phase") == "after" else entry
        if key in baseline and fact.get("source", {}).get("kind") != "inference":
            if fact.get("status") == "known":
                require(baseline[key] == fact["value"], "state baseline conflict: requirements contradict source fact: " + key)
            elif fact.get("critical"):
                ready = False
    k = r.get("keyframe", {})
    require(isinstance(k, dict) and k.get("phase") in ("entry", "action", "exit"), "keyframe phase must be entry/action/exit")
    require(isinstance(k.get("description"), str) and k["description"].strip(), "keyframe description required")
    require(isinstance(k.get("state", {}), dict), "keyframe state must be an object")
    frame = copy.deepcopy(end if k["phase"] == "exit" else entry)
    for key, value in k.get("state", {}).items():
        require(k["phase"] == "action" or key not in frame or frame[key] == value,
                "keyframe contradicts selected phase: " + key)
        frame[key] = copy.deepcopy(value)
    for name in ("must_have", "must_not_have"):
        require(isinstance(r.get(name), list) and all(isinstance(x, str) and x.strip() for x in r[name]), name + " must be text array")
    require(not set(r["must_have"]) & set(r["must_not_have"]), "opposing keyframe requirements")
    evidence = r.get("provenance", [])
    require(isinstance(evidence, list) and evidence, "requirements provenance required")
    for item in evidence:
        require(isinstance(item, dict) and item.get("field") and item.get("source") and
                item.get("status") in ("observed", "user_provided", "script", "assumed", "unknown"), "invalid requirements provenance")
    result[s["id"]] = dict(version=r["version"], ready=bool(ready), purpose=r["purpose"],
        entry_state=entry, exit_state=end, keyframe=dict(phase=k["phase"], description=k["description"], state=frame),
        must_have=copy.deepcopy(r["must_have"]), must_not_have=copy.deepcopy(r["must_not_have"]))


def target_text(context, medium):
    """Keep the static target separate from the full video action."""
    from previs import require
    require(context["ready"], "shot requirements provisional; resolve design before generation")
    dump = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
    k = context["keyframe"]
    lines = ["镜头目的：" + context["purpose"],
             f"目标分镜静帧（{k['phase']}）：{k['description']}",
             "目标时刻状态（含画外持久状态；不要求全部入画）：" + dump(k["state"]),
             "仅目标静帧必须出现：" + dump(context["must_have"]),
             "仅目标静帧不得出现：" + dump(context["must_not_have"])]
    if medium == "video":
        lines += ["本镜起态：" + dump(context["entry_state"]), "本镜终态：" + dump(context["exit_state"]),
                  "完整动作依逐镜脚本执行；目标静帧不是默认首帧，不把终态提前。"]
    else:
        lines += ["只表现上述单一时刻；不把动作前后多个状态拼在同一张图中。"]
    return "\n".join(lines)
