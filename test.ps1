$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot ".conda_env\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "找不到项目 Python：$pythonExe。"
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:QT_QPA_PLATFORM = "offscreen"
& $pythonExe -m unittest discover -s (Join-Path $projectRoot "tests") -p "test_*.py" -v
exit $LASTEXITCODE
