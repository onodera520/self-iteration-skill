"""Durable RunningHub adapter. No automatic retry of a paid submission."""
from __future__ import annotations
import argparse
import copy
import importlib.util
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
from previs import (read, save, locked, validate, require, number, resolve, sha, digest,
                    group, shots, prompt, group_fingerprint, video_references)


def kit(path=None):
    root = Path(path) if path else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "skills/runninghub"
    client = root / "examples/python/client.py"
    require(client.is_file(), "RunningHub skill client not found; use --rh-skill")
    spec = importlib.util.spec_from_file_location("previs_runninghub_client", client)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, module.load_registry(root / "model-registry.public.json")


def prepare(p, project_path, request, module, registry):
    validate(p, project_path)
    require(isinstance(request.get("id"), str) and re.fullmatch(r"[\w-]+", request["id"]), "safe unique request ID required")
    require(request.get("kind") in ("image", "video"), "kind must be image or video")
    require(number(request.get("estimated_cost_cny")) and request["estimated_cost_cny"] >= 0, "nonnegative cost estimate required")
    if request["kind"] == "video":
        g = group(p, request["target_id"])
    else:
        g = next(g for g in p["groups"] if request["target_id"] in g["shot_ids"])
    require(request.get("version") == g["version"], "request version mismatch")
    endpoint = request["endpoint"]
    model = module.find_model(registry, endpoint)
    payload = copy.deepcopy(request.get("payload", {}))
    files = copy.deepcopy(request.get("local_files", {}))
    if request["kind"] == "image":
        from requirements import contexts, target_text
        requirement = contexts(p).get(request["target_id"])
        if requirement:
            params = {x["fieldKey"]: x for x in model.get("params", [])}
            field = request.get("prompt_field")
            require(field in params and params[field].get("type") == "STRING", "image requirements need registered prompt_field")
            require(field not in request.get("mute_fields", {}) and field not in files, "cannot overwrite image prompt")
            require(isinstance(payload.get(field, ""), str), "image prompt must be text")
            payload[field] = payload.get(field, "") + "\n" + target_text(requirement, "image")
    if request["kind"] == "video":
        require(not files, "video reference mapping cannot include extra local_files")
        refs = video_references(p, g)
        require(refs and all(refs), "video needs existing input images (assets or anchors)")
        params = {x["fieldKey"]: x for x in model.get("params", [])}
        field = request.get("reference_field")
        require(field in params and params[field].get("type") == "IMAGE", "reference_field must be a registered image input")
        files[field] = refs
        require(request.get("prompt_field") in params and params[request["prompt_field"]].get("type") == "STRING", "registered string prompt_field required")
        require(not {field, request["prompt_field"]}.intersection(request.get("mute_fields", {})), "mute_fields cannot overwrite prompt or references")
        payload[request["prompt_field"]] = prompt(p, g["id"])
    payload.update(request.get("mute_fields", {}))
    file_hashes = {}
    for key, value in files.items():
        values = value if isinstance(value, list) else [value]
        require(values and all(isinstance(x, str) and resolve(project_path, x).is_file() for x in values), "local media missing: " + key)
        file_hashes[key] = [sha(resolve(project_path, x)) for x in values]
        placeholders = ["asset://local/" + h for h in file_hashes[key]]
        payload[key] = placeholders if isinstance(value, list) else placeholders[0]
    module.validate_payload(model, payload)
    fp = group_fingerprint(p, project_path, g)
    request_fp = digest({"request": request, "payload": payload, "files": file_hashes, "group": fp})
    return {"payload": payload, "files": files, "fingerprint": request_fp, "group_fingerprint": fp}


def download(url, destination):
    require(urllib.parse.urlsplit(url).scheme in ("https", "http"), "output is not downloadable media")
    part = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as out:
        while chunk := response.read(1024 * 1024):
            out.write(chunk)
    require(part.stat().st_size > 0, "empty media output")
    os.replace(part, destination)


def finish_outputs(p, project_path, task, module, downloader=download):
    root = resolve(project_path, "outputs/" + task["id"])
    root.mkdir(parents=True, exist_ok=True)
    try:
        urls = module.extract_outputs(task["raw_response"])
        require(urls, "successful task has no media outputs")
        outputs, hashes = [], []
        for n, url in enumerate(urls):
            suffix = Path(urllib.parse.urlsplit(url).path).suffix.lower()
            allowed = (".mp4", ".webm", ".mov") if task["kind"] == "video" else (".png", ".jpg", ".jpeg", ".webp")
            if suffix not in allowed:
                suffix = ".mp4" if task["kind"] == "video" else ".png"
            path = root / (str(n) + suffix)
            existing = task.get("output_hashes", [])
            if not path.is_file() or n >= len(existing) or sha(path) != existing[n]:
                downloader(url, path)
            outputs.append(os.path.relpath(path, Path(project_path).resolve().parent))
            hashes.append(sha(path))
            task.update(outputs=outputs, output_hashes=hashes)
            save(project_path, p)
        task["status"] = "SUCCESS"
        task.pop("last_error", None)
    except Exception as exc:
        task["status"] = "download_error"
        task["last_error"] = type(exc).__name__
    save(project_path, p)
    return task["status"]


