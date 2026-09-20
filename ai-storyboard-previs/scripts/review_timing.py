"""Internal phase timing. Tool runtime and reviewer wall time are distinct."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import time

import previs as core


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def measured(rows, name):
    row = dict(phase=name, kind='tool', started_at=utc_now(), status='running')
    rows.append(row)
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        row.update(status='failed', error=str(exc))
        raise
    else:
        row['status'] = 'complete'
    finally:
        row.update(ended_at=utc_now(), elapsed_seconds=round(time.perf_counter()-start, 6))


def mark(path, action, phase, kind='reviewer_wall', reason=None, retry_of=None):
    """One internal journal per run; phase IDs distinguish concurrent reviewers."""
    from pathlib import Path
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with core.locked(path):
        core.require(action in ('start', 'end', 'fail'), 'unknown timing action')
        data = core.read(path) if path.exists() else dict(schema='review-timing-1', phases=[])
        core.require(data.get('schema') == 'review-timing-1', 'not a timing journal')
        found = next((r for r in data['phases'] if r['phase'] == phase), None)
        if action == 'start':
            core.require(found is None, 'phase already recorded; use a unique phase ID')
            parent = next((r for r in data['phases'] if r['phase'] == retry_of), None)
            core.require(not retry_of or (parent and parent['status'] == 'failed'), 'retry must reference a failed phase')
            row = dict(phase=phase, kind=kind, started_at=utc_now(), status='running')
            if retry_of:
                row['retry_of'] = retry_of
            data['phases'].append(row)
        else:
            core.require(found and found['status'] == 'running', 'no running phase to end')
            core.require(not retry_of, 'retry-of belongs on start')
            core.require(action != 'fail' or (isinstance(reason, str) and reason.strip()), 'failure reason required')
            found.update(ended_at=utc_now(), status='failed' if action == 'fail' else 'complete')
            if action == 'fail':
                found['error'] = reason
            found['elapsed_seconds'] = (datetime.fromisoformat(found['ended_at']) -
                                        datetime.fromisoformat(found['started_at'])).total_seconds()
        core.save(path, data)
    return data


def summary(data):
    complete = [r for r in data['phases'] if r.get('ended_at')]
    spans = sorted((datetime.fromisoformat(r['started_at']), datetime.fromisoformat(r['ended_at'])) for r in complete)
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return dict(phases=data['phases'],
                recorded_union_seconds=sum((end-start).total_seconds() for start, end in merged),
                recorded_span_seconds=(max(e for _, e in spans)-spans[0][0]).total_seconds() if spans else 0,
                incomplete_phase_ids=[r['phase'] for r in data['phases'] if not r.get('ended_at')],
                failed_phase_ids=[r['phase'] for r in data['phases'] if r.get('status') == 'failed'],
                retries=[dict(phase=r['phase'], retry_of=r['retry_of']) for r in data['phases'] if r.get('retry_of')],
                note='Union excludes unrecorded gaps; span includes them. Neither is model thinking time. '
                     'Overlapping tasks must not be summed as total wall time.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=('start', 'end', 'fail', 'report'))
    ap.add_argument('journal')
    ap.add_argument('phase', nargs='?')
    ap.add_argument('--kind', choices=('reviewer_wall', 'tool', 'wait'), default='reviewer_wall')
    ap.add_argument('--reason', help='required on fail; retain the actual cause')
    ap.add_argument('--retry-of', help='failed phase ID, on start only')
    a = ap.parse_args()
    if a.command == 'report':
        import json
        print(json.dumps(summary(core.read(a.journal)), ensure_ascii=False, indent=2))
    else:
        ap.error('phase required') if not a.phase else mark(a.journal, a.command, a.phase, a.kind, a.reason, a.retry_of)


if __name__ == '__main__':
    main()
