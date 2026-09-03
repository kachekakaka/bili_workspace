[CmdletBinding()]
param(
    [string]$DataRoot = '',

    [Parameter(Mandatory = $true)]
    [ValidateSet('discovery', 'download', 'browser', 'playback')]
    [string]$Impact,

    [ValidateSet('source', 'candidate')]
    [string]$Target = 'source',

    [string]$CandidateRecord = '',

    [string]$ToolProviderRecord = ''
)

$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'T-BILIBILI-LIVE 只支持 PATH 中的 PowerShell 7。'
}

if (
    -not [string]::IsNullOrWhiteSpace($DataRoot) -and
    [string]::IsNullOrWhiteSpace($env:BILI_TEST_ROOT)
) {
    throw '显式 DataRoot 模式必须设置绝对 BILI_TEST_ROOT；不会回退到系统临时目录。'
}

$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$pythonExecutable = Join-Path $workspaceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw 'T-BILIBILI-LIVE 要求项目 .venv；请先按 README 创建并安装项目依赖。'
}
$arguments = @(
    '-B',
    '-X',
    'utf8',
    '-m',
    'tools.bilibili_live',
    'run',
    '--impact',
    $Impact,
    '--target',
    $Target
)

if (-not [string]::IsNullOrWhiteSpace($DataRoot)) {
    $arguments += @('--data-root', $DataRoot)
}

if ($Target -eq 'candidate') {
    if ([string]::IsNullOrWhiteSpace($CandidateRecord)) {
        throw 'candidate 目标必须显式提供 -CandidateRecord。'
    }
    if (-not [string]::IsNullOrWhiteSpace($ToolProviderRecord)) {
        throw 'candidate 目标使用自身工具，不接受 -ToolProviderRecord。'
    }
    $arguments += @('--candidate-record', $CandidateRecord)
}
elseif (-not [string]::IsNullOrWhiteSpace($CandidateRecord)) {
    throw 'source 目标不接受 -CandidateRecord。'
}

if ($Target -eq 'source' -and -not [string]::IsNullOrWhiteSpace($ToolProviderRecord)) {
    if ($Impact -eq 'discovery') {
        throw 'discovery 影响域不接受 -ToolProviderRecord。'
    }
    $arguments += @('--tool-provider-record', $ToolProviderRecord)
}

Push-Location -LiteralPath $workspaceRoot
try {
    & $pythonExecutable @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
