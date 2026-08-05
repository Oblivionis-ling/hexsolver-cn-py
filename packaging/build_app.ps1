[CmdletBinding()]
param(
    [switch]$SkipSourceTests,
    [switch]$SkipPackageSmokeTest
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonExe = Join-Path $projectRoot ".conda_env\python.exe"
$versionPath = Join-Path $projectRoot "VERSION"
$buildRequirements = Join-Path $projectRoot "requirements-build.txt"
$managedBuildScript = Join-Path $projectRoot "managed_core\build.ps1"
$specPath = Join-Path $projectRoot "packaging\HexInfiniteSolver.spec"
$assetScript = Join-Path $projectRoot "packaging\build_assets.py"
$assetDir = Join-Path $projectRoot "build\package_assets"
$workDir = Join-Path $projectRoot "build\pyinstaller"
$distDir = Join-Path $projectRoot "dist"
$expectedVersion = "0.6.3"

function Write-Step([string]$message) {
    Write-Host "[HexInfinite $expectedVersion] $message" -ForegroundColor Cyan
}

function Assert-ProjectChild([string]$path) {
    $root = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
    $resolved = [IO.Path]::GetFullPath($path)
    if (-not $resolved.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the project: $resolved"
    }
}

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Project Python not found: $pythonExe. Run run.ps1 to initialize the environment."
}

Set-Location -LiteralPath $projectRoot
$version = (Get-Content -Raw -Encoding UTF8 $versionPath).Trim()
if ($version -ne $expectedVersion) {
    throw "This packaging script only publishes $expectedVersion; current VERSION is $version."
}
$artifactName = "HexInfiniteSolver-$version-windows-x64"
$artifactPath = Join-Path $distDir "$artifactName.exe"
$checksumPath = "$artifactPath.sha256"

Write-Step "Checking PyInstaller build dependencies..."
& $pythonExe -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $pythonExe -m pip install --disable-pip-version-check -r $buildRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build dependencies could not be installed."
    }
}

Write-Step "Building the redistributable Easy managed host..."
& powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $managedBuildScript
if ($LASTEXITCODE -ne 0) {
    throw "Easy managed host build failed with exit code $LASTEXITCODE."
}

if (-not $SkipSourceTests) {
    Write-Step "Running the source regression suite..."
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot "test.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Source tests failed with exit code $LASTEXITCODE."
    }
}

foreach ($path in ($assetDir, $workDir, $artifactPath, $checksumPath)) {
    Assert-ProjectChild $path
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}

Write-Step "Generating the Windows icon and version resource..."
& $pythonExe $assetScript --output-dir $assetDir --version $version --artifact-name $artifactName
if ($LASTEXITCODE -ne 0) {
    throw "Package build assets could not be generated."
}

Write-Step "Building the single-file Windows x64 executable..."
& $pythonExe -m PyInstaller --noconfirm --clean --distpath $distDir --workpath $workDir $specPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
    throw "PyInstaller did not produce $artifactPath."
}

$archiveViewer = Join-Path (Split-Path -Parent $pythonExe) "Scripts\pyi-archive_viewer.exe"
if (-not (Test-Path -LiteralPath $archiveViewer -PathType Leaf)) {
    throw "Missing PyInstaller archive viewer: $archiveViewer"
}
$archiveListing = (& $archiveViewer -l $artifactPath 2>&1) -join "`n"
foreach ($required in ("HexcellsHeadless.exe", "UnityEngine.dll", "TextMeshPro-5.6-Runtime.dll")) {
    if (-not $archiveListing.Contains($required)) {
        throw "Packaged archive is missing $required."
    }
}
if ($archiveListing.Contains("Assembly-CSharp.dll")) {
    throw "The package must not contain the proprietary Assembly-CSharp.dll."
}

if (-not $SkipPackageSmokeTest) {
    Write-Step "Starting the real packaged UI and verifying Easy/Hard seed 1..."
    $previousPlatform = $env:QT_QPA_PLATFORM
    $previousSmokeLog = $env:HEXSOLVER_PACKAGE_SMOKE_LOG
    $previousCacheDir = $env:HEXSOLVER_CACHE_DIR
    $smokeLog = Join-Path $env:TEMP "HexInfiniteSolver-$version-package-smoke.log"
    $tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
    $smokeCacheDir = Join-Path $env:TEMP "HexInfiniteSolver-$version-package-smoke-$([Guid]::NewGuid().ToString('N'))"
    $resolvedSmokeCacheDir = [IO.Path]::GetFullPath($smokeCacheDir)
    if (-not $resolvedSmokeCacheDir.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Package smoke cache escaped the system temp directory: $resolvedSmokeCacheDir"
    }
    New-Item -ItemType Directory -Path $resolvedSmokeCacheDir | Out-Null
    if (Test-Path -LiteralPath $smokeLog) {
        Remove-Item -LiteralPath $smokeLog -Force
    }
    $env:QT_QPA_PLATFORM = "offscreen"
    $env:HEXSOLVER_PACKAGE_SMOKE_LOG = $smokeLog
    $env:HEXSOLVER_CACHE_DIR = $resolvedSmokeCacheDir
    try {
        $process = Start-Process -FilePath $artifactPath -ArgumentList "--package-smoke-test" -PassThru -WindowStyle Hidden
        if (-not $process.WaitForExit(180000)) {
            & taskkill.exe /PID $process.Id /T /F | Out-Null
            $progress = if (Test-Path -LiteralPath $smokeLog) {
                (Get-Content -LiteralPath $smokeLog -Raw -Encoding UTF8).Trim()
            } else {
                "No progress log was created."
            }
            throw "Packaged smoke test exceeded 180 seconds. Progress: $progress"
        }
        if ($process.ExitCode -ne 0) {
            $progress = if (Test-Path -LiteralPath $smokeLog) {
                (Get-Content -LiteralPath $smokeLog -Raw -Encoding UTF8).Trim()
            } else {
                "No progress log was created."
            }
            throw "Packaged smoke test failed with exit code $($process.ExitCode). Progress: $progress"
        }
    }
    finally {
        $env:QT_QPA_PLATFORM = $previousPlatform
        $env:HEXSOLVER_PACKAGE_SMOKE_LOG = $previousSmokeLog
        $env:HEXSOLVER_CACHE_DIR = $previousCacheDir
        if (Test-Path -LiteralPath $resolvedSmokeCacheDir) {
            Remove-Item -LiteralPath $resolvedSmokeCacheDir -Recurse -Force
        }
    }
}

$hash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumText = "$hash  $([IO.Path]::GetFileName($artifactPath))`n"
[IO.File]::WriteAllText($checksumPath, $checksumText, (New-Object Text.UTF8Encoding($false)))
$sizeMiB = [Math]::Round((Get-Item -LiteralPath $artifactPath).Length / 1MB, 2)

Write-Host "[OK] $artifactPath" -ForegroundColor Green
Write-Host "[OK] Size: $sizeMiB MiB" -ForegroundColor Green
Write-Host "[OK] SHA256: $hash" -ForegroundColor Green
