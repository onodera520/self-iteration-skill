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
from repair_readiness import diagnose


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


def intact(record):
    core.require(all(Path(f).is_file() and core.sha(Path(f)) == h for f, h in record['files'].items()),
                 'Immutable delivery changed')


def finish(project, profile, output, run_dir, stage='original', delivery_only=False,
           revision_reason=None, resume_from=None):
    project, output, run_dir = (Path(v).resolve() for v in (project, output, run_dir))
    core.require(stage in ('original', 'repaired'), 'Unknown finish stage')
    core.require(not run_dir.exists() and not project.is_relative_to(run_dir)
                 and not run_dir.is_relative_to(output) and not output.is_relative_to(run_dir),
                 'Use a fresh internal run directory separate from delivery and project')
    report = dict(schema='finish-review-2', project=str(project), stage=stage, profile_digest=core.digest(profile),
                  started_at=utc_now(), status='running', phases=[], decisions={},
                  delivery_only=delivery_only, revision_reason=revision_reason)
    # Acquire the project lock before creating any output. No nested CLI writers.
    with core.locked(project):
        run_dir.mkdir(parents=True)
        try:
            prior_run = None
            if resume_from:
                resume_from = Path(resume_from).resolve()
                prior_run = core.read(resume_from)
                core.require(prior_run.get('project') == str(project) and prior_run.get('stage') == stage
                             and prior_run.get('profile_digest') == core.digest(profile), 'Recovery must use the same project, stage and profile')
                report['resumed_from'] = str(resume_from)
            with measured(report['phases'], 'preflight'):
                with evidence_operation():
                    p = core.read(project)
                    core.require(p['config'].get('video_source') == 'imported', 'Imported video only')
                    core.validate(p, project)
                    for group in p['groups']:
                        r = core.review_current(p, project, group['id'])
                        core.require(r, 'Current review required: ' + group['id'])
                        diagnostics = diagnose(p, r)
                        if diagnostics.errors or diagnostics.blocked:
                            report['decisions'][group['id']] = dict(status='blocked', errors=diagnostics.errors,
                                                                   blocked=diagnostics.blocked,
                                                                   reason='repair_assessments incomplete')
                if report['decisions'] and not delivery_only:
                    report.update(status='preflight_blocked', next_action='Complete listed assessments and register the group review; rerun finish with a fresh run-dir and --resume-from this report. No delivery was frozen.')
                    return report
            with measured(report['phases'], 'planning'):
                with evidence_operation():
                    plan = planner.current_aggregation(p, project)
                    if not plan or plan.get('profile') != profile:
                        plan = planner.post_review_plan(p, project, profile)
                    if core.digest(p.get('aggregation')) != core.digest(plan):
                        planner.store_aggregation(p, project, plan)
                core.save(run_dir / 'AGGREGATION.json', plan)
            with measured(report['phases'], 'repair_decisions'):
                for group in p['groups']:
                    if group['id'] in report['decisions']:
                        p.get('repair_decisions', {}).pop(group['id'], None)
                        continue  # Explicit legacy delivery-only path, never a no-repair verdict.
                    try:
                        with evidence_operation():
                            candidate = copy.deepcopy(p)
                            decision = repair.decide(candidate, project, group['id'])
                        p = candidate
                        report['decisions'][group['id']] = dict(status='complete', decision=decision)
                    except ValueError as exc:
                        # Structural omissions were collected above. Integrity failures must not
                        # be downgraded to a legacy missing-field warning.
                        raise ValueError('Repair decision failed for ' + group['id'] + ': ' + str(exc)) from exc
                core.save(project, p)
                core.save(run_dir / 'REPAIR_DECISIONS.json', report['decisions'])
            with measured(report['phases'], 'delivery'):
                with evidence_operation():
                    candidate = copy.deepcopy(p)
                    previous = p.get('repair_deliveries', {}).get(stage)
                    if previous:
                        intact(previous)
                        if previous['aggregation_fingerprint'] != core.digest(plan):
                            core.require(isinstance(revision_reason, str) and revision_reason.strip(),
                                         'Immutable delivery belongs to an earlier aggregation; use --revision-reason and a new empty output directory')
                            candidate.setdefault('repair_delivery_history', []).append(dict(
                                stage=stage, record=copy.deepcopy(previous), revision_reason=revision_reason,
                                superseded_at=utc_now()))
                            del candidate['repair_deliveries'][stage]
                    pending = prior_run.get('pending_delivery') if prior_run else None
                    if pending and pending['base_digest'] == core.digest(p):
                        core.require(core.sha(Path(pending['path'])) == pending['sha256'], 'Pending delivery checkpoint changed')
                        checkpoint = core.read(pending['path'])
                        core.require(checkpoint['output'] == str(output) and checkpoint['stage'] == stage
                                     and checkpoint['revision_reason'] == revision_reason,
                                     'Resume staged delivery with the same output, stage and revision reason')
                        candidate.setdefault('repair_deliveries', {})[stage] = checkpoint['record']
                        intact(checkpoint['record'])
                        report['delivery_reused'] = True
                        report['delivery'] = checkpoint['record']['path']
                    else:
                        report['delivery'] = repair.snapshot(candidate, project, output, stage)
                    checkpoint_path = run_dir / 'PENDING_DELIVERY.json'
                    core.save(checkpoint_path, dict(record=candidate['repair_deliveries'][stage], output=str(output),
                                                    stage=stage, revision_reason=revision_reason))
                    report['pending_delivery'] = dict(path=str(checkpoint_path), sha256=core.sha(checkpoint_path),
                                                       base_digest=core.digest(p))
                # Persist the recovery pointer before validation; this is not a frozen delivery.
                core.save(run_dir / 'FINISH_REPORT.json', report)
            with measured(report['phases'], 'delivery_validation'):
                with evidence_operation():
                    core.require(planner.current_aggregation(candidate, project), 'Evidence changed before delivery validation')
                    if previous:
                        intact(previous)
                    report['validation'] = validate_delivery(candidate, stage)
                core.require(core.digest(core.read(project)) == core.digest(p), 'Project changed before delivery freeze')
                core.save(project, candidate)
            report['status'] = ('complete' if all(d['status'] == 'complete' for d in report['decisions'].values())
                                else 'delivery_complete_decision_blocked')
            report['next_action'] = ('Inspect the two tables and images once, then stop unless an authorized repair is due.'
                                     if report['status'] == 'complete' else
                                     'Legacy delivery only; repair decision blocked. Complete review then use --revision-reason with a new output directory.')
        except Exception as exc:
            report.update(status='failed', error=str(exc))
            raise
        finally:
            report['ended_at'] = utc_now()
            report['failed_phase'] = next((x['phase'] for x in report['phases'] if x['status'] == 'failed'), None)
            if report['status'] == 'failed':
                report['next_action'] = 'Fix the reported failure; use a fresh run-dir and --resume-from this report. Reuse staged output only with unchanged inputs; never rebind old evidence.'
            core.save(run_dir / 'FINISH_REPORT.json', report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project'); ap.add_argument('profile')
    ap.add_argument('--output', required=True)
    ap.add_argument('--run-dir', required=True, help='Fresh directory for internal reports/timing')
    ap.add_argument('--stage', choices=('original', 'repaired'), default='original')
    ap.add_argument('--delivery-only', action='store_true', help='explicit legacy path: allow missing repair assessments, report blocked')
    ap.add_argument('--revision-reason', help='preserve old frozen delivery and create a linked revision in a new output directory')
    ap.add_argument('--resume-from', help='previous FINISH_REPORT.json; reuse only verified current state')
    a = ap.parse_args()
    result = finish(a.project, core.read(a.profile), a.output, a.run_dir, a.stage,
                    a.delivery_only, a.revision_reason, a.resume_from)
    print(result['status'], result.get('delivery', 'no frozen delivery'))
    print(result['next_action'])
    raise SystemExit(0 if result['status'] == 'complete' else 2)


if __name__ == '__main__':
    main()
