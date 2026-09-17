"""Serial adapter to the installed fixed-workflow skill. Never retries create."""
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

import previs as core


class FixedWorkflow:
    def __init__(self, directory, skill=None):
        self.directory = Path(directory).resolve()
        self.skill = Path(skill or Path.home() / '.codex/skills/runninghub-fixed-workflow')

    def call(self, action, request=None, task_id=None):
        executable = shutil.which('pwsh')
        core.require(executable, 'PowerShell 7 (pwsh) required for fixed workflow')
        script = self.skill / 'scripts/workflow.ps1'
        core.require(script.is_file(), 'Installed runninghub-fixed-workflow missing')
        self.directory.mkdir(parents=True, exist_ok=True)
        job = self.directory / 'bridge-request.json'
        core.save(job, dict(action=action, request=request, task_id=task_id, skill_script=str(script.resolve())))
        # JSON file arguments prevent shell expansion of prompts, asset paths and credentials.
        response = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-File',
            str(Path(__file__).with_name('workflow_bridge.ps1')), '-JobFile', str(job)],
            capture_output=True, encoding='utf-8', timeout=1800)
        core.require(response.returncode == 0, 'Fixed workflow bridge failed; inspect saved task state, never retry create')
        return json.loads(response.stdout.lstrip('\ufeff'))

    def prepare(self, request):
        return self.call('prepare', request)

    def submit(self, request):
        return self.call('submit', request)

    def query(self, task_id):
        return self.call('query', task_id=task_id)

    def download(self, url, destination):
        core.require(url.startswith('https://'), 'HTTPS output URL required')
        temporary = destination.with_suffix('.part')
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as target:
            shutil.copyfileobj(response, target)
        temporary.replace(destination)
