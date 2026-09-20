"""Local imported-video preparation; no visual judgments or paid operations."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time

import previs as core
import media
import repair_cycle


def check_files(entries):
    """Cheap, aggregate path checks before structured extraction or media probing."""
    rows, errors = [], []
    for label, value in entries:
        try:
            core.require(isinstance(value, (str, Path)) and bool(str(value).strip()), 'path required')
            path = Path(value).resolve()
            core.require(path.is_file(), 'file not found')
            core.require(path.stat().st_size > 0, 'empty file')
            with path.open('rb') as stream:
                stream.read(1)
            rows.append({'input': label, 'path': str(path)})
        except (ValueError, OSError) as exc:
            errors.append(f'{label}: {value!s}: {exc}')
    core.require(not errors, 'Input preflight failed:\n' + '\n'.join(errors))
    return rows


def prepare(project, gid, video, output, run_dir):
    project, video, output, run_dir = map(lambda x: Path(x).resolve(), (project, video, output, run_dir))
    core.require(not output.exists(), 'choose a new evidence directory')
    core.require(not run_dir.exists(), 'choose a new internal run directory')
    core.require(output != run_dir and output not in run_dir.parents and run_dir not in output.parents,
                 'evidence and run directories must be separate')
    report = {'status': 'running', 'stages': [], 'verified': False}
    started = time.perf_counter()

    def stage(name, action):
        row = {'name': name, 'status': 'running'}
        report['stages'].append(row)
        begin = time.perf_counter()
        try:
            result = action()
            row['status'] = 'complete'
            return result
        except Exception as exc:
            row.update(status='failed', error=str(exc))
            raise
        finally:
            row['seconds'] = round(time.perf_counter() - begin, 6)
            core.save(run_dir / 'PREPARE_REPORT.json', report)

    # One lock across the chain, including validation and all project writes.
    with core.locked(project):
        run_dir.mkdir(parents=True, exist_ok=False)
        try:
            p = core.read(project)

            def validate():
                result = core.validate(p, project)
                core.require(p.get('config', {}).get('video_source') == 'imported', 'imported video required')
                core.require(p.get('config', {}).get('workflow') == 'video_evidence', 'video_evidence workflow required')
                core.require(any(g['id'] == gid for g in p['groups']), f'unknown group: {gid}')
                core.require(not result.get('missing_assets'), f"missing_assets: {result.get('missing_assets')}")
                # Missing anchors are expected before the first imported-video extraction.
                return result

            stage('validate', validate)
            entries = [('video', video)] + [
                (f"asset[{a['id']}]", core.resolve(project, a['path']) if a.get('path') else '')
                for a in p['assets']]
            stage('paths', lambda: check_files(entries))

            def register():
                g = core.group(p, gid)
                previous, path = core.current_video(p, project, g)
                if previous and path == video:
                    return previous
                record = core.import_video(p, project, gid, video)
                core.validate(p, project)
                core.save(project, p)
                return record

            record = stage('import-video', register)

            def baseline():
                repair_cycle.baseline(p)
                core.validate(p, project)
                core.save(project, p)

            stage('baseline', baseline)

            def extract():
                core.validate(p, project)
                current, path = core.current_video(p, project, core.group(p, gid))
                core.require(current and path == video, 'video is not the current group output')
                data = media.extract(video, output)  # Existing sparse defaults, no planned timestamps.
                core.require(data['video_sha256'] == record['output_hashes'][0], 'video changed during preparation')
                current['duration'] = data['duration']
                core.save(project, p)
                return data

            data = stage('extract', extract)
            report.update(status='complete', evidence_file=str(output / 'evidence.json'),
                          video_sha256=record['output_hashes'][0], frames=len(data['frames']),
                          contact_sheets=len(data['contact_sheets']))
        except Exception as exc:
            report.update(status='failed', error=str(exc))
            raise
        finally:
            report['total_seconds'] = round(time.perf_counter() - started, 6)
            core.save(run_dir / 'PREPARE_REPORT.json', report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='command', required=True)
    preflight = commands.add_parser('preflight', help='Run before constructing PROJECT.json')
    preflight.add_argument('--script', required=True)
    preflight.add_argument('--video', required=True)
    preflight.add_argument('--asset', action='append', required=True)
    run = commands.add_parser('run')
    for name in ('project', 'group', 'video', 'output'):
        run.add_argument(name)
    run.add_argument('--run-dir', required=True)
    args = ap.parse_args()
    if args.command == 'preflight':
        result = {'inputs': check_files([('script', args.script), ('video', args.video)] +
                  [(f'asset[{n}]', path) for n, path in enumerate(args.asset, 1)]),
                  'scope': 'paths_only', 'verified': False}
    else:
        result = prepare(args.project, args.group, args.video, args.output, args.run_dir)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
