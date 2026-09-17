param([Parameter(Mandatory=$true)][string]$JobFile)
$ErrorActionPreference = 'Stop'
$jobData = Get-Content -LiteralPath $JobFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($jobData.action -eq 'query') {
    & $jobData.skill_script -Action query -TaskId $jobData.task_id
    exit
}
# Reuse the installed skill's graph builder, exact node map, coin-key check and APIs.
# Dot-source its offline inspect entry only; no server call here.
. $jobData.skill_script -Action inspect | Out-Null
$request = $jobData.request
if ($request.workflow_id -ne $workflowId -or $request.instance_type -ne 'plus') { throw 'Unexpected workflow or mode.' }
$PromptText = $request.prompt
$PromptFile = ''
$AssetImages = @($request.assets | ForEach-Object { $_.path })
$DurationSeconds = [double]$request.duration_seconds
$durationProvided = $true
$Seed = -1
$inputData = Get-Inputs
foreach ($asset in $request.assets) {
    if ((Get-FileHash -LiteralPath $asset.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) {
        throw 'Asset changed before upload.'
    }
}
function Test-RepairGraph($candidate) {
    Assert-NodeMap $candidate
    $aspect = [string]$candidate.'115'.inputs.aspect_ratio
    if (($aspect -split ' ')[0] -ne $request.aspect_ratio) { throw 'Requested aspect ratio differs from fixed workflow; do not alter or crop.' }
    if ($candidate.'115'.class_type -ne 'ResolutionSelector' -or
        $candidate.'136'.inputs.width[0] -ne '115' -or $candidate.'136'.inputs.height[0] -ne '115' -or
        $candidate.'136'.inputs.length[0] -ne '131' -or $candidate.'131'.class_type -ne 'ComfyMathExpression' -or
        $candidate.'131'.inputs.'values.a'[0] -ne '132' -or
        $candidate.'131'.inputs.expression -ne 'max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17') {
        throw 'Duration/resolution wiring changed; inspect workflow before submitting.'
    }
    if ([double]::IsNaN($DurationSeconds) -or [double]::IsInfinity($DurationSeconds) -or $DurationSeconds -le 0) {
        throw 'Invalid full-script duration.'
    }
}
$source = Get-Content -LiteralPath $exportPath -Raw -Encoding UTF8 | ConvertFrom-Json
Test-RepairGraph $source
if ($jobData.action -eq 'prepare') {
    $prepared = New-DynamicGraph $source $inputData.prompt @($inputData.paths | ForEach-Object { [IO.Path]::GetFileName($_) })
    @{prepared=$true; submitted=$false; durationSeconds=$prepared['132']['inputs']['value']; aspectRatio=$request.aspect_ratio} |
        ConvertTo-Json -Compress
    exit
}
if ($jobData.action -ne 'submit' -or -not $env:RH_WORKFLOW_API_KEY) { throw 'Authorized coin-billed submission needs RH_WORKFLOW_API_KEY.' }
$key = Get-Key
Assert-CoinKey $key
$source = Get-ServerGraph $key
Test-RepairGraph $source
$filenames = @()
foreach ($path in $inputData.paths) {
    $response = Invoke-RestMethod -Method Post -Uri 'https://www.runninghub.cn/openapi/v2/media/upload/binary' `
        -Headers @{Authorization="Bearer $key"} -Form @{file=(Get-Item -LiteralPath $path)} -TimeoutSec 120
    if ($response.code -ne 0 -or -not $response.data.fileName) { throw 'Image upload failed.' }
    $filenames += $response.data.fileName
}
$dynamic = New-DynamicGraph $source $inputData.prompt $filenames
$body = @{apiKey=$key; workflowId=$workflowId; workflow=($dynamic | ConvertTo-Json -Depth 100 -Compress); instanceType='plus'}
# The Python caller has already persisted the request and reserved its single allowance.
# No retries, retainSeconds, saved-workflow edits, or undocumented API parameters.
$response = Invoke-RestMethod -Method Post -Uri 'https://www.runninghub.cn/task/openapi/create' `
    -Headers @{Authorization="Bearer $key"} -ContentType 'application/json' `
    -Body ($body | ConvertTo-Json -Depth 6 -Compress) -TimeoutSec 60
if ($response.code -ne 0 -or -not $response.data.taskId) { throw 'Create outcome unknown; inspect original task.' }
@{taskId=[string]$response.data.taskId} | ConvertTo-Json -Compress
