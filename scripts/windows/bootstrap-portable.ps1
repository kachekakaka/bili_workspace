[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Quiet,
    [string]$VerificationRunRoot = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$ManifestPath = Join-Path $Root 'vendor\windows\runtime-manifest.json'
$RuntimeRoot = Join-Path $Root '.runtime'
$MediaRoot = $Root
$PythonRoot = Join-Path $RuntimeRoot 'python'
$StatePath = Join-Path $RuntimeRoot 'runtime-state.json'

function Write-Status([string]$Message) {
    if (-not $Quiet) { Write-Host $Message }
}

function Assert-MarkerProperty([object]$Marker, [string]$Name, [object]$Expected, [string]$Label) {
    $property = $Marker.PSObject.Properties[$Name]
    if ($null -eq $property -or $property.Value -ne $Expected) {
        throw "$Label 字段不匹配: $Name"
    }
}

function Assert-NonEmptyMarkerProperty([object]$Marker, [string]$Name, [string]$Label) {
    $property = $Marker.PSObject.Properties[$Name]
    if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
        throw "$Label 缺少有效字段: $Name"
    }
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

function Assert-NoReparsePoint([string]$Path, [string]$Label) {
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

function Assert-VerificationRunRoot([string]$Candidate) {
    $runRoot = [System.IO.Path]::GetFullPath($Candidate)
    if (-not (Test-Path -LiteralPath $runRoot -PathType Container)) {
        throw "验证运行目录不存在: $runRoot"
    }
    Assert-NoReparsePoint $runRoot '验证运行目录'
    $runMarkerPath = Join-Path $runRoot '.bili-workspace-test-run.json'
    if (-not (Test-Path -LiteralPath $runMarkerPath -PathType Leaf)) {
        throw "验证运行目录缺少所有权标记: $runMarkerPath"
    }
    Assert-NoReparsePoint $runMarkerPath '验证运行目录所有权标记'
    try { $runMarker = Get-Content -LiteralPath $runMarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "无法读取验证运行目录所有权标记: $runMarkerPath" }

    $testRootProperty = $runMarker.PSObject.Properties['test_root']
    if ($null -eq $testRootProperty) { throw '验证运行目录所有权标记缺少 test_root' }
    $testRoot = [System.IO.Path]::GetFullPath([string]$testRootProperty.Value)
    if ((Test-IsWithin $testRoot $Root) -or (Test-IsWithin $Root $testRoot)) {
        throw "测试根目录与仓库不得相同或互相包含: $testRoot / $Root"
    }
    $rootMarkerPath = Join-Path $testRoot '.bili-workspace-test-root.json'
    if (-not (Test-Path -LiteralPath $rootMarkerPath -PathType Leaf)) {
        throw "测试根目录缺少所有权标记: $rootMarkerPath"
    }
    Assert-NoReparsePoint $rootMarkerPath '测试根目录所有权标记'
    Assert-NoReparsePoint $testRoot '测试根目录'
    try { $rootMarker = Get-Content -LiteralPath $rootMarkerPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw "无法读取测试根目录所有权标记: $rootMarkerPath" }

    Assert-MarkerProperty $rootMarker 'schema_version' 1 '测试根目录所有权标记'
    Assert-MarkerProperty $rootMarker 'kind' 'bili-workspace-test-root' '测试根目录所有权标记'
    Assert-MarkerProperty $rootMarker 'project_id' 'bili_workspace' '测试根目录所有权标记'
    Assert-MarkerProperty $rootMarker 'workspace_root' $Root '测试根目录所有权标记'
    Assert-MarkerProperty $rootMarker 'test_root' $testRoot '测试根目录所有权标记'
    Assert-NonEmptyMarkerProperty $rootMarker 'created_at' '测试根目录所有权标记'
    if (-not ([System.IO.Directory]::GetParent($runRoot).FullName.Equals($testRoot, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw '验证运行目录必须是测试根目录的直接子目录'
    }
    Assert-MarkerProperty $runMarker 'schema_version' 1 '验证运行目录所有权标记'
    Assert-MarkerProperty $runMarker 'kind' 'bili-workspace-test-run' '验证运行目录所有权标记'
    Assert-MarkerProperty $runMarker 'project_id' 'bili_workspace' '验证运行目录所有权标记'
    Assert-MarkerProperty $runMarker 'workspace_root' $Root '验证运行目录所有权标记'
    Assert-MarkerProperty $runMarker 'test_root' $testRoot '验证运行目录所有权标记'
    Assert-MarkerProperty $runMarker 'run_root' $runRoot '验证运行目录所有权标记'
    Assert-MarkerProperty $runMarker 'run_id' ([System.IO.Path]::GetFileName($runRoot)) '验证运行目录所有权标记'
    Assert-NonEmptyMarkerProperty $runMarker 'created_at' '验证运行目录所有权标记'
    if ([System.IO.Path]::GetFileName($runRoot) -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$') {
        throw '验证运行目录名称不是有效 run-id'
    }
    foreach ($directory in @('runtime', 'media')) {
        $child = Join-Path $runRoot $directory
        if (-not (Test-Path -LiteralPath $child -PathType Container)) {
            throw "验证运行子目录缺失: $child"
        }
        Assert-NoReparsePoint $child '验证运行子目录'
    }
    return $runRoot
}

function Get-Sha256([string]$Path) {
    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $digest = $sha256.ComputeHash($stream)
        }
        finally {
            $sha256.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
    return ([System.BitConverter]::ToString($digest)).Replace('-', '').ToLowerInvariant()
}

function Assert-SafeRelativePath([string]$Name) {
    $normalized = $Name.Replace('\', '/')
    if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized.StartsWith('/') -or $normalized.StartsWith('\')) {
        throw "运行包包含不安全路径: $Name"
    }
    $parts = $normalized.Split([char[]]'/', [System.StringSplitOptions]::RemoveEmptyEntries)
    if ($parts.Count -eq 0 -or $parts[0].EndsWith(':') -or $parts -contains '..') {
        throw "运行包包含不安全路径: $Name"
    }
    foreach ($part in $parts) {
        if ($part -eq '.') { throw "运行包包含不安全路径: $Name" }
    }
    return $parts
}

function Resolve-ManifestPack([object]$Pack, [string]$Name) {
    $pathProperty = $Pack.PSObject.Properties['path']
    $hashProperty = $Pack.PSObject.Properties['sha256']
    $sizeProperty = $Pack.PSObject.Properties['size']
    if ($null -eq $pathProperty -or $null -eq $hashProperty -or $null -eq $sizeProperty) {
        throw "$Name 运行包清单缺少 path、sha256 或 size"
    }
    $parts = Assert-SafeRelativePath ([string]$pathProperty.Value)
    if ($parts.Count -lt 3 -or $parts[0] -ne 'vendor' -or $parts[1] -ne 'windows') {
        throw "$Name 运行包必须位于 vendor\windows"
    }
    $candidate = [System.IO.Path]::GetFullPath(
        (Join-Path $Root ($parts -join [System.IO.Path]::DirectorySeparatorChar))
    )
    $vendorRoot = [System.IO.Path]::GetFullPath((Join-Path $Root 'vendor\windows'))
    if (-not (Test-IsWithin $candidate $vendorRoot)) {
        throw "$Name 运行包路径越过 vendor\windows"
    }
    $expectedHash = [string]$hashProperty.Value
    if ($expectedHash -notmatch '^[0-9a-fA-F]{64}$') {
        throw "$Name 运行包 SHA-256 格式无效"
    }
    $declaredSize = [long]0
    if (-not [long]::TryParse([string]$sizeProperty.Value, [ref]$declaredSize) -or $declaredSize -lt 1) {
        throw "$Name 运行包 size 无效"
    }
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $actualSize = (Get-Item -LiteralPath $candidate -Force).Length
        if ($actualSize -ne $declaredSize) {
            throw "$Name 运行包大小与清单不匹配"
        }
    }
    return $candidate
}

function Set-PortablePythonModulePath([string]$PythonDirectory) {
    $pthFiles = @(Get-ChildItem -LiteralPath $PythonDirectory -Filter 'python*._pth' -File)
    if ($pthFiles.Count -ne 1) {
        throw "内置 Python 运行时的 _pth 文件数量异常: $($pthFiles.Count)"
    }

    $pthPath = $pthFiles[0].FullName
    $rootPath = [System.IO.Path]::GetFullPath($Root)
    $lines = @(Get-Content -LiteralPath $pthPath -Encoding UTF8)
    $updated = @()
    $inserted = $false

    foreach ($line in $lines) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '../..' -or $trimmed -eq '..\..' -or $trimmed -eq $rootPath) {
            if (-not $inserted) {
                $updated += $rootPath
                $inserted = $true
            }
            continue
        }
        if ($trimmed -eq 'import site' -and -not $inserted) {
            $updated += $rootPath
            $inserted = $true
        }
        $updated += $line
    }
    if (-not $inserted) {
        $updated += $rootPath
    }

    $currentText = ($lines -join "`r`n") + "`r`n"
    $updatedText = ($updated -join "`r`n") + "`r`n"
    if ($currentText -ne $updatedText) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding
        [System.IO.File]::WriteAllText($pthPath, $updatedText, $utf8NoBom)
    }
}

function Expand-VerifiedPack([string]$PackPath, [string]$ExpectedSha256, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $PackPath -PathType Leaf)) {
        throw "缺少集成运行包: $PackPath"
    }
    $actualPackHash = Get-Sha256 $PackPath
    if ($actualPackHash -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "运行包 SHA-256 不匹配: $PackPath; 实际 $actualPackHash; 期望 $ExpectedSha256"
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $temp = Join-Path $RuntimeRoot ('.extract-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temp -Force | Out-Null
    try {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($PackPath)
        try {
            $seen = @{}
            foreach ($entry in $archive.Entries) {
                if ([string]::IsNullOrEmpty($entry.Name)) { continue }
                $parts = Assert-SafeRelativePath $entry.FullName
                $normalized = ($parts -join '/')
                if ($seen.ContainsKey($normalized)) { throw "运行包包含重复路径: $normalized" }
                $seen[$normalized] = $true
                $target = Join-Path $temp ($parts -join [System.IO.Path]::DirectorySeparatorChar)
                $targetDirectory = Split-Path -Parent $target
                New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
                $input = $entry.Open()
                try {
                    $output = [System.IO.File]::Open(
                        $target,
                        [System.IO.FileMode]::CreateNew,
                        [System.IO.FileAccess]::Write,
                        [System.IO.FileShare]::None
                    )
                    try { $input.CopyTo($output) } finally { $output.Dispose() }
                } finally { $input.Dispose() }
            }
        } finally { $archive.Dispose() }

        $internalManifest = Join-Path $temp 'runtime_manifest.sha256'
        if (-not (Test-Path -LiteralPath $internalManifest -PathType Leaf)) {
            throw "运行包缺少内部 runtime_manifest.sha256"
        }
        $expectedFiles = @{}
        foreach ($line in Get-Content -LiteralPath $internalManifest -Encoding UTF8) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            if ($line -notmatch '^([0-9a-fA-F]{64})\s{2}(.+)$') {
                throw "运行包内部清单格式错误: $line"
            }
            $relative = $Matches[2].Replace('\', '/')
            Assert-SafeRelativePath $relative | Out-Null
            if ($expectedFiles.ContainsKey($relative)) {
                throw "运行包内部清单包含重复路径: $relative"
            }
            $expectedFiles[$relative] = $Matches[1].ToLowerInvariant()
        }
        $actualFiles = Get-ChildItem -LiteralPath $temp -File -Recurse | ForEach-Object {
            $_.FullName.Substring($temp.Length).TrimStart([char[]]'\/').Replace('\', '/')
        } | Where-Object { $_ -ne 'runtime_manifest.sha256' }
        foreach ($relative in $actualFiles) {
            if (-not $expectedFiles.ContainsKey($relative)) {
                throw "运行包包含清单外文件: $relative"
            }
            $target = Join-Path $temp ($relative.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
            $actual = Get-Sha256 $target
            if ($actual -ne $expectedFiles[$relative]) {
                throw "运行包内部文件哈希不匹配: $relative"
            }
            $expectedFiles.Remove($relative) | Out-Null
        }
        if ($expectedFiles.Count -ne 0) {
            throw "运行包缺少清单文件: $($expectedFiles.Keys -join ', ')"
        }

        if (Test-Path -LiteralPath $Destination) {
            Remove-Item -LiteralPath $Destination -Recurse -Force
        }
        $destinationParent = Split-Path -Parent $Destination
        New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
        Move-Item -LiteralPath $temp -Destination $Destination
        $temp = $null
    }
    finally {
        if ($temp -and (Test-Path -LiteralPath $temp)) {
            Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($VerificationRunRoot)) {
    $VerificationRunRoot = Assert-VerificationRunRoot $VerificationRunRoot
    $RuntimeRoot = Join-Path $VerificationRunRoot 'runtime'
    $MediaRoot = Join-Path $VerificationRunRoot 'media'
    $PythonRoot = Join-Path $RuntimeRoot 'python'
    $StatePath = Join-Path $RuntimeRoot 'runtime-state.json'
}

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "仓库缺少 vendor\windows\runtime-manifest.json。请先 git pull 获取完整集成运行时。"
}

$manifestText = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8
$manifest = $manifestText | ConvertFrom-Json
if ($manifest.platform -ne 'windows-x64') {
    throw "不支持的集成运行时清单"
}
$manifestProperties = @($manifest.PSObject.Properties.Name)
if ($manifest.schema_version -eq 1) {
    if ($manifestProperties -notcontains 'bili_workspace_version' -or [string]::IsNullOrWhiteSpace([string]$manifest.bili_workspace_version)) {
        throw 'schema 1 集成运行时清单缺少 bili_workspace_version'
    }
    if ($manifestProperties -contains 'runtime_bundle_version') {
        throw 'schema 1 集成运行时清单不得同时写入 runtime_bundle_version'
    }
    $runtimeBundleVersion = [string]$manifest.bili_workspace_version
}
elseif ($manifest.schema_version -eq 2) {
    if ($manifestProperties -notcontains 'runtime_bundle_version' -or [string]::IsNullOrWhiteSpace([string]$manifest.runtime_bundle_version)) {
        throw 'schema 2 集成运行时清单缺少 runtime_bundle_version'
    }
    if ($manifestProperties -contains 'bili_workspace_version') {
        throw 'schema 2 集成运行时清单不得继续写入 bili_workspace_version'
    }
    $runtimeBundleVersion = [string]$manifest.runtime_bundle_version
}
else {
    throw "不支持的集成运行时清单 schema: $($manifest.schema_version)"
}
$manifestSha = Get-Sha256 $ManifestPath
$pythonPack = Resolve-ManifestPack $manifest.packs.python 'Python'
$mediaPack = Resolve-ManifestPack $manifest.packs.media '媒体'

$stateMatches = $false
if (-not $Force -and (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    try {
        $state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $stateMatches = (
            $state.schema_version -eq 2 -and
            $state.runtime_bundle_version -eq $runtimeBundleVersion -and
            $state.manifest_sha256 -eq $manifestSha -and
            (Test-Path -LiteralPath (Join-Path $PythonRoot 'python.exe') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $MediaRoot 'BBDown_portable\BBDown.exe') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $MediaRoot 'BBDown_portable\ffmpeg\bin\ffmpeg.exe') -PathType Leaf)
        )
    }
    catch { $stateMatches = $false }
}

if (-not $stateMatches) {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    Write-Status '[1/3] 解压并校验内置 Python 运行时...'
    Expand-VerifiedPack $pythonPack $manifest.packs.python.sha256 $PythonRoot

    Write-Status '[2/3] 解压并校验内置 BBDown / FFmpeg...'
    $mediaTemp = Join-Path $RuntimeRoot ('.media-' + [guid]::NewGuid().ToString('N'))
    Expand-VerifiedPack $mediaPack $manifest.packs.media.sha256 $mediaTemp
    try {
        foreach ($folder in @('BBDown_portable', 'LICENSES')) {
            $source = Join-Path $mediaTemp $folder
            if (Test-Path -LiteralPath $source) {
                $destination = Join-Path $MediaRoot $folder
                New-Item -ItemType Directory -Path $destination -Force | Out-Null
                Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
                    Copy-Item -LiteralPath $_.FullName -Destination $destination -Recurse -Force
                }
            }
        }
    }
    finally {
        if (Test-Path -LiteralPath $mediaTemp) {
            Remove-Item -LiteralPath $mediaTemp -Recurse -Force
        }
    }

    $stateObject = [ordered]@{
        schema_version = 2
        runtime_bundle_version = $runtimeBundleVersion
        manifest_sha256 = $manifestSha
        python_pack_sha256 = $manifest.packs.python.sha256
        media_pack_sha256 = $manifest.packs.media.sha256
    }
    $stateObject | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
}
else {
    Write-Status '[1/3] 内置运行时已是最新版本。'
}

Set-PortablePythonModulePath $PythonRoot

if (-not $Quiet -or -not $stateMatches) {
    Write-Status '[3/3] 执行运行时冒烟测试...'
    $pythonExe = Join-Path $PythonRoot 'python.exe'
    $bbdownExe = Join-Path $MediaRoot 'BBDown_portable\BBDown.exe'
    $ffmpegExe = Join-Path $MediaRoot 'BBDown_portable\ffmpeg\bin\ffmpeg.exe'
    & $pythonExe -c "import app,fastapi,httpx,pydantic,pytest,ruff,starlette,tools.config_sync,uvicorn; print('Portable Python OK')"
    if ($LASTEXITCODE -ne 0) { throw '内置 Python 运行时无法加载仓库模块或依赖' }
    & $bbdownExe --help *> $null
    if ($LASTEXITCODE -ne 0) { throw 'BBDown.exe 冒烟测试失败' }
    $ffmpegOutput = & $ffmpegExe -hide_banner -version 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or $ffmpegOutput -notmatch 'ffmpeg version') {
        throw 'FFmpeg 冒烟测试失败'
    }
}
Write-Status '[通过] 集成 Windows 运行时已就绪。'
