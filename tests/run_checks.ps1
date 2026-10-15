param([switch]$ImagesOnly)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$root = Split-Path $PSScriptRoot -Parent
$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }

if ($ImagesOnly) {
    & $python -m unittest discover -s $PSScriptRoot -p test_script_input.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Script input tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_initial_overviews.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Initial overview tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_review_storyboards.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Unified storyboard entry tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_storyboard_overviews.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Storyboard overview tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_agent_context.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Agent context tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_review_batches.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Batch review tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_single_pass_review.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Single-pass review tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_storyboard_conclusions.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Concise conclusion tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_storyboard_images.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Storyboard image tests failed' }
    & $python -m unittest discover -s $PSScriptRoot -p test_prompt_work.py -v
} else {
    & $python -m unittest discover -s $PSScriptRoot -v
}
if ($LASTEXITCODE -ne 0) { throw 'Current workflow tests failed' }

$validator = Join-Path $env:USERPROFILE '.codex/skills/.system/skill-creator/scripts/quick_validate.py'
if (Test-Path $validator) {
    & $python $validator (Join-Path $root 'ai-storyboard-previs')
    if ($LASTEXITCODE -ne 0) { throw 'Skill validation failed' }
} else {
    Write-Warning 'skill-creator validator not found; unit tests completed without it.'
}
