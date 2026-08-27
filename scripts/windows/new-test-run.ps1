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

$ProjectId = 'bili_workspace'
$RootMarkerName = '.bili-workspace-test-root.json'
$RunMarkerName = '.bili-workspace-test-run.json'
$DefaultWorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ([string]::IsNullOrWhiteSpace($WorkspaceRoot)) { $WorkspaceRoot = $DefaultWorkspaceRoot }
$WorkspaceRoot = [System.IO.Path]::GetFullPath($WorkspaceRoot)

if ($TestId -notmatch '^T-[A-Z0-9]+(?:-[A-Z0-9]+)*$') {
    throw 'TestId 必须是形如 T-PROJECT 或 T-DOCKER 的 Registry ID'
}

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
        throw "测试根目录与仓库不得相同或互相包含: $Candidate / $Workspace"
    }
}

function Assert-NotReparsePoint([string]$Path, [string]$Label) {
    $current = [System.IO.Path]::GetFullPath($Path)
    while (-not [string]::IsNullOrWhiteSpace($current)) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "$Label 路径不得经过符号链接或重解析点: $current"
            }
        }
        $parent = [System.IO.Directory]::GetParent($current)
        if ($null -eq $parent) { break }
        $current = $parent.FullName
    }
}

function Write-JsonAtomically([string]$Path, [object]$Value) {
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = Join-Path $parent ('.' + [System.IO.Path]::GetFileName($Path) + '.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        $json = ($Value | ConvertTo-Json -Depth 8) + "`n"
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
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "无法读取 ${Label}: $Path" }
}

function Assert-Property([object]$Object, [string]$Name, [object]$Expected, [string]$Label) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $property.Value -ne $Expected) {
        throw "$Label 字段不匹配: $Name"
    }
}

function Assert-NonEmptyStringProperty([object]$Object, [string]$Name, [string]$Label) {
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
        throw "$Label 缺少有效字段: $Name"
    }
}

function Assert-RootMarker([string]$Root, [string]$Workspace) {
    $markerPath = Join-Path $Root $RootMarkerName
    Assert-NotReparsePoint $markerPath '测试根目录所有权标记'
    $marker = Read-JsonObject $markerPath '测试根目录所有权标记'
    Assert-Property $marker 'schema_version' 1 '测试根目录所有权标记'
    Assert-Property $marker 'kind' 'bili-workspace-test-root' '测试根目录所有权标记'
    Assert-Property $marker 'project_id' $ProjectId '测试根目录所有权标记'
    Assert-Property $marker 'workspace_root' $Workspace '测试根目录所有权标记'
    Assert-Property $marker 'test_root' $Root '测试根目录所有权标记'
    Assert-NonEmptyStringProperty $marker 'created_at' '测试根目录所有权标记'
}

