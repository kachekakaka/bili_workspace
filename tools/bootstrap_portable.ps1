[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$ManifestPath = Join-Path $Root 'vendor\windows\runtime-manifest.json'
$RuntimeRoot = Join-Path $Root '.runtime'
$PythonRoot = Join-Path $RuntimeRoot 'python'
$StatePath = Join-Path $RuntimeRoot 'runtime-state.json'

function Write-Status([string]$Message) {
    if (-not $Quiet) { Write-Host $Message }
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-SafeRelativePath([string]$Name) {
    $normalized = $Name.Replace('\\', '/')
    if ([string]::IsNullOrWhiteSpace($normalized) -or $normalized.StartsWith('/') -or $normalized.StartsWith('\\')) {
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
            $relative = $Matches[2].Replace('\\', '/')
            Assert-SafeRelativePath $relative | Out-Null
            if ($expectedFiles.ContainsKey($relative)) {
                throw "运行包内部清单包含重复路径: $relative"
            }
            $expectedFiles[$relative] = $Matches[1].ToLowerInvariant()
        }
        $actualFiles = Get-ChildItem -LiteralPath $temp -File -Recurse | ForEach-Object {
            $_.FullName.Substring($temp.Length).TrimStart([char[]]'\/').Replace('\\', '/')
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

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "仓库缺少 vendor\windows\runtime-manifest.json。请先 git pull 获取完整集成运行时。"
}

$manifestText = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8
$manifest = $manifestText | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.platform -ne 'windows-x64') {
    throw "不支持的集成运行时清单"
}
$manifestSha = Get-Sha256 $ManifestPath
$pythonPack = Join-Path $Root $manifest.packs.python.path
$mediaPack = Join-Path $Root $manifest.packs.media.path

$stateMatches = $false
if (-not $Force -and (Test-Path -LiteralPath $StatePath -PathType Leaf)) {
    try {
        $state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $stateMatches = (
            $state.manifest_sha256 -eq $manifestSha -and
            (Test-Path -LiteralPath (Join-Path $PythonRoot 'python.exe') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $Root 'BBDown_portable\BBDown.exe') -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $Root 'BBDown_portable\ffmpeg\bin\ffmpeg.exe') -PathType Leaf)
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
                $destination = Join-Path $Root $folder
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
        schema_version = 1
        version = $manifest.bili_workspace_version
        manifest_sha256 = $manifestSha
        python_pack_sha256 = $manifest.packs.python.sha256
        media_pack_sha256 = $manifest.packs.media.sha256
    }
    $stateObject | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
}
else {
    Write-Status '[1/3] 内置运行时已是最新版本。'
}

if (-not $Quiet -or -not $stateMatches) {
    Write-Status '[3/3] 执行运行时冒烟测试...'
    $pythonExe = Join-Path $PythonRoot 'python.exe'
    $bbdownExe = Join-Path $Root 'BBDown_portable\BBDown.exe'
    $ffmpegExe = Join-Path $Root 'BBDown_portable\ffmpeg\bin\ffmpeg.exe'
    & $pythonExe -c "import fastapi,httpx,pydantic,pytest,ruff,starlette,uvicorn; print('Portable Python OK')"
    if ($LASTEXITCODE -ne 0) { throw '内置 Python 运行时无法加载依赖' }
    & $bbdownExe --help *> $null
    if ($LASTEXITCODE -ne 0) { throw 'BBDown.exe 冒烟测试失败' }
    $ffmpegOutput = & $ffmpegExe -hide_banner -version 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or $ffmpegOutput -notmatch 'ffmpeg version') {
        throw 'FFmpeg 冒烟测试失败'
    }
}
Write-Status '[通过] 集成 Windows 运行时已就绪。'
