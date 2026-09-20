"""Sequential post-review finish, with no visual judgments or paid submissions."""
from __future__ import annotations
import argparse
import copy
import re
from pathlib import Path
from PIL import Image

import previs as core
import planner
import repair_cycle as repair
from evidence_runtime import evidence_operation
from review_timing import measured, utc_now


def validate_delivery(p, stage):
    """Check immutable bytes, two tables, exact shot order, thumbnails and omission."""
    record = p['repair_deliveries'][stage]
    md = Path(record['path']).resolve()
    core.require(record['aggregation_fingerprint'] == core.digest(p['aggregation']), 'Delivery aggregation stale')
    core.require(all(Path(f).is_file() and core.sha(Path(f)) == h for f, h in record['files'].items()),
                 'Immutable delivery changed')
    text = md.read_text(encoding='utf-8')
    core.require(sum(line.startswith('| --- |') for line in text.splitlines()) == 2, 'Expected exactly two tables')
    rows = [re.split(r'(?<!\\)\|', line)[1:-1] for line in text.splitlines() if line.startswith('|')]
    rows = [r for r in rows if len(r) == 9 and r[1].strip() not in ('原镜号', '---')]
    core.require([r[1].strip() for r in rows] == [s['id'] for s in p['shots']], 'Delivery shot order/coverage changed')
    decisions = {d['shot_id']: d for d in p['aggregation']['decisions']}
    pictures = 0
    for row in rows:
        sid, picture = row[1].strip(), row[4].strip()
        if decisions[sid]['mode'] == 'ai_fill':
            core.require(picture == '可推导生成', 'ai_fill must not create an image/link')
            continue
        links = re.findall(r'\]\(<([^>]+)>\)', picture)
        core.require(links, 'Non-fill shot needs a local thumbnail')
        for i, link in enumerate(links):
            image = (md.parent / link).resolve()
            core.require(image.is_relative_to(md.parent) and str(image) in record['files'], 'Image outside immutable delivery')
            with Image.open(image) as img:
                if i == 0:
                    core.require(img.size == (240, 168), 'Unexpected thumbnail dimensions')
                img.verify()
        pictures += 1
    return dict(shot_count=len(rows), thumbnail_count=pictures, table_count=2,
                visual_review='existing evidence-bound review; no new visual approval')


def finish(project, profile, output, run_dir, stage='original'):
    project, output, run_dir = (Path(v).resolve() for v in (project, output, run_dir))
    core.require(stage in ('original', 'repaired'), 'Unknown finish stage')
    core.require(not run_dir.exists() and not project.is_relative_to(run_dir)
                 and not run_dir.is_relative_to(output) and not output.is_relative_to(run_dir),
                 'Use a fresh internal run directory separate from delivery and project')
    report = dict(schema='finish-review-1', started_at=utc_now(), status='running', phases=[], decisions={})
    # Acquire the project lock before creating any output. No nested CLI writers.
    with core.locked(project):
        run_dir.mkdir(parents=True)
        try:
            with measured(report['phases'], 'planning'):
                with evidence_operation():
                    p = core.read(project)
                    core.require(p['config'].get('video_source') == 'imported', 'Imported video only')
                    plan = planner.post_review_plan(p, project, profile)
                    if core.digest(p.get('aggregation')) != core.digest(plan):
                        planner.store_aggregation(p, project, plan)
                core.save(project, p)
                core.save(run_dir / 'AGGREGATION.json', plan)
            with measured(report['phases'], 'delivery'):
                with evidence_operation():
                    previous = p.get('repair_deliveries', {}).get(stage)
                    core.require(not previous or previous['aggregation_fingerprint'] == core.digest(plan),
                                 'Immutable delivery belongs to an earlier aggregation; preserve it and use an explicit project version')
                    report['delivery'] = repair.snapshot(p, project, output, stage)
                core.save(project, p)
            # Original report is safely saved before decision or any future paid action.
            with measured(report['phases'], 'repair_decisions'):
                for group in p['groups']:
                    try:
                        with evidence_operation():
                            candidate = copy.deepcopy(p)
                            decision = repair.decide(candidate, project, group['id'])
                        p = candidate
                        report['decisions'][group['id']] = dict(status='complete', decision=decision)
                    except ValueError as exc:
                        report['decisions'][group['id']] = dict(status='blocked', reason=str(exc))
                core.save(project, p)
                core.save(run_dir / 'REPAIR_DECISIONS.json', report['decisions'])
            with measured(report['phases'], 'delivery_validation'):
                with evidence_operation():
                    core.require(planner.current_aggregation(p, project), 'Evidence changed before delivery validation')
                    report['validation'] = validate_delivery(p, stage)
            report['status'] = ('complete' if all(d['status'] == 'complete' for d in report['decisions'].values())
                                else 'delivery_complete_decision_blocked')
        except Exception as exc:
            report.update(status='failed', error=str(exc))
            raise
        finally:
            report['ended_at'] = utc_now()
            core.save(run_dir / 'FINISH_REPORT.json', report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project'); ap.add_argument('profile')
    ap.add_argument('--output', required=True)
    ap.add_argument('--run-dir', required=True, help='Fresh directory for internal reports/timing')
    ap.add_argument('--stage', choices=('original', 'repaired'), default='original')
    a = ap.parse_args()
    result = finish(a.project, core.read(a.profile), a.output, a.run_dir, a.stage)
    print(result['status'], result['delivery'])
    raise SystemExit(0 if result['status'] == 'complete' else 2)


if __name__ == '__main__':
    main()