def resume(p, project_path, task, client, module, wait_seconds=300, interval=5, downloader=download):
    require(number(wait_seconds) and wait_seconds >= 0 and number(interval) and interval >= 0, "invalid poll timing")
    if task["status"] in ("SUCCESS", "download_error"):
        return finish_outputs(p, project_path, task, module, downloader)
    if task["status"] in ("FAILED", "CANCEL"):
        return task["status"]
    require(task.get("task_id"), "submission outcome unknown; recover original task ID with attach, do not resubmit")
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            raw = client._post_json(client.base_url + "/query", {"taskId": task["task_id"]}, retryable=False)
            task["raw_response"] = raw
            status = str(raw.get("status", "")).upper()
            if status not in ("CREATE", "QUEUED", "RUNNING", "SUCCESS", "FAILED", "CANCEL"):
                task["status"] = "query_error"
                task["last_error"] = "UnknownQueryResponse"
                save(project_path, p)
                return task["status"]
            task["status"] = status
            save(project_path, p)
            if status == "SUCCESS":
                return finish_outputs(p, project_path, task, module, downloader)
            if status in ("FAILED", "CANCEL"):
                return status
        except Exception as exc:
            task["last_error"] = type(exc).__name__
            task["status"] = "query_error"
            save(project_path, p)
            return task["status"]
        if time.monotonic() >= deadline:
            task["status"] = "timeout"
            save(project_path, p)
            return "timeout"
        time.sleep(min(interval, max(0, deadline - time.monotonic())))


def run(p, project_path, request, module, registry, client, wait_seconds=300, interval=5, downloader=download):
    prepared = prepare(p, project_path, request, module, registry)
    tasks = p.setdefault("tasks", {})
    if request["id"] in tasks:
        task = tasks[request["id"]]
        require(task["fingerprint"] == prepared["fingerprint"], "request changed; use a new version/request ID")
        return resume(p, project_path, task, client, module, wait_seconds, interval, downloader)
    c = p["config"]
    reserved = [t for t in tasks.values() if t.get("reserved")]
    require(len(reserved) < c.get("max_submissions", 0), "submission limit reached; no task submitted")
    if "budget_cny" in c:
        require(all(number(t.get("estimated_cost_cny")) for t in reserved),
                "existing reserved task has no CNY estimate; do not convert RH coins or ignore its cost")
        cost = sum(t["estimated_cost_cny"] for t in reserved) + request["estimated_cost_cny"]
        require(cost <= c["budget_cny"], "estimated budget reached; no task submitted")
    payload = prepared["payload"]
    # Upload errors precede paid submit and do not consume a generation reservation.
    for key, value in prepared["files"].items():
        values = value if isinstance(value, list) else [value]
        uploaded = [client.upload_file(resolve(project_path, v)) for v in values]
        payload[key] = uploaded if isinstance(value, list) else uploaded[0]
    module.validate_payload(module.find_model(registry, request["endpoint"]), payload)
    task = {k: request[k] for k in ("id", "kind", "target_id", "version", "endpoint", "estimated_cost_cny")}
    task.update(request=copy.deepcopy(request), fingerprint=prepared["fingerprint"], group_fingerprint=prepared["group_fingerprint"], payload=payload, status="submitting", reserved=True, outputs=[], output_hashes=[])
    tasks[task["id"]] = task
    save(project_path, p)
    try:
        task["task_id"] = client.submit(request["endpoint"], payload)
        task["status"] = "QUEUED"
    except Exception as exc:
        task["status"] = "submission_unknown"
        task["last_error"] = type(exc).__name__
        save(project_path, p)
        return task["status"]
    save(project_path, p)
    return resume(p, project_path, task, client, module, wait_seconds, interval, downloader)


def attach(p, request_id, task_id):
    t = p["tasks"][request_id]
    require(t["status"] in ("submitting", "submission_unknown") and not t.get("task_id"), "attach only for unknown original submission")
    require(isinstance(task_id, str) and task_id.strip(), "real task ID required")
    t.update(task_id=task_id, status="QUEUED")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=("dry-run", "run", "resume", "attach"))
    ap.add_argument("project")
    ap.add_argument("request")
    ap.add_argument("task_id", nargs="?")
    ap.add_argument("--rh-skill")
    ap.add_argument("--wait-seconds", type=float, default=300)
    args = ap.parse_args()
    with locked(args.project):
        p = read(args.project)
        validate(p, args.project)
        if args.cmd == "attach":
            attach(p, args.request, args.task_id)
            save(args.project, p)
            print("attached")
            return
        module, registry = kit(args.rh_skill)
        if args.cmd == "dry-run":
            data = prepare(p, args.project, read(args.request), module, registry)
            print("Validated; no upload/submission. Fingerprint: " + data["fingerprint"])
            return
        client = module.RunningHubClient(max_retries=1)
        if args.cmd == "run":
            status = run(p, args.project, read(args.request), module, registry, client, args.wait_seconds)
        else:
            status = resume(p, args.project, p["tasks"][args.request], client, module, args.wait_seconds)
        print(status)
        if status != "SUCCESS": sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # No API exception body or credentials in console logs.
        print("ERROR: " + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
