param(
    [string]$Message = "",
    [switch]$NoCommit
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path ".git")) {
    git init
    git branch -M main
}

if (-not $NoCommit) {
    git add -A
    $status = git status --porcelain
    if ($status) {
        if (-not $Message) {
            $Message = "Update project"
        }
        git commit -m $Message
    }
}

$remote = git remote get-url origin 2>$null
if (-not $remote) {
    Write-Host "No origin remote is configured yet. Add it with:"
    Write-Host "git remote add origin https://github.com/<user>/<repo>.git"
    exit 2
}

git push -u origin main