function Assert-Run([string]$Candidate, [string]$Workspace, [string]$ExpectedTestId) {
    $run = [System.IO.Path]::GetFullPath($Candidate)
    Assert-NotReparsePoint $run '测试运行目录'
    if (-not (Test-Path -LiteralPath $run -PathType Container)) { throw "测试运行目录不存在: $run" }
    $markerPath = Join-Path $run $RunMarkerName
    Assert-NotReparsePoint $markerPath '测试运行所有权标记'
    $marker = Read-JsonObject $markerPath '测试运行所有权标记'
    $rootProperty = $marker.PSObject.Properties['test_root']
    if ($null -eq $rootProperty) { throw '测试运行所有权标记缺少 test_root' }
    $root = [System.IO.Path]::GetFullPath([string]$rootProperty.Value)
    Assert-ExternalRoot $root $Workspace
    Assert-NotReparsePoint $root '测试根目录'
    Assert-RootMarker $root $Workspace
    if (-not ([System.IO.Directory]::GetParent($run).FullName.Equals($root, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw '测试运行目录必须是测试根目录的直接子目录'
    }
    $schemaProperty = $marker.PSObject.Properties['schema_version']
    if ($null -eq $schemaProperty) { throw '测试运行所有权标记缺少 schema_version' }
    $schemaVersion = [int]$schemaProperty.Value
    if ($schemaVersion -eq 1) {
        if ($ExpectedTestId -ne 'T-PROJECT') {
            throw 'schema v1 测试运行只能按隐式 T-PROJECT 记录，不能绑定其他 TestId'
        }
    }
    elseif ($schemaVersion -eq 2) {
        Assert-NonEmptyStringProperty $marker 'test_id' '测试运行所有权标记'
        Assert-Property $marker 'test_id' $ExpectedTestId '测试运行所有权标记'
    }
    else {
        throw "测试运行所有权标记使用不支持的 schema_version: $schemaVersion"
    }
    Assert-Property $marker 'kind' 'bili-workspace-test-run' '测试运行所有权标记'
    Assert-Property $marker 'project_id' $ProjectId '测试运行所有权标记'
    Assert-Property $marker 'workspace_root' $Workspace '测试运行所有权标记'
    Assert-Property $marker 'test_root' $root '测试运行所有权标记'
    Assert-Property $marker 'run_root' $run '测试运行所有权标记'
    Assert-Property $marker 'run_id' ([System.IO.Path]::GetFileName($run)) '测试运行所有权标记'
    Assert-NonEmptyStringProperty $marker 'created_at' '测试运行所有权标记'
    if ([System.IO.Path]::GetFileName($run) -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$') {
        throw '测试运行目录名称不是有效 run-id'
    }
    foreach ($directory in @('runtime', 'media', 'config', 'userdata', 'downloads', 'tmp', 'pycache', 'home', 'results')) {
        $child = Join-Path $run $directory
        if (-not (Test-Path -LiteralPath $child -PathType Container)) {
            throw "测试运行子目录缺失: $child"
        }
        Assert-NotReparsePoint $child '测试运行子目录'
    }
    return [pscustomobject]@{ Path = $run; Marker = $marker; SchemaVersion = $schemaVersion }
}

if ($Action -eq 'Create') {
    if ([string]::IsNullOrWhiteSpace($TestRoot)) {
        if (-not [string]::IsNullOrWhiteSpace($env:BILI_TEST_ROOT)) {
            $TestRoot = $env:BILI_TEST_ROOT
        }
        else {
            $TestRoot = 'D:\Projects\python\bili_workspace_test'
        }
    }
    $TestRoot = [System.IO.Path]::GetFullPath($TestRoot)
    Assert-ExternalRoot $TestRoot $WorkspaceRoot
    Assert-NotReparsePoint $WorkspaceRoot '仓库根目录'
    Assert-NotReparsePoint $TestRoot '测试根目录'

    if (Test-Path -LiteralPath $TestRoot) {
        if (-not (Test-Path -LiteralPath $TestRoot -PathType Container)) {
            throw "测试根目录不是目录: $TestRoot"
        }
        Assert-RootMarker $TestRoot $WorkspaceRoot
    }
    else {
        New-Item -ItemType Directory -Path $TestRoot | Out-Null
        $rootMarker = [ordered]@{
            schema_version = 1
            kind = 'bili-workspace-test-root'
            project_id = $ProjectId
            workspace_root = $WorkspaceRoot
            test_root = $TestRoot
            created_at = [DateTime]::UtcNow.ToString('o')
        }
        Write-JsonAtomically (Join-Path $TestRoot $RootMarkerName) $rootMarker
    }

    if ([string]::IsNullOrWhiteSpace($RunId)) {
        $RunId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
    }
    if ($RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$' -or $RunId -in @('.', '..')) {
        throw 'run-id 只能包含 1–80 个 ASCII 字母、数字、点、下划线或连字符，且必须以字母或数字开头'
    }
    $RunRoot = Join-Path $TestRoot $RunId
    if (Test-Path -LiteralPath $RunRoot) { throw "测试运行目录已存在: $RunRoot" }
    New-Item -ItemType Directory -Path $RunRoot | Out-Null
    $runMarker = [ordered]@{
        schema_version = 2
        kind = 'bili-workspace-test-run'
        project_id = $ProjectId
        test_id = $TestId
        workspace_root = $WorkspaceRoot
        test_root = $TestRoot
        run_root = $RunRoot
        run_id = $RunId
        created_at = [DateTime]::UtcNow.ToString('o')
    }
    Write-JsonAtomically (Join-Path $RunRoot $RunMarkerName) $runMarker
    foreach ($directory in @('runtime', 'media', 'config', 'userdata', 'downloads', 'tmp', 'pycache', 'home', 'results')) {
        New-Item -ItemType Directory -Path (Join-Path $RunRoot $directory) | Out-Null
    }
    $initialResult = [ordered]@{
        schema_version = 2
        project_id = $ProjectId
        test_id = $TestId
        run_id = $RunId
        status = 'inconclusive'
        updated_at = [DateTime]::UtcNow.ToString('o')
        finalized_at = $null
        workspace_root = $WorkspaceRoot
        run_root = $RunRoot
        message = '验证已创建，但尚未写入最终结果。'
    }
    $initialResultPath = Join-Path $RunRoot 'results\result.json'
    Assert-NotReparsePoint $initialResultPath '测试结果文件'
    Write-JsonAtomically $initialResultPath $initialResult
    Write-Output $RunRoot
    exit 0
}

if ([string]::IsNullOrWhiteSpace($RunRoot)) { throw 'Record 操作必须提供 -RunRoot' }
$validated = Assert-Run $RunRoot $WorkspaceRoot $TestId
$finalizedAt = [DateTime]::UtcNow.ToString('o')
$result = [ordered]@{
    schema_version = $validated.SchemaVersion
    project_id = $ProjectId
    run_id = $validated.Marker.run_id
    status = $Status
    updated_at = $finalizedAt
    finalized_at = $finalizedAt
    workspace_root = $WorkspaceRoot
    run_root = $validated.Path
}
if ($validated.SchemaVersion -eq 2) { $result['test_id'] = $TestId }
if ($ExitCode -ge 0) { $result['exit_code'] = $ExitCode }
if (-not [string]::IsNullOrWhiteSpace($Message)) { $result['message'] = $Message }
$resultPath = Join-Path $validated.Path 'results\result.json'
Assert-NotReparsePoint $resultPath '测试结果文件'
Write-JsonAtomically $resultPath $result
