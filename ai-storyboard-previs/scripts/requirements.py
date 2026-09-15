"""Resolve lightweight shot requirements; no visual inference or automatic approval."""
from __future__ import annotations
import copy
import json


def contexts(p):
    from previs import require
    result = {}
    for s in p["shots"]:
        r = s.get("requirements")
        if r is None:  # Existing projects can be migrated without losing their media.
            continue
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
    return result


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
