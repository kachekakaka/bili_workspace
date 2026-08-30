[CmdletBinding()]
param(
    [ValidateSet('Create', 'Record')]
    [string]$Action = 'Create',
    [string]$WorkspaceRoot = '',
    [string]$TestRoot = '',
    [string]$RunId = '',
    [string]$RunRoot = '',
    [Parameter(Mandatory = $true)]
    [string]$TestId,
    [ValidateSet('passed', 'failed', 'blocked', 'inconclusive', 'not_run')]
    [string]$Status = 'inconclusive',
    [int]$ExitCode = -1,
    [string]$Message = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($TestId -ne 'T-DOCKER') {
    throw 'new-test-run.ps1 只承接 T-DOCKER 手工验证'
}

$ProjectId = 'bili_workspace'
$RunMarkerName = '.bili-workspace-docker-run.json'
$DefaultWorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) { $WorkspaceRoot = $DefaultWorkspaceRoot }
$WorkspaceRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot)

function Test-IsWithin([string]$Path, [string]$Parent) {
    $candidate = [System.IO.Path]::GetFullPath($Path).TrimEnd([char[]]'\/')
    $container = [System.IO.Path]::GetFullPath($Parent).TrimEnd([char[]]'\/')
    if ($candidate.Equals($container, [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
    return $candidate.StartsWith(
        $container + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

function Assert-ExternalRoot([string]$Candidate, [string]$Workspace) {
    if ((Test-IsWithin $Candidate $Workspace) -or (Test-IsWithin $Workspace $Candidate)) {
        throw "Docker 验证根与仓库不得相同或互相包含: $Candidate / $Workspace"
    }
}

function Assert-NotReparsePoint([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "$Label 不能是符号链接或重解析点: $Path"
    }
}

function Write-JsonAtomically([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = Join-Path $parent ('.' + [System.IO.Path]::GetFileName($Path) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
        $json = ($Value | ConvertTo-Json -Depth 4) + "`n"
        [System.IO.File]::WriteAllText($temporary, $json, $utf8NoBom)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
}

function Read-JsonObject([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label 不存在: $Path" }
    Assert-NotReparsePoint $Path $Label
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "无法读取 ${Label}: $Path" }
}

function Assert-Property([object]$Object, [string]$Name, [object]$Expected) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $property.Value -ne $Expected) {
        throw "Docker 验证运行标记字段不匹配: $Name"
    }
}

function Assert-DockerRun([string]$Candidate) {
    $run = [System.IO.Path]::GetFullPath($Candidate)
    if (-not (Test-Path -LiteralPath $run -PathType Container)) {
        throw "Docker 验证运行目录不存在: $run"
    }
    Assert-NotReparsePoint $run 'Docker 验证运行目录'
    $marker = Read-JsonObject (Join-Path $run $RunMarkerName) 'Docker 验证运行标记'
    $testRoot = [System.IO.Path]::GetFullPath([string]$marker.test_root)
    Assert-ExternalRoot $testRoot $WorkspaceRoot
    Assert-NotReparsePoint $testRoot 'Docker 验证根'
    if (-not ([System.IO.Directory]::GetParent($run).FullName.Equals($testRoot, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw 'Docker 验证运行目录必须是验证根的直接子目录'
    }
    Assert-Property $marker 'kind' 'bili-workspace-docker-validation'
    Assert-Property $marker 'project_id' $ProjectId
    Assert-Property $marker 'workspace_root' $WorkspaceRoot
    Assert-Property $marker 'test_root' $testRoot
    Assert-Property $marker 'run_root' $run
    Assert-Property $marker 'run_id' ([System.IO.Path]::GetFileName($run))
    foreach ($directory in @('config', 'userdata', 'downloads', 'results')) {
        $child = Join-Path $run $directory
        if (-not (Test-Path -LiteralPath $child -PathType Container)) {
            throw "Docker 验证运行子目录缺失: $child"
        }
        Assert-NotReparsePoint $child 'Docker 验证运行子目录'
    }
    return $run
}

if ($Action -eq 'Create') {
    if ([string]::IsNullOrWhiteSpace($TestRoot)) {
        $TestRoot = if ([string]::IsNullOrWhiteSpace($env:BILI_TEST_ROOT)) {
            Join-Path ([System.IO.Path]::GetTempPath()) 'bili_workspace_docker_test'
        }
        else {
            $env:BILI_TEST_ROOT
        }
    }
    $TestRoot = [System.IO.Path]::GetFullPath($TestRoot)
    Assert-ExternalRoot $TestRoot $WorkspaceRoot
    Assert-NotReparsePoint $WorkspaceRoot '仓库根目录'
    Assert-NotReparsePoint $TestRoot 'Docker 验证根'
    New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null

    if ([string]::IsNullOrWhiteSpace($RunId)) {
        $RunId = 'docker-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    }
    if ($RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$' -or $RunId -in @('.', '..')) {
        throw 'run-id 只能包含字母、数字、点、下划线和连字符，且长度不超过 96'
    }
    $RunRoot = Join-Path $TestRoot $RunId
    if (Test-Path -LiteralPath $RunRoot) { throw "Docker 验证运行目录已存在: $RunRoot" }
    New-Item -ItemType Directory -Path $RunRoot | Out-Null
    foreach ($directory in @('config', 'userdata', 'downloads', 'results')) {
        New-Item -ItemType Directory -Path (Join-Path $RunRoot $directory) | Out-Null
    }
    Write-JsonAtomically (Join-Path $RunRoot $RunMarkerName) ([ordered]@{
        kind = 'bili-workspace-docker-validation'
        project_id = $ProjectId
        workspace_root = $WorkspaceRoot
        test_root = $TestRoot
        run_root = $RunRoot
        run_id = $RunId
        created_at = [DateTime]::UtcNow.ToString('o')
    })
    Write-Output $RunRoot
    exit 0
}

if ([string]::IsNullOrWhiteSpace($RunRoot)) { throw 'Record 操作必须提供 -RunRoot' }
$validatedRun = Assert-DockerRun $RunRoot
$result = [ordered]@{
    kind = 'bili-workspace-docker-validation-result'
    project_id = $ProjectId
    status = $Status
    recorded_at = [DateTime]::UtcNow.ToString('o')
    workspace_root = $WorkspaceRoot
    run_root = $validatedRun
}
if ($ExitCode -ge 0) { $result['exit_code'] = $ExitCode }
if (-not [string]::IsNullOrWhiteSpace($Message)) { $result['message'] = $Message }
Write-JsonAtomically (Join-Path $validatedRun 'results\result.json') $result
