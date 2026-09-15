$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$root = Split-Path $PSScriptRoot -Parent
$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }

if (-not $env:FFMPEG) {
    $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($ffmpeg) { $env:FFMPEG = $ffmpeg.Source }
}
if (-not $env:FFPROBE) {
    $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
    if ($ffprobe) { $env:FFPROBE = $ffprobe.Source }
}
if (-not $env:FFMPEG -or -not $env:FFPROBE) {
    throw 'FFmpeg and FFprobe must be available in PATH or supplied through FFMPEG and FFPROBE.'
}

& $python -m unittest discover -s $PSScriptRoot -v
if ($LASTEXITCODE -ne 0) { throw 'Behavior or media tests failed' }

$validator = Join-Path $env:USERPROFILE '.codex/skills/.system/skill-creator/scripts/quick_validate.py'
if (Test-Path $validator) {
    & $python $validator (Join-Path $root 'ai-storyboard-previs')
    if ($LASTEXITCODE -ne 0) { throw 'Skill validation failed' }
} else {
    Write-Warning 'skill-creator validator not found; unit tests completed without it.'
}
