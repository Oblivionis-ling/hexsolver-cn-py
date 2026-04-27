param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$Commit,
    [switch]$Tag
)

$ErrorActionPreference = "Stop"

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use semantic version format, for example 0.1.1."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Set-Content -Path "VERSION" -Value $Version -Encoding ASCII

$pyproject = Get-Content "pyproject.toml" -Raw
$pyproject = $pyproject -replace '(?m)^version = ".+"$', "version = `"$Version`""
Set-Content -Path "pyproject.toml" -Value $pyproject -Encoding UTF8

$initPath = "src\hexsolver_cn\__init__.py"
$init = Get-Content $initPath -Raw
$init = $init -replace '__version__ = ".+"', "__version__ = `"$Version`""
Set-Content -Path $initPath -Value $init -Encoding UTF8

Write-Host "Version updated to $Version."

if ($Commit) {
    git add VERSION pyproject.toml $initPath
    git commit -m "Bump version to $Version"
}

if ($Tag) {
    git tag "v$Version"
    git push origin "v$Version"
}
