"""Extract evidence with actual PTS; normalize and assemble silent current videos."""
from __future__ import annotations
import argparse
import bisect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from previs import (read, save, locked, validate, require, resolve, sha, group, shots,
                    current_video, delivery_fingerprint)


def binary(name):
    value = os.environ.get(name.upper()) or shutil.which(name)
    require(value and Path(value).is_file(), f"{name} not found; set {name.upper()} or PATH")
    return str(value)


def command(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    require(result.returncode == 0, "media command failed: " + result.stderr[-1800:])
    return result


def probe(path, frames=False):
    args = [binary("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    if frames:
        args += ["-select_streams", "v:0", "-show_frames", "-show_entries", "frame=best_effort_timestamp_time"]
    args += [path]
    result = json.loads(command(args).stdout)
    require(any(s["codec_type"] == "video" for s in result["streams"]), "video stream required")
    return result


def duration(info):
    return float(info["format"]["duration"])


def extract(path, out, planned=None, dense_step=None):
    path, out = Path(path).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    info = probe(path, frames=True)
    pts = [float(f["best_effort_timestamp_time"]) for f in info["frames"] if "best_effort_timestamp_time" in f]
    require(pts and pts == sorted(pts), "monotonic frame PTS required")
    start_pts = pts[0]
    times = [t - start_pts for t in pts]
    length = duration(info)
    # Scene scores are candidates only, never semantic hard-cut proof.
    scan = command([binary("ffmpeg"), "-hide_banner", "-i", path, "-vf", "select='gt(scene,0.30)',showinfo", "-an", "-f", "null", "-"])
    candidates = [float(x) - start_pts for x in re.findall(r"pts_time:([0-9.eE+-]+)", scan.stderr)]
    targets = [0, length / 2, max(0, length - .05)]
    spans = planned or []
    for span in spans:
        a, b = span["start"], span["end"]
        targets += [a, (a+b)/2, max(a, b-.05)]
        targets += [max(0, a-.05), min(length, a+.05)]
    targets += [max(0, c+d) for c in candidates for d in (-.08, 0, .08)]
    if dense_step is not None:
        require(dense_step > 0, "dense-step must be positive")
        require(length / dense_step <= 3000, "dense sampling exceeds 3000 frames; inspect a shorter clip")
        targets += [n * dense_step for n in range(int(length/dense_step)+1)]
    indexes = set()
    for target in targets:
        pos = bisect.bisect_left(times, target)
        nearest = min((i for i in (pos-1, pos) if 0 <= i < len(times)), key=lambda i: abs(times[i]-target))
        indexes.add(nearest)
    indexes = sorted(indexes)
    selection = "+".join(f"eq(n\\,{i})" for i in indexes)
    # Fresh hash-specific evidence folder prevents stale frame files being mistaken for this extraction.
    folder = out / (sha(path)[:16] + "-" + os.urandom(3).hex())
    folder.mkdir()
    command([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", path, "-vf", f"select={selection}", "-fps_mode", "passthrough", folder / "frame_%04d.png"])
    files = sorted(folder.glob("frame_*.png"))
    require(len(files) == len(indexes), "extracted frame/PTS count mismatch")
    data = {"video": str(path), "video_sha256": sha(path), "duration": length, "pts_origin": start_pts,
            "planned_spans": spans, "candidate_cuts": candidates, "verified": False,
            "limitations": ["Extraction is not visual inspection. Planned boundaries and scene candidates are not confirmed cuts."],
            "frames": [{"path": str(f), "sha256": sha(f), "frame_index": n, "pts": pts[n], "time": times[n]} for f, n in zip(files, indexes)]}
    save(out / "evidence.json", data)
    return data


def assemble(p, project_path, output):
    validate(p, project_path)
    selected = []
    for g in p["groups"]:
        t, path = current_video(p, project_path, g)
        require(t is not None, "current successful video missing: " + g["id"])
        selected.append((g, t, path))
    output = Path(output).resolve()
    require(output not in [f for _, _, f in selected], "output cannot overwrite a source video")
    require(not output.exists(), "choose a new delivery output filename; preserve prior versions")
    output.parent.mkdir(parents=True, exist_ok=True)
    first = probe(selected[0][2])
    stream = next(s for s in first["streams"] if s["codec_type"] == "video")
    width, height = stream["width"], stream["height"]
    aspect = p.get("config", {}).get("aspect_ratio")
    if aspect:
        match = re.fullmatch(r"(\d+):(\d+)", aspect)
        require(match and int(match[1]) > 0 and int(match[2]) > 0, "aspect_ratio must be W:H")
        ratio = int(match[1]) / int(match[2])
        width = round(height * ratio)
    width, height = max(2, width//2*2), max(2, height//2*2)
    require(width <= 8192 and height <= 8192, "delivery dimensions too large")
    segments, offset = [], 0.0
    with tempfile.TemporaryDirectory(prefix="previs-", dir=output.parent) as tmp:
        tmp = Path(tmp)
        for n, (g, task, path) in enumerate(selected):
            part = tmp / f"{n:04d}.mp4"
            # Establish timing before scaling; some builds lose the EOF duration through scale.
            filters = f"setpts=PTS-STARTPTS,fps=fps=24:eof_action=pass,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
            command([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", path, "-map", "0:v:0", "-vf", filters, "-r", "24", "-fps_mode", "cfr", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", part])
            source_duration = duration(probe(path))
            task["duration"] = source_duration
            part_duration = duration(probe(part))
            segments.append({"group_id": g["id"], "version": g["version"], "start": offset, "duration": part_duration, "source_duration": source_duration, "source_sha256": sha(path)})
            offset += part_duration
        (tmp / "concat.txt").write_text("\n".join(f"file '{n:04d}.mp4'" for n in range(len(selected))), encoding="utf-8")
        staged = tmp / "delivery.mp4"
        command([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "1", "-i", tmp / "concat.txt", "-map", "0:v:0", "-an", "-c:v", "copy", "-movflags", "+faststart", staged])
        final = probe(staged)
        require(not any(s["codec_type"] == "audio" for s in final["streams"]), "delivery unexpectedly has audio")
        require(abs(duration(final) - offset) < .2, "assembled duration mismatch")
        os.replace(staged, output)
    previous = p.get("delivery")
    if previous:
        p.setdefault("delivery_history", []).append(previous)
    p["delivery"] = {"revision": (previous or {}).get("revision", 0)+1, "path": os.path.relpath(output, Path(project_path).resolve().parent), "sha256": sha(output), "fingerprint": delivery_fingerprint(p, project_path), "duration": duration(final), "silent": True, "segments": segments}
    return p["delivery"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract")
    ex.add_argument("video")
    ex.add_argument("output")
    ex.add_argument("--project")
    ex.add_argument("--group")
    ex.add_argument("--dense-step", type=float)
    ass = sub.add_parser("assemble")
    ass.add_argument("project")
    ass.add_argument("output")
    args = ap.parse_args()
    if args.cmd == "assemble":
        with locked(args.project):
            p = read(args.project)
            d = assemble(p, args.project, args.output)
            save(args.project, p)
            print(json.dumps(d, ensure_ascii=False))
    else:
        planned = []
        require(bool(args.project) == bool(args.group), "--project and --group must be supplied together")
        if args.project:
            with locked(args.project):
                p = read(args.project)
                validate(p, args.project)
                g = group(p, args.group)
                t, path = current_video(p, args.project, g)
                require(t and path == Path(args.video).resolve(), "video is not the current group output")
                start = 0.0
                planned_shots = [] if p.get("config", {}).get("video_source") == "imported" else shots(p, g)
                for s in planned_shots:
                    planned.append({"shot_id": s["id"], "start": start, "end": start+s["duration"]})
                    start += s["duration"]
                dense_step = args.dense_step
                if p.get("config", {}).get("video_source") == "imported" and dense_step is None:
                    dense_step = max(.5, t["duration"] / 2999)
                data = extract(args.video, args.output, planned, dense_step)
                t["duration"] = data["duration"]
                save(args.project, p)
        else:
            data = extract(args.video, args.output, dense_step=args.dense_step)
        print(json.dumps({"frames": len(data["frames"]), "duration": data["duration"], "verified": False}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
