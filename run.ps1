[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$environmentDir = Join-Path $projectRoot ".conda_env"
$pythonExe = Join-Path $environmentDir "python.exe"
$pythonwExe = Join-Path $environmentDir "pythonw.exe"
$requirementsPath = Join-Path $projectRoot "requirements.txt"
$managedCoreDir = Join-Path $projectRoot "managed_core"
$managedBuildScript = Join-Path $managedCoreDir "build.ps1"
$managedExe = Join-Path $managedCoreDir "bin\HexcellsHeadless.exe"
$doctorScript = Join-Path $projectRoot "tools\doctor.py"
$mainScript = Join-Path $projectRoot "main.py"

function Write-Step([string]$message) {
    Write-Host "[HexInfinite] $message" -ForegroundColor Cyan
}

function Find-CondaExecutable {
    $knownPaths = @(
        "D:\MiniConda\Scripts\conda.exe",
        (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\Scripts\conda.exe")
    )
    foreach ($candidate in $knownPaths) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    $command = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    throw "Miniconda/Conda was not found. Install Miniconda, then double-click the launcher again."
}

function Test-RequiredModules {
    & $pythonExe -c "import PySide6, qtawesome, numpy, cv2, ortools, PIL, rapidocr, onnxruntime"
    return $LASTEXITCODE -eq 0
}

try {
    Set-Location -LiteralPath $projectRoot

    if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
        $condaExe = Find-CondaExecutable
        Write-Step "Creating the project Python environment (first launch only)..."
        & $condaExe create --yes --prefix $environmentDir python=3.11 pip
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
            throw "Conda could not create $environmentDir (exit code $LASTEXITCODE)."
        }
    }

    if (-not (Test-RequiredModules)) {
        Write-Step "Installing or repairing Python dependencies (first launch may take several minutes)..."
        & $pythonExe -m pip install --disable-pip-version-check -r $requirementsPath
        if ($LASTEXITCODE -ne 0 -or -not (Test-RequiredModules)) {
            throw "Python dependency installation failed (exit code $LASTEXITCODE)."
        }
    }

    $managedOutputs = @(
        $managedExe,
        (Join-Path $managedCoreDir "bin\UnityEngine.dll"),
        (Join-Path $managedCoreDir "bin\TextMeshPro-5.6-Runtime.dll")
    )
    $needsManagedBuild = $false
    foreach ($output in $managedOutputs) {
        if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
            $needsManagedBuild = $true
            break
        }
    }
    if (-not $needsManagedBuild) {
        $latestSource = Get-ChildItem -LiteralPath $managedCoreDir -Filter "*.cs" |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($null -ne $latestSource -and $latestSource.LastWriteTimeUtc -gt (Get-Item -LiteralPath $managedExe).LastWriteTimeUtc) {
            $needsManagedBuild = $true
        }
    }
    if ($needsManagedBuild) {
        Write-Step "Building the Easy headless managed core..."
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $managedBuildScript
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $managedExe -PathType Leaf)) {
            throw "The Easy headless managed core build failed (exit code $LASTEXITCODE)."
        }
    }

    Write-Step "Checking the offline generator and original assembly version..."
    & $pythonExe $doctorScript
    if ($LASTEXITCODE -ne 0) {
        throw "Offline generator diagnostics failed (exit code $LASTEXITCODE)."
    }

    if ($CheckOnly) {
        Write-Host "[OK] One-click launcher check passed." -ForegroundColor Green
        exit 0
    }

    if (-not (Test-Path -LiteralPath $pythonwExe -PathType Leaf)) {
        $pythonwExe = $pythonExe
    }
    Write-Step "Starting HexInfinite Solver..."
    Start-Process -FilePath $pythonwExe -ArgumentList @($mainScript) -WorkingDirectory $projectRoot
    exit 0
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
