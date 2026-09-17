"""Extract evidence with actual PTS; normalize and assemble silent current videos."""
from __future__ import annotations
import argparse
import bisect
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from evidence_runtime import evidence_operation
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


def dense_ranges(value):
    """CLI parser; bounds against actual video duration are checked after probing."""
    try:
        span = [float(t) for t in value.split(":")]
        if len(span) != 2 or not all(math.isfinite(t) for t in span) or not 0 <= span[0] < span[1]:
            raise ValueError()
        return span
    except ValueError:
        raise argparse.ArgumentTypeError("dense-range must be START:END with 0 <= START < END")


def contact_sheets(frames, out, prefix="contact"):
    """Navigation only; keep the original full-resolution evidence for inspection."""
    from PIL import Image, ImageDraw, ImageOps
    result = []
    for offset in range(0, len(frames), 24):
        page = frames[offset:offset + 24]
        sheet = Image.new("RGB", (4 * 256, math.ceil(len(page) / 4) * 168), "#202020")
        draw = ImageDraw.Draw(sheet)
        for i, frame in enumerate(page):
            x, y = (i % 4) * 256, (i // 4) * 168
            with Image.open(frame["path"]) as original:
                thumb = ImageOps.contain(original.convert("RGB"), (248, 140))
                sheet.paste(thumb, (x + (256 - thumb.width) // 2, y))
            draw.text((x + 4, y + 144), f'{offset+i+1} | {frame["time"]:.3f}s | n={frame["frame_index"]}', fill="white")
        file = out / f"{prefix}_{offset // 24 + 1:03d}.jpg"
        sheet.save(file, quality=90)
        result.append({"path": str(file), "frame_paths": [f["path"] for f in page]})
    return result


def extract(path, out, planned=None, dense_step=None, ranges=None, base_evidence=None, full_contact_sheet=False):
    out = Path(out).resolve()
    require(not (out / "evidence.json").exists(), "choose a new evidence directory; preserve prior evidence manifests")
    # Check source and reused evidence again before publishing the new manifest.
    with evidence_operation():
        data = _extract(path, out, planned, dense_step, ranges, base_evidence, full_contact_sheet)
    save(out / "evidence.json", data)
    return data


def _extract(path, out, planned, dense_step, ranges, base_evidence, full_contact_sheet):
    path, out = Path(path).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    video_hash = sha(path)
    info = probe(path, frames=True)
    pts = [float(f["best_effort_timestamp_time"]) for f in info["frames"] if "best_effort_timestamp_time" in f]
    require(pts and pts == sorted(pts), "monotonic frame PTS required")
    start_pts = pts[0]
    times = [t - start_pts for t in pts]
    length = duration(info)
    requested = ranges or []
    require(isinstance(requested, (list, tuple)), "dense ranges must be a list")
    for span in requested:
        require(isinstance(span, (list, tuple)) and len(span) == 2
                and all(isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) for t in span)
                and 0 <= span[0] < span[1] <= length, "dense range must lie within source video duration")
    merged = []
    for a, b in sorted(requested):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    step = dense_step if dense_step is not None else (.2 if merged else None)
    if step is not None:
        require(isinstance(step, (int, float)) and not isinstance(step, bool)
                and math.isfinite(step) and step > 0, "dense-step must be finite and positive")
    sampled_ranges = merged or ([[0, length]] if step is not None else [])
    if sampled_ranges:
        require(sum(math.ceil((b-a)/step) + 1 for a, b in sampled_ranges) <= 3000,
                "dense sampling exceeds 3000 frames; narrow disputed ranges or increase dense-step")
    previous = {}
    base = read(Path(base_evidence).resolve()) if base_evidence else None
    if base:
        require(base.get("video_sha256") == video_hash, "base evidence video mismatch")
        require(abs(base["duration"] - length) < .001 and abs(base["pts_origin"] - start_pts) < .001,
                "base evidence timeline mismatch")
        for frame in base["frames"]:
            n = frame["frame_index"]
            require(type(n) is int and 0 <= n < len(pts) and n not in previous,
                    "invalid base frame index")
            require(abs(frame["pts"] - pts[n]) < .000001 and abs(frame["time"] - times[n]) < .000001,
                    "base frame timestamp mismatch")
            require(Path(frame["path"]).is_absolute() and sha(frame["path"]) == frame["sha256"],
                    "base evidence frame changed")
            previous[n] = frame
    # Scene scores are candidates only, never semantic hard-cut proof.
    if base is not None and "candidate_cuts" in base:
        candidates = base["candidate_cuts"]
        require(all(isinstance(t, (int, float)) and math.isfinite(t) and 0 <= t <= length for t in candidates),
                "invalid base cut candidates")
    else:
        scan = command([binary("ffmpeg"), "-hide_banner", "-i", path, "-vf", "select='gt(scene,0.30)',showinfo", "-an", "-f", "null", "-"])
        candidates = [float(x) - start_pts for x in re.findall(r"pts_time:([0-9.eE+-]+)", scan.stderr)]
    boundaries = sorted({0.0, length, *(c for c in candidates if 0 < c < length)})
    segments = [{"start": a, "end": b} for a, b in zip(boundaries, boundaries[1:])]
    targets = [0, length / 4, length / 2, 3 * length / 4, max(0, length - .05)]
    targets += [(s["start"] + s["end"]) / 2 for s in segments]
    spans = planned or []
    for span in spans:
        a, b = span["start"], span["end"]
        targets += [a, (a+b)/2, max(a, b-.05)]
        targets += [max(0, a-.05), min(length, a+.05)]
    targets += [max(0, c+d) for c in candidates for d in (-.08, 0, .08)]
    for a, b in sampled_ranges:
        targets += [a + n * step for n in range(math.ceil((b-a)/step))] + [b]
    indexes = set()
    for target in targets:
        pos = bisect.bisect_left(times, target)
        nearest = min((i for i in (pos-1, pos) if 0 <= i < len(times)), key=lambda i: abs(times[i]-target))
        indexes.add(nearest)
    indexes = sorted(indexes - previous.keys())
    selection = "+".join(f"eq(n\\,{i})" for i in indexes)
    # Fresh hash-specific evidence folder prevents stale frame files being mistaken for this extraction.
    folder = out / (video_hash[:16] + "-" + os.urandom(3).hex())
    folder.mkdir()
    if indexes:
        command([binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", path, "-vf", f"select={selection}", "-fps_mode", "passthrough", folder / "frame_%04d.png"])
    files = sorted(folder.glob("frame_*.png"))
    require(len(files) == len(indexes), "extracted frame/PTS count mismatch")
    frames = dict(previous)
    frames.update({n: {"path": str(f), "sha256": sha(f), "frame_index": n, "pts": pts[n], "time": times[n]} for f, n in zip(files, indexes)})
    data = {"video": str(path), "video_sha256": video_hash, "duration": length, "pts_origin": start_pts,
            "planned_spans": spans, "candidate_cuts": candidates, "candidate_segments": segments, "verified": False,
            "sampling": {"mode": "local_dense" if merged else ("full_dense" if step is not None else "sparse"),
                         "dense_step": step, "dense_ranges": sampled_ranges, "new_frames": len(indexes)},
            "limitations": ["Extraction is not visual inspection. Planned boundaries and scene candidates are not confirmed cuts.",
                            "Sparse or dense samples alone do not establish absence or verify actions, subtitles or transitions."],
            "frames": [frames[n] for n in sorted(frames)]}
    if base_evidence:
        data["base_evidence"] = {"path": str(Path(base_evidence).resolve()), "sha256": sha(base_evidence)}
    fresh = [frames[n] for n in indexes]
    data["new_frame_paths"] = [f["path"] for f in fresh]
    data["contact_sheet_scope"] = "new_frames" if base else "all_frames"
    data["contact_sheets"] = contact_sheets(fresh if base else data["frames"], out)
    data["full_contact_sheets"] = (contact_sheets(data["frames"], out, "full_contact")
                                   if base and full_contact_sheet else ([] if base else data["contact_sheets"]))
    # Optional navigation context, not a claim that these frames are matched or reviewed.
    context = {}
    if base and fresh:
        for a, b in sampled_ranges:
            before = [f for f in previous.values() if f["time"] < a]
            after = [f for f in previous.values() if f["time"] > b]
            for f in ([max(before, key=lambda f: f["time"])] if before else []) + ([min(after, key=lambda f: f["time"])] if after else []):
                context[f["frame_index"]] = f
    data["context_contact_sheets"] = contact_sheets([context[n] for n in sorted(context)], out, "context")
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
    ex.add_argument("--dense-range", type=dense_ranges, action="append", default=[], help="START:END seconds; repeat for disputed intervals (default step .2s)")
    ex.add_argument("--base-evidence", help="Reuse unchanged extracted frames; output must be a new directory")
    ex.add_argument("--full-contact-sheet", action="store_true", help="Also render all old and new frames for tracing")
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
                data = extract(args.video, args.output, planned, args.dense_step, args.dense_range, args.base_evidence, args.full_contact_sheet)
                if args.base_evidence and p.get("config", {}).get("video_source") == "imported":
                    from incremental import prepare
                    prepare(p, args.project, args.group, Path(args.output) / "evidence.json", Path(args.output) / "incremental_review.json")
                t["duration"] = data["duration"]
                save(args.project, p)
        else:
            data = extract(args.video, args.output, dense_step=args.dense_step, ranges=args.dense_range, base_evidence=args.base_evidence, full_contact_sheet=args.full_contact_sheet)
        print(json.dumps({"frames": len(data["frames"]), "new_frames": data["sampling"]["new_frames"],
                          "contact_sheet_scope": data["contact_sheet_scope"], "contact_sheets": data["contact_sheets"],
                          "incremental_review": str(Path(args.output).resolve() / "incremental_review.json") if args.base_evidence and args.project and p.get("config", {}).get("video_source") == "imported" else None,
                          "duration": data["duration"], "verified": False}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
